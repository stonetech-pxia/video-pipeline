from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/plan_segments.py"
SPEC = importlib.util.spec_from_file_location("plan_segments", SCRIPT)
assert SPEC and SPEC.loader
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)


def shot(shot_id, start, end, scene="S01"):
    return {"id": shot_id, "start": start, "end": end, "scene_id": scene}


def shot_ir(shots):
    return {"schema_version": "1.1", "status": "complete", "duration": shots[-1]["end"], "shots": shots}


def boundaries(segments):
    return [(segment["start"], segment["end"]) for segment in segments]


class PlanSegmentsTests(unittest.TestCase):
    def test_a_scene_that_fits_is_one_segment(self):
        plan = planner.plan(shot_ir([shot("S01", 0, 5), shot("S02", 5, 12)]))
        self.assertEqual(boundaries(plan), [(0, 12)])
        self.assertEqual(plan[0]["shot_ids"], ["S01", "S02"])
        self.assertEqual(plan[0]["entry_strategy"], "references_only")

    def test_a_boundary_lands_inside_a_shot_never_at_a_cut(self):
        # Three 12s shots in one scene: cuts at 12 and 24, both avoided.
        plan = planner.plan(shot_ir([shot("A", 0, 12), shot("B", 12, 24), shot("C", 24, 36)]))
        cuts = {12, 24}
        opened = {segment["start"] for segment in plan[1:]}
        self.assertFalse(opened & cuts, f"a segment opened at a cut: {sorted(opened & cuts)}")

    def test_a_continuation_segment_spans_the_cut_into_the_next_shot(self):
        plan = planner.plan(shot_ir([shot("A", 0, 12), shot("B", 12, 24), shot("C", 24, 36)]))
        # Every segment after the first carries the tail of one shot and the head
        # of the next, so the frame handed forward is already in the next shot.
        for segment in plan[1:]:
            self.assertGreater(len(segment["shot_ids"]), 1, segment)

    def test_every_scene_opens_on_its_references_and_continues_on_the_tail(self):
        plan = planner.plan(shot_ir([
            shot("A", 0, 12, "S01"), shot("B", 12, 24, "S01"),
            shot("C", 24, 36, "S02"), shot("D", 36, 48, "S02"),
        ]))
        openers = [segment for segment in plan if segment["entry_strategy"] == "references_only"]
        self.assertEqual([segment["scene_id"] for segment in openers], ["S01", "S02"])
        for segment in plan:
            if segment not in openers:
                self.assertEqual(segment["entry_strategy"], "use_previous_tail_frame")

    def test_a_segment_never_crosses_a_scene_boundary(self):
        plan = planner.plan(shot_ir([
            shot("A", 0, 10, "S01"), shot("B", 10, 20, "S02"), shot("C", 20, 30, "S03"),
        ]))
        self.assertEqual(boundaries(plan), [(0, 10), (10, 20), (20, 30)])
        self.assertEqual([segment["scene_id"] for segment in plan], ["S01", "S02", "S03"])

    def test_segment_durations_stay_within_the_model_limit(self):
        plan = planner.plan(shot_ir([shot(f"S{i:02d}", i * 11, (i + 1) * 11) for i in range(6)]))
        for segment in plan:
            self.assertGreaterEqual(segment["duration"], planner.MIN_DURATION)
            self.assertLessEqual(segment["duration"], planner.MAX_DURATION)

    def test_the_timeline_is_covered_without_gaps(self):
        plan = planner.plan(shot_ir([shot("A", 0, 12), shot("B", 12, 24), shot("C", 24, 35)]))
        self.assertEqual(plan[0]["start"], 0)
        self.assertEqual(plan[-1]["end"], 35)
        for previous, following in zip(plan, plan[1:]):
            self.assertEqual(previous["end"], following["start"])
            self.assertEqual(following["previous_segment_id"], previous["segment_id"])

    def test_shot_bindings_report_where_each_shot_starts_in_the_segment(self):
        plan = planner.plan(shot_ir([shot("A", 0, 12), shot("B", 12, 24), shot("C", 24, 36)]))
        for segment in plan:
            for binding, shot_id in zip(segment["shot_bindings"], segment["shot_ids"]):
                self.assertEqual(binding["shot_id"], shot_id)
                self.assertGreaterEqual(binding["local_start"], 0)
                self.assertLess(binding["local_start"], segment["duration"])
        # A shot already running when its segment opens starts at 0 within it.
        self.assertEqual(plan[1]["shot_bindings"][0]["local_start"], 0)

    def test_a_scene_shorter_than_one_generation_is_refused(self):
        with self.assertRaises(planner.PlanError):
            planner.plan(shot_ir([shot("A", 0, 3, "S01"), shot("B", 3, 20, "S02")]))

    def test_shot_ir_without_scene_ids_is_refused(self):
        artifact = shot_ir([shot("A", 0, 10)])
        del artifact["shots"][0]["scene_id"]
        with self.assertRaises(planner.PlanError):
            planner.plan(artifact)

    def test_a_scene_needing_more_than_three_shots_per_segment_is_refused(self):
        # Four 1s shots cannot share a 4s segment, and none is long enough alone.
        with self.assertRaises(planner.PlanError):
            planner.plan(shot_ir([shot(f"S{i}", i, i + 1) for i in range(4)]))


if __name__ == "__main__":
    unittest.main()
