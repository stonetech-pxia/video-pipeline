#!/usr/bin/env python3
"""Merge frame-design chunks into one frame-design artifact.

Chunks number their segments locally and keep their own clock, the way the
Shot IR chunks they were designed from do, so a chunk can be retried on its own
without invalidating the ones after it. Global numbering and absolute time are
both assigned here: each chunk is laid after the one before it, and every
reference to a segment id is rewritten.

Media ids are local too, and the same subject is named by every chunk that shows
it. One record survives per id, carrying the union of the segments that use it:
a character has one reference image across the film, not one per chunk.

The merged artifact is written to stdout. It is not validated here; run
validate_frame_design.py over the result.

Usage: merge_frames.py <chunk1.json> [chunk2.json ...]
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import sys
from typing import Any


def in_order(chunk: dict[str, Any]) -> tuple[int, str]:
    """Chunk ids run K1, K2, ... K10, and every chunk now starts at 0.

    Sorting on the start time no longer says which comes first, and sorting the
    ids as text puts K10 before K2, so the trailing number decides.
    """
    chunk_id = chunk.get("chunk_id") if isinstance(chunk.get("chunk_id"), str) else ""
    match = re.search(r"(\d+)$", chunk_id)
    return (int(match.group(1)) if match else 0, chunk_id)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: top-level JSON value must be an object")
    return value


def merge(chunks: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    ordered = sorted(chunks, key=in_order)

    segments: list[dict[str, Any]] = []
    renamed: dict[str, str] = {}
    media: dict[str, dict[str, Any]] = {}
    warnings: list[Any] = []
    chunk_errors: list[Any] = []
    status = "complete"
    clock = 0

    for chunk in ordered:
        chunk_id = chunk.get("chunk_id")
        if chunk.get("status") != "complete":
            status = "partial"
        if chunk.get("start") != 0:
            errors.append(f"chunk {chunk_id} starts at {chunk.get('start')}; a chunk keeps its own clock")

        for item in chunk.get("segment_plan", []):
            if not isinstance(item, dict):
                continue
            item = copy.deepcopy(item)
            old = item.get("segment_id")
            new = f"SEG{len(segments) + 1:03d}"
            if old in renamed:
                errors.append(f"segment id {old} appears in more than one chunk")
            renamed[old] = new
            item["segment_id"] = new
            for field in ("start", "end"):
                value = item.get(field)
                if isinstance(value, int) and not isinstance(value, bool):
                    item[field] = value + clock
            segments.append(item)
        clock = chunk.get("end") + clock if isinstance(chunk.get("end"), int) else clock

        for item in chunk.get("media_manifest", {}).get("media", []):
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            item = copy.deepcopy(item)
            existing = media.get(item["id"])
            if existing is None:
                media[item["id"]] = item
                continue
            if existing.get("role") != item.get("role"):
                errors.append(
                    f"media {item['id']} is a {existing.get('role')} in one chunk and a "
                    f"{item.get('role')} in another"
                )
            for segment_id in item.get("related_segments", []):
                if segment_id not in existing.setdefault("related_segments", []):
                    existing["related_segments"].append(segment_id)

        warnings.extend(chunk.get("warnings", []))
        chunk_errors.extend(chunk.get("errors", []))

    # Every id a chunk wrote was local to it, so rewrite the lot in one pass.
    for item in segments:
        item["previous_segment_id"] = renamed.get(item.get("previous_segment_id"), item.get("previous_segment_id"))
        dependency = item.get("runtime_entry_dependency")
        if isinstance(dependency, dict):
            dependency["previous_segment_id"] = renamed.get(
                dependency.get("previous_segment_id"), dependency.get("previous_segment_id"))
    for item in media.values():
        item["related_segments"] = [renamed.get(ref, ref) for ref in item.get("related_segments", [])]
        if "derived_from_segment_id" in item:
            item["derived_from_segment_id"] = renamed.get(
                item["derived_from_segment_id"], item["derived_from_segment_id"])

    # The first segment of a chunk had no segment before it inside that chunk.
    for position, item in enumerate(segments):
        expected = segments[position - 1]["segment_id"] if position else None
        if item.get("previous_segment_id") != expected:
            item["previous_segment_id"] = expected

    if segments and segments[0].get("start") != 0:
        errors.append(f"the first segment starts at {segments[0].get('start')}, expected 0")

    artifact = {
        "schema_version": "1.3",
        "status": status,
        "segment_plan": segments,
        "media_manifest": {
            "status": "draft" if any(item.get("status") == "pending" for item in media.values()) else "ready_for_compile",
            "media": list(media.values()),
        },
        "warnings": warnings,
        "errors": chunk_errors,
    }
    return artifact, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge frame-design chunks into one artifact")
    parser.add_argument("chunks", nargs="+")
    args = parser.parse_args()

    try:
        chunks = [load(Path(path)) for path in args.chunks]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"merge failed: {exc}", file=sys.stderr)
        return 1

    artifact, errors = merge(chunks)
    for problem in errors:
        print(f"merge error: {problem}", file=sys.stderr)
    json.dump(artifact, sys.stdout, ensure_ascii=False, indent=2)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
