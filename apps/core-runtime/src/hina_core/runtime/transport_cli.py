from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from .durable import DurableStore
from .error_log import JsonlErrorLogger
from .transport import ControlPlaneServer, TransportConfig


ROOT = Path(__file__).resolve().parents[5]


async def _run(args: argparse.Namespace) -> None:
    logger = JsonlErrorLogger(
        args.log.resolve(),
        build_commit=os.environ.get("HINA_BUILD_COMMIT", "development"),
    )
    with DurableStore(args.database.resolve()) as store:
        server = ControlPlaneServer(
            TransportConfig(host=args.host, port=args.port),
            durable_store=store,
            error_logger=logger,
        )
        await server.start()
        host, port = server.address
        authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        print(
            json.dumps(
                {
                    "status": "ready",
                    "control": f"http://{authority}/v1/health",
                    "realtime": f"ws://{authority}/v1/realtime",
                    "protocol": "hina.realtime.v1",
                    "database": str(args.database.resolve()),
                    "errorLog": str(args.log.resolve()),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        try:
            await server.serve_forever()
        finally:
            await server.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the local Hina control plane.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--database",
        type=Path,
        default=ROOT / "var" / "data" / "hina-runtime.sqlite3",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=ROOT / "var" / "logs" / "hina-runtime.jsonl",
    )
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
