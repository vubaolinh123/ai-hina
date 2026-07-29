from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

from .errors import PerceptionError


VISION_QUALITY_CAPACITY = 100
VISION_QUALITY_MINIMUM_RATED_SAMPLES = 20
VISION_QUALITY_TARGET_PERCENT = 85.0
VISION_QUALITY_RATINGS = frozenset({"correct", "partial", "incorrect"})
_RATING_WEIGHTS = {
    "correct": 1.0,
    "partial": 0.5,
    "incorrect": 0.0,
}


@dataclass(slots=True)
class _VisionQualitySample:
    provider: str
    model: str | None
    state: str
    confidence: float
    rating: str | None = None


class VisionQualityLedger:
    """Bounded session-only owner ratings without image or summary retention."""

    def __init__(self, capacity: int = VISION_QUALITY_CAPACITY) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("vision quality capacity must be a positive integer")
        self._capacity = capacity
        self._samples: dict[str, _VisionQualitySample] = {}

    def register(
        self,
        observation_id: str,
        *,
        provider: str,
        model: str | None,
        state: str,
        confidence: float,
    ) -> None:
        _validate_uuid(observation_id)
        normalized_provider = _bounded_text(provider, "provider", 64)
        normalized_model = (
            _bounded_text(model, "model", 160) if model is not None else None
        )
        if state not in {"ready", "abstained"}:
            raise PerceptionError(
                "E_PERCEPTION_REQUEST",
                "only ready or abstained Vision observations can enter scene QA",
            )
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not 0.0 <= float(confidence) <= 1.0
        ):
            raise PerceptionError(
                "E_PERCEPTION_REQUEST",
                "Vision scene-QA confidence is invalid",
            )
        existing = self._samples.pop(observation_id, None)
        self._samples[observation_id] = _VisionQualitySample(
            provider=normalized_provider,
            model=normalized_model,
            state=state,
            confidence=float(confidence),
            rating=existing.rating if existing is not None else None,
        )
        while len(self._samples) > self._capacity:
            del self._samples[next(iter(self._samples))]

    def review(self, observation_id: str, rating: str) -> dict[str, object]:
        _validate_uuid(observation_id)
        if not isinstance(rating, str) or rating not in VISION_QUALITY_RATINGS:
            raise PerceptionError(
                "E_PERCEPTION_REQUEST",
                "Vision scene-QA rating must be correct, partial or incorrect",
            )
        sample = self._samples.get(observation_id)
        if sample is None:
            raise PerceptionError(
                "E_PERCEPTION_REQUEST",
                "Vision observation is unavailable for this runtime QA session",
            )
        replaced = sample.rating is not None
        sample.rating = rating
        return {
            "observationId": observation_id,
            "rating": rating,
            "replaced": replaced,
        }

    def status(
        self,
        *,
        provider: str | None,
        model: str | None,
    ) -> dict[str, object]:
        profile_samples = [
            sample
            for sample in self._samples.values()
            if sample.provider == provider and sample.model == model
        ]
        rated = [sample for sample in profile_samples if sample.rating is not None]
        ratings = {
            rating: sum(1 for sample in rated if sample.rating == rating)
            for rating in ("correct", "partial", "incorrect")
        }
        weighted = sum(_RATING_WEIGHTS.get(sample.rating or "", 0.0) for sample in rated)
        score = round(weighted / len(rated) * 100.0, 1) if rated else None
        candidate_ready = (
            len(rated) >= VISION_QUALITY_MINIMUM_RATED_SAMPLES
            and score is not None
            and score >= VISION_QUALITY_TARGET_PERCENT
        )
        return {
            "schemaVersion": "1.0",
            "storage": "memory-only",
            "persistsAfterRestart": False,
            "storesPixels": False,
            "storesSummaries": False,
            "capacity": self._capacity,
            "profile": {
                "provider": provider,
                "model": model,
            },
            "registeredSamples": len(profile_samples),
            "ratedSamples": len(rated),
            "unratedSamples": len(profile_samples) - len(rated),
            "ratings": ratings,
            "weightedScorePercent": score,
            "targetPercent": VISION_QUALITY_TARGET_PERCENT,
            "minimumRatedSamples": VISION_QUALITY_MINIMUM_RATED_SAMPLES,
            "candidateTargetMet": candidate_ready,
            "promotionApproved": False,
            "allProfilesRegisteredSamples": len(self._samples),
        }


def _validate_uuid(value: str) -> None:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise PerceptionError(
            "E_PERCEPTION_REQUEST",
            "Vision observation ID is invalid",
        ) from exc
    if str(parsed) != value:
        raise PerceptionError(
            "E_PERCEPTION_REQUEST",
            "Vision observation ID must use canonical UUID form",
        )


def _bounded_text(value: str, name: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise PerceptionError(
            "E_PERCEPTION_REQUEST",
            f"Vision scene-QA {name} is invalid",
        )
    return value
