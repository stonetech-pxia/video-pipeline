#!/usr/bin/env python3
"""Validate camera-neutral Story IR against the workspace contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from jsonschema import Draft202012Validator


SCHEMA = Path(__file__).resolve().parents[3] / "schemas/story-ir.schema.json"
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


def load_object(path: Path | None) -> dict[str, Any]:
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


def is_blocking(item: Any) -> bool:
    """Would this ambiguity force a story-changing assumption downstream?

    A bare string carries no assessment, so it counts as blocking. An object is
    blocking only when it says `severity: "blocking"`, letting the analyst record
    non-blocking observations alongside a `complete` result. The key `blocking`
    is unavailable here: it is reserved for actor blocking and rejected as a
    camera-layer decision.
    """
    if isinstance(item, dict):
        return item.get("severity") == "blocking"
    return True


def dicts(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [item for item in data.get(key, []) if isinstance(item, dict)]


def check_scenes(data: dict[str, Any], beat_ids: set[str], location_ids: set[str]) -> list[str]:
    """Scenes own beats exactly once, and every beat agrees with its owner."""
    errors: list[str] = []
    claimed: dict[str, str] = {}
    for index, scene in enumerate(dicts(data, "scenes")):
        if scene.get("location_id") not in location_ids:
            errors.append(f"scenes[{index}].location_id: unknown location")
        for beat_id in scene.get("beat_ids", []):
            if beat_id not in beat_ids:
                errors.append(f"scenes[{index}].beat_ids: unknown beat {beat_id}")
            elif beat_id in claimed:
                errors.append(f"scenes[{index}].beat_ids: beat {beat_id} already claimed by {claimed[beat_id]}")
            else:
                claimed[beat_id] = scene.get("id")

    scene_ids = {scene.get("id") for scene in dicts(data, "scenes")}
    for index, beat in enumerate(dicts(data, "beats")):
        beat_id = beat.get("id")
        if beat.get("scene_id") not in scene_ids:
            errors.append(f"beats[{index}].scene_id: unknown scene")
        elif claimed.get(beat_id) != beat.get("scene_id"):
            errors.append(f"beats[{index}]: scene_id disagrees with the owning scene's beat_ids")
        if beat_id not in claimed:
            errors.append(f"beats[{index}]: beat {beat_id} belongs to no scene")
    return errors


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


def check_wardrobe(data: dict[str, Any]) -> list[str]:
    """Unstated wardrobe must be recorded, never silently dropped."""
    declared = {
        item.get("id")
        for item in dicts(data, "ambiguities")
        if item.get("field") == "wardrobe"
    }
    errors = []
    for index, character in enumerate(dicts(data, "characters")):
        if character.get("wardrobe") is None:
            marker = "AMB-WARDROBE-" + str(character.get("id"))
            if marker not in declared:
                errors.append(f"characters[{index}]: unstated wardrobe requires ambiguity {marker}")
    return errors


def check_scope(data: dict[str, Any], known: set[str]) -> list[str]:
    errors = []
    for index, item in enumerate(dicts(data, "continuity_constraints")):
        scope = item.get("scope")
        refs = list(scope.values()) if isinstance(scope, dict) else scope
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if ref not in known:
                errors.append(f"continuity_constraints[{index}].scope: unknown id {ref}")
    return errors


def validate(data: dict[str, Any]) -> list[str]:
    schema = load_object(SCHEMA)
    errors = [
        f"{'.'.join(str(part) for part in item.absolute_path)}: {item.message}"
        for item in Draft202012Validator(schema).iter_errors(data)
    ]
    errors.extend(walk_forbidden(data))

    entities = {
        item.get("id")
        for key in ("characters", "locations", "props")
        for item in dicts(data, key)
    }
    location_ids = {item.get("id") for item in dicts(data, "locations")}
    beat_ids = {item.get("id") for item in dicts(data, "beats")}
    scene_ids = {item.get("id") for item in dicts(data, "scenes")}
    dialogue_ids = {item.get("id") for item in dicts(data, "dialogue")}
    all_ids = [
        item.get(id_key)
        for key, id_key in (
            ("scenes", "id"),
            ("characters", "id"),
            ("locations", "id"),
            ("props", "id"),
            ("beats", "id"),
            ("dialogue", "id"),
            ("continuity_constraints", "id"),
            ("transition_markers", "marker_id"),
        )
        for item in dicts(data, key)
    ]
    if len(all_ids) != len(set(all_ids)):
        errors.append("IDs must be globally unique")

    errors.extend(check_scenes(data, beat_ids, location_ids))
    errors.extend(check_wardrobe(data))
    errors.extend(
        check_markers(
            {
                scene["beat_ids"][0]: scene.get("id")
                for scene in dicts(data, "scenes")
                if scene.get("beat_ids")
            },
            data.get("transition_markers", []),
        )
    )
    errors.extend(check_scope(data, beat_ids | scene_ids))

    for index, beat in enumerate(dicts(data, "beats")):
        for ref in beat.get("entity_ids", []):
            if ref not in entities:
                errors.append(f"beats[{index}].entity_ids: unknown entity {ref}")
            elif ref in location_ids:
                errors.append(
                    f"beats[{index}].entity_ids: {ref} is a location; a beat's place "
                    f"comes from its scene, not from entity_ids"
                )
        for ref in beat.get("dialogue_ids", []):
            if ref not in dialogue_ids:
                errors.append(f"beats[{index}].dialogue_ids: unknown dialogue {ref}")
    for index, item in enumerate(dicts(data, "dialogue")):
        if item.get("speaker_id") is not None and item.get("speaker_id") not in entities:
            errors.append(f"dialogue[{index}].speaker_id: unknown entity")
        if item.get("beat_id") is not None and item.get("beat_id") not in beat_ids:
            errors.append(f"dialogue[{index}].beat_id: unknown beat")
    for index, item in enumerate(dicts(data, "transition_markers")):
        if item.get("at_beat_id") not in beat_ids:
            errors.append(f"transition_markers[{index}].at_beat_id: unknown beat")

    if data.get("status") == "complete" and any(
        is_blocking(item) for item in data.get("ambiguities", [])
    ):
        errors.append("complete Story IR cannot contain blocking ambiguities")
    if data.get("status") == "partial" and not data.get("ambiguities"):
        errors.append("partial Story IR requires at least one ambiguity")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", help="path to the Story IR JSON, or - to read stdin")
    args = parser.parse_args()
    try:
        errors = validate(load_object(None if args.artifact == "-" else Path(args.artifact)))
    except (OSError, ValueError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
