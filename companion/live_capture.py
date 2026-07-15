"""GIF of real gameplay for the Rich Presence, published via webhook.

Captures a few frames around the window center when the visual state changes,
encodes them in memory, and uploads off the main thread. The webhook URL is
never written to logs.
"""
from __future__ import annotations

import io
import json
import logging
import time
import urllib.request
import uuid
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor

from PIL import Image

log = logging.getLogger("dwow.live_capture")


def encode_gif(frames: list[Image.Image], fps: float) -> bytes:
    """Encodes RGB frames as a looping animated GIF."""
    if not frames:
        raise ValueError("nenhum frame para codificar")
    duration = max(40, round(1000 / max(1.0, fps)))
    out = io.BytesIO()
    frames[0].save(
        out,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=duration,
        loop=0,
        optimize=True,
        disposal=2,
    )
    return out.getvalue()


class LiveCaptureAnimator:
    def __init__(
        self,
        webhook_url: str,
        fps: float = 5.0,
        frame_count: int = 10,
        crop_size: int = 320,
    ):
        self.webhook_url = webhook_url
        self.fps = max(1.0, min(10.0, fps))
        self.frame_count = max(2, min(30, frame_count))
        self.crop_size = max(128, min(640, crop_size))
        self.frames: deque[Image.Image] = deque(maxlen=self.frame_count)
        self.current_key = ""
        self._last_sample = 0.0
        self._future: Future | None = None
        self._future_key = ""
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dwow-gif")
        self._urls: dict[str, str] = {}
        self._announced_url = ""

    def _crop(self, img: Image.Image) -> Image.Image:
        # The WoW character sits at the horizontal center and slightly below
        # the vertical center with the default camera.
        size = min(self.crop_size, img.width, img.height)
        cx, cy = img.width // 2, round(img.height * 0.54)
        left = max(0, min(img.width - size, cx - size // 2))
        top = max(0, min(img.height - size, cy - size // 2))
        frame = img.crop((left, top, left + size, top + size)).convert("RGB")
        if size != self.crop_size:
            frame = frame.resize((self.crop_size, self.crop_size), Image.Resampling.LANCZOS)
        return frame

    def _upload(self, key: str, frames: list[Image.Image]) -> tuple[str, str]:
        data = encode_gif(frames, self.fps)
        boundary = f"----Dwow{uuid.uuid4().hex}"
        meta = json.dumps({
            "content": f"Dwow animation: {key}",
            "allowed_mentions": {"parse": []},
        }).encode("utf-8")
        body = bytearray()

        def part(name: str, value: bytes, content_type: str, filename: str | None = None):
            body.extend(f"--{boundary}\r\n".encode())
            disp = f'Content-Disposition: form-data; name="{name}"'
            if filename:
                disp += f'; filename="{filename}"'
            body.extend(f"{disp}\r\nContent-Type: {content_type}\r\n\r\n".encode())
            body.extend(value)
            body.extend(b"\r\n")

        part("payload_json", meta, "application/json")
        part("files[0]", data, "image/gif", "dwow-live.gif")
        body.extend(f"--{boundary}--\r\n".encode())
        sep = "&" if "?" in self.webhook_url else "?"
        req = urllib.request.Request(
            self.webhook_url + sep + "wait=true",
            data=bytes(body),
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "Dwow companion",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read())
        attachments = result.get("attachments") or []
        if not attachments or not attachments[0].get("url"):
            raise RuntimeError("webhook respondeu sem URL de anexo")
        return key, str(attachments[0]["url"])

    def update(self, img: Image.Image, state_key: str) -> str | None:
        """Adds a frame and returns a new URL only when it changes."""
        now = time.monotonic()
        if state_key != self.current_key:
            self.current_key = state_key
            self.frames.clear()
            self._last_sample = 0.0
            cached = self._urls.get(state_key)
            if cached and cached != self._announced_url:
                self._announced_url = cached
                return cached

        if now - self._last_sample >= 1.0 / self.fps:
            self.frames.append(self._crop(img))
            self._last_sample = now

        if self._future is not None and self._future.done():
            try:
                key, url = self._future.result()
            except Exception as exc:
                log.warning("Falha ao publicar GIF pela webhook (%s).", exc)
            else:
                self._urls[key] = url
                log.info("GIF ao vivo publicado para o estado '%s'.", key.rsplit("|", 1)[-1])
                if key == self.current_key and url != self._announced_url:
                    self._announced_url = url
                    self._future = None
                    return url
            self._future = None

        if (
            self._future is None
            and self.current_key not in self._urls
            and len(self.frames) >= self.frame_count
        ):
            self._future_key = self.current_key
            snapshot = [frame.copy() for frame in self.frames]
            self._future = self._executor.submit(self._upload, self.current_key, snapshot)
        return None

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
