---
name: "script-structural-breakdown"
description: "Analyze narrative into camera-neutral Story IR with continuity markers"
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

## Procedure

1. Separate explicit facts, locked constraints, supported interpretations, and unresolved alternatives. Put every story-changing uncertainty in `ambiguities`; completion means no blocking story assumption remains.
2. Assign stable source-order IDs: `C01...`, `L01...`, `P01...`, `B01...`, `D01...`, `CC01...`, and `TM01...`; completion means every ID is unique and every reference resolves.
3. Extract characters, locations, and props without inventing appearance, age, wardrobe, ownership, geography, weather, time, or state; completion means unsupported downstream-relevant details are ambiguities rather than assertions.
4. Build causal beats. Start a new beat only when goal, action, information, power, emotion, location, time, or visible state materially changes; completion means the narrative is covered once in source order.
5. Preserve dialogue exactly, including language, characters, punctuation, speaker, beat placement, and order. Reference dialogue IDs from beats; completion means exact source text is recoverable.
6. Emit `continuity_constraints` for identity, wardrobe, props, scene state, weather, time, and spatial relationships. Each item contains `id`, `category`, `subject_id`, `rule`, `scope`, and `locked`; completion means every explicit continuity lock is represented.
7. Emit `transition_markers` only for explicit or unavoidable scene, time, location, weather, or continuity changes. Each marker contains `marker_id`, `at_beat_id`, `type`, `from`, `to`, and `reason`. It occurs immediately before `at_beat_id`; completion means no transition was added for visual variety.
8. Validate the result against `../../schemas/story-ir.schema.json`; return `complete` only when downstream direction can proceed without a story-changing assumption, otherwise return `partial` with at least one blocking ambiguity.

## Authority Boundary

Do not design shots, framing, lenses, camera position, camera movement, lighting, editing, anchor frames, media-generation strategy, Unified controls, or final H3 syntax. Do not change locked facts or add dialogue, characters, props, locations, events, transitions, or outcomes.

## Output Contract

Return valid JSON only with exactly these top-level fields:

```json
{
  "schema_version": "1.1",
  "status": "complete",
  "duration": 30,
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

Use empty arrays for supported categories with no entries. A `partial` result must contain at least one blocking ambiguity and must not proceed downstream.
