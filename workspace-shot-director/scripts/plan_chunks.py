#!/usr/bin/env python3
"""Deterministic chunk planning for a Story IR handed to the Shot Director.

One chunk has to fit in one model reply, and a reply carries both the shots and
one exit state each. Measured against GLM-5.3-Flash, a 240s chunk overran the
output limit partway through its 17th shot, so chunks are held near 70 seconds.

At that size most scenes are too long to be a chunk, so cuts fall on beats, not
only on scene boundaries. Cost decides which beat: a scene change is where the
world state resets anyway and costs nothing, a scene change back into the same
location costs a little, and a seam inside a scene -- landing on the action
axis, the screen direction, and an action already in progress -- costs most and
happens only when the size cap leaves no choice.

Time never chooses a cut point. Story IR beats carry no timing, so a scene's
`duration_budget` is spread evenly over its beats and the seconds follow from
that; time only balances chunk size.

Each chunk carries its own story slice: the scenes, beats, dialogue, entities,
and constraints it needs, plus the previous scene's exit state when the chunk
starts on a scene boundary.

Usage: plan_chunks.py <story-ir.json>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

TARGET_DURATION = 70
MAX_DURATION = 80
SIZE_WEIGHT = 40.0
STRADDLE_WEIGHT = 1.0
SAME_LOCATION = 8.0
MID_SCENE = 25.0
UNREACHABLE = float("inf")


class PlanError(Exception):
    """Raised when the Story IR cannot be chunked."""


def load_object(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PlanError(f"{path} must contain a JSON object")
    return value


def read_scenes(story: dict[str, Any]) -> list[dict[str, Any]]:
    scenes = story.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise PlanError("Story IR requires a non-empty scenes array")
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise PlanError(f"scenes[{index}] must be an object")
        budget = scene.get("duration_budget")
        if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
            raise PlanError(f"scenes[{index}].duration_budget must be a positive whole number of seconds")
    total = sum(scene["duration_budget"] for scene in scenes)
    if story.get("duration") != total:
        raise PlanError(
            f"duration_budget sums to {total}, but duration is {story.get('duration')}; "
            f"chunk time windows come from the budgets and must reach the total"
        )
    return scenes


def read_units(story: dict[str, Any], scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per beat, in story order, each holding its share of the scene."""
    by_scene: dict[str, list[dict[str, Any]]] = {}
    for beat in story.get("beats", []):
        if isinstance(beat, dict):
            by_scene.setdefault(beat.get("scene_id"), []).append(beat)

    units: list[dict[str, Any]] = []
    for scene in scenes:
        beats = by_scene.get(scene["id"], [])
        if not beats:
            raise PlanError(f"scene {scene['id']} has no beats; its seconds cannot be placed")
        share, extra = divmod(scene["duration_budget"], len(beats))
        if share == 0:
            raise PlanError(
                f"scene {scene['id']} budgets {scene['duration_budget']}s over {len(beats)} beats; "
                f"a beat cannot be shorter than a second"
            )
        for position, beat in enumerate(beats):
            units.append({
                "beat": beat,
                "scene": scene,
                "duration": share + (1 if position < extra else 0),
                "opens_scene": position == 0,
            })
    return units


def scope_range(scope: Any, order: dict[str, int]) -> tuple[int, int] | None:
    """Scene span a constraint covers, as 1-based scene numbers.

    Story IR writes a scope either as {"from", "to"} or as a list of scene IDs,
    and the list is not always contiguous. Either way what matters here is the
    first and last scene it reaches: state has to survive from one to the other.
    """
    if isinstance(scope, dict):
        start, end = order.get(scope.get("from")), order.get(scope.get("to"))
    elif isinstance(scope, list):
        numbers = [order[ref] for ref in scope if ref in order]
        start, end = (min(numbers), max(numbers)) if numbers else (None, None)
    else:
        return None
    return None if start is None or end is None else (start, end)


def straddling(story: dict[str, Any], order: dict[str, int], last: int, cut_after: int) -> list[str]:
    """Constraints crossing the boundary after scene number `cut_after`.

    Constraints spanning the whole film are excluded: every chunk carries them,
    so they never argue for one cut point over another.
    """
    crossing = []
    for item in story.get("continuity_constraints", []):
        if not isinstance(item, dict):
            continue
        span = scope_range(item.get("scope"), order)
        if span is None or span == (1, last):
            continue
        if span[0] <= cut_after < span[1]:
            crossing.append(item.get("id"))
    return crossing


def cut_cost(story: dict[str, Any], order: dict[str, int], last: int,
             units: list[dict[str, Any]], boundary: int) -> float:
    """Cost of opening a chunk at unit `boundary`."""
    unit, before = units[boundary], units[boundary - 1]
    if not unit["opens_scene"]:
        return MID_SCENE
    crossing = len(straddling(story, order, last, order[before["scene"]["id"]]))
    same_location = before["scene"].get("location_id") == unit["scene"].get("location_id")
    return STRADDLE_WEIGHT * crossing + (SAME_LOCATION if same_location else 0.0)


def size_cost(duration: int) -> float:
    return SIZE_WEIGHT * ((duration - TARGET_DURATION) / TARGET_DURATION) ** 2


def choose_groups(story: dict[str, Any], scenes: list[dict[str, Any]],
                  units: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Group beats into chunks by dynamic programming over beat boundaries."""
    count = len(units)
    order = {scene["id"]: index + 1 for index, scene in enumerate(scenes)}
    cuts = {boundary: cut_cost(story, order, len(scenes), units, boundary)
            for boundary in range(1, count)}

    best: list[float] = [0.0] + [UNREACHABLE] * count
    origin: list[int] = [0] * (count + 1)
    for end in range(1, count + 1):
        for start in range(end):
            if best[start] == UNREACHABLE:
                continue
            duration = sum(unit["duration"] for unit in units[start:end])
            # A single beat longer than the cap still has to be its own chunk.
            if duration > MAX_DURATION and end - start > 1:
                continue
            candidate = best[start] + size_cost(duration) + (cuts[start] if start else 0.0)
            if candidate < best[end]:
                best[end] = candidate
                origin[end] = start
    if best[count] == UNREACHABLE:
        raise PlanError("no grouping of beats covers the film; check duration_budget values")

    groups: list[tuple[int, int]] = []
    end = count
    while end:
        start = origin[end]
        groups.append((start, end))
        end = start
    groups.reverse()
    return groups


def pick(items: list[Any], wanted: set[Any], key: str = "id") -> list[Any]:
    return [item for item in items if isinstance(item, dict) and item.get(key) in wanted]


def story_slice(story: dict[str, Any], group: list[dict[str, Any]], order: dict[str, int],
                previous: dict[str, Any] | None) -> dict[str, Any]:
    beats = [unit["beat"] for unit in group]
    beat_ids = {beat.get("id") for beat in beats}
    scenes = list({unit["scene"]["id"]: unit["scene"] for unit in group}.values())
    dialogue_ids = {ref for beat in beats for ref in beat.get("dialogue_ids", [])}
    entity_ids = {ref for beat in beats for ref in beat.get("entity_ids", [])}
    location_ids = {scene.get("location_id") for scene in scenes}
    entity_ids = {ref for ref in entity_ids if ref is not None}
    location_ids = {ref for ref in location_ids if ref is not None}

    first, final = order[scenes[0]["id"]], order[scenes[-1]["id"]]
    constraints = []
    for item in story.get("continuity_constraints", []):
        if not isinstance(item, dict):
            continue
        span = scope_range(item.get("scope"), order)
        if span is None or (span[0] <= final and span[1] >= first):
            constraints.append(item)

    return {
        "scenes": scenes,
        "beats": beats,
        "dialogue": pick(story.get("dialogue", []), dialogue_ids),
        "characters": pick(story.get("characters", []), entity_ids),
        "props": pick(story.get("props", []), entity_ids),
        "locations": pick(story.get("locations", []), location_ids),
        "continuity_constraints": constraints,
        "transition_markers": pick(story.get("transition_markers", []), beat_ids, key="at_beat_id"),
        # What the story could not settle about the people, props, and places
        # this chunk shows. Without these the director invents an answer and
        # nothing downstream knows it was a guess.
        "ambiguities": [item for item in story.get("ambiguities", [])
                        if isinstance(item, dict)
                        and item.get("subject_id") in entity_ids | location_ids],
        "locked_constraints": story.get("locked_constraints", []),
        # Only meaningful when this chunk opens a scene: a scene's exit state
        # says where that scene ends, not where it happens to have been cut.
        "previous_scene_exit_state": None if previous is None else {
            "scene_id": previous.get("id"),
            "exit_state": previous.get("exit_state"),
        },
    }


def plan(story: dict[str, Any]) -> dict[str, Any]:
    if story.get("status") != "complete":
        raise PlanError("Story IR status must be complete before shots are designed")
    scenes = read_scenes(story)
    units = read_units(story, scenes)
    order = {scene["id"]: index + 1 for index, scene in enumerate(scenes)}
    groups = choose_groups(story, scenes, units)

    chunks: list[dict[str, Any]] = []
    clock = 0
    for index, (start, end) in enumerate(groups):
        group = units[start:end]
        duration = sum(unit["duration"] for unit in group)
        opens_scene = group[0]["opens_scene"]
        previous = units[start - 1]["scene"] if start and opens_scene else None
        crossing = straddling(story, order, len(scenes), order[previous["id"]]) if previous else []
        carried = story_slice(story, group, order, previous)
        chunks.append({
            "chunk_id": f"K{index + 1}",
            "previous_chunk_id": chunks[-1]["chunk_id"] if chunks else None,
            "start": clock,
            "end": clock + duration,
            "duration": duration,
            "scene_ids": [scene["id"] for scene in carried["scenes"]],
            "beat_ids": [beat.get("id") for beat in carried["beats"]],
            "dialogue_ids": [line.get("id") for line in carried["dialogue"]],
            # The size cap forced a seam inside a scene: the previous chunk's
            # last shot is the only handover, there is no scene exit state.
            "entry_mid_scene": bool(start) and not opens_scene,
            # The seam falls between two scenes sharing a location -- the
            # hardest kind of state to hand over.
            "entry_same_location": bool(previous)
            and previous.get("location_id") == group[0]["scene"].get("location_id"),
            "entry_constraints_crossed": crossing,
            "story_slice": carried,
        })
        clock += duration

    return {"schema_version": "1.0", "duration": story["duration"], "chunks": chunks}


def main() -> int:
    parser = argparse.ArgumentParser(description="Split a Story IR into Shot Director chunks")
    parser.add_argument("story_ir")
    args = parser.parse_args()
    try:
        result = plan(load_object(args.story_ir))
    except (OSError, UnicodeError, json.JSONDecodeError, PlanError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, ensure_ascii=False))
        return 2
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
