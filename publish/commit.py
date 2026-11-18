from collections.abc import Callable

from publish.artifact import PublishedArtifact, encode_artifact, make_artifact
from publish.receipt import PublicationReceipt, make_receipt
from publish.review import encode_review_plan
from publish.storage import PublicationStore
from qualify.result import QualificationResult
from qualify.review import ReviewPlan


class PublicationError(RuntimeError):
    pass


class PublicationService:
    def __init__(self, store: PublicationStore):
        self.store = store

    def commit(
        self,
        qualification: QualificationResult,
        *,
        after_artifact: Callable[[PublishedArtifact], None] | None = None,
    ) -> tuple[PublishedArtifact, PublicationReceipt]:
        try:
            payload = encode_artifact(qualification)
            with self.store.transaction() as connection:
                artifact = self._insert_artifact(connection, qualification, payload)
                if after_artifact is not None:
                    after_artifact(artifact)
                receipt = self._insert_receipt(connection, artifact)
        except Exception as error:
            raise PublicationError(f"publication failed for evidence {qualification.evidence_id}") from error
        return artifact, receipt

    def commit_review(
        self,
        qualification: QualificationResult,
        plan: ReviewPlan,
        *,
        after_artifact: Callable[[PublishedArtifact], None] | None = None,
    ) -> tuple[PublishedArtifact, PublicationReceipt]:
        try:
            payload = encode_artifact(qualification)
            review_payload = encode_review_plan(plan)
            with self.store.transaction() as connection:
                artifact = self._insert_artifact(connection, qualification, payload)
                connection.execute(
                    "INSERT INTO review_plans (artifact_id, evidence_id, payload) VALUES (?, ?, ?)",
                    (artifact.artifact_id, artifact.evidence_id, review_payload),
                )
                if after_artifact is not None:
                    after_artifact(artifact)
                receipt = self._insert_receipt(connection, artifact)
        except Exception as error:
            raise PublicationError(f"publication failed for evidence {qualification.evidence_id}") from error
        return artifact, receipt

    def _insert_artifact(
        self, connection, qualification: QualificationResult, payload: str
    ) -> PublishedArtifact:
        inserted = connection.execute(
            "INSERT INTO artifacts (evidence_id, payload) VALUES (?, ?)",
            (qualification.evidence_id, payload),
        )
        return make_artifact(inserted.lastrowid, qualification)

    def _insert_receipt(self, connection, artifact: PublishedArtifact) -> PublicationReceipt:
        receipt = make_receipt(artifact)
        connection.execute(
            "INSERT INTO receipts (artifact_id, evidence_id) VALUES (?, ?)",
            (receipt.artifact_id, receipt.evidence_id),
        )
        return receipt
