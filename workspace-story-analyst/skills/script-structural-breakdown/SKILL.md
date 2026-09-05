---
name: "script-structural-breakdown"
description: "Analyze narrative into a camera-neutral screenplay as Story IR with scenes and continuity markers"
---

# Story IR Analysis

## Input Contract

Accept an envelope containing:

- `narrative`: required source text;
- `duration`: optional requested total-video duration as a positive integer or `null`;
- `reference_media_description`: optional source-grounded descriptions used only as evidence about story facts;
- `locked_constraints`: facts no downstream stage may change;
- optional prior Story IR, deterministic diagnostics, and retry targets.

Do not accept or emit legacy generation-mode fields. H3 controls, media strategy, and per-segment duration belong to downstream stages.

When `narrative` is missing, return `partial` with a blocking ambiguity. Preserve a supplied total duration; never invent one.

Cover the entire narrative in one artifact. Never return a prefix of the film and never stop at a scene boundary.

## Procedure

1. Separate explicit facts, locked constraints, supported interpretations, and unresolved alternatives. Put every story-changing uncertainty in `ambiguities` as an object carrying `severity`, where `"blocking"` means downstream cannot proceed without a story-changing assumption; completion means no blocking story assumption remains.
2. Cut the narrative into scenes at each break of location, time, or dramatic situation. Give each a screenplay slugline, its `location_id`, `time_of_day`, and `exit_state`; completion means the scenes cover the narrative once, in order.
3. Distribute the supplied `duration` across scenes as `duration_budget` in proportion to dramatic weight; completion means the budgets sum to `duration`, or all are null when no duration was supplied.
4. Assign stable source-order IDs: `S01...`, `C01...`, `L01...`, `P01...`, `B01...`, `D01...`, `CC01...`, and `TM01...`; completion means every ID is unique and every reference resolves.
5. Extract characters, locations, and props without inventing appearance, age, wardrobe, ownership, geography, weather, time, or state. Set `wardrobe` from the narrative or to `null`; completion means unsupported downstream-relevant details are ambiguities rather than assertions.
6. Build causal beats inside each scene. Start a new beat only when goal, action, information, power, emotion, or visible state materially changes. Each beat carries `id`, `scene_id`, `action`, `emotion`, `entity_ids`, and `dialogue_ids` and nothing else, where `entity_ids` lists characters and props but never a location; completion means the narrative is covered once in source order, every beat belongs to exactly one scene, and no beat restates its scene's location.
7. Preserve dialogue exactly, including language, characters, punctuation, speaker, beat placement, and order. Reference dialogue IDs from beats; completion means exact source text is recoverable.
8. Emit `continuity_constraints` for identity, wardrobe, props, scene state, weather, time, and spatial relationships. Each item contains `id`, `category`, `subject_id`, `rule`, `scope`, and `locked`, where `scope` is a list of beat or scene IDs or a `{"from", "to"}` range; completion means every explicit continuity lock is represented.
9. Emit `transition_markers` only for changes the scene spine cannot express. A scene's first beat already implies a scene, location, and time-of-day change, so mark it only with `weather_change` or `continuity_break`; every other marker belongs mid-scene. Each marker contains `marker_id`, `at_beat_id`, `type`, `from`, `to`, and `reason`, and occurs immediately before `at_beat_id`; completion means no marker restates a scene boundary and none was added for visual variety.
10. Validate the result by running `scripts/validate_output.py` against it and repairing every reported error; return `complete` only when the validator reports `"valid": true` and downstream direction can proceed without a story-changing assumption, otherwise return `partial` with at least one blocking ambiguity.

## Authority Boundary

Do not design shots, framing, lenses, camera position, camera movement, lighting, editing, anchor frames, media-generation strategy, Unified controls, or final H3 syntax. Do not change locked facts or add dialogue, characters, props, locations, events, transitions, or outcomes. Do not assign beat timing; the Shot Director owns the timeline.

## Output Contract

Return valid JSON only with exactly these top-level fields:

```json
{
  "schema_version": "2.0",
  "status": "complete",
  "duration": 30,
  "scenes": [],
  "characters": [],
  "locations": [],
  "props": [],
  "beats": [],
  "dialogue": [],
  "continuity_constraints": [],
  "transition_markers": [],
  "locked_constraints": [],
  "ambiguities": []
}
```

Use empty arrays for supported categories with no entries. A `partial` result must contain at least one blocking ambiguity and must not proceed downstream. A `complete` result may carry non-blocking ambiguities. Never use the key `blocking`; it is reserved for actor blocking and rejected as a camera-layer decision.
