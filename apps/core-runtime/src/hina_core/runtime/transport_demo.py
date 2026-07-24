from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any

from .durable import DurableStore
from .error_log import JsonlErrorLogger
from .transport import BinaryMediaFrame, ControlPlaneServer, TransportConfig
from .transport_client import RealtimeClient, get_json


ROOT = Path(__file__).resolve().parents[5]
DEFAULT_DATABASE = ROOT / "var" / "data" / "m01-s4-demo.sqlite3"
DEFAULT_LOG = ROOT / "var" / "logs" / "m01-s4-demo.jsonl"
FIXTURE = ROOT / "packages" / "contracts" / "fixtures" / "golden" / "turn.media.echo.json"


def _demo_envelope() -> dict[str, Any]:
    envelope = json.loads(FIXTURE.read_text(encoding="utf-8"))
    envelope["eventId"] = str(uuid.uuid5(uuid.NAMESPACE_URL, "hina-m01-s4-event-0"))
    envelope["streamId"] = "demo-realtime-stream"
    envelope["sequence"] = 0
    envelope["idempotencyKey"] = "demo-realtime-0"
    envelope["payload"]["message"] = "Xin chào từ realtime transport"
    envelope["payload"]["metadata"] = {"demo": "m01-s4", "sequence": 0}
    envelope["media"] = []
    return envelope


def _reset_database(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        candidate.unlink(missing_ok=True)


async def run_transport_demo(database_path: Path, log_path: Path) -> dict[str, Any]:
    _reset_database(database_path)
    log_path.unlink(missing_ok=True)
    logger = JsonlErrorLogger(
        log_path,
        build_commit=os.environ.get("HINA_BUILD_COMMIT", "development"),
    )
    with DurableStore(database_path) as store:
        server = ControlPlaneServer(
            TransportConfig(port=0),
            durable_store=store,
            error_logger=logger,
        )
        await server.start()
        host, port = server.address
        try:
            health, version, config = await asyncio.gather(
                get_json(host, port, "/v1/health"),
                get_json(host, port, "/v1/version"),
                get_json(host, port, "/v1/config"),
            )

            async with await RealtimeClient.connect(host, port) as client:
                envelope = _demo_envelope()
                await client.send_json({"kind": "event", "envelope": envelope})
                accepted = await client.receive_json()
                await client.send_json({"kind": "event", "envelope": envelope})
                duplicate = await client.receive_json()

                await client.send_json(
                    {
                        "kind": "resume",
                        "streamId": "demo-realtime-stream",
                        "afterSequence": -1,
                    }
                )
                resumed = await client.receive_json()

                media = BinaryMediaFrame(
                    media_id=uuid.uuid5(uuid.NAMESPACE_URL, "hina-m01-s4-media"),
                    sequence=7,
                    payload=b"\x00\x01HINA-PCM-DEMO\xff",
                    end_of_stream=True,
                )
                await client.send_binary(media.encode())
                binary_opcode, binary_raw = await client.receive()
                returned_media = BinaryMediaFrame.decode(binary_raw)

                await client.send_json(
                    {
                        "kind": "event",
                        "envelope": {"type": "hina.unknown.v1"},
                    }
                )
                rejected = await client.receive_json()
            snapshot = store.snapshot()
        finally:
            await server.stop()

    records = (
        [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        if log_path.exists()
        else []
    )
    return {
        "status": "ok",
        "server": {
            "host": host,
            "port": port,
            "loopbackOnly": config.body["loopbackOnly"],
        },
        "control": {
            "health": health.body["status"],
            "version": version.body["controlApi"],
            "configStatus": config.status,
        },
        "realtime": {
            "protocol": version.body["realtimeProtocol"],
            "eventAccepted": accepted["kind"] == "event.accepted",
            "durable": accepted["durable"],
            "duplicateSuppressed": duplicate["deduplicated"],
            "journalRows": snapshot.journal,
            "resumedSequences": [
                event["sequence"] for event in resumed["events"]
            ],
            "invalidEventCode": rejected["errorCode"],
        },
        "binary": {
            "websocketOpcode": binary_opcode,
            "mediaId": str(returned_media.media_id),
            "sequence": returned_media.sequence,
            "bytes": len(returned_media.payload),
            "payloadMatches": returned_media.payload == media.payload,
            "endOfStream": returned_media.end_of_stream,
            "base64JsonUsed": False,
        },
        "errorLog": {
            "path": str(log_path),
            "records": len(records),
            "codes": [record["errorCode"] for record in records],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the visible M01-S4 control/realtime demo.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    args = parser.parse_args()
    result = asyncio.run(
        run_transport_demo(args.database.resolve(), args.log.resolve())
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
