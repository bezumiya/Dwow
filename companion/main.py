"""Dwow companion — captures the WoW window, decodes the addon's
pixel strip and updates the Discord Rich Presence.

Usage:
    1. copy config.example.json to config.json and fill in the application_id
    2. python main.py
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import time
from dataclasses import replace
from itertools import chain
from pathlib import Path

import capture
import decoder
from presence import PresenceClient
from log_i18n import configure as configure_log_language, detect_language, text as T
from settings import ConfigError, load_config
from version import __version__

log = logging.getLogger("dwow")

_mutex_handle = None  # keeps the handle alive for the process lifetime


def ensure_single_instance() -> None:
    """Global Windows mutex: a second instance (scheduled task + manual run,
    for example) would fight this one over the presence — better to refuse."""
    import ctypes

    global _mutex_handle
    # use_last_error + get_last_error: a "bare" GetLastError could be
    # overwritten by ctypes' internal calls between the two lines
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _mutex_handle = kernel32.CreateMutexW(None, False, "DwowCompanion")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        print(T("Já existe um Dwow companion rodando — saindo.",
                "A Dwow companion instance is already running — exiting."))
        sys.exit(0)


class CodeWatcher:
    """Auto-restart: when any .py in the folder (or config.json) changes on
    disk, the process relaunches itself to load the new code — no need to
    touch the scheduled task on every update."""

    def __init__(self, interval: float = 5.0):
        self.dir = Path(__file__).parent
        self.interval = interval
        self._next_check = 0.0
        self._mtimes = self._snapshot()

    def _snapshot(self) -> dict:
        files = list(self.dir.glob("*.py")) + [self.dir / "config.json"]
        return {f: f.stat().st_mtime for f in files if f.exists()}

    def changed(self, now: float) -> bool:
        if now < self._next_check:
            return False
        self._next_check = now + self.interval
        return self._snapshot() != self._mtimes

    @staticmethod
    def restart() -> None:
        """Relaunches the process. subprocess.Popen (not os.execv): on Windows
        execv does no quoting and a path with spaces would kill the child at
        startup. Release the mutex FIRST, otherwise the new process would see
        the 'other instance' and refuse to start."""
        import ctypes
        import subprocess

        global _mutex_handle
        if _mutex_handle:
            ctypes.WinDLL("kernel32").CloseHandle(_mutex_handle)
            _mutex_handle = None
        subprocess.Popen([sys.executable, str(Path(__file__))],
                         cwd=str(Path(__file__).parent), close_fds=True)
        os._exit(0)


class FreezeGuard:
    """Detects a frozen payload (game hung/minimized with a static capture):
    the addon's seq should change every ~1s; stuck beyond the threshold, the
    frame is considered dead and the presence must not be refreshed."""

    def __init__(self, threshold: float = 30.0):
        self.threshold = threshold
        self._seq = None
        self._since = 0.0
        self.warned = False

    def reset(self) -> None:
        """Call when capture is interrupted (window gone): the heuristic
        only holds within a continuous sequence of frames."""
        self._seq = None
        self.warned = False

    def tick(self, seq: int, now: float) -> bool:
        """True = frozen (do not refresh the presence with this frame)."""
        if seq != self._seq:
            self._seq, self._since = seq, now
            self.warned = False
            return False
        return now - self._since > self.threshold


def diagnose(cfg: dict) -> int:
    """Run read-only checks for the local setup and print actionable results."""
    from pypresence import Presence

    capture.set_dpi_aware()
    print(f"Dwow companion....... v{__version__}")
    print(f"Protocol............. v{decoder.PROTOCOL_VERSION}")
    print(f"Config............... OK ({cfg['language']}, {cfg['bnet']['flavor']})")
    hwnd = capture.find_window(str(cfg["window_title"]))
    if not hwnd:
        print("WoW window........... NOT FOUND (open the game in windowed/borderless mode)")
        state = None
    else:
        print(f"WoW window........... OK (HWND {hwnd})")
        img = capture.capture_client(hwnd)
        if img is None:
            print("Screen capture....... FAILED (minimized game or unsupported color depth)")
            state = None
        else:
            print(f"Screen capture....... OK ({img.width}x{img.height})")
            try:
                state, origin = decoder.decode_with_relocation(img)
            except decoder.DecodeError as exc:
                print(f"Pixel protocol....... FAILED ({exc})")
                state = None
            else:
                print(f"Pixel protocol....... OK (origin={origin}, seq={state.seq})")
                print(f"Character............ {state.name}-{state.realm}, {state.zone}")
    rpc = None
    try:
        rpc = Presence(str(cfg["application_id"]))
        rpc.connect()
    except Exception as exc:
        print(f"Discord desktop...... FAILED ({exc})")
        discord_ok = False
    else:
        print("Discord desktop...... OK")
        discord_ok = True
    finally:
        if rpc is not None:
            try:
                rpc.close()
            except Exception:
                pass
    bnet = cfg["bnet"]
    print("Battle.net render.... " + (
        f"ENABLED ({bnet['region']}/{bnet['flavor']})" if bnet["enabled"] else "DISABLED (optional)"))
    return 0 if state is not None and discord_ok else 1


def main(cfg: dict) -> None:
    configure_log_language(str(cfg.get("log_language", "pt")))
    ensure_single_instance()
    # console + file: running via pythonw (scheduled task) there is no console,
    # so companion.log is the only window into the process
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            # rotating: preserves the log of the session that crashed (mode="w"
            # would erase exactly the evidence we need)
            logging.handlers.RotatingFileHandler(
                Path(__file__).with_name("companion.log"),
                maxBytes=1_000_000, backupCount=2, encoding="utf-8"),
        ],
        force=True,
    )
    capture.set_dpi_aware()
    poll = float(cfg.get("poll_seconds", 1.0))
    clear_after = float(cfg.get("clear_after_seconds", 60))
    stale_clear_after = float(cfg.get("stale_clear_after_seconds", 900))
    window_title = cfg.get("window_title", "World of Warcraft")
    capture_method = str(cfg.get("capture_method", "auto"))
    infer_afk_after = float(cfg.get("infer_afk_after_seconds", 300))

    pres = PresenceClient(
        application_id=str(cfg["application_id"]),
        min_interval=float(cfg.get("presence_min_interval", 15)),
        large_image_key=cfg.get("large_image_key", "wow_classic"),
        use_race_image=bool(cfg.get("use_race_image", True)),
        show_realm=bool(cfg.get("show_realm", True)),
        show_guild=bool(cfg.get("show_guild", True)),
        show_xp=bool(cfg.get("show_xp", True)),
        show_gold=bool(cfg.get("show_gold", True)),
        language=str(cfg.get("language", "pt")),
    )

    bcfg = cfg.get("bnet") or {}
    if bcfg.get("enabled"):
        if bcfg.get("client_id") and bcfg.get("client_secret"):
            from bnet import BnetRenders

            renders = BnetRenders(
                client_id=str(bcfg["client_id"]),
                client_secret=str(bcfg["client_secret"]),
                region=str(bcfg.get("region", "us")),
                flavor=str(bcfg.get("flavor", "era")),
            )
            pres.render_resolver = lambda st: renders.render_url(st.name, st.realm)
            log.info(T("Render 3D via Battle.net API ativado (%s/%s).",
                       "Battle.net 3D render enabled (%s/%s)."),
                     bcfg.get("region", "us"), bcfg.get("flavor", "era"))
        else:
            log.warning(T(
                "bnet.enabled=true mas client_id/client_secret vazios — renders ignorados.",
                "bnet.enabled=true but client_id/client_secret are empty — renders disabled."))

    log.info(T("Dwow companion v%s iniciado — janela='%s', captura=%s, idioma=%s.",
               "Dwow companion v%s started — window='%s', capture=%s, language=%s."),
             __version__, window_title, capture_method, cfg.get("log_language"))
    last_good = 0.0
    presence_active = False
    fail_streak = 0
    window_was_found = False
    origin = (0, 0)  # strip corner; changes if a viewport addon shifts the WorldFrame
    last_scan = 0.0  # origin scan is expensive; at most once per 10s of failure
    freeze = FreezeGuard()
    watcher = CodeWatcher()
    failure_started = 0.0
    last_error = ""
    active_capture_method = ""
    last_afk = None
    health_at = time.time() + 300
    frames_ok = frames_failed = 0
    background_since = 0.0
    last_state = None
    inferred_afk = False

    try:
        while True:
            now = time.time()
            if watcher.changed(now):
                log.info(T("Código/config mudou no disco — reiniciando o companion…",
                           "Code/config changed on disk — restarting companion…"))
                pres.close()
                watcher.restart()
            hwnd = capture.find_window(window_title)
            valid_this_loop = False
            if hwnd and capture.is_foreground(hwnd):
                background_since = 0.0
            elif hwnd and not background_since:
                background_since = now
            elif not hwnd:
                background_since = 0.0
            candidates = capture.capture_candidates(hwnd, capture_method) if hwnd else iter(())
            first_candidate = next(candidates, None)

            if first_candidate is None:
                if window_was_found:
                    reason = (T("minimizada/não capturável", "minimized/not capturable")
                              if hwnd else T("não encontrada", "not found"))
                    log.info(T("Janela do WoW %s; mantendo o último presence válido.",
                               "WoW window %s; keeping the last valid presence."), reason)
                    window_was_found = False
                    # capture interrupted: the freeze detector starts over
                    # (a coincidentally equal seq after a relog is not a freeze)
                    freeze.reset()
            else:
                if not window_was_found:
                    log.info(T("Janela do WoW encontrada e capturável.",
                               "WoW window found and capturable."))
                    window_was_found = True
                allow_scan = now - last_scan >= 10.0
                if allow_scan:
                    last_scan = now
                state = new_origin = used_method = None
                errors = []
                for candidate_method, img in chain((first_candidate,), candidates):
                    try:
                        state, new_origin = decoder.decode_with_relocation(
                            img, origin, allow_scan=allow_scan)
                    except decoder.DecodeError as exc:
                        errors.append(f"{candidate_method}: {exc}")
                        continue
                    used_method = candidate_method
                    break
                if state is None:
                    fail_streak += 1
                    frames_failed += 1
                    if not failure_started:
                        failure_started = now
                    last_error = "; ".join(errors) or T("captura vazia", "empty capture")
                    if fail_streak in (1, 5, 60) or fail_streak % 600 == 0:
                        log.warning(
                            T("Falha de leitura #%d (%s). Tentativas: %s.",
                              "Read failure #%d (%s). Attempts: %s."),
                            fail_streak,
                            T("o último presence será preservado", "last presence will be preserved"),
                            last_error,
                        )
                else:
                    frames_ok += 1
                    if new_origin != origin:
                        log.info(T("Faixa localizada no offset %s.",
                                   "Pixel strip found at offset %s."), new_origin)
                        origin = new_origin
                    if used_method != active_capture_method:
                        log.info(T("Método de captura ativo: %s.",
                                   "Active capture method: %s."), used_method)
                        active_capture_method = used_method or ""
                    if failure_started:
                        log.info(T("Leitura recuperada após %.1fs e %d falhas; método=%s.",
                                   "Reading recovered after %.1fs and %d failures; method=%s."),
                                 now - failure_started, fail_streak, used_method)
                        failure_started = 0.0
                    fail_streak = 0
                    # seq frozen for too long = static frame (game hung/
                    # minimized with a frozen capture): don't refresh
                    # last_good, so clear_after acts normally
                    frozen = freeze.tick(state.seq, now)
                    if frozen and not freeze.warned:
                        log.warning(T("Payload congelado (seq=%s); aguardando heartbeat.",
                                      "Frozen payload (seq=%s); waiting for heartbeat."), state.seq)
                        freeze.warned = True
                    if not frozen:
                        valid_this_loop = True
                        last_good = now
                        last_state = state
                        if inferred_afk:
                            log.info(T("Leitura real restaurada; substituindo AFK inferido pelo estado do addon.",
                                       "Real reading restored; replacing inferred AFK with addon state."))
                            inferred_afk = False
                        if last_afk is None or state.afk != last_afk:
                            log.info(T("Estado AFK: %s (flags=%d, seq=%d).",
                                       "AFK state: %s (flags=%d, seq=%d)."),
                                     "ON" if state.afk else "OFF", state.flags, state.seq)
                            last_afk = state.afk
                        pres.update(state)
                        presence_active = True

            if (
                hwnd and last_state is not None and not valid_this_loop
                and infer_afk_after > 0 and background_since
                and now - background_since >= infer_afk_after
            ):
                inferred = replace(last_state, flags=last_state.flags | decoder.FLAG_AFK)
                if not inferred_afk:
                    log.warning(T(
                        "AFK inferido após %.0fs sem foco e sem leitura válida; mantendo presence.",
                        "AFK inferred after %.0fs unfocused with no valid reading; keeping presence."),
                        now - background_since)
                pres.update(inferred)
                inferred_afk = True
                presence_active = True

            if presence_active:
                stale_for = now - last_good
                limit = (float("inf") if hwnd and inferred_afk else
                         stale_clear_after if hwnd else clear_after)
                if stale_for > limit:
                    reason = (T("janela ausente", "window absent") if not hwnd else
                              T("dados inválidos por muito tempo", "data invalid for too long"))
                    log.info(T("Limpando presence: %s, último dado válido há %.0fs.",
                               "Clearing presence: %s, last valid data %.0fs ago."),
                             reason, stale_for)
                    pres.clear(end_session=not hwnd)
                    presence_active = False

            if now >= health_at:
                age = now - last_good if last_good else -1
                log.info(T(
                    "Saúde: presence=%s janela=%s método=%s ok=%d falhas=%d último_ok=%.1fs AFK=%s.",
                    "Health: presence=%s window=%s method=%s ok=%d failures=%d last_ok=%.1fs AFK=%s."),
                    "on" if presence_active else "off", "on" if hwnd else "off",
                    active_capture_method or "-", frames_ok, frames_failed, age,
                    "inferred" if inferred_afk else
                    "?" if last_afk is None else ("on" if last_afk else "off"))
                frames_ok = frames_failed = 0
                health_at = now + 300

            time.sleep(poll)
    except KeyboardInterrupt:
        log.info(T("Encerrando…", "Shutting down…"))
    finally:
        pres.close()


def cli() -> int:
    configure_log_language(detect_language())
    parser = argparse.ArgumentParser(description="Dwow companion")
    parser.add_argument("--diagnose", action="store_true",
                        help="verifica configuração, WoW, pixels e Discord sem publicar presence")
    parser.add_argument("--version", action="version", version=f"Dwow {__version__}")
    args = parser.parse_args()
    try:
        cfg = load_config()
    except ConfigError as exc:
        print(T(f"Erro de configuração: {exc}", f"Configuration error: {exc}"))
        return 2
    configure_log_language(str(cfg.get("log_language", "pt")))
    if args.diagnose:
        return diagnose(cfg)
    main(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(cli())
