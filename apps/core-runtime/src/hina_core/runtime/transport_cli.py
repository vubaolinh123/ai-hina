from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from .application import HinaRuntimeApplication, RuntimePaths
from .transport import TransportConfig


ROOT = Path(__file__).resolve().parents[5]


async def _run(args: argparse.Namespace) -> None:
    application = HinaRuntimeApplication(
        TransportConfig(host=args.host, port=args.port),
        RuntimePaths(
            database=args.database,
            error_log=args.log,
            audit_log=args.audit_log,
            safety_manifest=args.safety_manifest,
            persona_spec=args.persona_spec,
        ),
        build_commit=os.environ.get("HINA_BUILD_COMMIT", "development"),
    )
    await application.start()
    host, port = application.address
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
                "auditLog": str(args.audit_log.resolve()),
                "safetyManifest": str(args.safety_manifest.resolve()),
                "personaSpec": str(args.persona_spec.resolve()),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    try:
        await application.serve_forever()
    finally:
        await application.stop()


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
    parser.add_argument(
        "--audit-log",
        type=Path,
        default=ROOT / "var" / "audit" / "hina-safety.jsonl",
    )
    parser.add_argument(
        "--safety-manifest",
        type=Path,
        default=ROOT / "packages" / "safety-policy" / "manifests" / "default.v1.json",
    )
    parser.add_argument(
        "--persona-spec",
        type=Path,
        default=ROOT / "packages" / "text-brain" / "personas" / "hina.v1.json",
    )
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
