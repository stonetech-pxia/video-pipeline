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
        "schema_version": "1.1",
        "status": "complete",
        "duration": 20,
        "characters": [{"id": "C01", "name": "Lin"}],
        "locations": [],
        "props": [],
        "beats": [{"id": "B01", "action": "Lin waits"}],
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
        self.assertIn("complete Story IR cannot contain unresolved ambiguities", validator.validate(story))

    def test_rejects_broken_reference(self) -> None:
        story = valid_story()
        story["dialogue"] = [{"id": "D01", "text": "Hi", "speaker_id": "C99", "beat_id": "B99"}]
        errors = validator.validate(story)
        self.assertTrue(any("speaker_id" in item for item in errors))
        self.assertTrue(any("beat_id" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
