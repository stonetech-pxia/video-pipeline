from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/merge_chunks.py"
SPEC = importlib.util.spec_from_file_location("story_merge_chunks", SCRIPT)
assert SPEC and SPEC.loader
merger = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(merger)


def plan() -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "status": "complete",
        "duration": 40,
        "scenes": [
            {
                "id": "S01",
                "slugline": "INT. CAFE - NIGHT",
                "location_id": "L01",
                "time_of_day": "night",
                "duration_budget": 20,
                "synopsis": "Lin waits.",
                "estimated_beats": 1,
            },
            {
                "id": "S02",
                "slugline": "EXT. STREET - NIGHT",
                "location_id": "L02",
                "time_of_day": "night",
                "duration_budget": 20,
                "synopsis": "Lin leaves.",
                "estimated_beats": 1,
            },
        ],
        "characters": [
            {"id": "C01", "name": "Lin", "wardrobe": "grey coat", "description": "Waiting."}
        ],
        "locations": [{"id": "L01", "name": "Cafe"}, {"id": "L02", "name": "Street"}],
        "props": [],
        "continuity_constraints": [
            {
                "id": "CC01",
                "category": "wardrobe",
                "subject_id": "C01",
                "rule": "The grey coat never changes.",
                "scope": {"from": "S01", "to": "S02"},
                "locked": True,
            }
        ],
        "locked_constraints": ["Lin wears a grey coat"],
        "ambiguities": [],
        "chunks": [{"id": "K01", "scene_ids": ["S01"]}, {"id": "K02", "scene_ids": ["S02"]}],
    }


def chunk(chunk_id: str, scene_id: str, beat_id: str) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "chunk_id": chunk_id,
        "scenes": [{"id": scene_id, "beat_ids": [beat_id], "exit_state": "Lin is seated."}],
        "beats": [
            {
                "id": beat_id,
                "scene_id": scene_id,
                "action": "Lin waits",
                "emotion": "restless",
                "entity_ids": ["C01"],
                "dialogue_ids": [],
            }
        ],
        "dialogue": [],
        "continuity_constraints": [],
        "transition_markers": [],
        "ambiguities": [],
    }


class MergeChunksTests(unittest.TestCase):
    def test_merges_plan_spine_with_chunk_bodies(self) -> None:
        story, errors = merger.merge(plan(), [chunk("K01", "S01", "B01"), chunk("K02", "S02", "B02")])
        self.assertEqual(errors, [])
        self.assertEqual([s["id"] for s in story["scenes"]], ["S01", "S02"])
        self.assertEqual(story["scenes"][0]["slugline"], "INT. CAFE - NIGHT")
        self.assertEqual(story["scenes"][0]["beat_ids"], ["B01"])
        self.assertEqual([b["id"] for b in story["beats"]], ["B01", "B02"])
        self.assertEqual(story["characters"][0]["id"], "C01")
        self.assertEqual(len(story["continuity_constraints"]), 1)

    def test_reports_scene_no_chunk_completed(self) -> None:
        story, errors = merger.merge(plan(), [chunk("K01", "S01", "B01")])
        self.assertIn("scene S02 was planned but no chunk completed it", errors)
        self.assertEqual([s["id"] for s in story["scenes"]], ["S01"])

    def test_reports_scene_completed_twice(self) -> None:
        _, errors = merger.merge(plan(), [chunk("K01", "S01", "B01"), chunk("K02", "S01", "B02")])
        self.assertIn("scene S01 completed by more than one chunk", errors)

    def test_reports_unplanned_scene(self) -> None:
        _, errors = merger.merge(
            plan(), [chunk("K01", "S01", "B01"), chunk("K02", "S02", "B02"), chunk("K03", "S09", "B03")]
        )
        self.assertIn("chunk completed scene S09, which the plan never declared", errors)

    def test_blocking_ambiguity_forces_partial(self) -> None:
        late = chunk("K02", "S02", "B02")
        late["ambiguities"] = [{"id": "AMB01", "severity": "blocking", "question": "Who speaks?"}]
        story, _ = merger.merge(plan(), [chunk("K01", "S01", "B01"), late])
        self.assertEqual(story["status"], "partial")

    def test_deduplicates_repeated_constraint_ids(self) -> None:
        first = chunk("K01", "S01", "B01")
        second = chunk("K02", "S02", "B02")
        shared = {
            "id": "CC02",
            "category": "prop",
            "subject_id": "P01",
            "rule": "The cup stays cold.",
            "scope": ["B01"],
            "locked": True,
        }
        first["continuity_constraints"] = [shared]
        second["continuity_constraints"] = [dict(shared)]
        story, _ = merger.merge(plan(), [first, second])
        self.assertEqual([c["id"] for c in story["continuity_constraints"]], ["CC01", "CC02"])


if __name__ == "__main__":
    unittest.main()
