from publish.artifact import PublishedArtifact, decode_artifact
from publish.receipt import PublicationReceipt, receipt_from_row
from publish.review import decode_review_plan
from publish.storage import PublicationStore
from qualify.review import ReviewPlan


class UnknownArtifact(KeyError):
    pass


class UnknownReceipt(KeyError):
    pass


class UnknownReviewPlan(KeyError):
    pass


class PublicationCatalog:
    def __init__(self, store: PublicationStore):
        self.store = store

    def get(self, artifact_id: int) -> PublishedArtifact:
        with self.store.connect() as connection:
            row = connection.execute(
                "SELECT artifact_id, evidence_id, payload FROM artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise UnknownArtifact(artifact_id)
        return decode_artifact(*row)

    def get_receipt(self, artifact_id: int) -> PublicationReceipt:
        with self.store.connect() as connection:
            row = connection.execute(
                "SELECT artifact_id, evidence_id FROM receipts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        if row is None:
            raise UnknownReceipt(artifact_id)
        return receipt_from_row(row)

    def artifact_ids(self) -> tuple[int, ...]:
        with self.store.connect() as connection:
            rows = connection.execute("SELECT artifact_id FROM artifacts ORDER BY artifact_id")
            return tuple(row[0] for row in rows)

    def receipt_artifact_ids(self) -> tuple[int, ...]:
        with self.store.connect() as connection:
            rows = connection.execute("SELECT artifact_id FROM receipts ORDER BY artifact_id")
            return tuple(row[0] for row in rows)

    def get_review_plan(self, artifact_id: int) -> ReviewPlan:
        with self.store.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM review_plans WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        if row is None:
            raise UnknownReviewPlan(artifact_id)
        return decode_review_plan(row[0])

