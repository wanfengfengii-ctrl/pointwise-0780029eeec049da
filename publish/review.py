import json

from qualify.review import ReviewPlan


def encode_review_plan(plan: ReviewPlan) -> str:
    return json.dumps({
        "evidence_id": plan.evidence_id,
        "manifest_ids": list(plan.manifest_ids),
        "exposure_ids": list(plan.exposure_ids),
        "total_cost": plan.total_cost,
        "vectors": [list(vector) for vector in plan.vectors],
    })


def decode_review_plan(payload: str) -> ReviewPlan:
    document = json.loads(payload)
    if not isinstance(document, dict):
        raise ValueError("invalid stored review plan")
    evidence_id = document["evidence_id"]
    manifest_ids = tuple(document["manifest_ids"])
    exposure_ids = tuple(document["exposure_ids"])
    total_cost = document["total_cost"]
    vectors = tuple(tuple(vector) for vector in document["vectors"])
    if type(evidence_id) is not int or type(total_cost) is not int:
        raise ValueError("invalid stored review plan numbers")
    if not all(isinstance(item, str) and item for item in manifest_ids + exposure_ids):
        raise ValueError("invalid stored review plan exposure IDs")
    if len(set(manifest_ids)) != len(manifest_ids) or not set(exposure_ids) <= set(manifest_ids):
        raise ValueError("invalid stored review plan exposures")
    if not vectors or any(len(vector) != len(manifest_ids) for vector in vectors):
        raise ValueError("invalid stored review plan vectors")
    if any(
        element is not None and (not isinstance(element, str) or not element)
        for vector in vectors
        for element in vector
    ):
        raise ValueError("invalid stored review plan vector elements")
    return ReviewPlan(evidence_id, manifest_ids, exposure_ids, total_cost, vectors)
