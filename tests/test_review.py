from itertools import combinations
from random import Random

from publish.catalog import UnknownArtifact
from publish.commit import PublicationError
from qualify.result import UnexplainableRecording
from qualify.review import _select_exposures
from tests import ArchiveTestCase, RECORDINGS, SOURCE, recording, single_sample


class ReviewTests(ArchiveTestCase):
    def shared(self, count=1, roll="shared"):
        batch = self.station.registry.register(roll, SOURCE, ("A", "B"))
        return batch, self.ingest_document(batch, single_sample(count))

    def trap(self):
        document = recording("changeover.json")
        document["control"] = [
            {"tick": tick, "kind": kind, "exposure_id": exposure}
            for exposure, opening, closing in (("B", 0, 1), ("C", 3, 6), ("D", 6, 7))
            for tick, kind in ((opening, "open"), (closing, "close"))
        ]
        document["samples"] = [
            {"tick": 1, "event_id": "r", "value": 7},
            {"tick": 3, "event_id": "s", "value": 7},
            {"tick": 6, "event_id": "t", "value": 7},
            {"tick": 7, "event_id": "u", "value": 7},
        ]
        document["seal"]["latch_count"] = 2
        batch = self.station.registry.register("trap", SOURCE, ("B", "C", "D"))
        return batch, self.ingest_document(batch, document)

    def tie(self):
        document = recording("changeover.json")
        document["control"] = [
            {"tick": tick, "kind": kind, "exposure_id": exposure}
            for exposure, opening, closing in (("A", 0, 1), ("M", 2, 3), ("Z", 4, 5))
            for tick, kind in ((opening, "open"), (closing, "close"))
        ]
        document["samples"] = [
            {"tick": 0, "event_id": "a", "value": 7},
            {"tick": 2, "event_id": "m", "value": 7},
            {"tick": 4, "event_id": "z", "value": 7},
        ]
        document["seal"]["latch_count"] = 1
        batch = self.station.registry.register("tie", SOURCE, ("Z", "A", "M"))
        return batch, self.ingest_document(batch, document)

    def issue(self, evidence, costs, station=None, **kwargs):
        service = (station or self.station).qualification
        return service.qualify_release_review(evidence, costs, **kwargs)

    def test_v9_exact_minimum_and_pinned_plan(self):
        _, trap = self.trap()
        artifact, receipt = self.issue(trap, {"B": 1, "C": 1, "D": 5})
        self.assertEqual((receipt.artifact_id, receipt.evidence_id), (artifact.artifact_id, trap))
        later = self.reopen()
        self.assertEqual(later.catalog.get(artifact.artifact_id), artifact)
        self.assertEqual(later.catalog.get_receipt(receipt.artifact_id), receipt)
        self.assertEqual(later.handoff.pickup_review(artifact.artifact_id), {
            "evidence_id": trap, "exposure_ids": ("C", "D"), "total_cost": 6,
        })
        rows = later.handoff.resolve_review(artifact.artifact_id, {"D": None, "C": "s"})
        self.assertEqual(
            [(exposure, None if sample is None else
              (sample.evidence_id, sample.source_id, sample.sample_index, sample.event_id, sample.tick, sample.value))
             for exposure, sample in rows],
            [("B", (trap, SOURCE, 0, "r", 1, 7)),
             ("C", (trap, SOURCE, 1, "s", 3, 7)),
             ("D", None)],
        )
        self.assertEqual(tuple(exposure for exposure, _ in rows), ("B", "C", "D"))
        self.assertEqual(later.handoff.resolve_review(artifact.artifact_id, {"C": "t", "D": None}), (
            ("B", later.handoff.resolve_review(artifact.artifact_id, {"C": "t", "D": None})[0][1]),
            ("C", later.handoff.resolve_review(artifact.artifact_id, {"C": "t", "D": None})[1][1]),
            ("D", None),
        ))

    def test_v9_tie_uses_manifest_indices(self):
        _, tie = self.tie()
        artifact, _ = self.issue(tie, {"M": 1, "A": 1, "Z": 1})
        self.assertEqual(self.station.handoff.pickup_review(artifact.artifact_id), {
            "evidence_id": tie, "exposure_ids": ("Z", "A"), "total_cost": 2,
        })
        rows = self.station.handoff.resolve_review(artifact.artifact_id, {"Z": None, "A": None})
        self.assertEqual([(exposure, None if sample is None else sample.event_id) for exposure, sample in rows],
                         [("Z", None), ("A", None), ("M", "m")])

    def test_v9_single_vector_zero_plan(self):
        batch = self.station.registry.register("steady", SOURCE, ("C",))
        evidence = self.ingest_path(batch, RECORDINGS / "steady.json")
        artifact, receipt = self.issue(evidence, {"C": 3})
        self.assertEqual(self.station.handoff.pickup_review(receipt.artifact_id), {
            "evidence_id": evidence, "exposure_ids": (), "total_cost": 0,
        })
        rows = self.station.handoff.resolve_review(artifact.artifact_id, {})
        self.assertEqual(tuple(exposure for exposure, _ in rows), ("C",))
        sample = rows[0][1]
        self.assertEqual((sample.evidence_id, sample.source_id, sample.sample_index, sample.event_id,
                          sample.tick, sample.value), (evidence, SOURCE, 0, "early-c", 1, 7))

    def test_v9_invalid_costs_and_unexplainable(self):
        _, shared = self.shared()
        for costs in ({"A": 1}, {"A": True, "B": 1}, {"A": 0, "B": 1}, {"A": -2, "B": 1},
                      {"A": 1, "B": 1, "C": 1}, {"A": 1.0, "B": 1}, ["A", "B"], None,
                      {"A": "1", "B": 1}):
            with self.subTest(costs=costs):
                with self.assertRaises(ValueError):
                    self.issue(shared, costs)
        _, impossible = self.shared(count=2, roll="impossible")
        with self.assertRaises(UnexplainableRecording):
            self.issue(impossible, {"A": 4, "B": 1})
        self.assertEqual(self.station.catalog.artifact_ids(), ())
        self.assertEqual(self.station.catalog.receipt_artifact_ids(), ())

    def test_v9_legacy_artifact_has_no_plan(self):
        batch = self.station.registry.register("legacy", SOURCE, ("A", "B"))
        evidence = self.ingest_path(batch, RECORDINGS / "changeover.json")
        artifact, _ = self.station.qualification.qualify_release(evidence)
        reopened = self.reopen()
        self.assertEqual(tuple(row.exposure_id for row in reopened.handoff.pickup_report(artifact.artifact_id).review),
                         ("B",))
        with self.assertRaisesRegex(ValueError, "no review plan"):
            reopened.handoff.pickup_review(artifact.artifact_id)
        with self.assertRaisesRegex(ValueError, "no review plan"):
            reopened.handoff.resolve_review(artifact.artifact_id, {})
        with self.assertRaises(UnknownArtifact):
            reopened.handoff.pickup_review(artifact.artifact_id + 100)
        with self.assertRaises(UnknownArtifact):
            reopened.handoff.resolve_review(artifact.artifact_id + 100, {})

    def test_v9_answer_validation(self):
        _, shared = self.shared()
        artifact, _ = self.issue(shared, {"A": 4, "B": 1})
        for answers in ({}, {"A": "r"}, {"B": None, "A": "r"}, {"B": 17}, {"B": "unseen"},
                        {"B": ""}, {"B": True}, ["B"], None):
            with self.subTest(answers=answers):
                with self.assertRaises(ValueError):
                    self.station.handoff.resolve_review(artifact.artifact_id, answers)
        _, trap = self.trap()
        trap_artifact, _ = self.issue(trap, {"B": 1, "C": 1, "D": 5})
        with self.assertRaises(ValueError):
            self.station.handoff.resolve_review(trap_artifact.artifact_id, {"C": None, "D": None})
        before = (self.station.catalog.artifact_ids(), self.station.catalog.receipt_artifact_ids())
        self.assertEqual(len(before[0]), 2)
        self.assertEqual(before[1], before[0])

    def test_v9_two_cost_tables_are_independent(self):
        _, shared = self.shared()
        _, cheap_b = self.issue(shared, {"A": 4, "B": 1})
        _, cheap_a = self.issue(shared, {"A": 1, "B": 4})
        handoff = self.reopen().handoff
        self.assertEqual(handoff.pickup_review(cheap_b.artifact_id)["exposure_ids"], ("B",))
        self.assertEqual(handoff.pickup_review(cheap_a.artifact_id)["exposure_ids"], ("A",))
        rows_b = handoff.resolve_review(cheap_b.artifact_id, {"B": None})
        self.assertEqual([(exposure, None if sample is None else sample.event_id) for exposure, sample in rows_b],
                         [("A", "r"), ("B", None)])
        rows_a = handoff.resolve_review(cheap_a.artifact_id, {"A": None})
        self.assertEqual([(exposure, None if sample is None else sample.event_id) for exposure, sample in rows_a],
                         [("A", None), ("B", "r")])

    def test_v9_selection_matches_exhaustive_search(self):
        def brute(vectors, costs):
            best = None
            for size in range(len(costs) + 1):
                for combo in combinations(range(len(costs)), size):
                    if all(any(vec[i] != other[i] for i in combo)
                           for vec, other in combinations(vectors, 2)):
                        key = (sum(costs[i] for i in combo), combo)
                        if best is None or key < best:
                            best = key
            return best

        generator = Random(20261118)
        for _ in range(500):
            width = generator.randint(1, 6)
            vectors = tuple(dict.fromkeys(
                tuple(generator.choice((None, "a", "b", "c", "d")) for _ in range(width))
                for _ in range(generator.randint(1, 6))
            ))
            costs = [generator.randint(1, 6) for _ in range(width)]
            expected = brute(vectors, costs)
            if expected is None:
                continue
            with self.subTest(vectors=vectors, costs=costs):
                chosen = _select_exposures(vectors, costs)
                self.assertEqual(chosen, expected[1])
                self.assertEqual(sum(costs[index] for index in chosen), expected[0])

    def test_v9_atomic_publication_and_recovery(self):
        _, shared = self.shared()
        original, original_receipt = self.station.qualification.qualify_release(shared)
        before = (self.station.catalog.artifact_ids(), self.station.catalog.receipt_artifact_ids())
        observed = []

        def interrupt(staged):
            observed.append((staged.artifact_id, self.station.catalog.artifact_ids(),
                             self.station.catalog.receipt_artifact_ids()))
            raise OSError("fixture interrupted publication")

        with self.assertRaises(PublicationError) as caught:
            self.issue(shared, {"A": 4, "B": 1}, after_artifact=interrupt)
        self.assertIsInstance(caught.exception.__cause__, OSError)
        self.assertEqual(len(observed), 1)
        staged_id = observed[0][0]
        self.assertNotEqual(staged_id, original.artifact_id)
        final = self.reopen()
        self.assertEqual((final.catalog.artifact_ids(), final.catalog.receipt_artifact_ids()), before)
        self.assertEqual(final.catalog.get(original.artifact_id), original)
        self.assertEqual(final.catalog.get_receipt(original_receipt.artifact_id), original_receipt)
        with self.assertRaises(UnknownArtifact):
            final.handoff.pickup_review(staged_id)
        recovered, recovered_receipt = self.issue(shared, {"A": 4, "B": 1}, station=final)
        self.assertEqual(recovered.evidence_id, shared)
        self.assertEqual(final.handoff.pickup_review(recovered_receipt.artifact_id)["exposure_ids"], ("B",))
