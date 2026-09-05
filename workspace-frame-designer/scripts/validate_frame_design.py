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
EXIT_STATE_TEXT_FIELDS = ("staging", "wardrobe_state", "scene_state", "lighting_state")
RESET_CONTINUITY = ("scene_change", "location_change")


def diagnostic(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def load_object(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def validate(data: dict[str, Any], shot_ir: dict[str, Any] | None = None) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    segments = data.get("segment_plan")
    frame_plan = data.get("frame_plan")
    jobs = data.get("image_jobs")
    manifest = data.get("media_manifest")
    if not isinstance(segments, list) or not isinstance(frame_plan, list) or not isinstance(jobs, list) or not isinstance(manifest, dict):
        return [diagnostic("structure", "", "segment_plan, frame_plan, image_jobs, and media_manifest are required")]

    media_items = manifest.get("media", [])
    if not isinstance(media_items, list):
        return [diagnostic("structure", "media_manifest.media", "media must be an array")]

    shot_by_id: dict[str, dict[str, Any]] = {}
    shot_order: list[dict[str, Any]] = []
    exit_state_by_shot: dict[str, dict[str, Any]] = {}
    if shot_ir is not None:
        for item in shot_ir.get("shots", []) if isinstance(shot_ir.get("shots"), list) else []:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                shot_by_id[item["id"]] = item
                shot_order.append(item)
        exit_state = shot_ir.get("continuity_exit_state")
        by_shot = exit_state.get("by_shot") if isinstance(exit_state, dict) else None
        for item in by_shot if isinstance(by_shot, list) else []:
            if isinstance(item, dict) and isinstance(item.get("shot_id"), str):
                exit_state_by_shot[item["shot_id"]] = item

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

    segment_by_id = unique_map(segments, "segment_id", "segment_plan")
    frame_by_segment = unique_map(frame_plan, "segment_id", "frame_plan")
    media_by_id = unique_map(media_items, "id", "media_manifest.media")
    job_by_id = unique_map(jobs, "job_id", "image_jobs")

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
            if index == 0 and start != 0:
                errors.append(diagnostic("timeline_start", f"{path}.start", "first segment must start at 0"))
            if previous is not None and start != previous.get("end"):
                errors.append(diagnostic("timeline_gap", f"{path}.start", "segments must be ordered and contiguous"))

        expected_previous_id = None if previous is None else previous.get("segment_id")
        if segment.get("previous_segment_id") != expected_previous_id:
            errors.append(diagnostic("previous_segment", f"{path}.previous_segment_id", "must equal the immediately previous segment ID"))

        strategy = segment.get("entry_strategy")
        dependency = segment.get("runtime_entry_dependency")
        frame = frame_by_segment.get(segment_id)
        if frame is None:
            errors.append(diagnostic("missing_frame_plan", path, "each segment needs exactly one frame_plan item"))

        if strategy == "new_first_frame":
            entry_id = segment.get("entry_frame_source")
            if not isinstance(entry_id, str):
                errors.append(diagnostic("missing_first_frame", f"{path}.entry_frame_source", "new_first_frame requires a media ID"))
            else:
                media = media_by_id.get(entry_id)
                if media is None or media.get("role") != "first_frame" or segment_id not in media.get("related_segments", []):
                    errors.append(diagnostic("first_frame_mapping", f"{path}.entry_frame_source", "must map to this segment's first_frame media"))
            if dependency is not None:
                errors.append(diagnostic("unexpected_runtime_dependency", f"{path}.runtime_entry_dependency", "new_first_frame cannot use a runtime tail dependency"))
            if frame and frame.get("first_frame_media_id") != entry_id:
                errors.append(diagnostic("frame_plan_mismatch", f"frame_plan[{segment_id}].first_frame_media_id", "must match entry_frame_source"))
        elif strategy == "use_previous_tail_frame":
            if previous is None:
                errors.append(diagnostic("first_segment_tail", path, "the first segment cannot use a previous tail frame"))
            if segment.get("entry_frame_source") is not None:
                errors.append(diagnostic("continuation_first_frame", f"{path}.entry_frame_source", "continuation entry_frame_source must be null"))
            expected_tail = previous.get("actual_tail_frame_media_id") if previous else None
            if not isinstance(dependency, dict) or dependency.get("kind") != "previous_actual_tail_frame" or dependency.get("previous_segment_id") != expected_previous_id or dependency.get("expected_media_id") != expected_tail:
                errors.append(diagnostic("runtime_tail_link", f"{path}.runtime_entry_dependency", "must bind to the immediately previous segment's reserved actual tail frame"))
            if previous is not None and not previous.get("exit_frame_required"):
                errors.append(diagnostic("tail_capture_not_required", f"segment_plan[{index - 1}].exit_frame_required", "previous segment must require actual-tail capture"))
            continuity = segment.get("continuity_decision", {})
            required_true = ("is_same_shot", "continuous_action", "continuous_camera", "same_scene", "same_framing", "same_camera_position", "same_time", "same_visual_focus")
            if not isinstance(continuity, dict) or any(continuity.get(key) is not True for key in required_true) or continuity.get("requires_recomposition") is not False or continuity.get("change_triggers"):
                errors.append(diagnostic("invalid_tail_reuse", f"{path}.continuity_decision", "previous-tail reuse requires uninterrupted shot, action, camera, scene, framing, time, focus, and composition"))
            if frame and frame.get("first_frame_media_id") is not None:
                errors.append(diagnostic("continuation_frame_plan", f"frame_plan[{segment_id}].first_frame_media_id", "continuation must not define a first-frame medium"))
        else:
            errors.append(diagnostic("entry_strategy", f"{path}.entry_strategy", "unsupported entry strategy"))

        actual_tail_id = segment.get("actual_tail_frame_media_id")
        if segment.get("exit_frame_required"):
            tail = media_by_id.get(actual_tail_id)
            if tail is None or tail.get("role") != "actual_tail_frame" or tail.get("derived_from_segment_id") != segment_id:
                errors.append(diagnostic("actual_tail_mapping", f"{path}.actual_tail_frame_media_id", "must map to an extracted actual_tail_frame owned by this segment"))
        if frame:
            for field in ("last_frame_target_media_id", "actual_tail_frame_media_id"):
                if frame.get(field) != segment.get(field):
                    errors.append(diagnostic("frame_plan_mismatch", f"frame_plan[{segment_id}].{field}", f"must match segment_plan.{field}"))

        for group in segment.get("reference_strategy", {}).values() if isinstance(segment.get("reference_strategy"), dict) else ():
            if isinstance(group, list):
                for media_id in group:
                    if media_id not in media_by_id:
                        errors.append(diagnostic("unknown_reference", f"{path}.reference_strategy", f"unknown media ID: {media_id}"))

        shot_ids = segment.get("shot_ids") if isinstance(segment.get("shot_ids"), list) else []
        bindings = segment.get("shot_bindings") if isinstance(segment.get("shot_bindings"), list) else []

        if len(shot_ids) > MAX_SHOTS_PER_SEGMENT:
            errors.append(diagnostic("segment_shot_cap", f"{path}.shot_ids", f"a segment may cover at most {MAX_SHOTS_PER_SEGMENT} shots"))

        reference_total = len({
            media_id
            for group in (segment.get("reference_strategy") or {}).values() if isinstance(group, list)
            for media_id in group if isinstance(media_id, str)
        })
        if reference_total > MAX_REFERENCE_MEDIA:
            errors.append(diagnostic("reference_budget", f"{path}.reference_strategy", f"a segment may bind at most {MAX_REFERENCE_MEDIA} reference media"))

        if shot_by_id:
            covered = [shot_by_id[shot_id] for shot_id in shot_ids if shot_id in shot_by_id]
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

    if len(frame_by_segment) != len(segment_by_id):
        errors.append(diagnostic("frame_plan_cardinality", "frame_plan", "frame_plan must contain exactly one item per segment"))

    for job_id, job in job_by_id.items():
        if job.get("role") == "actual_tail_frame":
            errors.append(diagnostic("actual_tail_image_job", f"image_jobs[{job_id}]", "actual tail frames are runtime extractions, not image-generation jobs"))
        output_id = job.get("output_media_id")
        media = media_by_id.get(output_id)
        if media is None or media.get("source_job") != job_id:
            errors.append(diagnostic("job_media_link", f"image_jobs[{job_id}].output_media_id", "job output must map back to a media record with the same source_job"))

    for media_id, media in media_by_id.items():
        role = media.get("role")
        if role == "actual_tail_frame":
            if media.get("source_type") != "extracted" or media.get("source_job") is not None:
                errors.append(diagnostic("actual_tail_provenance", f"media_manifest.media[{media_id}]", "actual tail must be extracted and have no image-generation source job"))
        elif media.get("status") == "runtime_pending":
            errors.append(diagnostic("runtime_status_role", f"media_manifest.media[{media_id}].status", "runtime_pending is reserved for actual_tail_frame"))

    if manifest.get("status") in ("ready_for_compile", "resolved"):
        for media_id, media in media_by_id.items():
            if media.get("role") != "actual_tail_frame" and media.get("status") != "resolved":
                errors.append(diagnostic("static_media_unresolved", f"media_manifest.media[{media_id}].status", "compile-ready manifests require every static medium to be resolved"))

    job_by_output = {job.get("output_media_id"): job for job in job_by_id.values() if isinstance(job.get("output_media_id"), str)}
    compile_ready = manifest.get("status") in ("ready_for_compile", "resolved")

    for job_id, job in job_by_id.items():
        inputs = job.get("input_media_ids")
        if not isinstance(inputs, list):
            continue
        for media_id in inputs:
            source = media_by_id.get(media_id)
            if source is None:
                errors.append(diagnostic("unknown_input_media", f"image_jobs[{job_id}].input_media_ids", f"unknown media ID: {media_id}"))
                continue
            if source.get("role") == "actual_tail_frame":
                if job.get("status") != "runtime_pending":
                    errors.append(diagnostic("runtime_input_status", f"image_jobs[{job_id}].status", "a job consuming an actual tail frame resolves at runtime and must be runtime_pending"))
            elif compile_ready and source.get("status") != "resolved":
                errors.append(diagnostic("input_media_unresolved", f"image_jobs[{job_id}].input_media_ids", f"compile-ready manifests require resolved input media: {media_id}"))

    if exit_state_by_shot:
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict) or segment.get("entry_strategy") != "new_first_frame":
                continue
            if index == 0:
                continue
            shot_ids = segment.get("shot_ids") if isinstance(segment.get("shot_ids"), list) else []
            if not shot_ids:
                continue
            opening = shot_by_id.get(shot_ids[0], {})
            if opening.get("scene_continuity") in RESET_CONTINUITY:
                continue
            position = next((offset for offset, item in enumerate(shot_order) if item.get("id") == shot_ids[0]), None)
            if position is None or position == 0:
                continue
            carried = exit_state_by_shot.get(shot_order[position - 1].get("id"))
            if not carried:
                continue
            entry_id = segment.get("entry_frame_source")
            job = job_by_output.get(entry_id)
            if job is None:
                continue
            prompt = job.get("prompt") if isinstance(job.get("prompt"), str) else ""
            missing = [field for field in EXIT_STATE_TEXT_FIELDS if isinstance(carried.get(field), str) and carried[field].strip() and carried[field] not in prompt]
            missing += [prop for prop in carried.get("held_props", []) if isinstance(prop, str) and prop and prop not in prompt]
            if missing:
                errors.append(diagnostic("exit_state_not_carried", f"image_jobs[{job.get('job_id')}].prompt", f"first-frame prompt must restate the previous shot's exit state: {', '.join(missing)}"))

    if shot_by_id and segments:
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                continue
            shot_ids = segment.get("shot_ids") if isinstance(segment.get("shot_ids"), list) else []
            if not shot_ids or segment.get("entry_strategy") != "new_first_frame":
                continue
            opening = shot_by_id.get(shot_ids[0])
            decision = segment.get("continuity_decision")
            if not isinstance(opening, dict) or not isinstance(decision, dict) or index == 0:
                continue
            pairs = [
                ("is_same_shot", opening.get("boundary_type") == "same_shot_continuation"),
                ("same_scene", opening.get("scene_continuity") == "same_scene"),
                ("same_framing", opening.get("framing_continuity") == "same"),
                ("same_camera_position", opening.get("camera_continuity") == "continuous"),
            ]
            for field, expected in pairs:
                if decision.get(field) is not expected:
                    errors.append(diagnostic("continuity_label_conflict", f"segment_plan[{index}].continuity_decision.{field}", f"contradicts Shot IR continuity labels on {shot_ids[0]}"))

    if shot_ir is not None and segments:
        total = shot_ir.get("duration")
        if isinstance(total, int) and segments[-1].get("end") != total:
            errors.append(diagnostic("timeline_coverage", "segment_plan", "final segment end must equal Shot IR duration"))

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
