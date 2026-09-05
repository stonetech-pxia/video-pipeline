from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "resolve_assets.py"
SPEC = importlib.util.spec_from_file_location("resolve_assets", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
resolver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resolver)


def story():
    return {
        "scenes": [{"id": "S01", "location_id": "L01"}, {"id": "S02", "location_id": "L02"}],
        "beats": [{"id": "B01", "scene_id": "S01"}, {"id": "B02", "scene_id": "S01"},
                  {"id": "B03", "scene_id": "S02"}],
        "characters": [{"id": "C01", "name": "周砚", "description": "a postal clerk"}],
        "locations": [{"id": "L01", "name": "post office"}, {"id": "L02", "name": "back alley"}],
    }


def shot(shot_id, beats, cast=("C01",), environment="a room", lighting="cold light"):
    return {
        "id": shot_id,
        "source_beat_ids": list(beats),
        "characters_in_frame": list(cast),
        "environment": environment,
        "lighting": lighting,
    }


def shot_ir(*shots):
    return {"schema_version": "1.1", "status": "complete", "shots": list(shots)}


class ResolveAssetsTests(unittest.TestCase):
    def test_a_shot_learns_its_scene_and_location_from_the_story(self):
        resolved, _, _ = resolver.resolve(
            shot_ir(shot("A1", ["B01"]), shot("A2", ["B03"])), story(), resolver.blank_registry())
        self.assertEqual([(item["scene_id"], item["location_id"]) for item in resolved["shots"]],
                         [("S01", "L01"), ("S02", "L02")])

    def test_a_shot_whose_beats_span_two_scenes_is_refused(self):
        with self.assertRaises(resolver.ResolveError):
            resolver.resolve(shot_ir(shot("A1", ["B01", "B03"])), story(), resolver.blank_registry())

    def test_a_new_subject_gets_a_placeholder_carrying_the_story_name(self):
        registry = resolver.blank_registry()
        resolver.resolve(shot_ir(shot("A1", ["B01"])), story(), registry)
        self.assertEqual(registry["characters"]["C01"]["name"], "周砚")
        self.assertEqual(registry["characters"]["C01"]["description"], "a postal clerk")
        self.assertIsNone(registry["characters"]["C01"]["image"])
        self.assertEqual(registry["locations"]["L01"]["name"], "post office")

    def test_a_registered_image_is_bound_to_the_shot(self):
        registry = resolver.blank_registry()
        registry["characters"]["C01"] = {"name": "周砚", "image": "assets/C01.png", "settled": []}
        registry["locations"]["L01"] = {"name": "post office", "image": "assets/L01.png", "settled": []}
        resolved, unresolved, _ = resolver.resolve(shot_ir(shot("A1", ["B01"])), story(), registry)
        self.assertEqual(resolved["shots"][0]["reference_assets"],
                         {"characters": {"C01": "assets/C01.png"}, "location": {"L01": "assets/L01.png"}})
        self.assertEqual(unresolved, [])

    def test_a_subject_without_an_image_is_reported_not_invented(self):
        _, unresolved, _ = resolver.resolve(
            shot_ir(shot("A1", ["B01"])), story(), resolver.blank_registry())
        self.assertIn("A1: character C01 has no reference image", unresolved)
        self.assertIn("A1: location L01 has no reference image", unresolved)

    def test_what_the_director_settled_is_recorded_against_the_location(self):
        registry = resolver.blank_registry()
        _, _, recorded = resolver.resolve(
            shot_ir(shot("A1", ["B01"], environment="a green sorting room", lighting="east window")),
            story(), registry)
        self.assertEqual(recorded, 1)
        self.assertEqual(registry["locations"]["L01"]["settled"],
                         [{"shot_id": "A1", "text": "a green sorting room east window"}])

    def test_recording_the_same_shot_twice_replaces_rather_than_duplicates(self):
        registry = resolver.blank_registry()
        artifact = shot_ir(shot("A1", ["B01"], environment="a green room", lighting="east window"))
        resolver.resolve(artifact, story(), registry)
        _, _, again = resolver.resolve(artifact, story(), registry)
        self.assertEqual(again, 0)
        self.assertEqual(len(registry["locations"]["L01"]["settled"]), 1)

        artifact["shots"][0]["environment"] = "a repainted room"
        _, _, changed = resolver.resolve(artifact, story(), registry)
        self.assertEqual(changed, 1)
        self.assertEqual(registry["locations"]["L01"]["settled"][0]["text"],
                         "a repainted room east window")

    def test_a_later_shot_appends_beside_the_earlier_one(self):
        registry = resolver.blank_registry()
        resolver.resolve(
            shot_ir(shot("A1", ["B01"], environment="established"),
                    shot("A2", ["B02"], environment="unchanged")),
            story(), registry)
        self.assertEqual([item["shot_id"] for item in registry["locations"]["L01"]["settled"]],
                         ["A1", "A2"])


if __name__ == "__main__":
    unittest.main()
