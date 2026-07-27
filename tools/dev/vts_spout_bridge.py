"""Loopback-only VTube Studio Spout2 receiver for the Hina desktop widget.

The worker intentionally keeps the GPU/Spout boundary outside Electron.  It
retains only the latest bounded PNG in memory and never writes a captured frame
to disk.  The Electron main process starts it with a fixed sender name and
consumes the small status/HTTP contract; renderer input is never forwarded to
this process.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

SENDER_NAME = "VTubeStudioSpout"
MAX_FRAME_BYTES = 4 * 1024 * 1024
MAX_DIMENSION = 720
TARGET_HZ = 10.0


def emit(kind: str, payload: dict[str, Any]) -> None:
    """Emit a bounded, machine-readable line for the Electron parent."""

    safe = {
        key: value
        for key, value in payload.items()
        if key in {
            "errorCode",
            "message",
            "sender",
            "width",
            "height",
            "frameReady",
            "transparent",
            "port",
        }
    }
    print(f"{kind} {json.dumps(safe, ensure_ascii=False, separators=(',', ':'))}", flush=True)


class FrameStore:
    """Thread-safe latest-only frame store."""

    def __init__(self, sender: str) -> None:
        self._lock = threading.Lock()
        self._frame: bytes | None = None
        self._sequence = 0
        self._last_frame_monotonic = 0.0
        self._width = 0
        self._height = 0
        self._transparent = False
        self._sender = sender
        self._state = "starting"
        self._error_code: str | None = None

    def set_state(self, state: str, error_code: str | None = None) -> None:
        with self._lock:
            self._state = state
            self._error_code = error_code

    def update(
        self,
        frame: bytes,
        width: int,
        height: int,
        transparent: bool,
    ) -> None:
        with self._lock:
            self._frame = frame
            self._sequence += 1
            self._last_frame_monotonic = time.monotonic()
            self._width = width
            self._height = height
            self._transparent = transparent
            self._state = "ready"
            self._error_code = None

    def frame(self) -> bytes | None:
        with self._lock:
            return self._frame

    def status(self) -> dict[str, Any]:
        with self._lock:
            age = (
                None
                if self._last_frame_monotonic <= 0
                else max(0.0, time.monotonic() - self._last_frame_monotonic)
            )
            return {
                "available": True,
                "state": self._state,
                "sender": self._sender,
                "width": self._width,
                "height": self._height,
                "frameReady": self._frame is not None,
                "frameSequence": self._sequence,
                "frameAgeMilliseconds": (
                    None if age is None else round(age * 1000.0, 1)
                ),
                "transparent": self._transparent,
                "errorCode": self._error_code,
            }


class BridgeServer(ThreadingHTTPServer):
    """HTTP server carrying only status and the latest frame."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, store: FrameStore, port: int) -> None:
        super().__init__(("127.0.0.1", port), BridgeHandler)
        self.store = store


class BridgeHandler(BaseHTTPRequestHandler):
    """Bounded loopback HTTP surface consumed by the local widget."""

    server: BridgeServer

    def log_message(self, _format: str, *_args: object) -> None:
        # Requests are ephemeral telemetry and should not become noisy logs.
        return

    def _headers(self, content_type: str, length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()

    def _json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self._headers("application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        path = urlsplit(self.path).path
        if path in {"/health", "/v1/status"}:
            self._json(self.server.store.status())
            return
        if path == "/frame.png":
            frame = self.server.store.frame()
            if frame is None:
                self._json(
                    {
                        "errorCode": "E_SPOUT_FRAME_UNAVAILABLE",
                        "message": "VTube Studio has not published a frame yet.",
                    },
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return
            if len(frame) > MAX_FRAME_BYTES:
                self._json(
                    {
                        "errorCode": "E_SPOUT_FRAME_OVERSIZED",
                        "message": "The latest frame exceeded the bounded response size.",
                    },
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return
            self.send_response(HTTPStatus.OK)
            self._headers("image/png", len(frame))
            self.wfile.write(frame)
            return
        self._json(
            {
                "errorCode": "E_SPOUT_ROUTE",
                "message": "Only /health, /v1/status and /frame.png are available.",
            },
            HTTPStatus.NOT_FOUND,
        )


def _resize_and_encode(image: Any, max_dimension: int) -> tuple[bytes, bool, int, int]:
    """Crop transparent padding and encode a bounded PNG in memory."""

    from PIL import Image  # type: ignore[import-not-found]

    alpha = image.getchannel("A")
    alpha_min, _alpha_max = alpha.getextrema()
    transparent = alpha_min < 250
    if transparent:
        bbox = alpha.getbbox()
        if bbox:
            left, top, right, bottom = bbox
            padding = 24
            image = image.crop(
                (
                    max(0, left - padding),
                    max(0, top - padding),
                    min(image.width, right + padding),
                    min(image.height, bottom + padding),
                ),
            )

    scale = min(1.0, max_dimension / max(image.width, image.height))
    if scale < 1.0:
        image = image.resize(
            (
                max(1, round(image.width * scale)),
                max(1, round(image.height * scale)),
            ),
            resample=Image.Resampling.LANCZOS,
        )

    # A lower compression level keeps the UI responsive while the latest-only
    # contract prevents an unbounded queue of encoded frames.
    for _attempt in range(5):
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=False, compress_level=3)
        data = output.getvalue()
        if len(data) <= MAX_FRAME_BYTES:
            return data, transparent, image.width, image.height
        image = image.resize(
            (
                max(1, round(image.width * 0.78)),
                max(1, round(image.height * 0.78)),
            ),
            resample=Image.Resampling.BILINEAR,
        )
    raise RuntimeError("E_SPOUT_FRAME_OVERSIZED")


def capture_loop(store: FrameStore, stop_event: threading.Event) -> None:
    """Receive Spout textures through ModernGL and publish latest PNG bytes."""

    try:
        import liru  # type: ignore[import-not-found]
        import moderngl  # type: ignore[import-not-found]
        from PIL import Image  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - exercised by startup smoke
        store.set_state("error", "E_SPOUT_DEPENDENCY")
        emit(
            "ERROR",
            {
                "errorCode": "E_SPOUT_DEPENDENCY",
                "message": f"{type(exc).__name__}: {str(exc)[:160]}",
            },
        )
        return

    try:
        context = moderngl.create_standalone_context()
        receiver = liru.Receiver(SENDER_NAME)
        texture: Any | None = None
        texture_size: tuple[int, int] | None = None
        last_emit_state: tuple[str, str | None] | None = None
        receiver_needs_reconnect = False
        last_receiver_reset = time.monotonic()
        next_tick = time.monotonic()

        while not stop_event.is_set():
            senders = receiver.get_sender_list()
            if SENDER_NAME not in senders:
                receiver_needs_reconnect = True
                store.set_state("degraded", "E_SPOUT_SENDER_OFFLINE")
                state = ("degraded", "E_SPOUT_SENDER_OFFLINE")
                if state != last_emit_state:
                    emit(
                        "STATUS",
                        {
                            "errorCode": "E_SPOUT_SENDER_OFFLINE",
                            "message": "VTubeStudioSpout is not broadcasting.",
                            "sender": SENDER_NAME,
                        },
                    )
                    last_emit_state = state
                stop_event.wait(0.35)
                continue

            now = time.monotonic()
            width, height = int(receiver.width), int(receiver.height)
            dimensions_invalid = (
                width <= 0
                or height <= 0
                or width > 8192
                or height > 8192
            )
            if (
                receiver_needs_reconnect
                or (
                    dimensions_invalid
                    and now - last_receiver_reset >= 1.0
                )
            ):
                # liru resolves the shared texture dimensions when Receiver is
                # constructed. If VTube Studio starts after Hina, the original
                # receiver can keep 0x0 dimensions even after the sender name
                # appears. Recreate only on the offline→online edge or after a
                # bounded cooldown so normal frame capture never churns native
                # Spout handles.
                receiver = liru.Receiver(SENDER_NAME)
                texture = None
                texture_size = None
                receiver_needs_reconnect = False
                last_receiver_reset = now
                width, height = int(receiver.width), int(receiver.height)

            if width <= 0 or height <= 0 or width > 8192 or height > 8192:
                store.set_state("degraded", "E_SPOUT_DIMENSIONS")
                stop_event.wait(0.2)
                continue
            if texture is None or texture_size != (width, height):
                texture = context.texture((width, height), 4)
                texture_size = (width, height)

            receiver.receive_texture(texture.glo)
            # The OpenGL texture returned by liru is already top-left oriented
            # on the Windows WGL path used by VTube Studio/ModernGL.
            raw = texture.read(alignment=1)
            image = Image.frombytes("RGBA", (width, height), raw)
            if image.getchannel("A").getextrema()[1] == 0:
                # Spout allocates the shared texture before VTube Studio has
                # copied its first real frame. Never promote that zero-filled
                # bootstrap texture as a healthy transparent avatar.
                stop_event.wait(0.05)
                continue
            encoded, transparent, output_width, output_height = _resize_and_encode(
                image,
                MAX_DIMENSION,
            )
            store.update(encoded, output_width, output_height, transparent)
            state = ("ready", None)
            if state != last_emit_state:
                emit(
                    "STATUS",
                    {
                        "sender": SENDER_NAME,
                        "width": output_width,
                        "height": output_height,
                        "frameReady": True,
                        "transparent": transparent,
                    },
                )
                last_emit_state = state

            next_tick += 1.0 / TARGET_HZ
            delay = next_tick - time.monotonic()
            if delay > 0:
                stop_event.wait(delay)
            else:
                next_tick = time.monotonic()
    except Exception as exc:  # pragma: no cover - platform/native failure
        store.set_state("error", "E_SPOUT_RECEIVER")
        emit(
            "ERROR",
            {
                "errorCode": "E_SPOUT_RECEIVER",
                "message": f"{type(exc).__name__}: {str(exc)[:160]}",
            },
        )
    finally:
        # Drop Python references before the parent terminates the process so
        # the native Spout/GL handles are released deterministically.
        try:
            del texture, receiver, context
        except UnboundLocalError:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--sender", default=SENDER_NAME)
    return parser.parse_args()


def main() -> int:
    if sys.version_info < (3, 13):
        emit(
            "ERROR",
            {
                "errorCode": "E_SPOUT_PYTHON_VERSION",
                "message": "The pinned liru wheel requires Python 3.13 or newer.",
            },
        )
        return 1
    args = parse_args()
    if args.sender != SENDER_NAME:
        emit(
            "ERROR",
            {
                "errorCode": "E_SPOUT_SENDER_POLICY",
                "message": "Only VTubeStudioSpout is allowed.",
            },
        )
        return 1

    store = FrameStore(SENDER_NAME)
    try:
        server = BridgeServer(store, args.port)
    except Exception as exc:
        emit(
            "ERROR",
            {
                "errorCode": "E_SPOUT_HTTP",
                "message": f"{type(exc).__name__}: {str(exc)[:160]}",
            },
        )
        return 1
    stop_event = threading.Event()
    capture_thread = threading.Thread(
        target=capture_loop,
        args=(store, stop_event),
        name="hina-spout-capture",
        daemon=True,
    )
    capture_thread.start()
    emit(
        "READY",
        {
            "port": int(server.server_port),
            "sender": SENDER_NAME,
            "message": "Loopback Spout2 bridge is listening.",
        },
    )
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.shutdown()
        capture_thread.join(timeout=2.0)
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
