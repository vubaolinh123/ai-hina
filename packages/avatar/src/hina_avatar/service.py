from __future__ import annotations

import math
import threading
from collections import deque
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


HISTORY_LIMIT = 256
ALLOWED_EXPRESSIONS = frozenset(
    {"neutral", "happy", "curious", "focused", "concerned"}
)
ALLOWED_VISEMES = frozenset({"sil", "A", "I", "U", "E", "O"})
TRUSTED_SOURCES = frozenset(
    {
        "owner.console",
        "conversation.service",
        "speech.output",
        "runtime.lifecycle",
    }
)
ALLOWED_MODES = frozenset({"runtime", "manual-preview", "tts-playback"})
_CUE_FIELDS = frozenset(
    {
        "source",
        "state",
        "expression",
        "viseme",
        "intensity",
        "mode",
        "correlationId",
        "sessionId",
        "turnId",
        "utteranceId",
    }
)


class AvatarState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    ERROR = "error"


_DIRECT_TRANSITIONS: dict[AvatarState, frozenset[AvatarState]] = {
    AvatarState.IDLE: frozenset(AvatarState),
    AvatarState.LISTENING: frozenset(
        {
            AvatarState.IDLE,
            AvatarState.LISTENING,
            AvatarState.THINKING,
            AvatarState.SPEAKING,
            AvatarState.INTERRUPTED,
            AvatarState.ERROR,
        }
    ),
    AvatarState.THINKING: frozenset(
        {
            AvatarState.IDLE,
            AvatarState.LISTENING,
            AvatarState.THINKING,
            AvatarState.SPEAKING,
            AvatarState.INTERRUPTED,
            AvatarState.ERROR,
        }
    ),
    AvatarState.SPEAKING: frozenset(
        {
            AvatarState.IDLE,
            AvatarState.LISTENING,
            AvatarState.THINKING,
            AvatarState.SPEAKING,
            AvatarState.INTERRUPTED,
            AvatarState.ERROR,
        }
    ),
    AvatarState.INTERRUPTED: frozenset(
        {AvatarState.IDLE, AvatarState.LISTENING, AvatarState.INTERRUPTED}
    ),
    AvatarState.ERROR: frozenset(
        {AvatarState.IDLE, AvatarState.LISTENING, AvatarState.ERROR}
    ),
}

_STATE_EXPRESSIONS: dict[AvatarState, str] = {
    AvatarState.IDLE: "neutral",
    AvatarState.LISTENING: "curious",
    AvatarState.THINKING: "focused",
    AvatarState.SPEAKING: "happy",
    AvatarState.INTERRUPTED: "concerned",
    AvatarState.ERROR: "concerned",
}


class AvatarError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class AvatarStageService:
    """Thread-safe source of truth for renderer-safe avatar state.

    Snapshots contain identifiers and presentation cues only. Conversation text,
    model output, database handles and provider objects never cross this boundary.
    """

    def __init__(self, *, history_limit: int = HISTORY_LIMIT) -> None:
        if history_limit < 1 or history_limit > HISTORY_LIMIT:
            raise ValueError(f"history_limit must be between 1 and {HISTORY_LIMIT}")
        self._lock = threading.RLock()
        self._history: deque[dict[str, Any]] = deque(maxlen=history_limit)
        self._sequence = 0
        self._current = self._make_snapshot(
            state=AvatarState.IDLE,
            expression="neutral",
            viseme="sil",
            intensity=0.0,
            source="runtime.lifecycle",
            mode="runtime",
            identifiers={},
        )
        self._history.append(dict(self._current))

    def status(self) -> dict[str, Any]:
        with self._lock:
            current = dict(self._current)
            history_depth = len(self._history)
        return {
            "schemaVersion": "1.0",
            "available": True,
            **current,
            "historyDepth": history_depth,
            "historyLimit": self._history.maxlen,
            "trustedSources": sorted(TRUSTED_SOURCES),
            "allowedStates": [str(state) for state in AvatarState],
            "allowedExpressions": sorted(ALLOWED_EXPRESSIONS),
            "allowedVisemes": sorted(ALLOWED_VISEMES),
            "rendererContract": {
                "databaseAccess": False,
                "modelAccess": False,
                "providerAccess": False,
                "controlPlaneOnly": True,
            },
            "asset": {
                "id": "hina.code-avatar.v1",
                "displayName": "Hina code-native fallback",
                "type": "code-native-svg",
                "manifest": "assets/manifests/hina-code-avatar.v1.json",
                "provenance": "repository-original",
                "vrmLoaded": False,
                "live2dLoaded": False,
            },
            "lipSync": {
                "mode": "observed-audio-spectral-viseme",
                "phonemeAccurate": False,
            },
        }

    def history(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(dict(item) for item in self._history)

    def apply_cue(self, raw: Any) -> dict[str, Any]:
        cue = _parse_cue(raw)
        target = cue["state"]
        with self._lock:
            path = self._transition_path(self._current["state"], target)
            for index, state in enumerate(path):
                final = index == len(path) - 1
                expression = (
                    cue["expression"] if final else _STATE_EXPRESSIONS[state]
                )
                viseme = cue["viseme"] if final else "sil"
                intensity = cue["intensity"] if final else 0.0
                self._sequence += 1
                self._current = self._make_snapshot(
                    state=state,
                    expression=expression,
                    viseme=viseme,
                    intensity=intensity,
                    source=cue["source"],
                    mode=cue["mode"],
                    identifiers=cue["identifiers"],
                )
                self._history.append(dict(self._current))
            return self.status()

    def reset(self, *, source: str = "owner.console") -> dict[str, Any]:
        return self.apply_cue(
            {
                "source": source,
                "state": "idle",
                "expression": "neutral",
                "viseme": "sil",
                "intensity": 0,
                "mode": "runtime" if source == "runtime.lifecycle" else "manual-preview",
            }
        )

    def observe_turn_state(self, event: Any) -> dict[str, Any]:
        if not isinstance(event, dict):
            raise AvatarError("E_AVATAR_CUE", "turn state event must be an object")
        return self.apply_cue(
            {
                "source": "conversation.service",
                "state": event.get("state"),
                "mode": "runtime",
                "correlationId": event.get("correlationId"),
                "sessionId": event.get("sessionId"),
                "turnId": event.get("turnId"),
            }
        )

    @staticmethod
    def _transition_path(current_raw: str, target: AvatarState) -> tuple[AvatarState, ...]:
        current = AvatarState(current_raw)
        if target in _DIRECT_TRANSITIONS[current]:
            return (target,)
        return (AvatarState.IDLE, target)

    def _make_snapshot(
        self,
        *,
        state: AvatarState,
        expression: str,
        viseme: str,
        intensity: float,
        source: str,
        mode: str,
        identifiers: dict[str, str | None],
    ) -> dict[str, Any]:
        return {
            "sequence": self._sequence,
            "state": str(state),
            "expression": expression,
            "viseme": viseme,
            "intensity": round(intensity, 4),
            "source": source,
            "mode": mode,
            "updatedAt": _timestamp(),
            "correlationId": identifiers.get("correlationId"),
            "sessionId": identifiers.get("sessionId"),
            "turnId": identifiers.get("turnId"),
            "utteranceId": identifiers.get("utteranceId"),
        }


def _parse_cue(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise AvatarError("E_AVATAR_CUE", "avatar cue must be an object")
    if not set(raw).issubset(_CUE_FIELDS) or "source" not in raw or "state" not in raw:
        raise AvatarError("E_AVATAR_CUE", "avatar cue fields are invalid")
    source = raw.get("source")
    if not isinstance(source, str) or source not in TRUSTED_SOURCES:
        raise AvatarError("E_AVATAR_SOURCE", "avatar cue source is not trusted")
    try:
        state = AvatarState(raw.get("state"))
    except (TypeError, ValueError) as exc:
        raise AvatarError("E_AVATAR_STATE", "avatar state is invalid") from exc
    expression = raw.get("expression")
    if expression is None:
        normalized_expression = _STATE_EXPRESSIONS[state]
    elif isinstance(expression, str) and expression in ALLOWED_EXPRESSIONS:
        normalized_expression = expression
    else:
        normalized_expression = "neutral"
    viseme = raw.get("viseme", "sil")
    normalized_viseme = viseme if isinstance(viseme, str) and viseme in ALLOWED_VISEMES else "sil"
    intensity = raw.get("intensity", 0.0)
    if isinstance(intensity, bool) or not isinstance(intensity, (int, float)):
        normalized_intensity = 0.0
    else:
        numeric = float(intensity)
        normalized_intensity = min(1.0, max(0.0, numeric)) if math.isfinite(numeric) else 0.0
    mode = raw.get("mode", "runtime")
    if not isinstance(mode, str) or mode not in ALLOWED_MODES:
        raise AvatarError("E_AVATAR_CUE", "avatar cue mode is invalid")
    identifiers = {
        name: _identifier(raw.get(name), name)
        for name in ("correlationId", "sessionId", "turnId", "utteranceId")
    }
    return {
        "source": source,
        "state": state,
        "expression": normalized_expression,
        "viseme": normalized_viseme,
        "intensity": normalized_intensity,
        "mode": mode,
        "identifiers": identifiers,
    }


def _identifier(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 128:
        raise AvatarError("E_AVATAR_CUE", f"{field} is invalid")
    return value


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
