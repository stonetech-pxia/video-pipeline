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


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
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
        for item in data.get(key, [])
        if isinstance(item, dict)
    }
    beat_ids = {item.get("id") for item in data.get("beats", []) if isinstance(item, dict)}
    all_ids = [
        item.get(id_key)
        for key, id_key in (
            ("characters", "id"),
            ("locations", "id"),
            ("props", "id"),
            ("beats", "id"),
            ("dialogue", "id"),
            ("continuity_constraints", "id"),
            ("transition_markers", "marker_id"),
        )
        for item in data.get(key, [])
        if isinstance(item, dict)
    ]
    if len(all_ids) != len(set(all_ids)):
        errors.append("IDs must be globally unique")
    for index, item in enumerate(data.get("dialogue", [])):
        if not isinstance(item, dict):
            continue
        if item.get("speaker_id") is not None and item.get("speaker_id") not in entities:
            errors.append(f"dialogue[{index}].speaker_id: unknown entity")
        if item.get("beat_id") is not None and item.get("beat_id") not in beat_ids:
            errors.append(f"dialogue[{index}].beat_id: unknown beat")
    for index, item in enumerate(data.get("transition_markers", [])):
        if isinstance(item, dict) and item.get("at_beat_id") not in beat_ids:
            errors.append(f"transition_markers[{index}].at_beat_id: unknown beat")
    if data.get("status") == "complete" and data.get("ambiguities"):
        errors.append("complete Story IR cannot contain unresolved ambiguities")
    if data.get("status") == "partial" and not data.get("ambiguities"):
        errors.append("partial Story IR requires at least one ambiguity")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate camera-neutral Story IR")
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    try:
        errors = validate(load_object(args.artifact))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
