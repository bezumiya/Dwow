"""Dwow companion — captures the WoW window, decodes the addon's
pixel strip and updates the Discord Rich Presence.

Usage:
    1. copy config.example.json to config.json and fill in the application_id
    2. python main.py
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path

import capture
import decoder
from presence import PresenceClient

log = logging.getLogger("dwow")

CONFIG_PATH = Path(__file__).with_name("config.json")
EXAMPLE_PATH = Path(__file__).with_name("config.example.json")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"Config não encontrada: {CONFIG_PATH}")
        print(f"Copie {EXAMPLE_PATH.name} para config.json e preencha o application_id.")
        sys.exit(1)
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    app_id = str(cfg.get("application_id", ""))
    if not app_id.isdigit():
        print("application_id inválido no config.json — cole o Application ID numérico")
        print("do seu app em https://discord.com/developers/applications")
        sys.exit(1)
    return cfg


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
        print("Já existe um Dwow companion rodando — saindo.")
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


def main() -> None:
    ensure_single_instance()
    # console + file: running via pythonw (scheduled task) there is no console,
    # so companion.log is the only window into the process
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            # rotating: preserves the log of the session that crashed (mode="w"
            # would erase exactly the evidence we need)
            logging.handlers.RotatingFileHandler(
                Path(__file__).with_name("companion.log"),
                maxBytes=1_000_000, backupCount=2, encoding="utf-8"),
        ],
    )
    capture.set_dpi_aware()
    cfg = load_config()

    poll = float(cfg.get("poll_seconds", 1.0))
    clear_after = float(cfg.get("clear_after_seconds", 60))
    window_title = cfg.get("window_title", "World of Warcraft")

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
        buttons=cfg.get("buttons") or [],
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
            log.info("Render 3D via Battle.net API ativado (%s/%s).",
                     bcfg.get("region", "us"), bcfg.get("flavor", "era"))
        else:
            log.warning("bnet.enabled=true mas client_id/client_secret vazios — renders ignorados.")

    widget = None
    wcfg = cfg.get("widget") or {}
    if wcfg.get("enabled"):
        if wcfg.get("bot_token") and wcfg.get("user_id"):
            from widget import WidgetClient

            widget = WidgetClient(
                application_id=str(cfg["application_id"]),
                bot_token=str(wcfg["bot_token"]),
                user_id=str(wcfg["user_id"]),
                min_interval=float(wcfg.get("update_interval", 45)),
                level_cap=int(wcfg.get("level_cap", 0)),
            )
            log.info("Profile Widget V2 ativado (experimental).")
        else:
            log.warning("widget.enabled=true mas bot_token/user_id vazios — widget ignorado.")

    log.info("Dwow companion iniciado — procurando janela '%s'…", window_title)
    last_good = 0.0
    presence_active = False
    fail_streak = 0
    window_was_found = False
    origin = (0, 0)  # strip corner; changes if a viewport addon shifts the WorldFrame
    last_scan = 0.0  # origin scan is expensive; at most once per 10s of failure
    freeze = FreezeGuard()
    watcher = CodeWatcher()

    try:
        while True:
            now = time.time()
            if watcher.changed(now):
                log.info("Código/config mudou no disco — reiniciando o companion…")
                pres.close()
                watcher.restart()
            hwnd = capture.find_window(window_title)
            img = capture.capture_client(hwnd) if hwnd else None

            if img is None:
                if window_was_found:
                    log.info("Janela do WoW não encontrada/capturável.")
                    window_was_found = False
                    # capture interrupted: the freeze detector starts over
                    # (a coincidentally equal seq after a relog is not a freeze)
                    freeze.reset()
            else:
                if not window_was_found:
                    log.info("Janela do WoW encontrada.")
                    window_was_found = True
                try:
                    allow_scan = now - last_scan >= 10.0
                    if allow_scan:
                        last_scan = now
                    state, new_origin = decoder.decode_with_relocation(
                        img, origin, allow_scan=allow_scan)
                    if new_origin != origin:
                        log.info("Faixa localizada no offset %s (viewport deslocado?).", new_origin)
                        origin = new_origin
                except decoder.DecodeError as exc:
                    fail_streak += 1
                    # warn early and then rarely, to avoid flooding the console
                    if fail_streak in (5, 60) or fail_streak % 600 == 0:
                        log.warning(
                            "Sem dados válidos (%s). Checklist: personagem logado, "
                            "faixa ativa (/dwow status), modo janela/borderless, "
                            "anti-aliasing (MSAA) desligado.", exc,
                        )
                else:
                    fail_streak = 0
                    # seq frozen for too long = static frame (game hung/
                    # minimized with a frozen capture): don't refresh
                    # last_good, so clear_after acts normally
                    frozen = freeze.tick(state.seq, now)
                    if frozen and not freeze.warned:
                        log.warning("Payload congelado (seq %s) — jogo travado?", state.seq)
                        freeze.warned = True
                    if not frozen:
                        last_good = now
                        pres.update(state)
                        if widget is not None:
                            widget.update(state)
                        presence_active = True

            if presence_active and now - last_good > clear_after:
                log.info("Sem dados há %.0fs — limpando presence.", now - last_good)
                # window still visible = it just froze/minimized: keep the
                # session clock so the "elapsed" doesn't restart from zero
                pres.clear(end_session=not window_was_found)
                presence_active = False

            time.sleep(poll)
    except KeyboardInterrupt:
        log.info("Encerrando…")
    finally:
        pres.close()


if __name__ == "__main__":
    main()
