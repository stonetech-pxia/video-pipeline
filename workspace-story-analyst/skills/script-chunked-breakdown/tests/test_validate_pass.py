from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate_pass.py"
SPEC = importlib.util.spec_from_file_location("story_validate_pass", SCRIPT)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def plan() -> dict[str, object]:
    return {"locations": [{"id": "L01", "name": "Cafe"}]}


def chunk(entity_ids: list[str]) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "chunk_id": "K01",
        "scenes": [{"id": "S01", "beat_ids": ["B01"], "exit_state": "Lin is seated."}],
        "beats": [
            {
                "id": "B01",
                "scene_id": "S01",
                "action": "Lin waits",
                "emotion": None,
                "entity_ids": entity_ids,
                "dialogue_ids": [],
            }
        ],
        "dialogue": [],
        "continuity_constraints": [],
        "transition_markers": [],
        "ambiguities": [],
    }


class ValidatePassTests(unittest.TestCase):
    def test_accepts_a_clean_chunk(self) -> None:
        self.assertEqual(validator.validate("chunk", chunk(["C01"]), plan()), [])

    def test_rejects_a_location_in_entity_ids(self) -> None:
        errors = validator.validate("chunk", chunk(["C01", "L01"]), plan())
        self.assertTrue(any("L01 is a location" in item for item in errors))

    def test_rejects_a_marker_restating_a_scene_boundary(self) -> None:
        bad = chunk(["C01"])
        bad["transition_markers"] = [
            {
                "marker_id": "TM01",
                "at_beat_id": "B01",
                "type": "scene_change",
                "from": "a",
                "to": "b",
                "reason": "r",
            }
        ]
        errors = validator.validate("chunk", bad, plan())
        self.assertTrue(any("restates the start of scene S01" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
