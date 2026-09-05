#!/usr/bin/env python3
"""Validate one Shot IR chunk against the chunk plan that produced its input.

Catches a bad chunk while it is still cheap to redo, before the merge. What
needs the whole film -- global shot numbering, seams between chunks -- stays in
merge_shots.py.

Usage: validate_chunk.py <chunk-plan.json> <chunk_id> <chunk.json | ->
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from jsonschema import Draft202012Validator

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
MAX_SHOT_DURATION = 15


def load(path: Path | None) -> dict[str, Any]:
    raw = sys.stdin.read() if path is None else path.read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("top-level JSON value must be an object")
    return value


EXTERNAL = "shot-ir.schema.json#/"


def inline(node: Any, base: dict[str, Any]) -> Any:
    """Splice references to the Shot IR schema into the chunk schema.

    Resolving them at load time keeps one definition of a shot while staying
    off the resolver API, which changed shape across jsonschema versions and
    differs between this checkout and the openclaw runtime.
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(EXTERNAL):
            target: Any = base
            for part in ref[len(EXTERNAL):].split("/"):
                target = target[part]
            return inline(target, base)
        return {key: inline(value, base) for key, value in node.items()}
    if isinstance(node, list):
        return [inline(item, base) for item in node]
    return node


def schema_errors(chunk: dict[str, Any]) -> list[str]:
    base = json.loads((SCHEMAS / "shot-ir.schema.json").read_text(encoding="utf-8"))
    schema = json.loads((SCHEMAS / "shot-ir-chunk.schema.json").read_text(encoding="utf-8"))
    schema["$defs"] = base["$defs"]
    validator = Draft202012Validator(inline(schema, base))
    return [
        f"{'.'.join(str(part) for part in item.absolute_path)}: {item.message}"
        for item in validator.iter_errors(chunk)
    ]


def check_timeline(chunk: dict[str, Any], planned: dict[str, Any]) -> list[str]:
    errors = []
    if chunk.get("start") != planned["start"] or chunk.get("end") != planned["end"]:
        errors.append(
            f"the chunk claims {chunk.get('start')}-{chunk.get('end')}, "
            f"but the plan fixed its window at {planned['start']}-{planned['end']}"
        )
    shots = [shot for shot in chunk.get("shots", []) if isinstance(shot, dict)]
    if not shots:
        return errors
    if shots[0].get("start") != planned["start"]:
        errors.append(f"shots[0].start is {shots[0].get('start')}, expected {planned['start']}")
    if shots[-1].get("end") != planned["end"]:
        errors.append(f"shots[-1].end is {shots[-1].get('end')}, expected {planned['end']}")
    for index, shot in enumerate(shots):
        start, end = shot.get("start"), shot.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
            errors.append(f"shots[{index}]: start must come before end")
            continue
        if index and shots[index - 1].get("end") != start:
            errors.append(
                f"shots[{index}].start is {start}, but the previous shot ends at "
                f"{shots[index - 1].get('end')}; shots must be contiguous"
            )
    return errors


def check_coverage(chunk: dict[str, Any], planned: dict[str, Any]) -> list[str]:
    errors = []
    shots = [shot for shot in chunk.get("shots", []) if isinstance(shot, dict)]

    shot_ids = [shot.get("id") for shot in shots]
    if len(shot_ids) != len(set(shot_ids)):
        errors.append("shots: ids must be unique within the chunk")

    expected_beats = list(planned["beat_ids"])
    used_beats = {ref for shot in shots for ref in shot.get("source_beat_ids", [])}
    for stray in sorted(used_beats - set(expected_beats)):
        errors.append(f"source_beat_ids: beat {stray} is not in this chunk")
    for missing in [beat for beat in expected_beats if beat not in used_beats]:
        errors.append(f"source_beat_ids: beat {missing} is covered by no shot")

    expected_lines = list(planned["dialogue_ids"])
    used_lines = {ref for shot in shots for ref in shot.get("dialogue_ids", [])}
    for stray in sorted(used_lines - set(expected_lines)):
        errors.append(f"dialogue_ids: line {stray} is not in this chunk")
    for missing in [line for line in expected_lines if line not in used_lines]:
        errors.append(f"dialogue_ids: line {missing} is spoken in no shot")

    covered = [entry.get("shot_id") for entry in
               (chunk.get("continuity_exit_state") or {}).get("by_shot", [])]
    for missing in [shot_id for shot_id in shot_ids if shot_id not in covered]:
        errors.append(f"continuity_exit_state.by_shot: no exit state for {missing}")
    for stray in [shot_id for shot_id in covered if shot_id not in shot_ids]:
        errors.append(f"continuity_exit_state.by_shot: {stray} is not a shot in this chunk")
    return errors


def check_dialogue_text(chunk: dict[str, Any], planned: dict[str, Any]) -> list[str]:
    """Supplied dialogue must survive verbatim; the director may not rewrite it."""
    lines = {line.get("id"): line.get("text", "")
             for line in planned["story_slice"].get("dialogue", []) if isinstance(line, dict)}
    errors = []
    for index, shot in enumerate(chunk.get("shots", [])):
        if not isinstance(shot, dict):
            continue
        spoken = shot.get("dialogue") or ""
        for ref in shot.get("dialogue_ids", []):
            text = lines.get(ref)
            if text and text not in spoken:
                errors.append(f"shots[{index}].dialogue: the text of {ref} was changed or dropped")
    return errors


def check_boundaries(chunk: dict[str, Any], planned: dict[str, Any]) -> list[str]:
    errors = []
    shots = [shot for shot in chunk.get("shots", []) if isinstance(shot, dict)]
    if not shots:
        return errors

    first = shots[0]
    if first.get("boundary_type") != "shot_change":
        errors.append("shots[0].boundary_type must be shot_change; a chunk always opens on a cut")
    if planned["previous_chunk_id"] is None:
        load = (first.get("boundary_risk") or {}).get("state_transfer_load")
        if load != 0:
            errors.append(f"shots[0].boundary_risk.state_transfer_load is {load}; the film's first shot scores 0")
    elif first.get("scene_continuity") == "same_scene" and not planned.get("entry_mid_scene"):
        errors.append(
            "shots[0].scene_continuity is same_scene, but this chunk starts on a scene boundary"
        )

    for index, shot in enumerate(shots):
        hints = shot.get("split_hints") or []
        span = (shot.get("end") or 0) - (shot.get("start") or 0)
        if hints and span <= MAX_SHOT_DURATION:
            errors.append(f"shots[{index}].split_hints: only a shot longer than {MAX_SHOT_DURATION}s may be split")
        if not hints:
            if span > MAX_SHOT_DURATION:
                errors.append(
                    f"shots[{index}] runs {span}s: past {MAX_SHOT_DURATION}s a shot cannot be generated "
                    f"in one piece, so it needs split_hints at its action-phase boundaries"
                )
            continue
        if hints[0].get("start") != shot.get("start") or hints[-1].get("end") != shot.get("end"):
            errors.append(f"shots[{index}].split_hints: the hints must cover the shot exactly")
        for position, hint in enumerate(hints[1:], start=1):
            if hints[position - 1].get("end") != hint.get("start"):
                errors.append(f"shots[{index}].split_hints[{position}]: hints must be contiguous")
        for position, hint in enumerate(hints):
            piece = (hint.get("end") or 0) - (hint.get("start") or 0)
            if piece > MAX_SHOT_DURATION:
                errors.append(
                    f"shots[{index}].split_hints[{position}] runs {piece}s: a split hint names a piece "
                    f"that can be generated whole, so it cannot itself exceed {MAX_SHOT_DURATION}s"
                )
    return errors


def check_characters(chunk: dict[str, Any], planned: dict[str, Any]) -> list[str]:
    """Who is in frame is the director's call, but only within who the story puts there.

    A scene's cast is every character its beats name; a shot may show fewer of
    them, never more, and never one the story keeps out of that scene.
    """
    carried = planned["story_slice"]
    known = {item.get("id") for item in carried.get("characters", []) if isinstance(item, dict)}
    scene_of: dict[str, str] = {}
    cast: dict[str, set[str]] = {}
    for beat in carried.get("beats", []):
        if not isinstance(beat, dict):
            continue
        scene_id = beat.get("scene_id")
        scene_of[beat.get("id")] = scene_id
        cast.setdefault(scene_id, set()).update(set(beat.get("entity_ids", [])) & known)

    errors = []
    for index, shot in enumerate(chunk.get("shots", [])):
        if not isinstance(shot, dict):
            continue
        scenes = {scene_of[ref] for ref in shot.get("source_beat_ids", []) if ref in scene_of}
        if len(scenes) > 1:
            errors.append(
                f"shots[{index}].source_beat_ids: a shot draws its beats from one scene, "
                f"but these span {', '.join(sorted(str(item) for item in scenes))}"
            )
            continue
        present = cast.get(next(iter(scenes)), set()) if scenes else set()
        for stray in sorted(set(shot.get("characters_in_frame", [])) - present):
            errors.append(
                f"shots[{index}].characters_in_frame: {stray} is not in the scene this shot comes from"
            )
    return errors


def validate(plan: dict[str, Any], chunk_id: str, chunk: dict[str, Any]) -> list[str]:
    planned = next((item for item in plan.get("chunks", []) if item.get("chunk_id") == chunk_id), None)
    if planned is None:
        return [f"the plan declares no chunk {chunk_id}"]
    if chunk.get("chunk_id") != chunk_id:
        return [f"the artifact says chunk_id {chunk.get('chunk_id')}, expected {chunk_id}"]

    errors = schema_errors(chunk)
    if errors:
        return errors
    if chunk.get("status") == "partial" and not chunk.get("errors"):
        errors.append("a partial chunk must carry at least one error")
    errors.extend(check_timeline(chunk, planned))
    errors.extend(check_coverage(chunk, planned))
    errors.extend(check_dialogue_text(chunk, planned))
    errors.extend(check_characters(chunk, planned))
    errors.extend(check_boundaries(chunk, planned))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan")
    parser.add_argument("chunk_id")
    parser.add_argument("artifact", help="path to the chunk JSON, or - to read stdin")
    args = parser.parse_args()
    try:
        errors = validate(
            load(Path(args.plan)),
            args.chunk_id,
            load(None if args.artifact == "-" else Path(args.artifact)),
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
