#!/usr/bin/env python3
"""Deterministic segment packing for Shot IR.

Chooses generation-segment boundaries by dynamic programming. Boundaries are
preferred at real cuts — strongest cuts first — because a seam hidden inside an
edit costs nothing, while a seam inside a continuous take is visible. Packing
several short shots into one segment is therefore the normal case; splitting a
shot across segments only happens when the shot exceeds the model limit.
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
UNREACHABLE = float("inf")

BASE_COST = {
    "scene_change": 0,
    "location_change": 0,
    "time_change": 1,
}
SAME_SCENE_DISCONTINUOUS = 5
SAME_SCENE_CONTINUOUS = 25
MID_SHOT = 50
LOAD_WEIGHT = 3


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
        for field in ("id", "start", "end"):
            if shot.get(field) is None:
                raise PlanError(f"shots[{index}].{field} is required")
        for field in ("start", "end"):
            value = shot[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
                raise PlanError(f"shots[{index}].{field} must be a whole number of seconds")
        if shot.get("boundary_risk") is None or shot.get("composition_control") is None:
            raise PlanError(f"shots[{index}] requires boundary_risk and composition_control")
    return shots


def boundary_cost(shot: dict[str, Any]) -> float:
    """Cost of opening a segment at this shot's first frame."""
    labels = shot
    scene = labels.get("scene_continuity")
    if scene in BASE_COST:
        base = BASE_COST[scene]
    elif labels.get("action_continuity") == "discontinuous":
        base = SAME_SCENE_DISCONTINUOUS
    else:
        base = SAME_SCENE_CONTINUOUS
    load = (shot.get("boundary_risk") or {}).get("state_transfer_load", 0)
    if isinstance(load, bool) or not isinstance(load, int):
        load = 0
    return base + load * LOAD_WEIGHT


def candidate_points(shots: list[dict[str, Any]], total: int) -> list[int]:
    points = {0, total}
    for shot in shots:
        start, end = int(shot["start"]), int(shot["end"])
        points.add(start)
        if end - start > MAX_DURATION:
            points.update(range(start + 1, end))
    return sorted(point for point in points if 0 <= point <= total)


def shots_in(shots: list[dict[str, Any]], start: int, end: int) -> list[dict[str, Any]]:
    return [shot for shot in shots if int(shot["start"]) < end and int(shot["end"]) > start]


def segment_allowed(covered: list[dict[str, Any]]) -> bool:
    if not covered or len(covered) > MAX_SHOTS_PER_SEGMENT:
        return False
    # A shot needing exact composition control must open its segment, so that the
    # generated first frame anchors it rather than the model inventing framing.
    return not any(shot.get("composition_control") == "critical" for shot in covered[1:])


def cut_cost(shots: list[dict[str, Any]], point: int) -> float:
    if point == 0:
        return 0.0
    for shot in shots:
        if int(shot["start"]) == point:
            return boundary_cost(shot)
    return float(MID_SHOT)


def plan(shot_ir: dict[str, Any]) -> list[dict[str, Any]]:
    shots = read_shots(shot_ir)
    total = shot_ir.get("duration")
    if isinstance(total, bool) or not isinstance(total, int) or total < MIN_DURATION:
        raise PlanError("Shot IR duration must be an integer of at least 4 seconds")

    points = candidate_points(shots, total)
    best: dict[int, float] = {0: 0.0}
    origin: dict[int, int] = {}
    for end in points:
        if end == 0:
            continue
        for start in points:
            if start >= end or not (MIN_DURATION <= end - start <= MAX_DURATION):
                continue
            if best.get(start, UNREACHABLE) == UNREACHABLE:
                continue
            if not segment_allowed(shots_in(shots, start, end)):
                continue
            candidate = best[start] + cut_cost(shots, start)
            if candidate < best.get(end, UNREACHABLE):
                best[end] = candidate
                origin[end] = start
    if best.get(total, UNREACHABLE) == UNREACHABLE:
        raise PlanError(
            f"no segmentation covers {total}s under the 4-15s limit and "
            f"{MAX_SHOTS_PER_SEGMENT}-shot cap; check for shots that cannot be packed"
        )

    boundaries = [total]
    while boundaries[-1] != 0:
        boundaries.append(origin[boundaries[-1]])
    boundaries.reverse()

    cut_points = {int(shot["start"]) for shot in shots}
    segments: list[dict[str, Any]] = []
    for index in range(len(boundaries) - 1):
        start, end = boundaries[index], boundaries[index + 1]
        covered = shots_in(shots, start, end)
        opens_on_cut = start in cut_points
        segments.append({
            "segment_id": f"SEG{index + 1:03d}",
            "previous_segment_id": segments[-1]["segment_id"] if segments else None,
            "start": start,
            "end": end,
            "duration": end - start,
            "shot_ids": [shot["id"] for shot in covered],
            "shot_bindings": [
                {
                    "prompt_shot_index": position + 1,
                    "shot_id": shot["id"],
                    "local_start": max(int(shot["start"]), start) - start,
                }
                for position, shot in enumerate(covered)
            ],
            "entry_strategy": "new_first_frame" if opens_on_cut else "use_previous_tail_frame",
        })
    return segments


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack Shot IR into generation segments")
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
