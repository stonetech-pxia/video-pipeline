---
name: "ai-storyboard-director"
description: "Design Shot IR with camera, timing, blocking, and continuity labels"
---

# Shot IR Design

## Input Contract

Require approved Story IR `schema_version=1.1` with `status=complete`, a positive integer total duration, continuity and transition markers, dialogue references, and locked constraints. Accept optional aspect ratio, visual preferences, prior Shot IR, and targeted deterministic diagnostics.

Do not accept or emit legacy H3 generation-mode fields. Segment-level Unified controls belong to Frame Designer and H3 Compiler.

Return `partial` with structured errors when the Story IR is partial, duration is invalid, references are broken, or a missing fact would require changing the story.

## Procedure

1. Validate Story IR status, total duration, stable IDs, dialogue references, transition markers, continuity constraints, and locked facts; completion means every input reference resolves.
2. Establish world state for location, time, weather, character position and facing, entrances/exits, prop ownership and state, action axis, practical light direction, and continuous environmental motion; completion means every directed shot has a grounded state.
3. Design the minimum set of directorial shots needed to convey all beats. Every real cut changes narrative information, spatial understanding, action readability, viewpoint, or emotional pressure; completion means every cut has a stated purpose.
4. Own framing, angle, camera position, focal behavior, camera movement, blocking, visible performance, lighting, sound placement, pacing, and transitions without changing story facts; completion means all required shot fields are explicit.
5. Preserve supplied dialogue exactly and place it only in permitted beats; completion means Story IR dialogue text and order are unchanged.
6. Label every shot boundary with `boundary_type`, `camera_continuity`, `action_continuity`, `framing_continuity`, `scene_continuity`, and `recomposition_needed`; completion means a real cut is never labeled as same-shot continuation.
7. Add optional `segments` only as non-binding action-phase hints. Preserve the parent shot ID and stable hint IDs; completion means no final segment or media-entry decision appears in Shot IR.
8. Build a contiguous global timeline: first shot starts at `0`, intervals are positive, ordered, non-overlapping, gap-free, and the final shot ends at total duration; completion means deterministic timeline checks pass.
9. Record `continuity_exit_state` with character positions/facing, prop state, active action phase, scene, time, weather, camera position, framing, screen direction, and lighting direction; completion means Frame Designer need not guess the exit state.
10. Validate against `../../schemas/shot-ir.schema.json` and return JSON only; return `complete` only when every source beat and locked fact is represented.

## Authority Boundary

Do not rewrite dialogue, change locked story facts, add unrelated events or characters, choose final media assets, choose `new_first_frame` versus `use_previous_tail_frame`, finalize generation segments, choose Unified controls, or emit MiniMax H3 syntax.

## Output Contract

Return `schema_version=1.1`. The first shot uses `boundary_type=shot_change`. `status` is `complete` or `partial`; a partial result contains at least one structured error and must not proceed downstream.
