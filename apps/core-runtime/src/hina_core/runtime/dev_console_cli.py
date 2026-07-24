from __future__ import annotations

import argparse
import asyncio
import json
import os
import webbrowser
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
            static_dir=args.static_dir,
            audit_log=args.audit_log,
            safety_manifest=args.safety_manifest,
            persona_spec=args.persona_spec,
            memory_database=args.memory_database,
            memory_index=args.memory_index,
        ),
        build_commit=os.environ.get("HINA_BUILD_COMMIT", "development"),
    )
    await application.start()
    host, port = application.address
    authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    console_url = f"http://{authority}/"
    print(
        json.dumps(
            {
                "status": "ready",
                "application": "hina-dev-console",
                "console": console_url,
                "control": f"http://{authority}/v1/health",
                "realtime": f"ws://{authority}/v1/realtime",
                "protocol": "hina.realtime.v1",
                "database": str(args.database.resolve()),
                "errorLog": str(args.log.resolve()),
                "auditLog": str(args.audit_log.resolve()),
                "safetyManifest": str(args.safety_manifest.resolve()),
                "personaSpec": str(args.persona_spec.resolve()),
                "memoryDatabase": str(args.memory_database.resolve()),
                "memoryIndex": str(args.memory_index.resolve()),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if args.open_browser:
        webbrowser.open(console_url)
    if args.startup_check:
        await application.stop()
        return
    try:
        await application.serve_forever()
    finally:
        await application.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the local Hina Dev Console.")
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
        "--static-dir",
        type=Path,
        default=ROOT / "apps" / "dev-console" / "public",
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
    parser.add_argument(
        "--memory-database",
        type=Path,
        default=ROOT / "var" / "data" / "hina-memory.sqlite3",
    )
    parser.add_argument(
        "--memory-index",
        type=Path,
        default=ROOT / "var" / "data" / "hina-memory-qdrant",
    )
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument(
        "--startup-check",
        action="store_true",
        help="start the real application, print readiness, then close cleanly",
    )
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
