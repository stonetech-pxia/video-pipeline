#!/usr/bin/env python3
"""Validate one pass of a chunked breakdown: a story plan or a chunk.

Usage: validate_pass.py plan|chunk <artifact.json | ->

Catches a bad pass while it is still cheap to redo, before the merge. Cross-pass
checks that need the whole film — global ID uniqueness, references into other
chunks — stay in validate_output.py, which runs on the merged artifact.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from jsonschema import Draft202012Validator

SCHEMAS = Path(__file__).resolve().parents[3] / "schemas"
FORBIDDEN_FIELDS = {
    "camera",
    "camera_motion",
    "camera_position",
    "framing",
    "angle",
    "lighting",
    "blocking",
    "actor_blocking",
    "first_frame",
    "last_frame",
    "h3_mode",
    "generation_mode",
}


def load(path: Path | None) -> dict[str, Any]:
    raw = sys.stdin.read() if path is None else path.read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("top-level JSON value must be an object")
    return value


def walk_forbidden(value: Any, path: str = "") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if key in FORBIDDEN_FIELDS:
                errors.append(f"{child_path}: Story IR must not contain camera, anchor, lighting, blocking, or generation-mode decisions")
            errors.extend(walk_forbidden(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(walk_forbidden(child, f"{path}[{index}]"))
    return errors


def dicts(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [item for item in data.get(key, []) if isinstance(item, dict)]


# A scene boundary already states the change of scene, location, and time of
# day, so a marker restating it carries nothing. Only what the scene spine
# cannot express survives at a boundary: weather, which scenes do not record,
# and a continuity break such as a flashback.
BOUNDARY_ALLOWED = {"weather_change", "continuity_break"}


def check_markers(scene_first_beats: dict, markers: list) -> list[str]:
    errors = []
    for index, marker in enumerate(markers):
        if not isinstance(marker, dict):
            continue
        beat_id = marker.get("at_beat_id")
        scene_id = scene_first_beats.get(beat_id)
        if scene_id is None:
            continue
        kind = marker.get("type")
        if kind not in BOUNDARY_ALLOWED:
            errors.append(
                f"transition_markers[{index}]: {kind} at {beat_id} restates the "
                f"start of scene {scene_id}; mark only what the scene spine cannot express"
            )
    return errors


def check_plan(plan: dict[str, Any]) -> list[str]:
    errors = []
    scene_ids = [scene.get("id") for scene in dicts(plan, "scenes")]
    location_ids = {item.get("id") for item in dicts(plan, "locations")}
    for index, scene in enumerate(dicts(plan, "scenes")):
        if scene.get("location_id") not in location_ids:
            errors.append(f"scenes[{index}].location_id: unknown location")

    grouped: list[str] = []
    for index, chunk in enumerate(dicts(plan, "chunks")):
        for scene_id in chunk.get("scene_ids", []):
            if scene_id not in scene_ids:
                errors.append(f"chunks[{index}].scene_ids: unknown scene {scene_id}")
            grouped.append(scene_id)
    if len(grouped) != len(set(grouped)):
        errors.append("chunks: a scene is grouped into more than one chunk")
    missing = [scene_id for scene_id in scene_ids if scene_id not in set(grouped)]
    if missing:
        errors.append(f"chunks: no chunk covers {', '.join(str(m) for m in missing)}")
    if grouped != [s for s in scene_ids if s in set(grouped)]:
        errors.append("chunks: scenes must be grouped in story order")

    declared = {
        item.get("id")
        for item in dicts(plan, "ambiguities")
        if item.get("field") == "wardrobe"
    }
    for index, character in enumerate(dicts(plan, "characters")):
        if character.get("wardrobe") is None:
            marker = "AMB-WARDROBE-" + str(character.get("id"))
            if marker not in declared:
                errors.append(f"characters[{index}]: unstated wardrobe requires ambiguity {marker}")

    all_ids = [
        item.get("id")
        for key in ("scenes", "characters", "locations", "props", "continuity_constraints")
        for item in dicts(plan, key)
    ]
    if len(all_ids) != len(set(all_ids)):
        errors.append("IDs must be globally unique")

    budgets = [scene.get("duration_budget") for scene in dicts(plan, "scenes")]
    if plan.get("duration") is not None and all(b is not None for b in budgets):
        if sum(budgets) != plan["duration"]:
            errors.append(f"scenes: duration_budget sums to {sum(budgets)}, expected {plan['duration']}")
    return errors


def check_chunk(chunk: dict[str, Any], location_ids: set[str]) -> list[str]:
    errors = []
    owned = {scene.get("id") for scene in dicts(chunk, "scenes")}
    beat_ids = {beat.get("id") for beat in dicts(chunk, "beats")}
    dialogue_ids = {line.get("id") for line in dicts(chunk, "dialogue")}

    claimed: dict[str, str] = {}
    for index, scene in enumerate(dicts(chunk, "scenes")):
        for beat_id in scene.get("beat_ids", []):
            if beat_id not in beat_ids:
                errors.append(f"scenes[{index}].beat_ids: beat {beat_id} is not in this chunk")
            elif beat_id in claimed:
                errors.append(f"scenes[{index}].beat_ids: beat {beat_id} already claimed by {claimed[beat_id]}")
            else:
                claimed[beat_id] = scene.get("id")

    for index, beat in enumerate(dicts(chunk, "beats")):
        if beat.get("scene_id") not in owned:
            errors.append(f"beats[{index}].scene_id: scene is not owned by this chunk")
        if beat.get("id") not in claimed:
            errors.append(f"beats[{index}]: beat {beat.get('id')} belongs to no scene")
        for ref in beat.get("dialogue_ids", []):
            if ref not in dialogue_ids:
                errors.append(f"beats[{index}].dialogue_ids: unknown dialogue {ref}")
        for ref in beat.get("entity_ids", []):
            if ref in location_ids:
                errors.append(
                    f"beats[{index}].entity_ids: {ref} is a location; a beat's place "
                    f"comes from its scene, not from entity_ids"
                )
    for index, line in enumerate(dicts(chunk, "dialogue")):
        if line.get("beat_id") is not None and line.get("beat_id") not in beat_ids:
            errors.append(f"dialogue[{index}].beat_id: beat is not in this chunk")
    for index, marker in enumerate(dicts(chunk, "transition_markers")):
        if marker.get("at_beat_id") not in beat_ids:
            errors.append(f"transition_markers[{index}].at_beat_id: beat is not in this chunk")
    errors.extend(
        check_markers(
            {
                scene["beat_ids"][0]: scene.get("id")
                for scene in dicts(chunk, "scenes")
                if scene.get("beat_ids")
            },
            dicts(chunk, "transition_markers"),
        )
    )
    return errors


def validate(kind: str, data: dict[str, Any], plan: dict[str, Any] | None = None) -> list[str]:
    schema_file = "story-plan.schema.json" if kind == "plan" else "story-ir-chunk.schema.json"
    schema = json.loads((SCHEMAS / schema_file).read_text(encoding="utf-8"))
    errors = [
        f"{'.'.join(str(part) for part in item.absolute_path)}: {item.message}"
        for item in Draft202012Validator(schema).iter_errors(data)
    ]
    errors.extend(walk_forbidden(data))
    if kind == "plan":
        errors.extend(check_plan(data))
    else:
        location_ids = {item.get("id") for item in dicts(plan or {}, "locations")}
        errors.extend(check_chunk(data, location_ids))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["plan", "chunk"])
    parser.add_argument("artifact", help="path to the JSON, or - to read stdin")
    parser.add_argument(
        "--plan",
        help="the story plan, so a chunk can be checked against the entity registry",
    )
    args = parser.parse_args()
    try:
        plan = load(Path(args.plan)) if args.plan else None
        errors = validate(args.kind, load(None if args.artifact == "-" else Path(args.artifact)), plan)
    except (OSError, ValueError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
