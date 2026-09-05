#!/usr/bin/env python3
"""Deterministic stage gates for the H3 Unified video pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable

from jsonschema import Draft202012Validator


OPENCLAW_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = {
    "story": OPENCLAW_ROOT / "workspace-story-analyst/schemas/story-ir.schema.json",
    "shot": OPENCLAW_ROOT / "workspace-shot-director/schemas/shot-ir.schema.json",
    "frame": OPENCLAW_ROOT / "workspace-frame-designer/schemas/frame-design-output.schema.json",
    "draft_compile": OPENCLAW_ROOT / "workspace-h3-compiler/schemas/h3-draft-prompts.schema.json",
    "compile": OPENCLAW_ROOT / "workspace-h3-compiler/schemas/h3-segment-package.schema.json",
    "validation": OPENCLAW_ROOT / "workspace-h3-validator/schemas/h3-validation-report.schema.json",
    "result": OPENCLAW_ROOT / "workspace-video-pipeline/schemas/pipeline-result.schema.json",
}

FIRST_FRAME_DIRECTIVE = "以输入首帧作为视频的准确起始画面，保持首帧中的镜头角度、构图、人物位置、环境布局和光照关系。"
CONTINUATION_DIRECTIVE = "从当前首帧自然连续，保持人物身份、服装、场景、光线、机位、构图、空间关系和运动方向不变。"
NO_RESET_DIRECTIVE = "不要重置动作、不要重复前一动作、不要突然换机位或重新构图、不要切镜。"
SECTIONS = ("integrated_multimodal_description:", "overall_soundscape:", "non_diegetic_music:")
MAX_SHOT_DURATION = 15
LEGACY_MARKERS = (
    "For the target video, at 0.00 seconds into the target video",
    "How the reference pictures align with the target video",
    "subject_definitions:",
    "retention_analysis:",
    "detailed_description:",
)
TIMESTAMP_PATTERN = re.compile(r"\bAt\s+(\d{2}):(\d{2})\.(\d{3})\b")
REFERENCE_PATTERN = re.compile(r"<(Picture|Video|Audio)\s+(\d+)>")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("top-level JSON value must be an object")
    return value


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def error(
    error_class: str,
    code: str,
    path: str,
    message: str,
    owner: str,
    *,
    retryable: bool = True,
    segment_id: str | None = None,
) -> dict[str, Any]:
    return {
        "error_class": error_class,
        "code": code,
        "path": path,
        "message": message,
        "owner": owner,
        "retryable": retryable,
        "segment_id": segment_id,
    }


def schema_errors(stage: str, value: dict[str, Any]) -> list[dict[str, Any]]:
    schema = load_json(SCHEMAS[stage])
    owner = {
        "story": "story-analyst",
        "shot": "shot-director",
        "frame": "frame-designer",
        "draft_compile": "h3-compiler",
        "compile": "h3-compiler",
        "validation": "h3-validator",
        "result": "video-pipeline",
    }[stage]
    result: list[dict[str, Any]] = []
    for item in sorted(Draft202012Validator(schema).iter_errors(value), key=lambda entry: list(entry.absolute_path)):
        path = ".".join(str(part) for part in item.absolute_path)
        result.append(error("FORMAT", "schema_violation", path, item.message, owner))
    return result


def unique_map(items: Any, key: str, base: str, owner: str, errors: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(items, list):
        return result
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get(key), str):
            errors.append(error("FORMAT", "missing_id", f"{base}[{index}].{key}", "stable string ID is required", owner))
            continue
        item_id = item[key]
        if item_id in result:
            errors.append(error("FORMAT", "duplicate_id", f"{base}[{index}].{key}", f"duplicate ID: {item_id}", owner))
        result[item_id] = item
    return result


def validate_story(value: dict[str, Any]) -> list[dict[str, Any]]:
    errors = schema_errors("story", value)
    if value.get("status") != "complete":
        errors.append(error("STORY", "story_not_complete", "status", "Story IR must be complete", "story-analyst"))
    if "generation_mode" in value:
        errors.append(error("FORMAT", "legacy_generation_mode", "generation_mode", "Story IR must not contain a legacy generation mode", "story-analyst"))
    entities: dict[str, dict[str, Any]] = {}
    for name in ("characters", "locations", "props"):
        entities.update(unique_map(value.get(name), "id", name, "story-analyst", errors))
    scenes = unique_map(value.get("scenes"), "id", "scenes", "story-analyst", errors)
    beats = unique_map(value.get("beats"), "id", "beats", "story-analyst", errors)
    dialogue = unique_map(value.get("dialogue"), "id", "dialogue", "story-analyst", errors)
    claimed: set[str] = set()
    for index, item in enumerate(value.get("scenes", [])):
        if not isinstance(item, dict):
            continue
        if item.get("location_id") not in entities:
            errors.append(error("STORY", "unknown_scene_location", f"scenes[{index}].location_id", "scene location ID does not resolve", "story-analyst"))
        for beat_id in item.get("beat_ids", []):
            if beat_id not in beats:
                errors.append(error("STORY", "unknown_scene_beat", f"scenes[{index}].beat_ids", f"beat ID does not resolve: {beat_id}", "story-analyst"))
            elif beat_id in claimed:
                errors.append(error("STORY", "beat_claimed_twice", f"scenes[{index}].beat_ids", f"beat belongs to more than one scene: {beat_id}", "story-analyst"))
            else:
                claimed.add(beat_id)
    for index, item in enumerate(value.get("beats", [])):
        if not isinstance(item, dict):
            continue
        if item.get("scene_id") not in scenes:
            errors.append(error("STORY", "unknown_beat_scene", f"beats[{index}].scene_id", "scene ID does not resolve", "story-analyst"))
        if item.get("id") not in claimed:
            errors.append(error("STORY", "beat_without_scene", f"beats[{index}]", "beat belongs to no scene", "story-analyst"))
    for index, item in enumerate(value.get("dialogue", [])):
        if not isinstance(item, dict):
            continue
        if item.get("speaker_id") is not None and item.get("speaker_id") not in entities:
            errors.append(error("STORY", "unknown_speaker", f"dialogue[{index}].speaker_id", "speaker ID does not resolve", "story-analyst"))
        if item.get("beat_id") is not None and item.get("beat_id") not in beats:
            errors.append(error("STORY", "unknown_dialogue_beat", f"dialogue[{index}].beat_id", "beat ID does not resolve", "story-analyst"))
    for index, item in enumerate(value.get("transition_markers", [])):
        if isinstance(item, dict) and item.get("at_beat_id") not in beats:
            errors.append(error("STORY", "unknown_transition_beat", f"transition_markers[{index}].at_beat_id", "transition beat ID does not resolve", "story-analyst"))
    del dialogue
    return errors


def validate_shot(value: dict[str, Any], story: dict[str, Any] | None) -> list[dict[str, Any]]:
    errors = schema_errors("shot", value)
    if value.get("status") != "complete":
        errors.append(error("SHOT_DESIGN", "shot_not_complete", "status", "Shot IR must be complete", "shot-director"))
    if "generation_mode" in value:
        errors.append(error("FORMAT", "legacy_generation_mode", "generation_mode", "Shot IR must not contain a legacy generation mode", "shot-director"))
    shots = value.get("shots") if isinstance(value.get("shots"), list) else []
    previous_end: int | float | None = None
    beat_ids = {item.get("id") for item in (story or {}).get("beats", []) if isinstance(item, dict)}
    dialogue_by_id = {item.get("id"): item for item in (story or {}).get("dialogue", []) if isinstance(item, dict)}
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            continue
        path = f"shots[{index}]"
        start, end = shot.get("start"), shot.get("end")
        if not isinstance(start, (int, float)) or isinstance(start, bool) or not isinstance(end, (int, float)) or isinstance(end, bool) or end <= start:
            errors.append(error("TIMELINE", "invalid_shot_interval", path, "shot end must be greater than start", "shot-director"))
        elif index == 0 and start != 0:
            errors.append(error("TIMELINE", "shot_timeline_start", f"{path}.start", "first shot must start at 0", "shot-director"))
        elif previous_end is not None and start != previous_end:
            errors.append(error("TIMELINE", "shot_timeline_gap", f"{path}.start", "shots must be contiguous", "shot-director"))
        if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end - start > MAX_SHOT_DURATION:
            errors.append(error("SHOT_DESIGN", "shot_too_long", path, f"a shot is one generatable piece and cannot exceed {MAX_SHOT_DURATION}s", "shot-director"))
        previous_end = end if isinstance(end, (int, float)) else previous_end
        for beat_id in shot.get("source_beat_ids", []):
            if story is not None and beat_id not in beat_ids:
                errors.append(error("SHOT_DESIGN", "unknown_source_beat", f"{path}.source_beat_ids", f"unknown beat ID: {beat_id}", "shot-director"))
        for dialogue_id in shot.get("dialogue_ids", []):
            if story is not None and dialogue_id not in dialogue_by_id:
                errors.append(error("STORY", "unknown_dialogue", f"{path}.dialogue_ids", f"unknown dialogue ID: {dialogue_id}", "shot-director"))
    if shots and previous_end != value.get("duration"):
        errors.append(error("TIMELINE", "shot_timeline_coverage", "shots", "final shot must end at total duration", "shot-director"))
    return errors


def validate_frame(value: dict[str, Any], shot: dict[str, Any] | None) -> list[dict[str, Any]]:
    errors = schema_errors("frame", value)
    module_path = OPENCLAW_ROOT / "workspace-frame-designer/scripts/validate_frame_design.py"
    namespace: dict[str, Any] = {"__name__": "frame_validator_import"}
    exec(compile(module_path.read_text(encoding="utf-8"), str(module_path), "exec"), namespace)
    for item in namespace["validate"](value, shot):
        errors.append(error("FRAME_DESIGN", item["code"], item["path"], item["message"], "frame-designer"))
    return errors


def validate_media(value: dict[str, Any], shot: dict[str, Any] | None) -> list[dict[str, Any]]:
    errors = validate_frame(value, shot)
    manifest = value.get("media_manifest") if isinstance(value.get("media_manifest"), dict) else {}
    if manifest.get("status") not in ("ready_for_compile", "resolved"):
        errors.append(error("MEDIA", "manifest_not_compile_ready", "media_manifest.status", "media manifest must be ready_for_compile or resolved", "media-resolution"))
    media_items = manifest.get("media") if isinstance(manifest.get("media"), list) else []
    for index, media in enumerate(media_items):
        if not isinstance(media, dict) or media.get("status") != "resolved":
            continue
        path = media.get("path")
        runtime_handle = media.get("runtime_handle")
        if isinstance(runtime_handle, str) and runtime_handle.strip():
            continue
        if not isinstance(path, str) or not path.strip():
            errors.append(error("MEDIA", "resolved_asset_location", f"media_manifest.media[{index}]", "resolved media requires a non-empty path or runtime handle", "media-resolution"))
            continue
        if not Path(path).is_file() or not os.access(path, os.R_OK):
            errors.append(error("MEDIA", "asset_not_readable", f"media_manifest.media[{index}].path", f"resolved media file is missing or unreadable: {path}", "media-resolution"))
    return errors


def _reference_labels(labels: Iterable[str]) -> list[str]:
    return [f"<{label}>" for label in labels]


def validate_unified_package(package: dict[str, Any], segment: dict[str, Any], media_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    segment_id = package.get("segment_id") if isinstance(package.get("segment_id"), str) else None
    errors: list[dict[str, Any]] = []
    path = f"packages[{segment_id or '?'}]"
    if "h3_mode" in package:
        errors.append(error("H3_SCHEMA", "legacy_h3_mode", f"{path}.h3_mode", "Unified packages must not declare a legacy H3 mode", "h3-compiler", segment_id=segment_id))
    if package.get("prompt_schema") != "unified_multimodal":
        errors.append(error("H3_SCHEMA", "prompt_schema", f"{path}.prompt_schema", "prompt schema must be unified_multimodal", "h3-compiler", segment_id=segment_id))
    if package.get("execution_node") != "MiniMax H3 Unified to Video":
        errors.append(error("H3_SCHEMA", "execution_node", f"{path}.execution_node", "wrong execution node", "h3-compiler", segment_id=segment_id))
    for field in ("shot_id", "start", "end"):
        if package.get(field) != segment.get(field):
            errors.append(error("FORMAT", "segment_mapping", f"{path}.{field}", f"must equal Segment Plan {field}", "h3-compiler", segment_id=segment_id))
    if package.get("local_duration") != segment.get("end", 0) - segment.get("start", 0):
        errors.append(error("TIMELINE", "local_duration", f"{path}.local_duration", "must equal segment end - start", "h3-compiler", segment_id=segment_id))

    mapping = package.get("media_mapping") if isinstance(package.get("media_mapping"), dict) else {}
    controls = package.get("unified_controls") if isinstance(package.get("unified_controls"), dict) else {}
    expected_entry = {
        "none": "none",
        "resolved_media": "resolved_first_frame",
        "previous_segment_actual_tail": "previous_segment_actual_tail",
    }.get(mapping.get("entry_frame_source_type"))
    if controls.get("entry_source") != expected_entry:
        errors.append(error("H3_SCHEMA", "entry_control_mismatch", f"{path}.unified_controls.entry_source", "Unified entry control does not match media mapping", "h3-compiler", segment_id=segment_id))
    if controls.get("last_frame_target") != mapping.get("last_frame_target"):
        errors.append(error("H3_SCHEMA", "last_control_mismatch", f"{path}.unified_controls.last_frame_target", "last-frame control does not match media mapping", "h3-compiler", segment_id=segment_id))
    if controls.get("reference_media") != mapping.get("reference_media"):
        errors.append(error("H3_SCHEMA", "reference_control_mismatch", f"{path}.unified_controls.reference_media", "reference controls do not match media mapping order", "h3-compiler", segment_id=segment_id))

    strategy = segment.get("entry_strategy")
    if strategy == "new_first_frame" and (mapping.get("entry_frame_source_type") != "resolved_media" or mapping.get("entry_frame") != segment.get("entry_frame_source")):
        errors.append(error("FRAME_DESIGN", "first_frame_binding", f"{path}.media_mapping", "new first frame is not mapped exactly", "h3-compiler", segment_id=segment_id))
    if strategy == "use_previous_tail_frame":
        dependency = segment.get("runtime_entry_dependency") or {}
        binding = mapping.get("runtime_entry_binding") or {}
        if mapping.get("entry_frame") is not None or mapping.get("entry_frame_source_type") != "previous_segment_actual_tail":
            errors.append(error("FRAME_DESIGN", "runtime_entry_mapping", f"{path}.media_mapping", "continuation entry must remain runtime-bound", "h3-compiler", segment_id=segment_id))
        if binding.get("previous_segment_id") != dependency.get("previous_segment_id") or binding.get("actual_tail_frame_media_id") != dependency.get("expected_media_id"):
            errors.append(error("FRAME_DESIGN", "runtime_tail_binding", f"{path}.media_mapping.runtime_entry_binding", "runtime tail binding does not match Segment Plan", "h3-compiler", segment_id=segment_id))

    for media_id in mapping.get("reference_media", []):
        media = media_by_id.get(media_id)
        if media is None or media.get("status") != "resolved":
            errors.append(error("MEDIA", "reference_unresolved", f"{path}.media_mapping.reference_media", f"unresolved reference: {media_id}", "media-resolution", segment_id=segment_id))

    bindings = mapping.get("reference_bindings", [])
    binding_ids = [item.get("media_id") for item in bindings if isinstance(item, dict)]
    if binding_ids != mapping.get("reference_media", []):
        errors.append(error("H3_SCHEMA", "reference_binding_order", f"{path}.media_mapping.reference_bindings", "bindings must match reference_media in order", "h3-compiler", segment_id=segment_id))
    labels = [item.get("label") for item in bindings if isinstance(item, dict)]
    for kind in ("Picture", "Video", "Audio"):
        numbers = [int(label.split()[1]) for label in labels if isinstance(label, str) and label.startswith(kind + " ")]
        if numbers != list(range(1, len(numbers) + 1)):
            errors.append(error("H3_SCHEMA", "reference_label_sequence", f"{path}.media_mapping.reference_bindings", f"{kind} labels must be sequential from 1", "h3-compiler", segment_id=segment_id))

    prompt = package.get("prompt") if isinstance(package.get("prompt"), str) else ""
    if any(marker in prompt for marker in LEGACY_MARKERS):
        errors.append(error("H3_SCHEMA", "legacy_prompt_syntax", f"{path}.prompt", "Unified prompt contains a Legacy alignment or Ref2VA section", "h3-compiler", segment_id=segment_id))
    positions = [prompt.find(section) for section in SECTIONS]
    if any(position < 0 for position in positions) or positions != sorted(positions) or any(prompt.count(section) != 1 for section in SECTIONS):
        errors.append(error("H3_SCHEMA", "unified_sections", f"{path}.prompt", "Unified prompt requires exactly three ordered sections", "h3-compiler", segment_id=segment_id))
    if not prompt.startswith(SECTIONS[0]):
        errors.append(error("H3_SCHEMA", "unified_prompt_start", f"{path}.prompt", "Unified prompt must start with integrated_multimodal_description", "h3-compiler", segment_id=segment_id))
    if strategy == "new_first_frame" and FIRST_FRAME_DIRECTIVE not in prompt:
        errors.append(error("H3_SCHEMA", "first_frame_directive", f"{path}.prompt", "missing exact first-frame directive", "h3-compiler", segment_id=segment_id))
    if strategy == "use_previous_tail_frame" and (CONTINUATION_DIRECTIVE not in prompt or NO_RESET_DIRECTIVE not in prompt):
        errors.append(error("H3_SCHEMA", "continuation_directive", f"{path}.prompt", "missing continuation directives", "h3-compiler", segment_id=segment_id))
    expected_labels = set(_reference_labels(label for label in labels if isinstance(label, str)))
    used_labels = {f"<{kind} {number}>" for kind, number in REFERENCE_PATTERN.findall(prompt)}
    if used_labels != expected_labels:
        errors.append(error("H3_SCHEMA", "reference_label_usage", f"{path}.prompt", "prompt reference labels must exactly match bindings", "h3-compiler", segment_id=segment_id))
    duration = package.get("local_duration")
    if isinstance(duration, int):
        for minute, second, millisecond in TIMESTAMP_PATTERN.findall(prompt):
            timestamp = int(minute) * 60 + int(second) + int(millisecond) / 1000
            if timestamp >= duration:
                errors.append(error("TIMELINE", "timestamp_range", f"{path}.prompt", "prompt timestamp must be inside local duration", "h3-compiler", segment_id=segment_id))
    return errors


def validate_compile(value: dict[str, Any], frame: dict[str, Any] | None, shot: dict[str, Any] | None) -> list[dict[str, Any]]:
    errors = schema_errors("compile", value)
    if value.get("status") != "complete":
        errors.append(error("H3_SCHEMA", "compile_not_complete", "status", "compiler output must be complete", "h3-compiler"))
    if frame is None:
        errors.append(error("FORMAT", "missing_frame_context", "", "compile validation requires Frame Design", "video-pipeline", retryable=False))
        return errors
    segments = frame.get("segment_plan") if isinstance(frame.get("segment_plan"), list) else []
    packages = value.get("packages") if isinstance(value.get("packages"), list) else []
    if [item.get("segment_id") for item in packages if isinstance(item, dict)] != [item.get("segment_id") for item in segments if isinstance(item, dict)]:
        errors.append(error("FORMAT", "package_cardinality", "packages", "packages must match Segment Plan order exactly", "h3-compiler"))
    manifest = frame.get("media_manifest") if isinstance(frame.get("media_manifest"), dict) else {}
    media_by_id = {item.get("id"): item for item in manifest.get("media", []) if isinstance(item, dict) and isinstance(item.get("id"), str)}
    for package, segment in zip(packages, segments):
        if isinstance(package, dict) and isinstance(segment, dict):
            errors.extend(validate_unified_package(package, segment, media_by_id))
    if shot is not None and segments and segments[-1].get("end") != shot.get("duration"):
        errors.append(error("TIMELINE", "compile_timeline_coverage", "packages", "compiled timeline must cover Shot IR duration", "h3-compiler"))
    return errors


def validate_draft_compile(value: dict[str, Any], frame: dict[str, Any] | None, shot: dict[str, Any] | None) -> list[dict[str, Any]]:
    errors = schema_errors("draft_compile", value)
    if value.get("status") != "draft":
        errors.append(error("H3_SCHEMA", "draft_compile_not_complete", "status", "draft compiler output must have status=draft", "h3-compiler"))
    if frame is None:
        errors.append(error("FORMAT", "missing_frame_context", "", "draft compile validation requires Frame Design", "video-pipeline", retryable=False))
        return errors

    segments = frame.get("segment_plan") if isinstance(frame.get("segment_plan"), list) else []
    prompts = value.get("draft_video_prompts") if isinstance(value.get("draft_video_prompts"), list) else []
    if [item.get("segment_id") for item in prompts if isinstance(item, dict)] != [item.get("segment_id") for item in segments if isinstance(item, dict)]:
        errors.append(error("FORMAT", "draft_prompt_cardinality", "draft_video_prompts", "draft prompts must match Segment Plan order exactly", "h3-compiler"))

    manifest = frame.get("media_manifest") if isinstance(frame.get("media_manifest"), dict) else {}
    media_items = manifest.get("media") if isinstance(manifest.get("media"), list) else []
    media_by_id = {item.get("id"): item for item in media_items if isinstance(item, dict) and isinstance(item.get("id"), str)}
    expected_pending = [
        item["id"]
        for item in media_items
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and item.get("status") != "resolved"
        and item.get("role") != "actual_tail_frame"
    ]
    if value.get("pending_media_ids") != expected_pending:
        errors.append(error("MEDIA", "draft_pending_media", "pending_media_ids", "must equal unresolved non-runtime media IDs in manifest order", "h3-compiler"))

    for prompt, segment in zip(prompts, segments):
        if not isinstance(prompt, dict) or not isinstance(segment, dict):
            continue
        segment_id = prompt.get("segment_id") if isinstance(prompt.get("segment_id"), str) else None
        path = f"draft_video_prompts[{segment_id or '?'}]"
        symbolic = prompt.get("symbolic_media_mapping") if isinstance(prompt.get("symbolic_media_mapping"), dict) else {}
        controls = prompt.get("planned_controls") if isinstance(prompt.get("planned_controls"), dict) else {}
        referenced_ids = []
        for media_id in (symbolic.get("entry_frame"), symbolic.get("last_frame_target")):
            if isinstance(media_id, str):
                referenced_ids.append(media_id)
        referenced_ids.extend(media_id for media_id in symbolic.get("reference_media", []) if isinstance(media_id, str))
        for media_id in referenced_ids:
            if media_id not in media_by_id:
                errors.append(error("MEDIA", "draft_unknown_media", f"{path}.symbolic_media_mapping", f"unknown media ID: {media_id}", "h3-compiler", segment_id=segment_id))
        expected_unresolved = [media_id for media_id in referenced_ids if media_by_id.get(media_id, {}).get("status") != "resolved"]
        if symbolic.get("unresolved_media_ids") != expected_unresolved:
            errors.append(error("MEDIA", "draft_unresolved_mapping", f"{path}.symbolic_media_mapping.unresolved_media_ids", "must equal this segment's unresolved static media IDs in mapping order", "h3-compiler", segment_id=segment_id))

        executable_shape = dict(prompt)
        executable_shape["unified_controls"] = dict(controls)
        if executable_shape["unified_controls"].get("entry_source") == "planned_first_frame":
            executable_shape["unified_controls"]["entry_source"] = "resolved_first_frame"
        executable_mapping = dict(symbolic)
        executable_mapping.pop("unresolved_media_ids", None)
        if executable_mapping.get("entry_frame_source_type") == "planned_media":
            executable_mapping["entry_frame_source_type"] = "resolved_media"
        executable_shape["media_mapping"] = executable_mapping
        synthetic_resolved = {media_id: {**media, "status": "resolved"} for media_id, media in media_by_id.items()}
        errors.extend(validate_unified_package(executable_shape, segment, synthetic_resolved))

    if shot is not None and segments and segments[-1].get("end") != shot.get("duration"):
        errors.append(error("TIMELINE", "draft_timeline_coverage", "draft_video_prompts", "draft prompt timeline must cover Shot IR duration", "h3-compiler"))
    return errors


def validate_validation(
    value: dict[str, Any],
    packages: dict[str, Any] | None,
    deterministic_report: dict[str, Any] | None,
    packages_path: Path | None,
) -> list[dict[str, Any]]:
    errors = schema_errors("validation", value)
    if value.get("status") != "PASS":
        errors.append(error("H3_SCHEMA", "semantic_validation_failed", "status", "semantic validator did not pass", "h3-validator"))
    if packages is not None and value.get("status") == "PASS" and value.get("validated_packages") != packages.get("packages"):
        errors.append(error("FORMAT", "validated_package_drift", "validated_packages", "PASS must return exact unchanged packages", "h3-validator"))
    expected_segment_ids = [item.get("segment_id") for item in (packages or {}).get("packages", []) if isinstance(item, dict)]
    check_segment_ids = [item.get("segment_id") for item in value.get("segment_checks", []) if isinstance(item, dict)]
    if check_segment_ids != expected_segment_ids:
        errors.append(error("FORMAT", "segment_check_cardinality", "segment_checks", "segment checks must match package order exactly", "h3-validator"))
    gate = value.get("deterministic_gate") if isinstance(value.get("deterministic_gate"), dict) else {}
    if deterministic_report is None:
        errors.append(error("FORMAT", "missing_deterministic_report", "deterministic_gate", "final validation requires the exact compile-gate report", "video-pipeline", retryable=False))
    else:
        if deterministic_report.get("stage") != "compile" or deterministic_report.get("status") != "PASS":
            errors.append(error("FORMAT", "invalid_deterministic_report", "deterministic_gate", "deterministic report must be a compile-stage PASS", "video-pipeline", retryable=False))
        if gate.get("report_id") != deterministic_report.get("report_id"):
            errors.append(error("FORMAT", "deterministic_report_mismatch", "deterministic_gate.report_id", "semantic report references a different deterministic report", "h3-validator"))
        expected_hash = file_hash(packages_path) if packages_path is not None else None
        artifact_hash = (deterministic_report.get("artifact_hashes") or {}).get("artifact")
        if expected_hash is not None and artifact_hash != expected_hash:
            errors.append(error("FORMAT", "stale_deterministic_report", "deterministic_gate", "compile-gate artifact hash does not match packages", "video-pipeline", retryable=False))
    return errors


def validate_result(value: dict[str, Any], shot: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The result is what the renderer is handed, so it carries the render target.

    Aspect ratio is a production parameter, not a per-segment one: it is decided
    once and used when the video is finally rendered. Shot IR is where it is
    recorded, and this is the only place it can be checked to have survived.
    """
    errors = schema_errors("result", value)
    result = value.get("result")
    if shot is None or not isinstance(result, dict):
        return errors
    for field, expected in (("aspect_ratio", shot.get("aspect_ratio")), ("total_duration", shot.get("duration"))):
        if result.get(field) != expected:
            errors.append(error("FORMAT", "render_target_mismatch", f"result.{field}",
                                f"is {result.get(field)!r}, but Shot IR says {expected!r}", "video-pipeline"))
    return errors


def make_report(stage: str, paths: dict[str, Path], errors: list[dict[str, Any]]) -> dict[str, Any]:
    hashes = {name: file_hash(path) for name, path in sorted(paths.items())}
    core = {"stage": stage, "status": "PASS" if not errors else "FAIL", "artifact_hashes": hashes, "errors": errors, "warnings": []}
    report_id = hashlib.sha256(json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"schema_version": "1.0", "report_id": report_id, **core}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic H3 pipeline stage gates")
    parser.add_argument("stage", choices=("story", "shot", "frame", "media", "draft_compile", "compile", "validation", "result"))
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--story", type=Path)
    parser.add_argument("--shot", type=Path)
    parser.add_argument("--frame", type=Path)
    parser.add_argument("--packages", type=Path)
    parser.add_argument("--deterministic-report", type=Path)
    args = parser.parse_args()
    paths = {"artifact": args.artifact}
    try:
        artifact = load_json(args.artifact)
        story = load_json(args.story) if args.story else None
        shot = load_json(args.shot) if args.shot else None
        frame = load_json(args.frame) if args.frame else None
        packages = load_json(args.packages) if args.packages else None
        deterministic_report = load_json(args.deterministic_report) if args.deterministic_report else None
        for name in ("story", "shot", "frame", "packages", "deterministic_report"):
            path = getattr(args, name)
            if path:
                paths[name] = path
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        report = make_report(args.stage, {"artifact": args.artifact}, [error("FORMAT", "input_error", "", str(exc), "video-pipeline", retryable=False)])
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    if args.stage == "story":
        errors = validate_story(artifact)
    elif args.stage == "shot":
        errors = validate_shot(artifact, story)
    elif args.stage == "frame":
        errors = validate_frame(artifact, shot)
    elif args.stage == "media":
        errors = validate_media(artifact, shot)
    elif args.stage == "draft_compile":
        errors = validate_draft_compile(artifact, frame, shot)
    elif args.stage == "compile":
        errors = validate_compile(artifact, frame, shot)
    elif args.stage == "validation":
        errors = validate_validation(artifact, packages, deterministic_report, args.packages)
    else:
        errors = validate_result(artifact, shot)
    report = make_report(args.stage, paths, errors)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
