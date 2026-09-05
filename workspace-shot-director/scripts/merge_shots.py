#!/usr/bin/env python3
"""Merge a film head and its Shot IR chunks into one Shot IR.

Chunks number their shots locally, so a chunk can be retried on its own without
invalidating the ones after it. Global numbering is assigned here, and every
reference to a shot id is rewritten with it.

Film-level fields come from the head and overwrite nothing from the chunks:
a chunk that invented its own visual style cannot drift into the film.

The merged artifact is written to stdout. It is not validated here; run the
Shot IR schema over the result.

Usage: merge_shots.py <chunk-plan.json> <film-head.json> <chunk1.json> [chunk2.json ...]
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
from typing import Any

HEAD_FIELDS = ("aspect_ratio", "visual_style", "overall_soundscape", "music")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: top-level JSON value must be an object")
    return value


def renumber(shots: list[dict[str, Any]], first: int) -> tuple[list[dict[str, Any]], dict[str, str]]:
    renamed: dict[str, str] = {}
    output = []
    for offset, shot in enumerate(shots):
        shot = copy.deepcopy(shot)
        old, new = shot.get("id"), f"S{first + offset:03d}"
        renamed[old] = new
        shot["id"] = new
        output.append(shot)
    return output, renamed


def merge(plan: dict[str, Any], head: dict[str, Any], chunks: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    for field in HEAD_FIELDS:
        if head.get(field) is None:
            errors.append(f"the film head is missing {field}")

    supplied = {chunk.get("chunk_id"): chunk for chunk in chunks}
    if len(supplied) != len(chunks):
        errors.append("the same chunk_id was supplied more than once")

    shots: list[dict[str, Any]] = []
    exit_states: list[dict[str, Any]] = []
    warnings: list[str] = []
    chunk_errors: list[str] = []
    status = "complete"
    clock = 0

    for planned in plan.get("chunks", []):
        chunk_id = planned.get("chunk_id")
        chunk = supplied.pop(chunk_id, None)
        if chunk is None:
            errors.append(f"chunk {chunk_id} was planned but not supplied")
            continue
        if chunk.get("status") != "complete":
            status = "partial"
        if chunk.get("start") != clock:
            errors.append(
                f"chunk {chunk_id} starts at {chunk.get('start')}, but the film reached {clock}"
            )
        clock = chunk.get("end") if isinstance(chunk.get("end"), int) else clock

        numbered, renamed = renumber(
            [shot for shot in chunk.get("shots", []) if isinstance(shot, dict)], len(shots) + 1
        )
        shots.extend(numbered)
        for entry in (chunk.get("continuity_exit_state") or {}).get("by_shot", []):
            entry = copy.deepcopy(entry)
            entry["shot_id"] = renamed.get(entry.get("shot_id"), entry.get("shot_id"))
            exit_states.append(entry)
        warnings.extend(chunk.get("warnings", []))
        chunk_errors.extend(chunk.get("errors", []))

    for orphan in supplied:
        errors.append(f"chunk {orphan} was supplied, but the plan never declared it")

    duration = plan.get("duration")
    if shots and shots[0].get("start") != 0:
        errors.append(f"the first shot starts at {shots[0].get('start')}, expected 0")
    if shots and shots[-1].get("end") != duration:
        errors.append(f"the last shot ends at {shots[-1].get('end')}, expected {duration}")

    for shot in shots:
        if not isinstance(shot.get("characters_in_frame"), list):
            errors.append(f"{shot['id']}: characters_in_frame is missing; every shot must name who is in it")

    covered = {entry.get("shot_id") for entry in exit_states}
    for missing in [shot["id"] for shot in shots if shot["id"] not in covered]:
        errors.append(f"continuity_exit_state.by_shot: no exit state for {missing}")

    shot_ir = {
        "schema_version": "1.1",
        "status": status,
        "duration": duration,
        **{field: head.get(field) for field in HEAD_FIELDS},
        "shots": shots,
        "continuity_exit_state": {"by_shot": exit_states},
        "warnings": warnings,
        "errors": chunk_errors,
    }
    return shot_ir, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge Shot IR chunks into one Shot IR")
    parser.add_argument("plan")
    parser.add_argument("head")
    parser.add_argument("chunks", nargs="+")
    args = parser.parse_args()

    try:
        plan = load(Path(args.plan))
        head = load(Path(args.head))
        chunks = [load(Path(path)) for path in args.chunks]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"merge failed: {exc}", file=sys.stderr)
        return 1

    shot_ir, errors = merge(plan, head, chunks)
    for error in errors:
        print(f"merge error: {error}", file=sys.stderr)
    json.dump(shot_ir, sys.stdout, ensure_ascii=False, indent=2)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
