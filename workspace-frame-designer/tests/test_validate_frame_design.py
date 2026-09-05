from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_frame_design.py"
SPEC = importlib.util.spec_from_file_location("validate_frame_design", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def media(media_id: str, role: str, segment: str, **extra: object) -> dict[str, object]:
    result: dict[str, object] = {
        "id": media_id,
        "type": "frame" if role in {"first_frame", "actual_tail_frame"} else "image",
        "role": role,
        "status": "runtime_pending" if role == "actual_tail_frame" else "resolved",
        "source_type": "extracted" if role == "actual_tail_frame" else "uploaded",
        "source_job": None,
        "related_segments": [segment],
        "provenance": {"source_type": "extracted" if role == "actual_tail_frame" else "uploaded"},
    }
    if role == "actual_tail_frame":
        result.update({"derived_from_segment_id": segment})
    else:
        result["path"] = f"/{media_id}.png"
    result.update(extra)
    return result


def continuity(decision: str) -> dict[str, object]:
    reuse = decision == "reuse_previous_tail"
    return {
        "is_same_shot": reuse,
        "continuous_action": reuse,
        "continuous_camera": reuse,
        "same_scene": reuse,
        "same_framing": reuse,
        "same_camera_position": reuse,
        "same_time": reuse,
        "same_visual_focus": reuse,
        "requires_recomposition": not reuse,
        "change_triggers": [] if reuse else ["shot"],
        "decision": decision,
    }


def valid_document() -> dict[str, object]:
    refs = {"character_reference_ids": [], "location_reference_ids": [], "style_reference_ids": [], "video_reference_ids": [], "audio_reference_ids": []}
    return {
        "segment_plan": [
            {"segment_id": "SEG001", "shot_ids": ["S01"], "shot_bindings": [{"prompt_shot_index": 1, "shot_id": "S01", "local_start": 0}], "previous_segment_id": None, "start": 0, "end": 5, "duration": 5, "entry_strategy": "new_first_frame", "entry_frame_source": "FF001", "runtime_entry_dependency": None, "exit_frame_required": True, "last_frame_target_media_id": None, "actual_tail_frame_media_id": "AT001", "reference_strategy": refs, "continuity_decision": continuity("generate_new_first_frame"), "reason": "scene entry"},
            {"segment_id": "SEG002", "shot_ids": ["S01"], "shot_bindings": [{"prompt_shot_index": 1, "shot_id": "S01", "local_start": 0}], "previous_segment_id": "SEG001", "start": 5, "end": 10, "duration": 5, "entry_strategy": "use_previous_tail_frame", "entry_frame_source": None, "runtime_entry_dependency": {"kind": "previous_actual_tail_frame", "previous_segment_id": "SEG001", "expected_media_id": "AT001"}, "exit_frame_required": False, "last_frame_target_media_id": None, "actual_tail_frame_media_id": None, "reference_strategy": refs, "continuity_decision": continuity("reuse_previous_tail"), "reason": "continuous action"},
        ],
        "frame_plan": [
            {"segment_id": "SEG001", "first_frame_media_id": "FF001", "last_frame_target_media_id": None, "actual_tail_frame_media_id": "AT001", "reference_media_ids": []},
            {"segment_id": "SEG002", "first_frame_media_id": None, "last_frame_target_media_id": None, "actual_tail_frame_media_id": None, "reference_media_ids": []},
        ],
        "image_jobs": [],
        "media_manifest": {"status": "ready_for_compile", "media": [media("FF001", "first_frame", "SEG001"), media("AT001", "actual_tail_frame", "SEG001")]},
    }


class SemanticValidationTests(unittest.TestCase):
    def test_accepts_runtime_tail_dependency(self) -> None:
        self.assertEqual(validator.validate(valid_document()), [])

    def test_rejects_first_segment_tail_reuse(self) -> None:
        document = valid_document()
        first = document["segment_plan"][0]
        first["entry_strategy"] = "use_previous_tail_frame"
        first["entry_frame_source"] = None
        errors = validator.validate(document)
        self.assertIn("first_segment_tail", {item["code"] for item in errors})

    def test_rejects_short_segment_and_gap(self) -> None:
        document = valid_document()
        document["segment_plan"][1].update({"start": 6, "end": 8, "duration": 2})
        codes = {item["code"] for item in validator.validate(document)}
        self.assertIn("timeline_gap", codes)
        self.assertIn("h3_duration", codes)

    def test_rejects_first_frame_on_continuation(self) -> None:
        document = valid_document()
        document["segment_plan"][1]["entry_frame_source"] = "FF001"
        self.assertIn("continuation_first_frame", {item["code"] for item in validator.validate(document)})


if __name__ == "__main__":
    unittest.main()


def _shot(shot_id, start, end, scene="scene_change", framing="changed", camera="changed",
          boundary="shot_change"):
    return {"id": shot_id, "start": start, "end": end, "boundary_type": boundary,
            "camera_continuity": camera, "action_continuity": "discontinuous",
            "framing_continuity": framing, "scene_continuity": scene,
            "recomposition_needed": True}


def _packed_document():
    """One 10s segment covering three short shots."""
    refs = {"character_reference_ids": [], "location_reference_ids": [], "style_reference_ids": [],
            "video_reference_ids": [], "audio_reference_ids": []}
    return {
        "schema_version": "1.2",
        "status": "complete",
        "segment_plan": [{
            "segment_id": "SEG001",
            "shot_ids": ["S01", "S02", "S03"],
            "shot_bindings": [{"prompt_shot_index": 1, "shot_id": "S01", "local_start": 0},
                              {"prompt_shot_index": 2, "shot_id": "S02", "local_start": 3},
                              {"prompt_shot_index": 3, "shot_id": "S03", "local_start": 6}],
            "previous_segment_id": None, "start": 0, "end": 10, "duration": 10,
            "entry_strategy": "new_first_frame", "entry_frame_source": "FF001",
            "runtime_entry_dependency": None, "exit_frame_required": False,
            "last_frame_target_media_id": None, "actual_tail_frame_media_id": None,
            "reference_strategy": refs, "continuity_decision": continuity("generate_new_first_frame"),
            "reason": "packed short shots",
        }],
        "frame_plan": [{"segment_id": "SEG001", "first_frame_media_id": "FF001",
                        "last_frame_target_media_id": None, "actual_tail_frame_media_id": None,
                        "reference_media_ids": []}],
        "image_jobs": [],
        "media_manifest": {"status": "draft", "media": [media("FF001", "first_frame", "SEG001")]},
        "warnings": [], "errors": [],
    }


def _packed_shot_ir():
    return {"schema_version": "1.1", "status": "complete", "duration": 10,
            "shots": [_shot("S01", 0, 3), _shot("S02", 3, 6), _shot("S03", 6, 10)]}


class PackedSegmentTests(unittest.TestCase):
    def codes(self, document, shot_ir):
        return {item["code"] for item in validator.validate(document, shot_ir)}

    def test_packed_segment_is_accepted(self):
        self.assertEqual(validator.validate(_packed_document(), _packed_shot_ir()), [])

    def test_unknown_shot_id_is_rejected(self):
        document = _packed_document()
        document["segment_plan"][0]["shot_ids"][2] = "S99"
        document["segment_plan"][0]["shot_bindings"][2]["shot_id"] = "S99"
        self.assertIn("unknown_shot", self.codes(document, _packed_shot_ir()))

    def test_incomplete_shot_coverage_is_rejected(self):
        document = _packed_document()
        document["segment_plan"][0]["shot_ids"] = ["S01", "S02"]
        document["segment_plan"][0]["shot_bindings"] = document["segment_plan"][0]["shot_bindings"][:2]
        self.assertIn("shot_coverage", self.codes(document, _packed_shot_ir()))

    def test_wrong_local_start_is_rejected(self):
        document = _packed_document()
        document["segment_plan"][0]["shot_bindings"][1]["local_start"] = 4
        self.assertIn("shot_binding_mismatch", self.codes(document, _packed_shot_ir()))

    def test_more_than_three_shots_is_rejected(self):
        document = _packed_document()
        shot_ir = _packed_shot_ir()
        shot_ir["shots"] = [_shot("S01", 0, 2), _shot("S02", 2, 4), _shot("S03", 4, 7), _shot("S04", 7, 10)]
        document["segment_plan"][0]["shot_ids"] = ["S01", "S02", "S03", "S04"]
        document["segment_plan"][0]["shot_bindings"] = [
            {"prompt_shot_index": index + 1, "shot_id": shot_id, "local_start": local}
            for index, (shot_id, local) in enumerate([("S01", 0), ("S02", 2), ("S03", 4), ("S04", 7)])]
        self.assertIn("segment_shot_cap", self.codes(document, shot_ir))

    def test_reference_budget_is_capped(self):
        document = _packed_document()
        document["segment_plan"][0]["reference_strategy"]["character_reference_ids"] = ["R1", "R2", "R3"]
        document["segment_plan"][0]["reference_strategy"]["style_reference_ids"] = ["R4", "R5"]
        self.assertIn("reference_budget", self.codes(document, _packed_shot_ir()))

    def test_continuity_labels_must_agree_with_decision(self):
        document = _packed_document()
        shot_ir = _packed_shot_ir()
        document["segment_plan"].append({
            **document["segment_plan"][0], "segment_id": "SEG002", "previous_segment_id": "SEG001",
            "start": 10, "end": 15, "duration": 5, "shot_ids": ["S04"],
            "shot_bindings": [{"prompt_shot_index": 1, "shot_id": "S04", "local_start": 0}],
            "entry_frame_source": "FF002",
            "continuity_decision": {**continuity("generate_new_first_frame"), "same_scene": True},
        })
        document["frame_plan"].append({**document["frame_plan"][0], "segment_id": "SEG002",
                                       "first_frame_media_id": "FF002"})
        document["media_manifest"]["media"].append(media("FF002", "first_frame", "SEG002"))
        shot_ir["shots"].append(_shot("S04", 10, 15, scene="scene_change"))
        shot_ir["duration"] = 15
        self.assertIn("continuity_label_conflict", self.codes(document, shot_ir))

    def test_exit_state_must_be_carried_into_the_first_frame_prompt(self):
        document = _packed_document()
        shot_ir = _packed_shot_ir()
        shot_ir["shots"].append(_shot("S04", 10, 15, scene="same_scene", framing="same", camera="continuous"))
        shot_ir["duration"] = 15
        shot_ir["continuity_exit_state"] = {"by_shot": [{
            "shot_id": "S03", "staging": "he stands at the door", "wardrobe_state": "coat open",
            "held_props": ["brass key"], "scene_state": "door ajar", "lighting_state": "dusk"}]}
        document["segment_plan"].append({
            **document["segment_plan"][0], "segment_id": "SEG002", "previous_segment_id": "SEG001",
            "start": 10, "end": 15, "duration": 5, "shot_ids": ["S04"],
            "shot_bindings": [{"prompt_shot_index": 1, "shot_id": "S04", "local_start": 0}],
            "entry_frame_source": "FF002",
            "continuity_decision": {**continuity("generate_new_first_frame"), "same_scene": True,
                                    "same_framing": True, "same_camera_position": True},
        })
        document["frame_plan"].append({**document["frame_plan"][0], "segment_id": "SEG002",
                                       "first_frame_media_id": "FF002"})
        document["media_manifest"]["media"].append(media("FF002", "first_frame", "SEG002", source_job="JOB1"))
        document["image_jobs"].append({
            "job_id": "JOB1", "type": "image_generation", "role": "first_frame",
            "related_segments": ["SEG002"], "prompt": "he stands at the door, coat open",
            "negative_prompt": "", "output_media_id": "FF002", "status": "pending"})
        self.assertIn("exit_state_not_carried", self.codes(document, shot_ir))

        document["image_jobs"][0]["prompt"] = ("he stands at the door, coat open, holding a brass key; "
                                               "door ajar; dusk")
        self.assertNotIn("exit_state_not_carried", self.codes(document, shot_ir))

    def test_tail_frame_input_requires_runtime_pending_job(self):
        document = _packed_document()
        document["media_manifest"]["media"].append(media("AT001", "actual_tail_frame", "SEG001"))
        document["media_manifest"]["media"].append(media("FF009", "first_frame", "SEG001", source_job="JOB9"))
        document["image_jobs"].append({
            "job_id": "JOB9", "type": "image_generation", "role": "first_frame",
            "related_segments": ["SEG001"], "prompt": "x", "negative_prompt": "",
            "output_media_id": "FF009", "input_media_ids": ["AT001"], "status": "pending"})
        self.assertIn("runtime_input_status", self.codes(document, _packed_shot_ir()))
        document["image_jobs"][0]["status"] = "runtime_pending"
        self.assertNotIn("runtime_input_status", self.codes(document, _packed_shot_ir()))
