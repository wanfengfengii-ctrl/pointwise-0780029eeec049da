from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache

from capture.archive import FixedEvidence
from qualify.replay import CompleteInterpretation
from qualify.result import UnexplainableRecording


@dataclass(frozen=True, slots=True)
class ReviewPlan:
    """One issued plan plus every distinct complete first-sample vector.

    ``manifest_ids`` keeps the registered manifest order. ``exposure_ids`` is the
    ascending manifest-index subsequence selected for manual review. ``vectors``
    hold the full first-sample vector of each distinct complete interpretation,
    in manifest order, with ``None`` for an empty first sample.
    """

    evidence_id: int
    manifest_ids: tuple[str, ...]
    exposure_ids: tuple[str, ...]
    total_cost: int
    vectors: tuple[tuple[str | None, ...], ...]


def validate_costs(costs: object, exposure_ids: Iterable[str]) -> dict[str, int]:
    """Return work hours in manifest order after enforcing the issuance rules."""
    ordered = tuple(exposure_ids)
    if not isinstance(costs, Mapping):
        raise ValueError("review costs must map exposure IDs to positive work hours")
    if set(costs) != set(ordered):
        missing = sorted(set(ordered) - set(costs))
        extra = sorted(repr(key) for key in set(costs) - set(ordered))
        detail = []
        if missing:
            detail.append("missing " + ", ".join(repr(key) for key in missing))
        if extra:
            detail.append("unexpected " + ", ".join(extra))
        raise ValueError("review costs must cover the registered manifest exactly: " + "; ".join(detail))
    validated: dict[str, int] = {}
    for exposure_id in ordered:
        value = costs[exposure_id]
        if type(value) is not int or value <= 0:
            raise ValueError(f"work hours for exposure {exposure_id!r} must be a positive integer")
        validated[exposure_id] = value
    return validated


def collect_vectors(
    interpretations: Iterable[CompleteInterpretation], exposure_ids: Iterable[str]
) -> tuple[tuple[str | None, ...], ...]:
    """Deduplicate complete interpretations by their manifest-ordered first-sample vector."""
    ordered = tuple(exposure_ids)
    vectors: list[tuple[str | None, ...]] = []
    seen: set[tuple[str | None, ...]] = set()
    for interpretation in interpretations:
        firsts = dict(interpretation.closed)
        vector = tuple(
            None if firsts.get(exposure_id) is None else firsts[exposure_id].origin.event_id
            for exposure_id in ordered
        )
        if vector not in seen:
            seen.add(vector)
            vectors.append(vector)
    return tuple(vectors)


def _pair_masks(vectors: tuple[tuple[str | None, ...], ...]) -> tuple[list[int], int]:
    pairs = [
        (left, right)
        for left in range(len(vectors))
        for right in range(left + 1, len(vectors))
    ]
    masks: list[int] = []
    for position in range(len(vectors[0])):
        mask = 0
        for bit, (left, right) in enumerate(pairs):
            if vectors[left][position] != vectors[right][position]:
                mask |= 1 << bit
        masks.append(mask)
    return masks, len(pairs)


def _select_exposures(
    vectors: tuple[tuple[str | None, ...], ...], costs: list[int]
) -> tuple[int, ...]:
    """Exact minimum-cost separating set, lexicographically least index sequence on ties."""
    if len(vectors) <= 1:
        return ()
    masks, pair_count = _pair_masks(vectors)
    if pair_count == 0:
        return ()
    full = (1 << pair_count) - 1
    count = len(masks)

    suffix_union = [0] * (count + 1)
    for index in range(count - 1, -1, -1):
        suffix_union[index] = suffix_union[index + 1] | masks[index]
    if suffix_union[0] != full:
        raise ValueError("distinct first-sample vectors cannot be separated")

    @lru_cache(maxsize=None)
    def minimum(index: int, covered: int) -> int | None:
        if covered == full:
            return 0
        if index >= count or (covered | suffix_union[index]) != full:
            return None
        best = minimum(index + 1, covered)
        gain = masks[index] & ~covered
        if gain:
            tail = minimum(index + 1, covered | gain)
            if tail is not None:
                candidate = costs[index] + tail
                if best is None or candidate < best:
                    best = candidate
        return best

    target = minimum(0, 0)
    if target is None:
        raise ValueError("distinct first-sample vectors cannot be separated")

    # Among equally cheap completions, keeping the earliest affordable index
    # makes the ascending index sequence lexicographically least.
    chosen: list[int] = []
    covered = 0
    remaining = target
    for index in range(count):
        if remaining == 0:
            break
        gain = masks[index] & ~covered
        if not gain:
            continue
        tail = minimum(index + 1, covered | gain)
        if tail is not None and costs[index] + tail == remaining:
            chosen.append(index)
            covered |= gain
            remaining -= costs[index]
    if covered != full or remaining != 0:
        raise ValueError("distinct first-sample vectors cannot be separated")
    return tuple(chosen)


def build_review_plan(
    evidence: FixedEvidence,
    interpretations: Iterable[CompleteInterpretation],
    costs: Mapping[str, int],
) -> ReviewPlan:
    manifest_ids = evidence.batch.manifest.exposure_ids
    vectors = collect_vectors(interpretations, manifest_ids)
    if not vectors:
        raise UnexplainableRecording(evidence.evidence_id, evidence.seal.latch_count)
    ordered_costs = [costs[exposure_id] for exposure_id in manifest_ids]
    chosen = _select_exposures(vectors, ordered_costs)
    return ReviewPlan(
        evidence.evidence_id,
        manifest_ids,
        tuple(manifest_ids[index] for index in chosen),
        sum(ordered_costs[index] for index in chosen),
        vectors,
    )
