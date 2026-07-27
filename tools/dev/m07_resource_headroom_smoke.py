from __future__ import annotations

import http.client
import json
import time
from uuid import uuid4


HOST = "127.0.0.1"
PORT = 8765


def _request(method: str, path: str, payload: dict[str, object] | None = None) -> tuple[int, dict[str, str], bytes]:
    body = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if payload is not None
        else None
    )
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
        headers["Content-Length"] = str(len(body))
    connection = http.client.HTTPConnection(HOST, PORT, timeout=300)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        response_headers = {name.lower(): value for name, value in response.getheaders()}
        response_body = response.read(32 * 1024 * 1024)
        return response.status, response_headers, response_body
    finally:
        connection.close()


def _json(method: str, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    status, _headers, body = _request(method, path, payload)
    data = json.loads(body.decode("utf-8"))
    if status != 200:
        raise RuntimeError(f"{method} {path} returned HTTP {status}: {data}")
    if not isinstance(data, dict):
        raise RuntimeError(f"{method} {path} returned a non-object")
    return data


def _tts(text: str, session_id: str) -> tuple[float, int]:
    started = time.monotonic()
    status, headers, wav = _request(
        "POST",
        "/v1/tts/synthesis",
        {
            "text": text,
            "utteranceId": str(uuid4()),
            "sessionId": session_id,
            "source": "owner.console",
        },
    )
    if status != 200:
        try:
            detail = json.loads(wav.decode("utf-8"))
        except Exception:
            detail = {"rawBytes": len(wav)}
        raise RuntimeError(f"TTS returned HTTP {status}: {detail}")
    if not wav.startswith(b"RIFF") or b"WAVE" not in wav[:16]:
        raise RuntimeError("TTS response was not a WAV")
    if headers.get("content-type") != "audio/wav":
        raise RuntimeError("TTS response content type was not audio/wav")
    return time.monotonic() - started, len(wav)


def main() -> int:
    session_id = str(uuid4())
    first_tts_seconds, first_tts_bytes = _tts(
        "Hina đang giữ mô hình giọng nói trên GPU trước khi bắt đầu trò chuyện.",
        session_id,
    )
    resident = _json("GET", "/v1/tts/status")
    turn = _json(
        "POST",
        "/v1/chat/turns",
        {
            "sessionId": session_id,
            "source": "owner.console",
            "text": "Chỉ trả lời một câu ngắn để kiểm tra bộ nhớ GPU.",
        },
    )
    turn_id = str(turn["turnId"])
    deadline = time.monotonic() + 120
    while turn.get("outcome") == "running" and time.monotonic() < deadline:
        time.sleep(0.2)
        turn = _json("GET", f"/v1/chat/turns/{turn_id}")
    if turn.get("outcome") != "completed":
        raise RuntimeError(
            f"chat did not complete: outcome={turn.get('outcome')} error={turn.get('errorCode')}"
        )

    resource = _json("GET", "/v1/model/status")
    resource_state = resource["resource"]
    telemetry = resource_state["telemetry"]
    if int(telemetry["freeVramMiB"]) < int(resource_state["headroomMiB"]):
        raise RuntimeError("live VRAM fell below the mandatory headroom after chat")

    second_tts_seconds, second_tts_bytes = _tts(
        "Lượt chat đã hoàn tất mà không gặp lỗi dung lượng tài nguyên.",
        session_id,
    )
    final_tts = _json("GET", "/v1/tts/status")
    result = {
        "passed": True,
        "chatOutcome": turn["outcome"],
        "chatErrorCode": turn.get("errorCode"),
        "ttsProvider": final_tts["configured"]["provider"],
        "ttsModel": final_tts["configured"]["model"],
        "ttsResidentBeforeChat": resident["provider"]["modelLoaded"],
        "ttsLeaseBeforeChat": resident["provider"]["resourceLease"]["state"],
        "ttsResidentAfterChat": final_tts["provider"]["modelLoaded"],
        "ttsLeaseAfterChat": final_tts["provider"]["resourceLease"]["state"],
        "firstTtsSeconds": round(first_tts_seconds, 3),
        "secondTtsSeconds": round(second_tts_seconds, 3),
        "firstTtsBytes": first_tts_bytes,
        "secondTtsBytes": second_tts_bytes,
        "freeVramMiB": telemetry["freeVramMiB"],
        "headroomMiB": resource_state["headroomMiB"],
        "activeLeasesAfterChat": resource_state["activeLeases"],
    }
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
