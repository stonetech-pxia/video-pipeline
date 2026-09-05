---
name: "minimax-h3-prompting"
description: "Review H3 Unified packages for semantic and continuity fidelity"
---

# MiniMax H3 Unified Package Semantic Review

## Input Contract

Require exact per-segment Unified packages, approved Story IR and Shot IR, approved Segment Plan, compile-ready Media Manifest, locked constraints, verbatim text, and an Orchestrator-produced deterministic validation report with `status=PASS` for the same artifact hashes.

Operate in review-only mode. Never run tools or scripts, repair, rewrite, normalize, recompile, choose replacement media, or redesign an artifact. If the deterministic report is missing, stale, or failed, return `FORMAT` failure owned by the malformed producer or Orchestrator as identified by that report.

## Semantic Review

1. Verify each package targets `MiniMax H3 Unified to Video`, uses `prompt_schema=unified_multimodal`, contains no `h3_mode`, legacy I2VA/FL2VA/L2VA alignment preamble, or six-section Ref2VA schema; completion means only Unified syntax remains.
2. Compare every package with approved story facts, Shot IR direction, Segment Plan, Media Manifest, dialogue, visible text, and locked constraints; completion means no content or mapping changed.
3. For `new_first_frame`, verify the prompt treats the node-supplied first frame as the exact starting image while references constrain only their declared identity, location, or style attributes; completion means no reference silently replaces entry composition.
4. For `use_previous_tail_frame`, verify the prompt begins from the runtime-injected current frame, describes only subsequent action, continues existing camera motion, and prohibits reset, repetition, recomposition, and cuts; completion means it never recaps the prior segment.
5. Verify last-frame targets and actual runtime tails remain semantically distinct; completion means the prompt never claims an extracted tail was a generated target.
6. Verify reference labels are ordered, used consistently, and match declared roles; completion means no undeclared preservation or copying instruction appears.
7. Classify every semantic error by the earliest owning stage and return one `segment_checks` entry per package; completion means every false check has a structured diagnostic.

## Error Ownership

- `STORY` → `story-analyst` for facts, entities, outcomes, dialogue, or Story IR continuity.
- `SHOT_DESIGN` → `shot-director` for camera, blocking, shot timing, or boundary intent.
- `FRAME_DESIGN` → `frame-designer` for segmentation, entry strategy, anchors, image prompts, or media mapping.
- `MEDIA` → `media-resolution` for unresolved static assets or invalid runtime-tail provenance.
- `TIMELINE` → the earliest stage that introduced the interval error.
- `H3_SCHEMA` → `h3-compiler` for Unified prompt structure, labels, continuation directives, speakers, or length.
- `FORMAT` → the malformed producer or failed deterministic gate.

## Output Contract

Return JSON conforming to `../../schemas/h3-validation-report.schema.json` with `schema_version=1.3`, one `segment_checks` item per package, structured diagnostics, and exact unchanged `validated_packages` only on `PASS`.

`PASS` requires a fresh deterministic `PASS`, every semantic segment check true, and no errors. On `FAIL`, return at least one error and `validated_packages=[]`.
