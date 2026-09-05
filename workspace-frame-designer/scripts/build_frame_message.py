#!/usr/bin/env python3
"""Write the message that asks the Frame Designer for one chunk.

The boundaries are not the designer's to choose, so they are packed here and
handed over as a skeleton to be copied. What the message adds is what the
designer would otherwise have to hunt for: the reference images its subjects
resolve to, and, for every segment that opens a scene cold, the exact state the
shot before it left behind.

Usage: build_frame_message.py <resolved-shot-chunk.json> <assets.json>
                              [--previous <previous-resolved-shot-chunk.json>]
                              [--continues-scene]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plan_segments import PlanError, plan  # noqa: E402
from validate_frame_design import (  # noqa: E402
    carried_exit_state,
    index_shots,
    with_previous_shot,
)

TEMPLATE = """Produce frame-design chunk {chunk_id} for the shots below, following the frame-design skill.

Start at step 1 of that skill: open schemas/frame-design-chunk.schema.json and the $defs it points at in
schemas/frame-design-output.schema.json. Both reject any field they do not define, so read them before drafting.

Return only JSON. Nothing else: no prose, no commentary, no Markdown fence.
Write Chinese text directly as UTF-8 characters; never escape it as \\uXXXX.

Emit exactly these top-level fields and no others: schema_version, chunk_id, status, start, end, segment_plan, media_manifest, warnings, errors.
Set chunk_id to {chunk_id}, start to {start}, end to {end}, schema_version to 1.3, status to complete.

Hard constraints for this chunk:

- The segments are already chosen. For each item in "Segments" below, copy these fields through unchanged: segment_id, scene_id, start, end, duration, shot_ids, shot_bindings, previous_segment_id, entry_strategy. Do not add, remove, move, resize, or renumber a segment.
- Add to each segment exactly these fields and no others: runtime_entry_dependency, exit_frame_required, actual_tail_frame_media_id, reference_strategy, prompt, reason.
- A segment whose entry_strategy is references_only gets runtime_entry_dependency = null and, unless a later segment continues from it, actual_tail_frame_media_id = null with exit_frame_required = false.
- A segment whose entry_strategy is use_previous_tail_frame gets runtime_entry_dependency = {{"kind": "previous_actual_tail_frame", "previous_segment_id": <the segment before it>, "expected_media_id": <that segment's actual_tail_frame_media_id>}}. That earlier segment must carry exit_frame_required = true and an actual_tail_frame_media_id.
- Every actual_tail_frame medium has type "frame", source_type "extracted", status "runtime_pending", and derived_from_segment_id set to the segment it is captured from. It is never a reference image.
- reference_strategy names one character_reference for every character in the characters_in_frame of the shots that segment covers, no more and no fewer, plus one location_reference for its location. At most four reference media per segment.
- Reuse one media id per subject across the whole chunk: a character has one reference image, not one per segment. List every segment that uses it in related_segments.
- A character_reference carries subject_id, the Story IR character id whose likeness it is.
- Reference images come from the registry below. Every image there is null, so give each reference medium status "pending" with no path, and set media_manifest.status to "draft".
- warnings and errors are arrays of objects, each exactly {{"code": ..., "path": ..., "message": ...}}. Never a plain string, and never any other key.
- prompt has exactly three string fields: integrated_multimodal_description, overall_soundscape, non_diegetic_music. Name the characters and the location; do not describe what they look like or how the room is furnished, because the reference images carry that. Describe what changes: action, camera, visible emotion, sound. Preserve dialogue exactly as the shots write it.
{carried}{selfcheck}
One filled segment and its media records, for shape only. Copy the shape; the content is not from this film:

{example}

The segments to fill in:

{segments}

The shots they cover:

{shots}

The reference images these subjects resolve to:

{registry}
"""

SELFCHECK = """
Before you answer, do step 8 of the skill:

1. Write your complete artifact to {candidate}
2. Run: python3 scripts/validate_frame_chunk.py {resolved} {candidate}
3. If it reports errors, fix them in the file and run it again. Only answer once it prints "valid": true.
4. Leave that file in place; it is the artifact. The pipeline reads it, not your reply, so do not retype
   the JSON afterwards. Answer with one short line saying the checker passed.
"""

CARRIED = """- {segment_id} opens a scene, so it is generated cold from its references and nothing on screen carries over on its own. Its integrated_multimodal_description must restate, word for word, what survived the change from {shot_id}: wardrobe_state {wardrobe}{props}. The place resets; the people do not.
"""


EXAMPLE = {
    "segment_plan": [{
        "segment_id": "KX-SEG002", "scene_id": "S09", "start": 5, "end": 20, "duration": 15,
        "shot_ids": ["KX-01", "KX-02"],
        "shot_bindings": [{"prompt_shot_index": 1, "shot_id": "KX-01", "local_start": 0},
                          {"prompt_shot_index": 2, "shot_id": "KX-02", "local_start": 7}],
        "previous_segment_id": "KX-SEG001", "entry_strategy": "use_previous_tail_frame",
        "runtime_entry_dependency": {"kind": "previous_actual_tail_frame",
                                     "previous_segment_id": "KX-SEG001",
                                     "expected_media_id": "TAIL-KX-SEG001"},
        "exit_frame_required": False, "actual_tail_frame_media_id": None,
        "reference_strategy": {"character_reference_ids": ["REF-C09"],
                               "location_reference_ids": ["REF-L09"],
                               "style_reference_ids": [], "video_reference_ids": [],
                               "audio_reference_ids": []},
        "prompt": {"integrated_multimodal_description": "某人在某地放下手中的东西，镜头缓缓推近。",
                   "overall_soundscape": "室内环境音，远处的车声。",
                   "non_diegetic_music": ""},
        "reason": "continues inside the shot the previous segment left running",
    }],
    "media_manifest": {"status": "draft", "media": [
        {"id": "REF-C09", "type": "image", "role": "character_reference", "status": "pending",
         "source_type": "generated", "related_segments": ["KX-SEG001", "KX-SEG002"],
         "subject_id": "C09"},
        {"id": "TAIL-KX-SEG001", "type": "frame", "role": "actual_tail_frame",
         "status": "runtime_pending", "source_type": "extracted",
         "related_segments": ["KX-SEG001"],
         "derived_from_segment_id": "KX-SEG001"},
    ]},
    "warnings": [{"code": "reference_image_pending", "path": "media_manifest.media[REF-C09]",
                  "message": "the registry has no image for C09 yet"}],
}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: top-level JSON value must be an object")
    return value


def carried_state(shot_chunk: dict[str, Any], previous: dict[str, Any] | None,
                  segments: list[dict[str, Any]]) -> str:
    """Tell every cold-started segment what to restate, and where it comes from.

    Which segments those are, and what each must carry, is decided by the
    checker's own `carried_exit_state`. Asking and checking through one function
    is the point: the designer can only be graded on what it was given.
    """
    context = with_previous_shot(shot_chunk, previous)
    shot_by_id, shot_order, exit_state_by_shot = index_shots(context)

    lines = []
    for segment in segments:
        if segment.get("entry_strategy") != "references_only":
            continue
        source_id, carried = carried_exit_state(
            segment.get("shot_ids") or [], shot_by_id, shot_order, exit_state_by_shot)
        if not carried:
            continue
        props = carried.get("held_props") or []
        lines.append(CARRIED.format(
            segment_id=segment["segment_id"],
            shot_id=source_id,
            wardrobe=json.dumps(carried.get("wardrobe_state", ""), ensure_ascii=False),
            props=f", and held_props {json.dumps(props, ensure_ascii=False)}" if props else "",
        ))
    return "".join(lines)


def registry_slice(shots: list[dict[str, Any]], assets: dict[str, Any]) -> dict[str, Any]:
    """Only the subjects this chunk shows, so the designer is not handed the film."""
    characters = {name for shot in shots for name in shot.get("characters_in_frame", [])}
    locations = {shot.get("location_id") for shot in shots} - {None}
    return {
        "characters": {key: value for key, value in assets.get("characters", {}).items() if key in characters},
        "locations": {key: value for key, value in assets.get("locations", {}).items() if key in locations},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shot_chunk")
    parser.add_argument("assets")
    parser.add_argument("--previous", help="the previous resolved Shot IR chunk, for the seam")
    parser.add_argument("--continues-scene", action="store_true",
                        help="the chunk plan says this chunk opens inside a scene")
    parser.add_argument("--resolved-path",
                        help="where the designer can read this chunk, so it can run the checker")
    parser.add_argument("--candidate-path",
                        help="where the designer should write its draft before checking it")
    args = parser.parse_args()

    try:
        shot_chunk = load(Path(args.shot_chunk))
        assets = load(Path(args.assets))
        previous = load(Path(args.previous)) if args.previous else None
        segments = plan(shot_chunk, args.continues_scene)
    except (OSError, ValueError, json.JSONDecodeError, PlanError) as exc:
        print(f"cannot ask for this chunk: {exc}", file=sys.stderr)
        return 2

    shots = [shot for shot in shot_chunk.get("shots", []) if isinstance(shot, dict)]
    sys.stdout.write(TEMPLATE.format(
        chunk_id=shot_chunk.get("chunk_id"),
        start=shot_chunk.get("start"),
        end=shot_chunk.get("end"),
        carried=carried_state(shot_chunk, previous, segments),
        selfcheck=SELFCHECK.format(resolved=args.resolved_path, candidate=args.candidate_path)
        if args.resolved_path and args.candidate_path else "",
        example=json.dumps(EXAMPLE, ensure_ascii=False, indent=2),
        segments=json.dumps(segments, ensure_ascii=False, indent=2),
        shots=json.dumps(shots, ensure_ascii=False, indent=2),
        registry=json.dumps(registry_slice(shots, assets), ensure_ascii=False, indent=2),
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
