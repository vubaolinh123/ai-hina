from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

from .errors import PerceptionError


VISION_QUALITY_CAPACITY = 100
VISION_QUALITY_MINIMUM_RATED_SAMPLES = 20
VISION_QUALITY_TARGET_PERCENT = 85.0
VISION_QUALITY_RELIABILITY_BIN_COUNT = 5
VISION_QUALITY_RATINGS = frozenset({"correct", "partial", "incorrect"})
VISION_SCENE_TAGS = (
    "gameplay",
    "menu_hud",
    "chat_text",
    "desktop_ui",
    "motion_effects",
    "dark_occluded",
)
VISION_SCENE_TAG_SET = frozenset(VISION_SCENE_TAGS)
VISION_SCENE_MINIMUM_TAGS = 1
VISION_SCENE_MAXIMUM_TAGS = 3
VISION_SCENE_MINIMUM_COVERED_TAGS = 4
VISION_SCENE_MINIMUM_SAMPLES_PER_TAG = 2
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
    scene_tags: tuple[str, ...] = ()


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
            scene_tags=existing.scene_tags if existing is not None else (),
        )
        while len(self._samples) > self._capacity:
            del self._samples[next(iter(self._samples))]

    def review(
        self,
        observation_id: str,
        rating: str,
        scene_tags: object,
    ) -> dict[str, object]:
        _validate_uuid(observation_id)
        if not isinstance(rating, str) or rating not in VISION_QUALITY_RATINGS:
            raise PerceptionError(
                "E_PERCEPTION_REQUEST",
                "Vision scene-QA rating must be correct, partial or incorrect",
            )
        normalized_scene_tags = _normalize_scene_tags(scene_tags)
        sample = self._samples.get(observation_id)
        if sample is None:
            raise PerceptionError(
                "E_PERCEPTION_REQUEST",
                "Vision observation is unavailable for this runtime QA session",
            )
        replaced = sample.rating is not None
        sample.rating = rating
        sample.scene_tags = normalized_scene_tags
        return {
            "observationId": observation_id,
            "rating": rating,
            "sceneTags": list(normalized_scene_tags),
            "replaced": replaced,
        }

    def reset_profile(
        self,
        *,
        provider: str | None,
        model: str | None,
    ) -> dict[str, object]:
        normalized_provider = (
            _bounded_text(provider, "provider", 64)
            if provider is not None
            else None
        )
        normalized_model = (
            _bounded_text(model, "model", 160) if model is not None else None
        )
        matching_ids = [
            observation_id
            for observation_id, sample in self._samples.items()
            if (
                sample.provider == normalized_provider
                and sample.model == normalized_model
            )
        ]
        for observation_id in matching_ids:
            del self._samples[observation_id]
        return {
            "removedSamples": len(matching_ids),
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
        states = {
            state: sum(1 for sample in profile_samples if sample.state == state)
            for state in ("ready", "abstained")
        }
        scene_tag_counts = {
            tag: sum(1 for sample in rated if tag in sample.scene_tags)
            for tag in VISION_SCENE_TAGS
        }
        covered_scene_tags = sum(
            1
            for count in scene_tag_counts.values()
            if count >= VISION_SCENE_MINIMUM_SAMPLES_PER_TAG
        )
        diversity_target_met = (
            covered_scene_tags >= VISION_SCENE_MINIMUM_COVERED_TAGS
        )
        weighted = sum(_RATING_WEIGHTS.get(sample.rating or "", 0.0) for sample in rated)
        score = round(weighted / len(rated) * 100.0, 1) if rated else None
        candidate_ready = (
            len(rated) >= VISION_QUALITY_MINIMUM_RATED_SAMPLES
            and score is not None
            and score >= VISION_QUALITY_TARGET_PERCENT
            and diversity_target_met
        )
        return {
            "schemaVersion": "1.1",
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
            "states": states,
            "abstentionRatePercent": (
                round(states["abstained"] / len(profile_samples) * 100.0, 1)
                if profile_samples
                else None
            ),
            "weightedScorePercent": score,
            "targetPercent": VISION_QUALITY_TARGET_PERCENT,
            "minimumRatedSamples": VISION_QUALITY_MINIMUM_RATED_SAMPLES,
            "sceneDiversity": {
                "fixedAllowlist": list(VISION_SCENE_TAGS),
                "counts": scene_tag_counts,
                "coveredTags": covered_scene_tags,
                "minimumCoveredTags": VISION_SCENE_MINIMUM_COVERED_TAGS,
                "minimumSamplesPerCoveredTag": VISION_SCENE_MINIMUM_SAMPLES_PER_TAG,
                "targetMet": diversity_target_met,
                "aggregateOnly": True,
            },
            "candidateTargetMet": candidate_ready,
            "promotionApproved": False,
            "calibration": _calibration_status(rated),
            "allProfilesRegisteredSamples": len(self._samples),
        }


def _calibration_status(
    rated: list[_VisionQualitySample],
) -> dict[str, object]:
    bins: list[list[_VisionQualitySample]] = [
        [] for _ in range(VISION_QUALITY_RELIABILITY_BIN_COUNT)
    ]
    for sample in rated:
        index = min(
            VISION_QUALITY_RELIABILITY_BIN_COUNT - 1,
            int(sample.confidence * VISION_QUALITY_RELIABILITY_BIN_COUNT),
        )
        bins[index].append(sample)

    sample_count = len(rated)
    mean_confidence = (
        sum(sample.confidence for sample in rated) / sample_count
        if sample_count
        else None
    )
    observed = (
        sum(_RATING_WEIGHTS[sample.rating or "incorrect"] for sample in rated)
        / sample_count
        if sample_count
        else None
    )
    absolute_error = (
        sum(
            abs(sample.confidence - _RATING_WEIGHTS[sample.rating or "incorrect"])
            for sample in rated
        )
        / sample_count
        if sample_count
        else None
    )
    brier = (
        sum(
            (
                sample.confidence
                - _RATING_WEIGHTS[sample.rating or "incorrect"]
            )
            ** 2
            for sample in rated
        )
        / sample_count
        if sample_count
        else None
    )
    return {
        "calibrated": False,
        "diagnosticOnly": True,
        "sampleCount": sample_count,
        "minimumSamples": VISION_QUALITY_MINIMUM_RATED_SAMPLES,
        "sufficientEvidence": (
            sample_count >= VISION_QUALITY_MINIMUM_RATED_SAMPLES
        ),
        "meanConfidencePercent": (
            round(mean_confidence * 100.0, 1)
            if mean_confidence is not None
            else None
        ),
        "meanObservedScorePercent": (
            round(observed * 100.0, 1) if observed is not None else None
        ),
        "meanAbsoluteErrorPercent": (
            round(absolute_error * 100.0, 1)
            if absolute_error is not None
            else None
        ),
        "brierScore": round(brier, 4) if brier is not None else None,
        "ratingTruthMapping": {
            "correct": 1.0,
            "partial": 0.5,
            "incorrect": 0.0,
        },
        "reliabilityBins": [
            _reliability_bin_status(index, samples)
            for index, samples in enumerate(bins)
        ],
    }


def _reliability_bin_status(
    index: int,
    samples: list[_VisionQualitySample],
) -> dict[str, object]:
    lower = index / VISION_QUALITY_RELIABILITY_BIN_COUNT
    upper = (index + 1) / VISION_QUALITY_RELIABILITY_BIN_COUNT
    count = len(samples)
    return {
        "lowerConfidence": lower,
        "upperConfidence": upper,
        "includesUpper": index == VISION_QUALITY_RELIABILITY_BIN_COUNT - 1,
        "sampleCount": count,
        "meanConfidencePercent": (
            round(sum(sample.confidence for sample in samples) / count * 100.0, 1)
            if count
            else None
        ),
        "observedScorePercent": (
            round(
                sum(
                    _RATING_WEIGHTS[sample.rating or "incorrect"]
                    for sample in samples
                )
                / count
                * 100.0,
                1,
            )
            if count
            else None
        ),
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


def _normalize_scene_tags(value: object) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or not VISION_SCENE_MINIMUM_TAGS <= len(value) <= VISION_SCENE_MAXIMUM_TAGS
        or any(not isinstance(tag, str) or tag not in VISION_SCENE_TAG_SET for tag in value)
        or len(set(value)) != len(value)
    ):
        raise PerceptionError(
            "E_PERCEPTION_REQUEST",
            "Vision scene-QA requires one to three unique allowlisted scene tags",
        )
    selected = set(value)
    return tuple(tag for tag in VISION_SCENE_TAGS if tag in selected)


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
