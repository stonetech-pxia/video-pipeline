#!/usr/bin/env python3
"""Bind Shot IR to the asset registry, and record what the director settled.

Shot IR says who is in a shot but not where it is: a shot names beats, a beat
names its scene, and a scene names its location. That chain is a lookup, not a
judgement, so it is resolved here rather than asked of a model. Each shot comes
back carrying `scene_id` and `location_id`, and the reference images its
subjects resolve to.

The registry also accumulates. Story IR gives a location a line; the director
settles the rest -- light direction, surfaces, background life -- and that text
is appended here per shot, so a later chunk can be shown what an earlier one
already established rather than inventing the place a second time. Recording
happens per chunk, under the chunk's local shot ids; run the merged Shot IR
through with --no-record, since merging renumbers every shot.

Usage: resolve_assets.py <shot-ir.json> <story-ir.json> <assets.json>
       The enriched Shot IR goes to stdout; the registry is updated in place.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


class ResolveError(Exception):
    """Raised when the artifacts cannot be bound together."""


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ResolveError(f"{path.name}: top-level JSON value must be an object")
    return value


def blank_registry() -> dict[str, Any]:
    return {"schema_version": "1.0", "characters": {}, "locations": {}}


def index_story(story: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """beat id -> scene id, and scene id -> location id."""
    scene_of = {beat.get("id"): beat.get("scene_id")
                for beat in story.get("beats", []) if isinstance(beat, dict)}
    location_of = {scene.get("id"): scene.get("location_id")
                   for scene in story.get("scenes", []) if isinstance(scene, dict)}
    return scene_of, location_of


def register(registry: dict[str, Any], group: str, subject_id: str, story_items: list[Any]) -> dict[str, Any]:
    """Return the registry entry for a subject, creating a placeholder if new."""
    entries = registry.setdefault(group, {})
    entry = entries.get(subject_id)
    if entry is None:
        source = next((item for item in story_items
                       if isinstance(item, dict) and item.get("id") == subject_id), {})
        entry = {
            "name": source.get("name") or subject_id,
            "image": None,
            "settled": [],
        }
        if source.get("description"):
            entry["description"] = source["description"]
        entries[subject_id] = entry
    return entry


def record(entry: dict[str, Any], shot_id: str, text: str) -> bool:
    """Append what this shot settled, replacing any earlier text for that shot."""
    if not text:
        return False
    settled = entry.setdefault("settled", [])
    for item in settled:
        if item.get("shot_id") == shot_id:
            if item.get("text") == text:
                return False
            item["text"] = text
            return True
    settled.append({"shot_id": shot_id, "text": text})
    return True


def resolve(shot_ir: dict[str, Any], story: dict[str, Any], registry: dict[str, Any],
            recording: bool = True) -> tuple[dict[str, Any], list[str], int]:
    scene_of, location_of = index_story(story)
    characters = story.get("characters", [])
    locations = story.get("locations", [])

    shots = shot_ir.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ResolveError("Shot IR requires a non-empty shots array")

    unresolved: list[str] = []
    recorded = 0
    resolved_shots: list[dict[str, Any]] = []
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            raise ResolveError(f"shots[{index}] must be an object")
        shot = dict(shot)
        shot_id = shot.get("id")

        scenes = {scene_of[ref] for ref in shot.get("source_beat_ids", []) if ref in scene_of}
        if len(scenes) > 1:
            raise ResolveError(
                f"{shot_id}: beats span {', '.join(sorted(str(s) for s in scenes))}; "
                f"a shot draws its beats from one scene"
            )
        scene_id = next(iter(scenes)) if scenes else None
        location_id = location_of.get(scene_id)
        shot["scene_id"] = scene_id
        shot["location_id"] = location_id

        bound: dict[str, Any] = {"characters": {}, "location": None}
        for subject_id in shot.get("characters_in_frame", []):
            entry = register(registry, "characters", subject_id, characters)
            bound["characters"][subject_id] = entry.get("image")
            if entry.get("image") is None:
                unresolved.append(f"{shot_id}: character {subject_id} has no reference image")
        if location_id is not None:
            entry = register(registry, "locations", location_id, locations)
            bound["location"] = {location_id: entry.get("image")}
            if entry.get("image") is None:
                unresolved.append(f"{shot_id}: location {location_id} has no reference image")
            if recording:
                settled = " ".join(part for part in (shot.get("environment"), shot.get("lighting")) if part)
                recorded += record(entry, shot_id, settled)

        shot["reference_assets"] = bound
        resolved_shots.append(shot)

    return {**shot_ir, "shots": resolved_shots}, unresolved, recorded


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shot_ir")
    parser.add_argument("story_ir")
    parser.add_argument("assets", help="the registry; created if it does not exist")
    parser.add_argument(
        "--no-record", action="store_true",
        help="resolve provenance without recording settled descriptions. Use on a merged Shot IR, "
             "whose shots were already recorded under their chunk-local ids.",
    )
    args = parser.parse_args()

    assets_path = Path(args.assets)
    try:
        shot_ir = load(Path(args.shot_ir))
        story = load(Path(args.story_ir))
        registry = load(assets_path) if assets_path.exists() else blank_registry()
        resolved, unresolved, recorded = resolve(shot_ir, story, registry, not args.no_record)
    except (OSError, UnicodeError, json.JSONDecodeError, ResolveError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, ensure_ascii=False))
        return 2

    assets_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for line in unresolved:
        print(f"unresolved: {line}", file=sys.stderr)
    print(f"recorded {recorded} settled description(s) into {assets_path.name}", file=sys.stderr)
    json.dump(resolved, sys.stdout, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
