from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

from test_validate_chunk import chunk, exit_state, shot


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/merge_shots.py"
SPEC = importlib.util.spec_from_file_location("merge_shots", SCRIPT)
assert SPEC and SPEC.loader
merger = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(merger)

HEAD = {
    "aspect_ratio": "16:9",
    "visual_style": {"look": "cold coastal daylight"},
    "overall_soundscape": {"bed": "sea wind"},
    "music": {"cue": "none until the end"},
}


def plan(*windows):
    return {
        "schema_version": "1.0",
        "duration": windows[-1][1],
        "chunks": [
            {
                "chunk_id": f"K{index + 1}",
                "previous_chunk_id": f"K{index}" if index else None,
                "start": start,
                "end": end,
            }
            for index, (start, end) in enumerate(windows)
        ],
    }


def two_chunks():
    first = chunk([shot("A1", 0, 10, ["B01"]), shot("A2", 10, 20, ["B02"])])
    second = chunk([shot("A1", 20, 30, ["B03"])], chunk_id="K2", start=20, end=30)
    return first, second


class MergeShotsTests(unittest.TestCase):
    def test_shots_are_renumbered_across_chunks(self):
        merged, errors = merger.merge(plan((0, 20), (20, 30)), HEAD, list(two_chunks()))
        self.assertEqual(errors, [])
        self.assertEqual([item["id"] for item in merged["shots"]], ["S001", "S002", "S003"])
        self.assertEqual(
            [item["shot_id"] for item in merged["continuity_exit_state"]["by_shot"]],
            ["S001", "S002", "S003"],
        )

    def test_film_level_fields_come_from_the_head(self):
        first, second = two_chunks()
        second["visual_style"] = {"look": "a style the chunk invented"}
        merged, _ = merger.merge(plan((0, 20), (20, 30)), HEAD, [first, second])
        self.assertEqual(merged["visual_style"], HEAD["visual_style"])
        self.assertEqual(merged["aspect_ratio"], "16:9")

    def test_a_missing_head_field_is_reported(self):
        head = {key: value for key, value in HEAD.items() if key != "music"}
        _, errors = merger.merge(plan((0, 20), (20, 30)), head, list(two_chunks()))
        self.assertIn("the film head is missing music", errors)

    def test_a_seam_that_does_not_meet_is_reported(self):
        first, second = two_chunks()
        second["start"] = 25
        _, errors = merger.merge(plan((0, 20), (25, 30)), HEAD, [first, second])
        self.assertTrue(any("but the film reached 20" in error for error in errors))

    def test_a_missing_chunk_is_reported(self):
        first, _ = two_chunks()
        merged, errors = merger.merge(plan((0, 20), (20, 30)), HEAD, [first])
        self.assertIn("chunk K2 was planned but not supplied", errors)
        self.assertTrue(any("the last shot ends at 20" in error for error in errors))

    def test_an_unplanned_chunk_is_reported(self):
        first, second = two_chunks()
        second["chunk_id"] = "K9"
        _, errors = merger.merge(plan((0, 20)), HEAD, [first, second])
        self.assertIn("chunk K9 was supplied, but the plan never declared it", errors)

    def test_a_partial_chunk_makes_the_film_partial(self):
        first, second = two_chunks()
        second["status"] = "partial"
        second["errors"] = ["a fact the story never fixed"]
        merged, _ = merger.merge(plan((0, 20), (20, 30)), HEAD, [first, second])
        self.assertEqual(merged["status"], "partial")
        self.assertEqual(merged["errors"], ["a fact the story never fixed"])

    def test_a_shot_that_never_says_who_is_in_it_is_reported(self):
        first, second = two_chunks()
        del second["shots"][0]["characters_in_frame"]
        _, errors = merger.merge(plan((0, 20), (20, 30)), HEAD, [first, second])
        self.assertIn("S003: characters_in_frame is missing; every shot must name who is in it", errors)

    def test_an_exit_state_for_an_unknown_shot_is_reported(self):
        first, second = two_chunks()
        second["continuity_exit_state"]["by_shot"] = [exit_state("A9")]
        _, errors = merger.merge(plan((0, 20), (20, 30)), HEAD, [first, second])
        self.assertIn("continuity_exit_state.by_shot: no exit state for S003", errors)


if __name__ == "__main__":
    unittest.main()
