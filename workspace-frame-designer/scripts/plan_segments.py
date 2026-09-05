#!/usr/bin/env python3
"""Deterministic segment packing for a resolved Shot IR.

There are no first frames. A segment is generated from its prompt and the
reference images for the characters and the location it shows, and everything
after the opening of a scene continues from the frame the previous generation
actually ended on.

That inverts where a boundary belongs. A boundary at a cut hands the next
generation a tail frame of the shot that just ended -- the wrong shot to start
from. A boundary a few seconds *inside* a shot hands forward a frame already in
that shot, so the next generation continues what is on screen. Segments
therefore run past the cut into the next shot and break in open air.

A segment never crosses a scene boundary: a scene change resets the location,
and the reference images bound to a segment are the ones for the place it
shows. The first segment of each scene opens on its references alone.

Input is Shot IR after `resolve_assets.py`, which is where `scene_id` comes from.

Usage: plan_segments.py <resolved-shot-ir.json>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

MIN_DURATION = 4
MAX_DURATION = 15
MAX_SHOTS_PER_SEGMENT = 3
AT_CUT = 30.0
SEGMENT_COST = 1.0
UNREACHABLE = float("inf")


class PlanError(Exception):
    """Raised when the Shot IR cannot be packed."""


def load_object(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PlanError(f"{path} must contain a JSON object")
    return value


def read_shots(shot_ir: dict[str, Any]) -> list[dict[str, Any]]:
    shots = shot_ir.get("shots")
    if not isinstance(shots, list) or not shots:
        raise PlanError("Shot IR requires a non-empty shots array")
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            raise PlanError(f"shots[{index}] must be an object")
        for field in ("id", "start", "end", "scene_id"):
            if shot.get(field) is None:
                raise PlanError(
                    f"shots[{index}].{field} is required; run resolve_assets.py first"
                    if field == "scene_id" else f"shots[{index}].{field} is required"
                )
        for field in ("start", "end"):
            value = shot[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
                raise PlanError(f"shots[{index}].{field} must be a whole number of seconds")
    return shots


def scene_runs(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Consecutive shots sharing a scene, in story order."""
    runs: list[dict[str, Any]] = []
    for shot in shots:
        if runs and runs[-1]["scene_id"] == shot["scene_id"]:
            runs[-1]["shots"].append(shot)
            runs[-1]["end"] = int(shot["end"])
        else:
            runs.append({
                "scene_id": shot["scene_id"],
                "start": int(shot["start"]),
                "end": int(shot["end"]),
                "shots": [shot],
            })
    return runs


def shots_in(shots: list[dict[str, Any]], start: int, end: int) -> list[dict[str, Any]]:
    return [shot for shot in shots if int(shot["start"]) < end and int(shot["end"]) > start]


def segment_allowed(covered: list[dict[str, Any]]) -> bool:
    return bool(covered) and len(covered) <= MAX_SHOTS_PER_SEGMENT


def pack_scene(run: dict[str, Any]) -> list[tuple[int, int]]:
    """Choose the boundaries inside one scene."""
    start, end, shots = run["start"], run["end"], run["shots"]
    span = end - start
    if span < MIN_DURATION:
        raise PlanError(
            f"scene {run['scene_id']} runs {span}s, below the {MIN_DURATION}s minimum for one "
            f"generation; it cannot be filmed as its own segment"
        )
    cuts = {int(shot["start"]) for shot in shots} - {start}

    best: dict[int, float] = {start: 0.0}
    origin: dict[int, int] = {}
    for stop in range(start + 1, end + 1):
        for begin in range(max(start, stop - MAX_DURATION), stop - MIN_DURATION + 1):
            if best.get(begin, UNREACHABLE) == UNREACHABLE:
                continue
            if not segment_allowed(shots_in(shots, begin, stop)):
                continue
            candidate = best[begin] + SEGMENT_COST + (AT_CUT if begin in cuts else 0.0)
            # Ties keep the earliest boundary, which keeps the segment that opens
            # the scene short. That one is generated cold, from references and
            # prompt alone; the rest continue from a real frame.
            if candidate < best.get(stop, UNREACHABLE):
                best[stop] = candidate
                origin[stop] = begin
    if best.get(end, UNREACHABLE) == UNREACHABLE:
        raise PlanError(
            f"scene {run['scene_id']} ({span}s) cannot be split into {MIN_DURATION}-{MAX_DURATION}s "
            f"segments of at most {MAX_SHOTS_PER_SEGMENT} shots"
        )

    boundaries = [end]
    while boundaries[-1] != start:
        boundaries.append(origin[boundaries[-1]])
    boundaries.reverse()
    return list(zip(boundaries, boundaries[1:]))


def plan(shot_ir: dict[str, Any]) -> list[dict[str, Any]]:
    shots = read_shots(shot_ir)
    total = shot_ir.get("duration")
    if isinstance(total, bool) or not isinstance(total, int) or total < MIN_DURATION:
        raise PlanError(f"Shot IR duration must be an integer of at least {MIN_DURATION} seconds")
    if int(shots[-1]["end"]) != total:
        raise PlanError(f"shots end at {shots[-1]['end']}, but duration is {total}")

    segments: list[dict[str, Any]] = []
    for run in scene_runs(shots):
        for position, (start, end) in enumerate(pack_scene(run)):
            covered = shots_in(run["shots"], start, end)
            segments.append({
                "segment_id": f"SEG{len(segments) + 1:03d}",
                "previous_segment_id": segments[-1]["segment_id"] if segments else None,
                "scene_id": run["scene_id"],
                "start": start,
                "end": end,
                "duration": end - start,
                "shot_ids": [shot["id"] for shot in covered],
                "shot_bindings": [
                    {
                        "prompt_shot_index": index + 1,
                        "shot_id": shot["id"],
                        "local_start": max(int(shot["start"]), start) - start,
                    }
                    for index, shot in enumerate(covered)
                ],
                # The opening of a scene has nothing to continue from: the place
                # changed, so the previous tail frame shows somewhere else.
                "entry_strategy": "references_only" if position == 0 else "use_previous_tail_frame",
            })
    return segments


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack a resolved Shot IR into generation segments")
    parser.add_argument("shot_ir")
    args = parser.parse_args()
    try:
        segments = plan(load_object(args.shot_ir))
    except (OSError, UnicodeError, json.JSONDecodeError, PlanError) as error:
        print(json.dumps({"status": "blocked", "segment_plan": [], "error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "complete", "segment_plan": segments}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
