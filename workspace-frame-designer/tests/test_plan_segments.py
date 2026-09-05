from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/plan_segments.py"
SPEC = importlib.util.spec_from_file_location("plan_segments", SCRIPT)
assert SPEC and SPEC.loader
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)


def shot(shot_id, start, end, scene="scene_change", action="discontinuous", load=0, control="normal",
         boundary="shot_change"):
    return {
        "id": shot_id,
        "start": start,
        "end": end,
        "boundary_type": boundary,
        "camera_continuity": "changed",
        "action_continuity": action,
        "framing_continuity": "changed",
        "scene_continuity": scene,
        "recomposition_needed": True,
        "boundary_risk": {"state_transfer_load": load, "reason": "test"},
        "composition_control": control,
    }


def shot_ir(shots):
    return {"schema_version": "1.1", "status": "complete", "duration": shots[-1]["end"], "shots": shots}


class PlanSegmentsTests(unittest.TestCase):
    def test_a_continuation_shot_enters_on_the_previous_tail_frame(self):
        # One 24s take, too long to generate at once, written as two shots.
        plan = planner.plan(shot_ir([
            shot("S01", 0, 12),
            shot("S02", 12, 24, scene="same_scene", action="continuous",
                 boundary="same_shot_continuation"),
            shot("S03", 24, 36),
        ]))
        strategies = {segment["shot_ids"][0]: segment["entry_strategy"] for segment in plan}
        self.assertEqual(strategies["S01"], "new_first_frame")
        self.assertEqual(strategies["S02"], "use_previous_tail_frame")
        self.assertEqual(strategies["S03"], "new_first_frame")

    def test_short_shots_are_packed_into_one_segment(self):
        plan = planner.plan(shot_ir([shot("S01", 0, 4), shot("S02", 4, 8), shot("S03", 8, 12)]))
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["shot_ids"], ["S01", "S02", "S03"])
        self.assertEqual([b["local_start"] for b in plan[0]["shot_bindings"]], [0, 4, 8])
        self.assertEqual([b["prompt_shot_index"] for b in plan[0]["shot_bindings"]], [1, 2, 3])

    def test_long_shot_is_split_within_limits(self):
        plan = planner.plan(shot_ir([shot("S01", 0, 20)]))
        self.assertGreater(len(plan), 1)
        for segment in plan:
            self.assertTrue(4 <= segment["duration"] <= 15)
            self.assertEqual(segment["shot_ids"], ["S01"])
        self.assertEqual(plan[0]["entry_strategy"], "new_first_frame")
        self.assertEqual(plan[1]["entry_strategy"], "use_previous_tail_frame")

    def test_short_shot_between_long_shots_never_yields_a_tiny_segment(self):
        plan = planner.plan(shot_ir([shot("S01", 0, 20), shot("S02", 20, 22), shot("S03", 22, 42)]))
        for segment in plan:
            self.assertTrue(4 <= segment["duration"] <= 15, segment)
        self.assertEqual(plan[-1]["end"], 42)

    def test_timeline_is_covered_without_gaps(self):
        plan = planner.plan(shot_ir([shot("S01", 0, 6), shot("S02", 6, 13), shot("S03", 13, 24)]))
        self.assertEqual(plan[0]["start"], 0)
        self.assertEqual(plan[-1]["end"], 24)
        for previous, current in zip(plan, plan[1:]):
            self.assertEqual(current["start"], previous["end"])
            self.assertEqual(current["previous_segment_id"], previous["segment_id"])

    def test_plan_is_reproducible(self):
        ir = shot_ir([shot("S01", 0, 5), shot("S02", 5, 9, scene="same_scene", action="continuous", load=7),
                      shot("S03", 9, 18, scene="same_scene", action="continuous", load=6)])
        self.assertEqual(planner.plan(ir), planner.plan(ir))

    def test_critical_shot_opens_its_segment(self):
        plan = planner.plan(shot_ir([
            shot("S01", 0, 4, scene="same_scene", action="discontinuous"),
            shot("S02", 4, 8, scene="same_scene", action="discontinuous", control="critical"),
            shot("S03", 8, 12, scene="same_scene", action="discontinuous"),
        ]))
        owning = [segment for segment in plan if "S02" in segment["shot_ids"]][0]
        self.assertEqual(owning["shot_ids"][0], "S02")

    def test_continuous_same_scene_cuts_are_packed_rather_than_split(self):
        # Three shot/reverse-shot beats that fit in one call: packing hides the
        # seams inside the model instead of across two generations.
        plan = planner.plan(shot_ir([
            shot("S01", 0, 4, scene="same_scene", action="continuous", load=8),
            shot("S02", 4, 8, scene="same_scene", action="continuous", load=8),
            shot("S03", 8, 12, scene="same_scene", action="continuous", load=8),
        ]))
        self.assertEqual(len(plan), 1)

    def test_missing_scores_are_rejected(self):
        bare = shot("S01", 0, 5)
        del bare["boundary_risk"]
        with self.assertRaises(planner.PlanError):
            planner.plan(shot_ir([bare]))


if __name__ == "__main__":
    unittest.main()
