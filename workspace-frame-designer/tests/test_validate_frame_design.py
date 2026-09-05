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
    tail = role == "actual_tail_frame"
    result: dict[str, object] = {
        "id": media_id,
        "type": "frame" if tail else "image",
        "role": role,
        "status": "runtime_pending" if tail else "resolved",
        "source_type": "extracted" if tail else "uploaded",
        "related_segments": [segment],
    }
    if tail:
        result["derived_from_segment_id"] = segment
    else:
        result["path"] = f"/{media_id}.png"
    result.update(extra)
    return result


def prompt(description: str = "the sorting room, morning") -> dict[str, object]:
    return {
        "integrated_multimodal_description": description,
        "overall_soundscape": "room tone",
        "non_diegetic_music": "",
    }


def valid_document() -> dict[str, object]:
    refs = {"character_reference_ids": [], "location_reference_ids": [], "style_reference_ids": [], "video_reference_ids": [], "audio_reference_ids": []}
    return {
        "segment_plan": [
            {"segment_id": "SEG001", "scene_id": "SC01", "shot_ids": ["S01"], "shot_bindings": [{"prompt_shot_index": 1, "shot_id": "S01", "local_start": 0}], "previous_segment_id": None, "start": 0, "end": 5, "duration": 5, "entry_strategy": "references_only", "runtime_entry_dependency": None, "exit_frame_required": True, "actual_tail_frame_media_id": "AT001", "reference_strategy": refs, "prompt": prompt(), "reason": "scene entry"},
            {"segment_id": "SEG002", "scene_id": "SC01", "shot_ids": ["S01"], "shot_bindings": [{"prompt_shot_index": 1, "shot_id": "S01", "local_start": 0}], "previous_segment_id": "SEG001", "start": 5, "end": 10, "duration": 5, "entry_strategy": "use_previous_tail_frame", "runtime_entry_dependency": {"kind": "previous_actual_tail_frame", "previous_segment_id": "SEG001", "expected_media_id": "AT001"}, "exit_frame_required": False, "actual_tail_frame_media_id": None, "reference_strategy": refs, "prompt": prompt(), "reason": "continues inside the shot"},
        ],
        "media_manifest": {"status": "ready_for_compile", "media": [media("AT001", "actual_tail_frame", "SEG001")]},
    }


class SemanticValidationTests(unittest.TestCase):
    def codes(self, document, shot_ir=None):
        return {item["code"] for item in validator.validate(document, shot_ir)}

    def test_accepts_runtime_tail_dependency(self) -> None:
        self.assertEqual(validator.validate(valid_document()), [])

    def test_rejects_first_segment_tail_reuse(self) -> None:
        document = valid_document()
        document["segment_plan"][0]["entry_strategy"] = "use_previous_tail_frame"
        self.assertIn("first_segment_tail", self.codes(document))

    def test_rejects_short_segment_and_gap(self) -> None:
        document = valid_document()
        document["segment_plan"][1].update({"start": 6, "end": 8, "duration": 2})
        codes = self.codes(document)
        self.assertIn("timeline_gap", codes)
        self.assertIn("h3_duration", codes)

    def test_a_scene_opener_must_use_its_references(self) -> None:
        document = valid_document()
        document["segment_plan"][1]["scene_id"] = "SC02"
        self.assertIn("scene_entry_strategy", self.codes(document))

    def test_a_segment_inside_a_scene_cannot_start_cold(self) -> None:
        document = valid_document()
        document["segment_plan"][1].update({"entry_strategy": "references_only", "runtime_entry_dependency": None})
        self.assertIn("scene_entry_strategy", self.codes(document))

    def test_a_cold_start_has_nothing_to_continue_from(self) -> None:
        document = valid_document()
        document["segment_plan"][0]["runtime_entry_dependency"] = {
            "kind": "previous_actual_tail_frame", "previous_segment_id": "SEG000", "expected_media_id": "AT000"}
        self.assertIn("unexpected_runtime_dependency", self.codes(document))


def _shot(shot_id, start, end, scene="scene_change", framing="changed", camera="changed",
          boundary="shot_change", scene_id="SC01"):
    return {"id": shot_id, "start": start, "end": end, "boundary_type": boundary,
            "camera_continuity": camera, "action_continuity": "discontinuous",
            "framing_continuity": framing, "scene_continuity": scene,
            "recomposition_needed": True, "scene_id": scene_id}


def _packed_document():
    """One 10s segment covering three short shots."""
    refs = {"character_reference_ids": [], "location_reference_ids": [], "style_reference_ids": [],
            "video_reference_ids": [], "audio_reference_ids": []}
    return {
        "schema_version": "1.3",
        "status": "complete",
        "segment_plan": [{
            "segment_id": "SEG001",
            "scene_id": "SC01",
            "shot_ids": ["S01", "S02", "S03"],
            "shot_bindings": [{"prompt_shot_index": 1, "shot_id": "S01", "local_start": 0},
                              {"prompt_shot_index": 2, "shot_id": "S02", "local_start": 3},
                              {"prompt_shot_index": 3, "shot_id": "S03", "local_start": 6}],
            "previous_segment_id": None, "start": 0, "end": 10, "duration": 10,
            "entry_strategy": "references_only", "runtime_entry_dependency": None,
            "exit_frame_required": False, "actual_tail_frame_media_id": None,
            "reference_strategy": refs, "prompt": prompt(), "reason": "packed short shots",
        }],
        "media_manifest": {"status": "draft", "media": []},
        "warnings": [], "errors": [],
    }


def _packed_shot_ir():
    return {"schema_version": "1.1", "status": "complete", "duration": 10,
            "shots": [_shot("S01", 0, 3), _shot("S02", 3, 6), _shot("S03", 6, 10)]}


def _second_scene(document, shot_ir, **segment):
    """Append a second scene: one shot at 10-15s, opened by one segment."""
    shot_ir["shots"].append(_shot("S04", 10, 15, scene_id="SC02"))
    shot_ir["duration"] = 15
    document["segment_plan"].append({
        **document["segment_plan"][0], "segment_id": "SEG002", "previous_segment_id": "SEG001",
        "scene_id": "SC02", "start": 10, "end": 15, "duration": 5, "shot_ids": ["S04"],
        "shot_bindings": [{"prompt_shot_index": 1, "shot_id": "S04", "local_start": 0}],
        **segment,
    })
    return document, shot_ir


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

    def test_a_shot_from_another_scene_is_rejected(self):
        document = _packed_document()
        shot_ir = _packed_shot_ir()
        shot_ir["shots"][2]["scene_id"] = "SC02"
        self.assertIn("scene_mismatch", self.codes(document, shot_ir))


class CarriedExitStateTests(unittest.TestCase):
    """A scene opens cold, so what survives the change must be said in words."""

    def codes(self, document, shot_ir):
        return {item["code"] for item in validator.validate(document, shot_ir)}

    def scene_change(self, description, scene="scene_change"):
        document, shot_ir = _second_scene(_packed_document(), _packed_shot_ir(),
                                          prompt=prompt(description))
        shot_ir["shots"][-1]["scene_continuity"] = scene
        shot_ir["continuity_exit_state"] = {"by_shot": [{
            "shot_id": "S03", "staging": "he stands at the door", "wardrobe_state": "coat still buttoned",
            "held_props": ["folded letter"], "scene_state": "door ajar", "lighting_state": "dusk"}]}
        return document, shot_ir

    def test_wardrobe_and_props_must_survive_the_scene_change(self):
        document, shot_ir = self.scene_change("he steps onto the platform")
        self.assertIn("exit_state_not_carried", self.codes(document, shot_ir))

    def test_restating_both_is_accepted(self):
        document, shot_ir = self.scene_change(
            "he steps onto the platform, coat still buttoned, the folded letter in his pocket")
        self.assertNotIn("exit_state_not_carried", self.codes(document, shot_ir))

    def test_the_place_is_not_carried_because_it_reset(self):
        document, shot_ir = self.scene_change(
            "coat still buttoned, the folded letter in his pocket")
        # staging, scene_state, and lighting_state belong to the place left behind.
        self.assertNotIn("exit_state_not_carried", self.codes(document, shot_ir))

    def test_a_time_jump_carries_nothing(self):
        document, shot_ir = self.scene_change("a week later, at the counter", scene="time_change")
        self.assertNotIn("exit_state_not_carried", self.codes(document, shot_ir))

    def test_the_film_opening_carries_nothing(self):
        document = _packed_document()
        shot_ir = _packed_shot_ir()
        shot_ir["continuity_exit_state"] = {"by_shot": [{
            "shot_id": "S01", "staging": "x", "wardrobe_state": "coat still buttoned",
            "held_props": [], "scene_state": "", "lighting_state": ""}]}
        self.assertNotIn("exit_state_not_carried", self.codes(document, shot_ir))


def _cast_document(character_reference_ids):
    """The packed segment, with a character-reference slot under test."""
    document = _packed_document()
    segment = document["segment_plan"][0]
    segment["reference_strategy"] = {
        "character_reference_ids": list(character_reference_ids),
        "location_reference_ids": [], "style_reference_ids": [],
        "video_reference_ids": [], "audio_reference_ids": [],
    }
    document["media_manifest"]["media"].extend([
        media("REF_C01", "character_reference", "SEG001", subject_id="C01"),
        media("REF_C02", "character_reference", "SEG001", subject_id="C02"),
        media("REF_L01", "location_reference", "SEG001"),
    ])
    return document


def _cast_shot_ir(*casts):
    shot_ir = _packed_shot_ir()
    for shot, cast in zip(shot_ir["shots"], casts):
        shot["characters_in_frame"] = list(cast)
    return shot_ir


class CharacterReferenceTests(unittest.TestCase):
    def codes(self, document, shot_ir):
        return {item["code"] for item in validator.validate(document, shot_ir)}

    def test_a_reference_for_everyone_in_frame_is_accepted(self):
        document = _cast_document(["REF_C01", "REF_C02"])
        shot_ir = _cast_shot_ir(["C01"], ["C01", "C02"], ["C02"])
        self.assertEqual(validator.validate(document, shot_ir), [])

    def test_a_face_in_frame_without_a_reference_is_rejected(self):
        document = _cast_document(["REF_C01"])
        shot_ir = _cast_shot_ir(["C01"], ["C01", "C02"], ["C01"])
        self.assertIn("missing_character_reference", self.codes(document, shot_ir))

    def test_a_reference_for_someone_who_never_appears_is_rejected(self):
        document = _cast_document(["REF_C01", "REF_C02"])
        shot_ir = _cast_shot_ir(["C01"], ["C01"], ["C01"])
        self.assertIn("unused_character_reference", self.codes(document, shot_ir))

    def test_a_location_image_in_the_character_slot_is_rejected(self):
        document = _cast_document(["REF_C01", "REF_L01"])
        shot_ir = _cast_shot_ir(["C01"], ["C01"], ["C01"])
        self.assertIn("reference_role", self.codes(document, shot_ir))


if __name__ == "__main__":
    unittest.main()
