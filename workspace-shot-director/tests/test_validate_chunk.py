from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate_chunk.py"
SPEC = importlib.util.spec_from_file_location("validate_chunk", SCRIPT)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)

PROSE = {
    "dramatic_purpose": "open the scene",
    "framing": "medium",
    "angle": "eye level",
    "camera_position": "in front of her",
    "camera_motion": "static",
    "focus": "on her hands",
    "blocking": "she stands left of the door",
    "subject_action": "she reads the letter",
    "visible_emotion": "still face, slow blink",
    "environment": "a sorting hall",
    "lighting": "cold overhead light",
    "diegetic_audio": "paper, a distant radio",
    "transition": "cut",
}
LABELS = {
    "boundary_type": "shot_change",
    "camera_continuity": "changed",
    "action_continuity": "discontinuous",
    "framing_continuity": "changed",
    "scene_continuity": "scene_change",
    "recomposition_needed": True,
}


def shot(shot_id, start, end, beats, lines=(), spoken="", load=0, cast=("C01",)):
    return {
        "id": shot_id,
        "start": start,
        "end": end,
        "source_beat_ids": list(beats),
        "characters_in_frame": list(cast),
        "dialogue_ids": list(lines),
        "dialogue": spoken,
        "boundary_risk": {"state_transfer_load": load, "reason": "test"},
        "composition_control": "normal",
        **PROSE,
        **LABELS,
    }


def exit_state(shot_id):
    return {
        "shot_id": shot_id,
        "staging": "she stands left of the door, facing the corridor",
        "wardrobe_state": "coat buttoned",
        "held_props": ["letter"],
        "scene_state": "door half open",
        "lighting_state": "late afternoon",
    }


def chunk(shots, chunk_id="K1", start=0, end=20, status="complete", **extra):
    data = {
        "schema_version": "1.1",
        "chunk_id": chunk_id,
        "status": status,
        "start": start,
        "end": end,
        "shots": shots,
        "continuity_exit_state": {"by_shot": [exit_state(item["id"]) for item in shots]},
        "warnings": [],
        "errors": [],
    }
    data.update(extra)
    return data


def plan(chunk_id="K1", previous=None, start=0, end=20, beats=("B01", "B02"), dialogue=(),
         scene_of=None, cast=("C01", "C02"), mid_scene=False):
    scene_of = scene_of or {beat: "S01" for beat in beats}
    return {
        "schema_version": "1.0",
        "duration": end,
        "chunks": [{
            "chunk_id": chunk_id,
            "previous_chunk_id": previous,
            "start": start,
            "end": end,
            "duration": end - start,
            "scene_ids": sorted(set(scene_of.values())),
            "beat_ids": list(beats),
            "dialogue_ids": [line["id"] for line in dialogue],
            "entry_mid_scene": mid_scene,
            "entry_constraints_crossed": [],
            "story_slice": {
                "dialogue": list(dialogue),
                "characters": [{"id": item} for item in cast],
                "beats": [{"id": beat, "scene_id": scene_of[beat], "entity_ids": list(cast)}
                          for beat in beats],
            },
        }],
    }


def valid_chunk():
    return chunk([shot("A1", 0, 10, ["B01"]), shot("A2", 10, 20, ["B02"])])


class ValidateChunkTests(unittest.TestCase):
    def test_a_well_formed_chunk_passes(self):
        self.assertEqual(checker.validate(plan(), "K1", valid_chunk()), [])

    def test_a_window_the_plan_did_not_fix_is_refused(self):
        artifact = valid_chunk()
        artifact["start"], artifact["shots"][0]["start"] = 5, 5
        errors = checker.validate(plan(), "K1", artifact)
        self.assertTrue(any("the plan fixed its window" in error for error in errors))

    def test_shots_must_reach_the_end_of_the_window(self):
        artifact = chunk([shot("A1", 0, 10, ["B01", "B02"])])
        errors = checker.validate(plan(), "K1", artifact)
        self.assertTrue(any("shots[-1].end is 10" in error for error in errors))

    def test_a_gap_between_shots_is_refused(self):
        artifact = chunk([shot("A1", 0, 8, ["B01"]), shot("A2", 10, 20, ["B02"])])
        errors = checker.validate(plan(), "K1", artifact)
        self.assertTrue(any("must be contiguous" in error for error in errors))

    def test_a_beat_no_shot_covers_is_reported(self):
        artifact = chunk([shot("A1", 0, 10, ["B01"]), shot("A2", 10, 20, ["B01"])])
        errors = checker.validate(plan(), "K1", artifact)
        self.assertIn("source_beat_ids: beat B02 is covered by no shot", errors)

    def test_a_beat_from_another_chunk_is_reported(self):
        artifact = chunk([shot("A1", 0, 10, ["B01"]), shot("A2", 10, 20, ["B02", "B09"])])
        errors = checker.validate(plan(), "K1", artifact)
        self.assertIn("source_beat_ids: beat B09 is not in this chunk", errors)

    def test_rewritten_dialogue_is_refused(self):
        lines = [{"id": "D01", "text": "you promised you would come back"}]
        artifact = chunk([
            shot("A1", 0, 10, ["B01"], lines=["D01"], spoken="you said you would come back"),
            shot("A2", 10, 20, ["B02"]),
        ])
        errors = checker.validate(plan(dialogue=lines), "K1", artifact)
        self.assertTrue(any("the text of D01 was changed" in error for error in errors))

    def test_dialogue_kept_verbatim_passes(self):
        lines = [{"id": "D01", "text": "you promised you would come back"}]
        artifact = chunk([
            shot("A1", 0, 10, ["B01"], lines=["D01"],
                 spoken="she says: you promised you would come back"),
            shot("A2", 10, 20, ["B02"]),
        ])
        self.assertEqual(checker.validate(plan(dialogue=lines), "K1", artifact), [])

    def test_a_shot_without_an_exit_state_is_reported(self):
        artifact = valid_chunk()
        artifact["continuity_exit_state"]["by_shot"].pop()
        errors = checker.validate(plan(), "K1", artifact)
        self.assertIn("continuity_exit_state.by_shot: no exit state for A2", errors)

    def test_the_films_first_shot_scores_zero_transfer_load(self):
        artifact = chunk([shot("A1", 0, 10, ["B01"], load=4), shot("A2", 10, 20, ["B02"])])
        errors = checker.validate(plan(), "K1", artifact)
        self.assertTrue(any("the film's first shot scores 0" in error for error in errors))

    def test_a_chunk_on_a_scene_boundary_may_not_open_inside_a_scene(self):
        artifact = valid_chunk()
        artifact["chunk_id"] = "K2"
        artifact["shots"][0]["scene_continuity"] = "same_scene"
        errors = checker.validate(plan(chunk_id="K2", previous="K1"), "K2", artifact)
        self.assertTrue(any("starts on a scene boundary" in error for error in errors))

    def test_a_chunk_the_plan_cut_inside_a_scene_may_open_inside_it(self):
        artifact = valid_chunk()
        artifact["chunk_id"] = "K2"
        artifact["shots"][0]["scene_continuity"] = "same_scene"
        self.assertEqual(
            checker.validate(plan(chunk_id="K2", previous="K1", mid_scene=True), "K2", artifact), []
        )

    def test_a_shot_past_fifteen_seconds_is_refused(self):
        artifact = chunk([shot("A1", 0, 20, ["B01", "B02"])], end=20)
        errors = checker.validate(plan(), "K1", artifact)
        self.assertTrue(any("a shot is one generatable piece" in error for error in errors))

    def test_a_film_level_field_may_not_appear_in_a_chunk(self):
        errors = checker.validate(plan(), "K1", chunk(
            [shot("A1", 0, 20, ["B01", "B02"])], visual_style={"look": "cold"}))
        self.assertTrue(any("visual_style" in error for error in errors))

    def test_a_character_the_scene_does_not_hold_is_refused(self):
        artifact = chunk([shot("A1", 0, 10, ["B01"], cast=("C01", "C09")),
                          shot("A2", 10, 20, ["B02"])])
        errors = checker.validate(plan(), "K1", artifact)
        self.assertIn(
            "shots[0].characters_in_frame: C09 is not in the scene this shot comes from", errors
        )

    def test_a_shot_may_show_fewer_characters_than_the_scene_holds(self):
        artifact = chunk([shot("A1", 0, 10, ["B01"], cast=()),
                          shot("A2", 10, 20, ["B02"], cast=("C01", "C02"))])
        self.assertEqual(checker.validate(plan(), "K1", artifact), [])

    def test_a_shot_may_not_straddle_two_scenes(self):
        artifact = chunk([shot("A1", 0, 20, ["B01", "B02"])])
        errors = checker.validate(plan(scene_of={"B01": "S01", "B02": "S02"}), "K1", artifact)
        self.assertTrue(any("draws its beats from one scene" in error for error in errors))

    def test_an_unplanned_chunk_id_is_refused(self):
        self.assertEqual(
            checker.validate(plan(), "K9", valid_chunk()),
            ["the plan declares no chunk K9"],
        )


if __name__ == "__main__":
    unittest.main()
