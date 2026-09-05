#!/usr/bin/env python3
"""Deterministic cross-record checks for frame-design output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


MAX_SHOTS_PER_SEGMENT = 3
MAX_REFERENCE_MEDIA = 4
TIME_JUMP = "time_change"  # a day later the coat is a different coat
REFERENCE_ROLE = {
    "character_reference_ids": "character_reference",
    "location_reference_ids": "location_reference",
    "style_reference_ids": "style_reference",
    "video_reference_ids": "video_reference",
    "audio_reference_ids": "audio_reference",
}


def diagnostic(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def load_object(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def missing_carried_state(carried: dict[str, Any], prompt: str) -> list[str]:
    """What of a shot's exit state the next prompt fails to restate."""
    missing = []
    wardrobe = carried.get("wardrobe_state")
    if isinstance(wardrobe, str) and wardrobe.strip() and wardrobe not in prompt:
        missing.append(wardrobe)
    missing.extend(prop for prop in carried.get("held_props", [])
                   if isinstance(prop, str) and prop and prop not in prompt)
    return missing


def index_shots(shot_ir: dict[str, Any] | None) -> tuple[dict[str, Any], list[Any], dict[str, Any]]:
    """Shots by id, in story order, and the exit state each one leaves behind."""
    shot_by_id: dict[str, Any] = {}
    shot_order: list[Any] = []
    exit_state_by_shot: dict[str, Any] = {}
    if not isinstance(shot_ir, dict):
        return shot_by_id, shot_order, exit_state_by_shot
    for item in shot_ir.get("shots") or []:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            shot_by_id[item["id"]] = item
            shot_order.append(item)
    exit_state = shot_ir.get("continuity_exit_state")
    for item in (exit_state.get("by_shot") if isinstance(exit_state, dict) else None) or []:
        if isinstance(item, dict) and isinstance(item.get("shot_id"), str):
            exit_state_by_shot[item["shot_id"]] = item
    return shot_by_id, shot_order, exit_state_by_shot


def with_previous_shot(shot_ir: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    """A chunk's shots, preceded by the last shot of the chunk before it.

    A chunk cannot see past its own first shot, so the state carried across that
    seam is invisible to it. Splicing the handover in front gives both the ask
    and the check the one shot they are missing.
    """
    if not isinstance(previous, dict):
        return shot_ir
    earlier = [shot for shot in previous.get("shots") or [] if isinstance(shot, dict)]
    if not earlier:
        return shot_ir
    handover = earlier[-1]
    carried = [entry for entry in (previous.get("continuity_exit_state") or {}).get("by_shot", [])
               if isinstance(entry, dict) and entry.get("shot_id") == handover.get("id")]
    spliced = dict(shot_ir)
    spliced["shots"] = [handover] + list(shot_ir.get("shots") or [])
    exit_state = dict(shot_ir.get("continuity_exit_state") or {})
    exit_state["by_shot"] = carried + list(exit_state.get("by_shot") or [])
    spliced["continuity_exit_state"] = exit_state
    return spliced


def carried_exit_state(shot_ids: list[Any], shot_by_id: dict[str, Any], shot_order: list[Any],
                       exit_state_by_shot: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """What a segment opening a scene must restate, and the shot it comes from.

    Defined once because it is used twice: to tell the designer what to carry,
    and to check that the prompt carried it. Two implementations of one rule
    drift apart, and the drift lands on the designer as a rule it was never given.
    """
    opening_id = shot_ids[0] if shot_ids else None
    position = next((offset for offset, item in enumerate(shot_order)
                     if item.get("id") == opening_id), None)
    if not position:  # falsy at the film's own opening, which carries nothing
        return None, None
    if shot_by_id.get(opening_id, {}).get("scene_continuity") == TIME_JUMP:
        return None, None
    source_id = shot_order[position - 1].get("id")
    return source_id, exit_state_by_shot.get(source_id)


def covered_window(shot_ir: dict[str, Any] | None) -> tuple[int, int | None]:
    """The span the segments must cover: a whole film, or one chunk of one."""
    if not isinstance(shot_ir, dict):
        return 0, None
    if isinstance(shot_ir.get("chunk_id"), str):
        start, end = shot_ir.get("start"), shot_ir.get("end")
        return start if isinstance(start, int) else 0, end if isinstance(end, int) else None
    total = shot_ir.get("duration")
    return 0, total if isinstance(total, int) else None


def validate(data: dict[str, Any], shot_ir: dict[str, Any] | None = None) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    window_start, window_end = covered_window(shot_ir)
    segments = data.get("segment_plan")
    manifest = data.get("media_manifest")
    if not isinstance(segments, list) or not isinstance(manifest, dict):
        return [diagnostic("structure", "", "segment_plan and media_manifest are required")]

    media_items = manifest.get("media", [])
    if not isinstance(media_items, list):
        return [diagnostic("structure", "media_manifest.media", "media must be an array")]

    shot_by_id, shot_order, exit_state_by_shot = index_shots(shot_ir)

    def unique_map(items: list[Any], key: str, path: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for index, item in enumerate(items):
            if not isinstance(item, dict) or not isinstance(item.get(key), str):
                errors.append(diagnostic("missing_id", f"{path}[{index}].{key}", "stable string ID is required"))
                continue
            item_id = item[key]
            if item_id in result:
                errors.append(diagnostic("duplicate_id", f"{path}[{index}].{key}", f"duplicate ID: {item_id}"))
            result[item_id] = item
        return result

    unique_map(segments, "segment_id", "segment_plan")
    media_by_id = unique_map(media_items, "id", "media_manifest.media")

    previous: dict[str, Any] | None = None
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            errors.append(diagnostic("segment_type", f"segment_plan[{index}]", "segment must be an object"))
            continue
        path = f"segment_plan[{index}]"
        segment_id = segment.get("segment_id")
        start, end, duration = segment.get("start"), segment.get("end"), segment.get("duration")
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in (start, end, duration)):
            errors.append(diagnostic("integer_timing", path, "start, end, and duration must be integers"))
        else:
            if end <= start:
                errors.append(diagnostic("nonpositive_duration", f"{path}.end", "end must be greater than start"))
            if duration != end - start:
                errors.append(diagnostic("duration_mismatch", f"{path}.duration", "duration must equal end - start"))
            if not 4 <= duration <= 15:
                errors.append(diagnostic("h3_duration", f"{path}.duration", "segment duration must be 4 through 15 seconds"))
            if index == 0 and start != window_start:
                errors.append(diagnostic("timeline_start", f"{path}.start", f"first segment must start at {window_start}"))
            if previous is not None and start != previous.get("end"):
                errors.append(diagnostic("timeline_gap", f"{path}.start", "segments must be ordered and contiguous"))

        expected_previous_id = None if previous is None else previous.get("segment_id")
        if segment.get("previous_segment_id") != expected_previous_id:
            errors.append(diagnostic("previous_segment", f"{path}.previous_segment_id", "must equal the immediately previous segment ID"))

        strategy = segment.get("entry_strategy")
        dependency = segment.get("runtime_entry_dependency")
        shot_ids = segment.get("shot_ids") if isinstance(segment.get("shot_ids"), list) else []
        bindings = segment.get("shot_bindings") if isinstance(segment.get("shot_bindings"), list) else []
        prompt = segment.get("prompt") if isinstance(segment.get("prompt"), dict) else {}
        description = prompt.get("integrated_multimodal_description")
        description = description if isinstance(description, str) else ""

        scene_id = segment.get("scene_id")
        if shot_by_id:
            for shot_id in shot_ids:
                shot = shot_by_id.get(shot_id)
                if shot is not None and shot.get("scene_id") != scene_id:
                    errors.append(diagnostic("scene_mismatch", f"{path}.scene_id", f"{shot_id} belongs to scene {shot.get('scene_id')}, not {scene_id}"))

        # A scene change resets the location, so the frame the previous segment
        # ended on shows somewhere else. That, and only that, is where a segment
        # is generated from its references alone.
        opens_scene = previous is None or previous.get("scene_id") != scene_id

        if strategy == "references_only":
            if not opens_scene:
                errors.append(diagnostic("scene_entry_strategy", f"{path}.entry_strategy", "references_only belongs to the segment that opens a scene; inside a scene, continue from the previous tail"))
            if dependency is not None:
                errors.append(diagnostic("unexpected_runtime_dependency", f"{path}.runtime_entry_dependency", "references_only has nothing to continue from"))
            # The place resets, but the people do not: a coat still buttoned and a
            # photograph still in a pocket have to survive a cold start in words.
            source_id, carried = carried_exit_state(shot_ids, shot_by_id, shot_order, exit_state_by_shot)
            absent = missing_carried_state(carried, description) if carried else []
            if absent:
                errors.append(diagnostic("exit_state_not_carried", f"{path}.prompt.integrated_multimodal_description", f"a scene opens cold, so the prompt must restate what survived the change from {source_id}: {', '.join(absent)}"))
        elif strategy == "use_previous_tail_frame":
            if opens_scene:
                errors.append(diagnostic("scene_entry_strategy", f"{path}.entry_strategy", "a segment that opens a scene cannot continue from a tail frame of somewhere else"))
            if previous is None:
                errors.append(diagnostic("first_segment_tail", path, "the first segment cannot use a previous tail frame"))
            expected_tail = previous.get("actual_tail_frame_media_id") if previous else None
            if not isinstance(dependency, dict) or dependency.get("kind") != "previous_actual_tail_frame" or dependency.get("previous_segment_id") != expected_previous_id or dependency.get("expected_media_id") != expected_tail:
                errors.append(diagnostic("runtime_tail_link", f"{path}.runtime_entry_dependency", "must bind to the immediately previous segment's reserved actual tail frame"))
            if previous is not None and not previous.get("exit_frame_required"):
                errors.append(diagnostic("tail_capture_not_required", f"segment_plan[{index - 1}].exit_frame_required", "previous segment must require actual-tail capture"))
        else:
            errors.append(diagnostic("entry_strategy", f"{path}.entry_strategy", "unsupported entry strategy"))

        actual_tail_id = segment.get("actual_tail_frame_media_id")
        if segment.get("exit_frame_required"):
            tail = media_by_id.get(actual_tail_id)
            if tail is None or tail.get("role") != "actual_tail_frame" or tail.get("derived_from_segment_id") != segment_id:
                errors.append(diagnostic("actual_tail_mapping", f"{path}.actual_tail_frame_media_id", "must map to an extracted actual_tail_frame owned by this segment"))

        references = segment.get("reference_strategy") if isinstance(segment.get("reference_strategy"), dict) else {}
        for slot, group in references.items():
            if not isinstance(group, list):
                continue
            expected_role = REFERENCE_ROLE.get(slot)
            for media_id in group:
                item = media_by_id.get(media_id)
                if item is None:
                    errors.append(diagnostic("unknown_reference", f"{path}.reference_strategy.{slot}", f"unknown media ID: {media_id}"))
                elif expected_role is not None and item.get("role") != expected_role:
                    errors.append(diagnostic("reference_role", f"{path}.reference_strategy.{slot}", f"{media_id} carries role {item.get('role')}, but this slot only takes {expected_role}"))

        if len(shot_ids) > MAX_SHOTS_PER_SEGMENT:
            errors.append(diagnostic("segment_shot_cap", f"{path}.shot_ids", f"a segment may cover at most {MAX_SHOTS_PER_SEGMENT} shots"))

        reference_total = len({
            media_id
            for group in references.values() if isinstance(group, list)
            for media_id in group if isinstance(media_id, str)
        })
        if reference_total > MAX_REFERENCE_MEDIA:
            errors.append(diagnostic("reference_budget", f"{path}.reference_strategy", f"a segment may bind at most {MAX_REFERENCE_MEDIA} reference media"))

        if shot_by_id:
            covered = [shot_by_id[shot_id] for shot_id in shot_ids if shot_id in shot_by_id]
            in_frame = {name for item in covered for name in item.get("characters_in_frame", []) if isinstance(name, str)}
            faces = {media_by_id[media_id].get("subject_id")
                     for media_id in references.get("character_reference_ids") or []
                     if media_id in media_by_id}
            for missing in sorted(in_frame - faces):
                errors.append(diagnostic("missing_character_reference", f"{path}.reference_strategy.character_reference_ids", f"{missing} is in frame in this segment but has no character reference"))
            for stray in sorted(face for face in faces - in_frame if face is not None):
                errors.append(diagnostic("unused_character_reference", f"{path}.reference_strategy.character_reference_ids", f"{stray} is in no shot of this segment"))

            if len(covered) != len(shot_ids):
                errors.append(diagnostic("unknown_shot", f"{path}.shot_ids", "every shot ID must exist in Shot IR"))
            elif isinstance(start, int) and isinstance(end, int):
                spans = [(int(item.get("start", -1)), int(item.get("end", -1))) for item in covered]
                if spans != sorted(spans):
                    errors.append(diagnostic("shot_order", f"{path}.shot_ids", "shot IDs must be ordered by time"))
                elif spans:
                    if max(spans[0][0], start) != start or min(spans[-1][1], end) != end:
                        errors.append(diagnostic("shot_coverage", f"{path}.shot_ids", "covered shots must span the whole segment interval"))
                    for first, second in zip(spans, spans[1:]):
                        if first[1] != second[0]:
                            errors.append(diagnostic("shot_coverage_gap", f"{path}.shot_ids", "covered shots must be contiguous"))
                            break

            expected = [
                {"prompt_shot_index": position + 1, "shot_id": item.get("id"), "local_start": max(int(item.get("start", 0)), start if isinstance(start, int) else 0) - (start if isinstance(start, int) else 0)}
                for position, item in enumerate(covered)
            ]
            if bindings != expected:
                errors.append(diagnostic("shot_binding_mismatch", f"{path}.shot_bindings", "bindings must index the covered shots in order with local_start = shot.start - segment.start"))

        previous = segment

    for media_id, media in media_by_id.items():
        role = media.get("role")
        if role == "actual_tail_frame":
            if media.get("source_type") != "extracted":
                errors.append(diagnostic("actual_tail_provenance", f"media_manifest.media[{media_id}]", "an actual tail frame is captured from rendered video, never generated"))
        elif media.get("status") == "runtime_pending":
            errors.append(diagnostic("runtime_status_role", f"media_manifest.media[{media_id}].status", "runtime_pending is reserved for actual_tail_frame"))

    if manifest.get("status") in ("ready_for_compile", "resolved"):
        for media_id, media in media_by_id.items():
            if media.get("role") != "actual_tail_frame" and media.get("status") != "resolved":
                errors.append(diagnostic("static_media_unresolved", f"media_manifest.media[{media_id}].status", "compile-ready manifests require every static medium to be resolved"))

    if window_end is not None and segments and segments[-1].get("end") != window_end:
        errors.append(diagnostic("timeline_coverage", "segment_plan", f"final segment end must equal {window_end}"))

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate frame-design cross-record semantics")
    parser.add_argument("frame_design")
    parser.add_argument("--shot-ir")
    args = parser.parse_args()
    try:
        data = load_object(args.frame_design)
        shot_ir = load_object(args.shot_ir) if args.shot_ir else None
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(json.dumps({"valid": False, "errors": [diagnostic("input", "", str(error))]}, ensure_ascii=False))
        return 2
    errors = validate(data, shot_ir)
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
