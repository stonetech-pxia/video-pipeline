#!/usr/bin/env python3
"""Merge a story plan and its chunk artifacts into one Story IR.

Usage: merge_chunks.py <plan.json> <chunk1.json> [chunk2.json ...]

The merged artifact is written to stdout. It is not validated here; run
validate_output.py on the result.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PLAN_ONLY_SCENE_FIELDS = ("slugline", "location_id", "time_of_day", "duration_budget")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: top-level JSON value must be an object")
    return value


def merge_by_id(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Concatenate, keeping the first item seen for any repeated id."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            key = item.get("id") or item.get("marker_id")
            if key is not None and key in seen:
                continue
            if key is not None:
                seen.add(key)
            merged.append(item)
    return merged


def merge(plan: dict[str, Any], chunks: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []

    completions: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        for completion in chunk.get("scenes", []):
            scene_id = completion.get("id")
            if scene_id in completions:
                errors.append(f"scene {scene_id} completed by more than one chunk")
            completions[scene_id] = completion

    scenes = []
    for planned in plan.get("scenes", []):
        scene_id = planned.get("id")
        completion = completions.pop(scene_id, None)
        if completion is None:
            errors.append(f"scene {scene_id} was planned but no chunk completed it")
            continue
        scenes.append(
            {
                "id": scene_id,
                **{field: planned.get(field) for field in PLAN_ONLY_SCENE_FIELDS},
                "beat_ids": completion.get("beat_ids", []),
                "exit_state": completion.get("exit_state"),
            }
        )
    for orphan in completions:
        errors.append(f"chunk completed scene {orphan}, which the plan never declared")

    story = {
        "schema_version": "2.0",
        "status": plan.get("status", "complete"),
        "duration": plan.get("duration"),
        "scenes": scenes,
        "characters": plan.get("characters", []),
        "locations": plan.get("locations", []),
        "props": plan.get("props", []),
        "beats": [beat for chunk in chunks for beat in chunk.get("beats", [])],
        "dialogue": [line for chunk in chunks for line in chunk.get("dialogue", [])],
        "continuity_constraints": merge_by_id(
            plan.get("continuity_constraints", []),
            *[chunk.get("continuity_constraints", []) for chunk in chunks],
        ),
        "transition_markers": merge_by_id(
            *[chunk.get("transition_markers", []) for chunk in chunks]
        ),
        "locked_constraints": plan.get("locked_constraints", []),
        "ambiguities": merge_by_id(
            plan.get("ambiguities", []),
            *[chunk.get("ambiguities", []) for chunk in chunks],
        ),
    }

    if any(item.get("severity") == "blocking" for item in story["ambiguities"]):
        story["status"] = "partial"
    return story, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan")
    parser.add_argument("chunks", nargs="+")
    args = parser.parse_args()

    try:
        plan = load(Path(args.plan))
        chunks = [load(Path(path)) for path in args.chunks]
    except (OSError, ValueError) as exc:
        print(f"merge failed: {exc}", file=sys.stderr)
        return 1

    story, errors = merge(plan, chunks)
    for error in errors:
        print(f"merge error: {error}", file=sys.stderr)
    json.dump(story, sys.stdout, ensure_ascii=False, indent=2)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
