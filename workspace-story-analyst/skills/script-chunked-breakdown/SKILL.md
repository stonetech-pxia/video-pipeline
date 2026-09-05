---
name: "script-chunked-breakdown"
description: "Break a long narrative into a scene plan and per-chunk Story IR passes so a feature-length script never has to be emitted in one turn"
---

# Chunked Story IR

A Story IR the size of a feature is not safely emitted in one reply: the artifact is all-or-nothing, so one wrong field near the end wastes the whole pass. This skill splits the work into a small plan followed by bounded chunks. The runner merges them and validates the merged artifact against `schemas/story-ir.schema.json`.

Use it together with `script-structural-breakdown`, which defines what a scene, beat, and continuity constraint mean. This skill only decides how the work is divided.

## Pass 0 — Story Plan

Given the envelope, emit a plan conforming to `../../schemas/story-plan.schema.json`.

The plan carries the whole film's spine and nothing that grows with beat count:

- every scene, in order, with its slugline, location, time of day, duration budget, a one-paragraph `synopsis`, and `estimated_beats`;
- the global registry of characters (with wardrobe), locations, and props, with their final IDs;
- cross-scene continuity constraints, the supplied locked constraints, and any ambiguity already visible;
- the `chunks` grouping.

The IDs assigned here are final. Later passes reference them and never invent new characters, locations, or props. When a later pass genuinely needs an entity the plan missed, it records a blocking ambiguity instead of inventing one.

`estimated_beats` is your own forecast of how many beats the scene will need, at the granularity `script-structural-breakdown` defines. It drives the grouping, so estimate honestly rather than optimistically.

## Grouping Rule

Walk the scenes in order and start a new chunk when adding the next scene would exceed either budget:

- **20 beats** of `estimated_beats`, or
- **6 scenes**.

Never split one scene across chunks; a scene is the smallest unit that can move. Prefer to break where the story already breaks: a location change, a time jump, an act turn. When a single scene alone exceeds 20 estimated beats, give it a chunk of its own.

A short film usually yields one chunk, and the pass that follows is then an ordinary full breakdown. Do not force a split that the story does not need.

## Pass N — Chunk

For each chunk, emit an artifact conforming to `../../schemas/story-ir-chunk.schema.json`, covering only that chunk's scenes:

- `scenes`: for each scene the chunk owns, its `beat_ids` in order and its `exit_state`;
- `beats`, `dialogue`, scene-local `continuity_constraints`, `transition_markers`, and any new `ambiguities`. A marker at a scene's first beat may only be `weather_change` or `continuity_break`; the scene spine already carries the rest.

Do not repeat the plan's characters, locations, props, or cross-scene constraints. The merge adds them back once. A beat's `entity_ids` names characters and props only; its location comes from the plan's scene.

Beat IDs continue across the whole film in one sequence: if the previous chunk ended at `B037`, this chunk starts at `B038`. The same holds for `D`, `CC`, and `TM` IDs. Never restart numbering per chunk and never reuse an ID.

Each chunk begins from the previous chunk's last `exit_state`. Treat that state as fact and do not contradict it.

## Procedure

1. Read the envelope and apply the input contract of `script-structural-breakdown`.
2. Emit the plan. Stop and return it; the runner asks for each chunk separately.
3. For each requested chunk, emit only that chunk's artifact.
4. The runner merges plan and chunks, then runs `scripts/validate_output.py` on the merged Story IR. Repair whatever it reports for the chunk you are asked about.

## Output Contract

Return valid JSON only, one artifact per turn, with no prose around it. A pass that cannot proceed returns its artifact with a blocking ambiguity rather than a partial or truncated structure.
