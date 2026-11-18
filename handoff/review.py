from collections.abc import Mapping

from capture.archive import FixedEvidence
from capture.events import SampleOrigin
from handoff.source import SourceReading, resolve_source
from qualify.review import ReviewPlan


class ReviewResolutionError(ValueError):
    pass


def _validate_answers(answers: object, selected: tuple[str, ...]) -> dict[str, str | None]:
    if not isinstance(answers, Mapping):
        raise ReviewResolutionError("review answers must map exposure IDs to event IDs or None")
    if set(answers) != set(selected):
        missing = sorted(set(selected) - set(answers))
        extra = sorted(repr(key) for key in set(answers) - set(selected))
        detail = []
        if missing:
            detail.append("missing " + ", ".join(repr(key) for key in missing))
        if extra:
            detail.append("unexpected " + ", ".join(extra))
        raise ReviewResolutionError("review answers must cover the selected exposures exactly: " + "; ".join(detail))
    validated: dict[str, str | None] = {}
    for exposure_id in selected:
        value = answers[exposure_id]
        if value is not None and (not isinstance(value, str) or not value):
            raise ReviewResolutionError(
                f"answer for exposure {exposure_id!r} must be an event ID or None"
            )
        validated[exposure_id] = value
    return validated


def select_vector(plan: ReviewPlan, answers: Mapping[str, str | None]) -> tuple[str | None, ...]:
    """Return the single complete vector consistent with every supplied answer."""
    positions = [plan.manifest_ids.index(exposure_id) for exposure_id in plan.exposure_ids]
    matches = [
        vector
        for vector in plan.vectors
        if all(
            vector[position] == answers[exposure_id]
            for position, exposure_id in zip(positions, plan.exposure_ids)
        )
    ]
    if not matches:
        raise ReviewResolutionError("review answers do not fit any complete interpretation")
    # The plan separates every pair of distinct vectors, so at most one vector fits.
    if len(matches) != 1:
        raise ReviewResolutionError("review answers do not determine a unique interpretation")
    return matches[0]


def resolve_samples(
    evidence: FixedEvidence, plan: ReviewPlan, answers: object
) -> tuple[tuple[str, SourceReading | None], ...]:
    validated = _validate_answers(answers, plan.exposure_ids)
    vector = select_vector(plan, validated)
    by_event = {sample.event_id: (index, sample) for index, sample in enumerate(evidence.channels.samples)}
    resolved: list[tuple[str, SourceReading | None]] = []
    for exposure_id, event_id in zip(plan.manifest_ids, vector):
        if event_id is None:
            resolved.append((exposure_id, None))
            continue
        located = by_event.get(event_id)
        if located is None:
            raise ReviewResolutionError(f"answered event {event_id!r} is absent from the fixed evidence")
        sample_index, sample = located
        origin = SampleOrigin(plan.evidence_id, sample_index, sample.event_id)
        resolved.append((exposure_id, resolve_source(evidence, origin, sample.value)))
    return tuple(resolved)
