---
name: "frame-design"
description: "Bind reference media and tail-frame dependencies to planned segments, and draft their MiniMax H3 prompts"
---

# Frame Design

## Input Contract

Require a resolved Shot IR chunk — Shot IR after `resolve_assets.py`, so every shot carries `scene_id`, `location_id`, and `reference_assets` — plus the segment skeleton `scripts/plan_segments.py` produced for that chunk, and the asset registry entries for the subjects it shows.

There are no first frames. A segment is generated from two things: its prompt, and the reference images for the characters and the location it shows. Everything after the opening of a scene also continues from the frame the previous generation actually ended on.

Return `partial` with structured errors when a required reference subject is missing from the registry, or when a fact you would have to invent is not in the chunk.

## Procedure

1. **Read the output contract before drafting anything.** Open `../../schemas/frame-design-chunk.schema.json` and the `$defs` it refers to in `../../schemas/frame-design-output.schema.json`. Both are strict: `additionalProperties` is false everywhere, so a field you invent is a rejection, not a nicety. Completion means you know every required field, every enum value, and every conditional branch before you write a line.
2. Take the segment skeleton verbatim. `segment_id`, `scene_id`, `start`, `end`, `duration`, `shot_ids`, `shot_bindings`, `previous_segment_id`, and `entry_strategy` are already decided and are not yours to touch. Completion means every one of those fields is byte-identical to what you were handed.
3. Bind the entry. `references_only` opens a scene and has nothing to continue from: `runtime_entry_dependency` is null. `use_previous_tail_frame` opens inside a shot still running: point `runtime_entry_dependency` at the previous segment and its reserved `actual_tail_frame`, and set that earlier segment's `exit_frame_required` to true with an `actual_tail_frame_media_id`. Completion means every continuation has a tail to continue from, and no segment reserves a tail nobody uses.
4. Bind the cast and the place. Take the union of `characters_in_frame` over the shots a segment covers and give exactly those characters a `character_reference`, each carrying `subject_id`; add one `location_reference` for the segment's `location_id`. One media id per subject across the whole chunk, listing every segment that uses it in `related_segments`. Completion means the checker finds no face without a reference and no reference without a face, and no more than four reference media on any segment.
5. Reserve the tail frames as media: `type` frame, `source_type` extracted, `status` runtime_pending, `derived_from_segment_id` set to the segment they are captured from. A tail frame is never generated and never an image job. Completion means every reserved tail is owned by exactly one segment.
6. Draft each segment's prompt in the three Unified sections. Read `references/prompt-craft.md` before the first one; it holds what belongs in a prompt when the reference images already carry appearance. Completion means every prompt names its subjects and describes only what changes.
7. Carry what survived a scene change. A segment that opens a scene is generated cold, so `wardrobe_state` and every item in `held_props` from the shot before it must appear word for word in its `integrated_multimodal_description`. The message names them for each such segment. Completion means the place resets and the people do not.
8. **Check your own work before returning.** Write the complete artifact to the candidate path the message gives you and run `scripts/validate_frame_chunk.py` against it, as the message spells out. Fix what it reports and run it again. **That file is the artifact** — the pipeline reads it, not your reply, so leave it in place and do not retype the JSON into your answer. Completion means the checker prints `"valid": true`; a reply retyped afterwards is a second, unchecked artifact.

## References

Read these yourself. Nothing here is loaded for you; open what the step you are on needs.

- `../../schemas/frame-design-chunk.schema.json` — **required reading at step 1.** The exact envelope you return: `chunk_id`, `start`, `end`, `segment_plan`, `media_manifest`, `warnings`, `errors`, and nothing else.
- `../../schemas/frame-design-output.schema.json` — **required reading at step 1.** The chunk schema is a thin wrapper; the real definitions of a segment, a medium, and a diagnostic live in this file's `$defs`. `warnings` and `errors` are arrays of `{code, path, message}` objects, never strings.
- `references/prompt-craft.md` — **required reading at step 6.** What a prompt says when the reference images already carry the faces and the room, how the three sections divide, and why describing appearance twice makes the result worse.
- `../../AGENTS.md` — your standing role and authority. The procedure above is how you exercise it.

## Authority Boundary

Do not choose, move, merge, split, resize, or renumber a segment; those come from `scripts/plan_segments.py`. Do not change `entry_strategy`. Do not change story facts, dialogue, shot order, or directed framing, camera movement, and blocking. Do not describe what a character or a place looks like — the reference images carry that. Do not write final MiniMax H3 syntax; the compiler does. Do not claim a medium is resolved without a real path or runtime handle.

## Output Contract

Write the artifact to the candidate path as `schema_version=1.3` JSON. Write Chinese directly as UTF-8, never as `\uXXXX` escapes.

When the message gives no candidate path, return the JSON in your reply instead — JSON only, no prose, no Markdown fence.

Reference images come from the asset registry. Where its `image` is null the medium is `pending` with no path and `media_manifest.status` is `draft`; do not invent a path and do not describe the subject from scratch to compensate. Nothing at this stage generates an image.

`status` is `complete`, `partial`, or `blocked`; anything but `complete` carries at least one structured error and must not proceed downstream.
