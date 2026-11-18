from capture.archive import EvidenceArchive
from handoff.export import PickupReport, export_report
from handoff.review import resolve_samples
from handoff.source import InvalidOrigin, SourceReading, resolve_source
from publish.catalog import PublicationCatalog, UnknownReviewPlan


class HandoffService:
    def __init__(self, catalog: PublicationCatalog, evidence: EvidenceArchive):
        self.catalog = catalog
        self.evidence = evidence

    def pickup_report(self, artifact_id: int) -> PickupReport:
        artifact = self.catalog.get(artifact_id)
        fixed = self.evidence.get(artifact.evidence_id)
        if fixed.batch.identity.batch_id != artifact.qualification.batch_id:
            raise InvalidOrigin("published batch disagrees with the fixed evidence")
        sources = {}
        for exposure in artifact.qualification.exposures:
            for candidate in exposure.candidates:
                sources[candidate.origin] = resolve_source(fixed, candidate.origin, candidate.value)
        return export_report(artifact, fixed.batch.identity.key, sources)

    def _review_plan(self, artifact_id: int):
        artifact = self.catalog.get(artifact_id)
        try:
            plan = self.catalog.get_review_plan(artifact_id)
        except UnknownReviewPlan:
            raise ValueError(f"artifact {artifact_id} has no review plan") from None
        if plan.evidence_id != artifact.evidence_id:
            raise InvalidOrigin("review plan disagrees with the published artifact")
        return plan

    def pickup_review(self, artifact_id: int) -> dict:
        plan = self._review_plan(artifact_id)
        return {
            "evidence_id": plan.evidence_id,
            "exposure_ids": plan.exposure_ids,
            "total_cost": plan.total_cost,
        }

    def resolve_review(
        self, artifact_id: int, answers: object
    ) -> tuple[tuple[str, SourceReading | None], ...]:
        plan = self._review_plan(artifact_id)
        fixed = self.evidence.get(plan.evidence_id)
        if fixed.batch.manifest.exposure_ids != plan.manifest_ids:
            raise InvalidOrigin("review plan disagrees with the fixed manifest")
        return resolve_samples(fixed, plan, answers)