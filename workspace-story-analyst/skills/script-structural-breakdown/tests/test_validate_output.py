from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate_output.py"
SPEC = importlib.util.spec_from_file_location("story_validate_output", SCRIPT)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def valid_story() -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "status": "complete",
        "duration": 20,
        "scenes": [
            {
                "id": "S01",
                "slugline": "INT. CAFE - NIGHT",
                "location_id": "L01",
                "time_of_day": "night",
                "duration_budget": 20,
                "beat_ids": ["B01"],
                "exit_state": "Lin is still seated.",
            }
        ],
        "characters": [
            {"id": "C01", "name": "Lin", "wardrobe": "grey knit coat", "description": "Waiting."}
        ],
        "locations": [{"id": "L01", "name": "Cafe"}],
        "props": [],
        "beats": [
            {
                "id": "B01",
                "scene_id": "S01",
                "action": "Lin waits",
                "emotion": "restless",
                "entity_ids": ["C01"],
                "dialogue_ids": [],
            }
        ],
        "dialogue": [],
        "continuity_constraints": [],
        "transition_markers": [],
        "locked_constraints": [],
        "ambiguities": [],
    }


class StoryIRValidatorTests(unittest.TestCase):
    def test_accepts_camera_neutral_story_ir(self) -> None:
        self.assertEqual(validator.validate(valid_story()), [])

    def test_rejects_legacy_camera_contract(self) -> None:
        story = valid_story()
        story["beats"][0]["camera"] = "dolly in"
        self.assertTrue(any("camera" in item for item in validator.validate(story)))

    def test_rejects_complete_with_ambiguity(self) -> None:
        story = valid_story()
        story["ambiguities"] = ["Who speaks?"]
        self.assertIn("complete Story IR cannot contain blocking ambiguities", validator.validate(story))

    def test_allows_complete_with_non_blocking_ambiguity(self) -> None:
        story = valid_story()
        story["ambiguities"] = [
            {"id": "AMB01", "severity": "low", "field": "weather", "question": "Weather is unstated."}
        ]
        self.assertEqual(validator.validate(story), [])

    def test_rejects_complete_with_flagged_blocking_ambiguity(self) -> None:
        story = valid_story()
        story["ambiguities"] = [
            {"id": "AMB01", "severity": "blocking", "question": "Who speaks?"}
        ]
        self.assertIn("complete Story IR cannot contain blocking ambiguities", validator.validate(story))

    def test_rejects_marker_restating_a_scene_boundary(self) -> None:
        story = valid_story()
        story["transition_markers"] = [
            {"marker_id": "TM01", "at_beat_id": "B01", "type": "scene_change",
             "from": "a", "to": "b", "reason": "r"}
        ]
        errors = validator.validate(story)
        self.assertTrue(any("restates the start of scene S01" in item for item in errors))

    def test_allows_weather_change_at_a_scene_boundary(self) -> None:
        story = valid_story()
        story["transition_markers"] = [
            {"marker_id": "TM01", "at_beat_id": "B01", "type": "weather_change",
             "from": "rain", "to": "clear", "reason": "r"}
        ]
        self.assertEqual(validator.validate(story), [])

    def test_allows_continuity_break_at_a_scene_boundary(self) -> None:
        story = valid_story()
        story["transition_markers"] = [
            {"marker_id": "TM01", "at_beat_id": "B01", "type": "continuity_break",
             "from": "now", "to": "three years earlier", "reason": "flashback"}
        ]
        self.assertEqual(validator.validate(story), [])

    def test_allows_time_change_inside_a_scene(self) -> None:
        story = valid_story()
        story["beats"].append(
            {"id": "B02", "scene_id": "S01", "action": "Dawn arrives", "emotion": None,
             "entity_ids": ["C01"], "dialogue_ids": []}
        )
        story["scenes"][0]["beat_ids"] = ["B01", "B02"]
        story["transition_markers"] = [
            {"marker_id": "TM01", "at_beat_id": "B02", "type": "time_change",
             "from": "night", "to": "dawn", "reason": "the night ends mid-scene"}
        ]
        self.assertEqual(validator.validate(story), [])

    def test_rejects_location_in_beat_entity_ids(self) -> None:
        story = valid_story()
        story["beats"][0]["entity_ids"] = ["C01", "L01"]
        errors = validator.validate(story)
        self.assertTrue(any("L01 is a location" in item for item in errors))

    def test_accepts_props_in_beat_entity_ids(self) -> None:
        story = valid_story()
        story["props"] = [{"id": "P01", "name": "Cold coffee"}]
        story["beats"][0]["entity_ids"] = ["C01", "P01"]
        self.assertEqual(validator.validate(story), [])

    def test_rejects_broken_reference(self) -> None:
        story = valid_story()
        story["dialogue"] = [
            {"id": "D01", "text": "Hi", "speaker_id": "C99", "beat_id": "B99"}
        ]
        errors = validator.validate(story)
        self.assertTrue(any("speaker_id" in item for item in errors))
        self.assertTrue(any("beat_id" in item for item in errors))

    def test_rejects_beat_outside_any_scene(self) -> None:
        story = valid_story()
        story["beats"].append(
            {
                "id": "B02",
                "scene_id": "S01",
                "action": "Lin stands",
                "emotion": None,
                "entity_ids": ["C01"],
                "dialogue_ids": [],
            }
        )
        self.assertIn("beats[1]: beat B02 belongs to no scene", validator.validate(story))

    def test_rejects_scene_claiming_unknown_beat(self) -> None:
        story = valid_story()
        story["scenes"][0]["beat_ids"] = ["B01", "B99"]
        self.assertIn("scenes[0].beat_ids: unknown beat B99", validator.validate(story))

    def test_rejects_unstated_wardrobe_without_ambiguity(self) -> None:
        story = valid_story()
        story["characters"][0]["wardrobe"] = None
        self.assertIn(
            "characters[0]: unstated wardrobe requires ambiguity AMB-WARDROBE-C01",
            validator.validate(story),
        )

    def test_accepts_unstated_wardrobe_with_ambiguity(self) -> None:
        story = valid_story()
        story["characters"][0]["wardrobe"] = None
        story["ambiguities"] = [
            {
                "id": "AMB-WARDROBE-C01",
                "severity": "low",
                "field": "wardrobe",
                "subject_id": "C01",
                "question": "Wardrobe is unstated.",
            }
        ]
        self.assertEqual(validator.validate(story), [])

    def test_accepts_scene_range_scope(self) -> None:
        story = valid_story()
        story["continuity_constraints"] = [
            {
                "id": "CC01",
                "category": "wardrobe",
                "subject_id": "C01",
                "rule": "The grey coat never changes.",
                "scope": {"from": "S01", "to": "S01"},
                "locked": True,
            }
        ]
        self.assertEqual(validator.validate(story), [])

    def test_rejects_scope_with_unknown_id(self) -> None:
        story = valid_story()
        story["continuity_constraints"] = [
            {
                "id": "CC01",
                "category": "wardrobe",
                "subject_id": "C01",
                "rule": "The grey coat never changes.",
                "scope": ["B01", "S99"],
                "locked": True,
            }
        ]
        self.assertIn(
            "continuity_constraints[0].scope: unknown id S99", validator.validate(story)
        )


if __name__ == "__main__":
    unittest.main()
