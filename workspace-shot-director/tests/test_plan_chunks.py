from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/plan_chunks.py"
SPEC = importlib.util.spec_from_file_location("plan_chunks", SCRIPT)
assert SPEC and SPEC.loader
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)


def scene(scene_id, budget, location, beats):
    return {
        "id": scene_id,
        "slugline": f"INT. {location} - DAY",
        "location_id": location,
        "time_of_day": "day",
        "duration_budget": budget,
        "beat_ids": list(beats),
        "exit_state": f"state after {scene_id}",
    }


def beat(beat_id, scene_id, entities=(), lines=()):
    return {
        "id": beat_id,
        "scene_id": scene_id,
        "action": "something happens",
        "emotion": "calm",
        "entity_ids": list(entities),
        "dialogue_ids": list(lines),
    }


def story(scenes, beats, **extra):
    data = {
        "schema_version": "2.0",
        "status": "complete",
        "duration": sum(item["duration_budget"] for item in scenes),
        "scenes": scenes,
        "characters": [],
        "locations": [],
        "props": [],
        "beats": beats,
        "dialogue": [],
        "continuity_constraints": [],
        "transition_markers": [],
        "locked_constraints": [],
        "ambiguities": [],
    }
    data.update(extra)
    return data


def film(*spec):
    """Build a story from (budget, location, beat_count) triples."""
    scenes, beats, number = [], [], 1
    for index, (budget, location, count) in enumerate(spec, start=1):
        scene_id = f"S{index:02d}"
        owned = [f"B{number + offset:03d}" for offset in range(count)]
        number += count
        scenes.append(scene(scene_id, budget, location, owned))
        beats.extend(beat(beat_id, scene_id) for beat_id in owned)
    return story(scenes, beats)


class ChunkGroupingTests(unittest.TestCase):
    def test_windows_are_contiguous_and_reach_the_total(self):
        plan = planner.plan(film(*[(70, f"L{i:02d}", 2) for i in range(1, 7)]))
        self.assertEqual(plan["chunks"][0]["start"], 0)
        self.assertEqual(plan["chunks"][-1]["end"], plan["duration"])
        for previous, following in zip(plan["chunks"], plan["chunks"][1:]):
            self.assertEqual(previous["end"], following["start"])
            self.assertEqual(following["previous_chunk_id"], previous["chunk_id"])

    def test_every_beat_lands_in_exactly_one_chunk(self):
        data = film((100, "L01", 3), (90, "L02", 2), (80, "L03", 2))
        grouped = [ref for chunk in planner.plan(data)["chunks"] for ref in chunk["beat_ids"]]
        self.assertEqual(grouped, [item["id"] for item in data["beats"]])

    def test_no_chunk_exceeds_the_cap(self):
        plan = planner.plan(film((110, "L01", 2), (100, "L02", 3), (90, "L03", 2), (50, "L04", 1)))
        for chunk in plan["chunks"]:
            self.assertLessEqual(chunk["duration"], planner.MAX_DURATION)

    def test_a_short_film_stays_one_chunk(self):
        plan = planner.plan(film((30, "L01", 1)))
        self.assertEqual(len(plan["chunks"]), 1)
        self.assertEqual(plan["chunks"][0]["duration"], 30)

    def test_a_scene_over_the_cap_is_cut_at_a_beat_and_flagged(self):
        plan = planner.plan(film((120, "L01", 2)))
        self.assertEqual([chunk["beat_ids"] for chunk in plan["chunks"]], [["B001"], ["B002"]])
        self.assertFalse(plan["chunks"][0]["entry_mid_scene"])
        self.assertTrue(plan["chunks"][1]["entry_mid_scene"])

    def test_a_scene_boundary_is_preferred_over_a_seam_inside_a_scene(self):
        plan = planner.plan(film((40, "L01", 1), (40, "L02", 1), (80, "L03", 2)))
        self.assertEqual([chunk["scene_ids"] for chunk in plan["chunks"]],
                         [["S01", "S02"], ["S03"]])
        self.assertFalse(any(chunk["entry_mid_scene"] for chunk in plan["chunks"]))

    def test_a_seam_between_two_scenes_sharing_a_location_is_flagged(self):
        plan = planner.plan(film((70, "L01", 1), (70, "L01", 1)))
        self.assertEqual(len(plan["chunks"]), 2)
        self.assertFalse(plan["chunks"][0]["entry_same_location"])
        self.assertTrue(plan["chunks"][1]["entry_same_location"])

    def test_a_scene_budget_is_spread_evenly_with_the_remainder_first(self):
        data = film((80, "L01", 3))
        durations = [unit["duration"] for unit in planner.read_units(data, data["scenes"])]
        self.assertEqual(durations, [27, 27, 26])
        self.assertEqual(sum(durations), 80)

    def test_a_beat_longer_than_the_cap_becomes_its_own_chunk(self):
        plan = planner.plan(film((60, "L01", 1), (planner.MAX_DURATION + 40, "L02", 1)))
        self.assertEqual([chunk["beat_ids"] for chunk in plan["chunks"]], [["B001"], ["B002"]])

    def test_a_scope_may_be_a_range_or_a_list_of_scenes(self):
        # Story IR writes either shape, and a list is not always contiguous.
        data = film((70, "L01", 1), (70, "L02", 1), (70, "L03", 1), (70, "L04", 1))
        data["continuity_constraints"] = [
            {"id": "CC01", "scope": {"from": "S01", "to": "S03"}},
            {"id": "CC02", "scope": ["S02", "S03"]},
            {"id": "CC03", "scope": ["S01", "S04"]},
            {"id": "CC04", "scope": ["S04"]},
        ]
        chunks = planner.plan(data)["chunks"]
        crossed = [set(chunk["entry_constraints_crossed"]) for chunk in chunks]
        # CC03 spans the whole film, so it never argues for a cut point.
        self.assertEqual(crossed, [set(), {"CC01"}, {"CC01", "CC02"}, set()])
        last = {item["id"] for item in chunks[-1]["story_slice"]["continuity_constraints"]}
        self.assertEqual(last, {"CC03", "CC04"})

    def test_a_scene_with_no_beats_is_refused(self):
        data = film((70, "L01", 1), (70, "L02", 1))
        data["beats"] = [item for item in data["beats"] if item["scene_id"] != "S02"]
        with self.assertRaises(planner.PlanError):
            planner.plan(data)

    def test_budgets_that_miss_the_total_are_refused(self):
        data = film((70, "L01", 1))
        data["duration"] += 10
        with self.assertRaises(planner.PlanError):
            planner.plan(data)

    def test_a_partial_story_is_refused(self):
        data = film((70, "L01", 1))
        data["status"] = "partial"
        with self.assertRaises(planner.PlanError):
            planner.plan(data)


class StorySliceTests(unittest.TestCase):
    def setUp(self):
        scenes = [scene("S01", 70, "L01", ["B01"]),
                  scene("S02", 70, "L02", ["B02"]),
                  scene("S03", 70, "L03", ["B03"])]
        beats = [beat("B01", "S01", entities=["C01"], lines=["D01"]),
                 beat("B02", "S02", entities=["C02", "P01"]),
                 beat("B03", "S03", entities=["C01"])]
        self.story = story(
            scenes, beats,
            characters=[{"id": "C01"}, {"id": "C02"}],
            props=[{"id": "P01"}],
            locations=[{"id": "L01"}, {"id": "L02"}, {"id": "L03"}],
            dialogue=[{"id": "D01", "beat_id": "B01", "text": "hello"}],
            transition_markers=[{"marker_id": "TM01", "at_beat_id": "B02", "type": "weather_change"}],
            continuity_constraints=[
                {"id": "CC01", "scope": {"from": "S01", "to": "S03"}},
                {"id": "CC02", "scope": {"from": "S02", "to": "S03"}},
                {"id": "CC03", "scope": {"from": "S01", "to": "S01"}},
            ],
            locked_constraints=["the coat never changes"],
            ambiguities=[
                {"id": "AMB-C01", "severity": "low", "subject_id": "C01", "question": "his age?"},
                {"id": "AMB-P01", "severity": "low", "subject_id": "P01", "question": "how worn?"},
                {"id": "AMB-L03", "severity": "low", "subject_id": "L03", "question": "how lit?"},
                {"id": "AMB-NONE", "severity": "low", "question": "about nothing in particular"},
            ],
        )

    def chunks(self):
        chunks = planner.plan(self.story)["chunks"]
        self.assertEqual([chunk["scene_ids"] for chunk in chunks], [["S01"], ["S02"], ["S03"]])
        return chunks

    def test_a_chunk_carries_only_its_own_beats_and_entities(self):
        first = self.chunks()[0]
        self.assertEqual(first["beat_ids"], ["B01"])
        self.assertEqual([item["id"] for item in first["story_slice"]["characters"]], ["C01"])
        self.assertEqual(first["story_slice"]["props"], [])
        self.assertEqual([item["id"] for item in first["story_slice"]["locations"]], ["L01"])
        self.assertEqual([line["id"] for line in first["story_slice"]["dialogue"]], ["D01"])
        self.assertEqual(first["story_slice"]["transition_markers"], [])

    def test_a_chunk_carries_the_constraints_that_reach_it(self):
        carried = [{item["id"] for item in chunk["story_slice"]["continuity_constraints"]}
                   for chunk in self.chunks()]
        self.assertEqual(carried, [{"CC01", "CC03"}, {"CC01", "CC02"}, {"CC01", "CC02"}])

    def test_locked_constraints_ride_along_in_every_chunk(self):
        for chunk in self.chunks():
            self.assertEqual(chunk["story_slice"]["locked_constraints"], ["the coat never changes"])

    def test_a_later_chunk_carries_the_previous_scene_exit_state(self):
        chunks = self.chunks()
        self.assertIsNone(chunks[0]["story_slice"]["previous_scene_exit_state"])
        for previous, following in zip(chunks, chunks[1:]):
            entry = following["story_slice"]["previous_scene_exit_state"]
            self.assertEqual(entry["scene_id"], previous["scene_ids"][-1])
            self.assertEqual(entry["exit_state"], f"state after {previous['scene_ids'][-1]}")

    def test_a_chunk_carries_the_ambiguities_about_what_it_shows(self):
        carried = [{item["id"] for item in chunk["story_slice"]["ambiguities"]}
                   for chunk in self.chunks()]
        # C01 is in the first and third chunks, P01 only in the second, L03 is
        # the third chunk's location, and an ambiguity about nothing is dropped.
        self.assertEqual(carried, [{"AMB-C01"}, {"AMB-P01"}, {"AMB-C01", "AMB-L03"}])

    def test_a_chunk_cut_inside_a_scene_carries_no_scene_exit_state(self):
        chunks = planner.plan(film((120, "L01", 2)))["chunks"]
        self.assertTrue(chunks[1]["entry_mid_scene"])
        self.assertIsNone(chunks[1]["story_slice"]["previous_scene_exit_state"])


if __name__ == "__main__":
    unittest.main()
