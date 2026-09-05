from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


planner = load("plan_segments")
gate = load("validate_frame_chunk")
merger = load("merge_frames")
builder = load("build_frame_message")


def shot(shot_id, start, end, scene="S01", **extra):
    return {"id": shot_id, "start": start, "end": end, "scene_id": scene, **extra}


def shot_chunk(chunk_id, shots, **extra):
    return {"schema_version": "1.1", "chunk_id": chunk_id, "status": "complete",
            "start": shots[0]["start"], "end": shots[-1]["end"], "shots": shots,
            "continuity_exit_state": {"by_shot": []}, "warnings": [], "errors": [], **extra}


def prompt(description="she looks up"):
    return {"integrated_multimodal_description": description,
            "overall_soundscape": "room tone", "non_diegetic_music": ""}


def fill(shot_chunk_value, segments):
    """The parts the designer adds on top of the packed skeleton."""
    refs = {"character_reference_ids": [], "location_reference_ids": ["REF_L01"],
            "style_reference_ids": [], "video_reference_ids": [], "audio_reference_ids": []}
    media = [{"id": "REF_L01", "type": "image", "role": "location_reference", "status": "pending",
              "source_type": "generated", "related_segments": [item["segment_id"] for item in segments]}]
    plan = []
    for index, item in enumerate(segments):
        following = segments[index + 1] if index + 1 < len(segments) else None
        needs_tail = bool(following and following["entry_strategy"] == "use_previous_tail_frame")
        tail_id = f"TAIL_{item['segment_id']}" if needs_tail else None
        if needs_tail:
            media.append({"id": tail_id, "type": "frame", "role": "actual_tail_frame",
                          "status": "runtime_pending", "source_type": "extracted",
                          "related_segments": [item["segment_id"]],
                          "derived_from_segment_id": item["segment_id"]})
        previous = plan[-1] if plan else None
        plan.append({
            **item,
            "runtime_entry_dependency": None if item["entry_strategy"] == "references_only" else {
                "kind": "previous_actual_tail_frame", "previous_segment_id": previous["segment_id"],
                "expected_media_id": previous["actual_tail_frame_media_id"]},
            "exit_frame_required": needs_tail, "actual_tail_frame_media_id": tail_id,
            "reference_strategy": refs, "prompt": prompt(), "reason": "packed"})
    return {"schema_version": "1.3", "chunk_id": shot_chunk_value["chunk_id"], "status": "complete",
            "start": shot_chunk_value["start"], "end": shot_chunk_value["end"],
            "segment_plan": plan, "media_manifest": {"status": "draft", "media": media},
            "warnings": [], "errors": []}


class ChunkPlanningTests(unittest.TestCase):
    def test_a_chunk_numbers_its_segments_under_its_own_id(self):
        segments = planner.plan(shot_chunk("K2", [shot("K2-01", 70, 82), shot("K2-02", 82, 94)]))
        self.assertTrue(all(item["segment_id"].startswith("K2-SEG") for item in segments), segments)

    def test_a_chunk_is_packed_inside_its_own_window(self):
        segments = planner.plan(shot_chunk("K2", [shot("K2-01", 70, 82), shot("K2-02", 82, 94)]))
        self.assertEqual(segments[0]["start"], 70)
        self.assertEqual(segments[-1]["end"], 94)

    def test_a_chunk_whose_window_disagrees_with_its_shots_is_refused(self):
        artifact = shot_chunk("K2", [shot("K2-01", 70, 82)])
        artifact["end"] = 90
        with self.assertRaises(planner.PlanError):
            planner.plan(artifact)

    def test_a_chunk_opening_inside_a_scene_is_refused(self):
        # Packing that scene needs shots from both chunks, and the seam is a cut.
        with self.assertRaises(planner.PlanError):
            planner.plan(shot_chunk("K2", [shot("K2-01", 70, 82)]), continues_scene=True)

    def test_a_film_still_has_to_start_at_zero(self):
        artifact = {"schema_version": "1.1", "status": "complete", "duration": 12,
                    "shots": [shot("S01", 4, 12)]}
        with self.assertRaises(planner.PlanError):
            planner.plan(artifact)


class ChunkGateTests(unittest.TestCase):
    def chunk(self):
        shots = shot_chunk("K1", [shot("K1-01", 0, 12), shot("K1-02", 12, 24)])
        return shots, fill(shots, planner.plan(shots))

    def test_a_filled_chunk_is_accepted(self):
        shots, artifact = self.chunk()
        self.assertEqual(gate.validate(shots, artifact), [])

    def test_a_window_that_drifted_from_the_shots_is_rejected(self):
        shots, artifact = self.chunk()
        artifact["end"] = 30
        self.assertTrue(any("but its shots run" in item for item in gate.validate(shots, artifact)))

    def test_a_chunk_claiming_another_chunks_id_is_rejected(self):
        shots, artifact = self.chunk()
        artifact["chunk_id"] = "K7"
        self.assertTrue(any("chunk_id" in item for item in gate.validate(shots, artifact)))

    def test_the_seam_carries_the_previous_chunks_exit_state(self):
        shots = shot_chunk("K2", [shot("K2-01", 24, 36, scene="S02")])
        artifact = fill(shots, planner.plan(shots))
        earlier = shot_chunk("K1", [shot("K1-01", 0, 24)])
        earlier["continuity_exit_state"] = {"by_shot": [{
            "shot_id": "K1-01", "staging": "at the door", "wardrobe_state": "coat still buttoned",
            "held_props": ["folded letter"], "scene_state": "", "lighting_state": ""}]}
        # Without the previous chunk the check has no shot to look back at.
        self.assertEqual(gate.validate(shots, artifact), [])
        errors = gate.validate(shots, artifact, earlier)
        self.assertTrue(any("exit_state_not_carried" in item for item in errors), errors)

        artifact["segment_plan"][0]["prompt"] = prompt("coat still buttoned, the folded letter in hand")
        self.assertEqual(gate.validate(shots, artifact, earlier), [])


class MessageTests(unittest.TestCase):
    """The ask must name every carry the gate will check, or the loop cannot converge."""

    def chunk(self):
        shots = shot_chunk("K1", [shot("K1-01", 0, 12), shot("K1-02", 12, 24, scene="S02")])
        shots["continuity_exit_state"] = {"by_shot": [{
            "shot_id": "K1-01", "staging": "at the door", "wardrobe_state": "coat still buttoned",
            "held_props": ["folded letter"], "scene_state": "", "lighting_state": ""}]}
        return shots

    def test_a_scene_opening_inside_the_chunk_is_told_what_to_carry(self):
        shots = self.chunk()
        segments = planner.plan(shots)
        text = builder.carried_state(shots, None, segments)
        self.assertIn("coat still buttoned", text)
        self.assertIn("folded letter", text)
        self.assertIn(segments[-1]["segment_id"], text)

    def test_the_chunk_opening_is_told_nothing_without_the_previous_chunk(self):
        shots = self.chunk()
        text = builder.carried_state(shots, None, planner.plan(shots)[:1])
        self.assertEqual(text, "")

    def test_a_time_jump_is_not_asked_to_carry_a_wardrobe(self):
        shots = self.chunk()
        shots["shots"][1]["scene_continuity"] = "time_change"
        self.assertEqual(builder.carried_state(shots, None, planner.plan(shots)), "")

    def test_the_ask_names_every_carry_the_gate_will_check(self):
        """The bug that cost two runs: the ask covered fewer segments than the gate.

        Both now go through carried_exit_state, so this holds by construction --
        the test is here to keep it that way.
        """
        shots = self.chunk()
        segments = planner.plan(shots)
        artifact = fill(shots, segments)  # every prompt carries nothing
        text = builder.carried_state(shots, None, segments)
        flagged = [artifact["segment_plan"][int(item.split("[")[1].split("]")[0])]["segment_id"]
                   for item in gate.validate(shots, artifact) if "exit_state_not_carried" in item]
        self.assertTrue(flagged, "the gate flagged nothing, so this proves nothing")
        for segment_id in flagged:
            self.assertIn(segment_id, text)


class MergeTests(unittest.TestCase):
    def two_chunks(self):
        # Each chunk keeps its own clock, so the second starts at 0 as well.
        first = shot_chunk("K1", [shot("K1-01", 0, 12), shot("K1-02", 12, 24)])
        second = shot_chunk("K2", [shot("K2-01", 0, 12, scene="S02")])
        return fill(first, planner.plan(first)), fill(second, planner.plan(second))

    def test_segments_are_renumbered_across_the_film(self):
        merged, errors = merger.merge(list(self.two_chunks()))
        self.assertEqual(errors, [])
        self.assertEqual([item["segment_id"] for item in merged["segment_plan"]],
                         ["SEG001", "SEG002", "SEG003"])

    def test_the_chain_is_rewritten_to_the_new_ids(self):
        merged, _ = merger.merge(list(self.two_chunks()))
        plan = merged["segment_plan"]
        self.assertEqual([item["previous_segment_id"] for item in plan],
                         [None, "SEG001", "SEG002"])
        self.assertEqual(plan[1]["runtime_entry_dependency"]["previous_segment_id"], "SEG001")

    def test_one_reference_image_survives_per_subject(self):
        merged, _ = merger.merge(list(self.two_chunks()))
        location = [item for item in merged["media_manifest"]["media"] if item["id"] == "REF_L01"]
        self.assertEqual(len(location), 1)
        self.assertEqual(location[0]["related_segments"], ["SEG001", "SEG002", "SEG003"])

    def test_a_chunk_carrying_its_own_offset_is_reported(self):
        first, second = self.two_chunks()
        second["start"], second["segment_plan"][0]["start"] = 30, 30
        self.assertTrue(any("keeps its own clock" in item for item in merger.merge([first, second])[1]))

    def test_a_later_chunk_is_laid_after_the_one_before_it(self):
        merged, errors = merger.merge(list(self.two_chunks()))
        self.assertEqual(errors, [])
        spans = [(item["start"], item["end"]) for item in merged["segment_plan"]]
        self.assertEqual(spans[0][0], 0)
        self.assertEqual(spans[-1], (24, 36))
        for earlier, later in zip(spans, spans[1:]):
            self.assertEqual(earlier[1], later[0])

    def test_the_merged_plan_names_the_shots_the_merged_shot_ir_has(self):
        """Both merges renumber, so both have to renumber the same way.

        This runs the real merge_shots beside merge_frames rather than trusting
        two implementations of one rule to stay in step.
        """
        spec = importlib.util.spec_from_file_location(
            "merge_shots", SCRIPTS.parents[1] / "workspace-shot-director/scripts/merge_shots.py")
        shot_merger = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(shot_merger)

        shot_chunks, frame_chunks = [], []
        for chunk_id, spans in (("K1", [(0, 12), (12, 24)]), ("K2", [(0, 13)]),
                                ("K3", [(0, 11), (11, 22)])):
            shots = [shot(f"{chunk_id}-{i:02d}", a, b, scene=f"S{chunk_id}",
                          characters_in_frame=[]) for i, (a, b) in enumerate(spans, 1)]
            piece = shot_chunk(chunk_id, shots)
            piece["continuity_exit_state"] = {"by_shot": [
                {"shot_id": s["id"], "staging": "x", "wardrobe_state": "",
                 "held_props": [], "scene_state": "", "lighting_state": ""} for s in shots]}
            shot_chunks.append(piece)
            frame_chunks.append(fill(piece, planner.plan(piece)))

        plan = {"chunks": [{"chunk_id": c["chunk_id"]} for c in shot_chunks]}
        head = {"aspect_ratio": "16:9", "visual_style": {}, "overall_soundscape": {}, "music": {}}
        shot_ir, shot_errors = shot_merger.merge(plan, head, shot_chunks)
        merged, frame_errors = merger.merge(frame_chunks)
        self.assertEqual((shot_errors, frame_errors), ([], []))

        available = {item["id"] for item in shot_ir["shots"]}
        named = {ref for item in merged["segment_plan"] for ref in item["shot_ids"]}
        self.assertTrue(named, "the merged plan named no shots, so this proves nothing")
        self.assertEqual(named - available, set(), "merged plan names shots the merged Shot IR lacks")
        bound = {b["shot_id"] for item in merged["segment_plan"] for b in item["shot_bindings"]}
        self.assertEqual(bound - available, set(), "shot_bindings kept a chunk-local id")

        # And they line up in time, not merely by name.
        spans = {item["id"]: (item["start"], item["end"]) for item in shot_ir["shots"]}
        for item in merged["segment_plan"]:
            self.assertLessEqual(spans[item["shot_ids"][0]][0], item["start"])
            self.assertGreaterEqual(spans[item["shot_ids"][-1]][1], item["end"])


if __name__ == "__main__":
    unittest.main()
