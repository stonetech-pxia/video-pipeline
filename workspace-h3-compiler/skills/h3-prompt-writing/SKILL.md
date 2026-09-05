---
name: "h3-prompt-writing"
description: "Compile MiniMax H3 Unified segment prompts from approved IR and media"
---

# MiniMax H3 Unified Segment Compilation

## Input Gate

Require approved Shot IR, approved contiguous Segment Plan, locked verbatim text, and a Media Manifest with `status=ready_for_compile` or `resolved`. Require each segment duration to equal `end - start` and be an integer from 4 through 15 seconds.

Require every static first frame, last-frame target, and reference medium used by a segment to be resolved with a path or runtime handle. Permit an `actual_tail_frame` to remain `runtime_pending` only when it is reserved as the exact runtime entry dependency of the immediately following segment.

Target only `MiniMax H3 Unified to Video`. Reject legacy generation-mode fields and legacy I2VA/FL2VA/L2VA alignment headers instead of translating them silently.

## Unified Controls

Describe controls independently from prompt syntax:

- `entry_source`: `none | resolved_first_frame | previous_segment_actual_tail`;
- `last_frame_target`: nullable resolved media ID;
- `reference_media`: ordered reference media IDs;
- `prompt_schema`: always `unified_multimodal`.

Keyframes and reference media may coexist. Entry-frame media is supplied through the Unified node input and is not numbered as `<Picture N>`. Number only reference media in stable order as `<Picture N>`, `<Video N>`, or `<Audio N>`.

## Procedure

1. Treat Shot IR and Segment Plan as source code. Preserve segment count, order, global timing, story facts, camera design, anchor strategy, and verbatim dialogue, lyrics, and visible text; completion means no source decision changed.
2. Resolve every media ID. For `new_first_frame`, require its resolved `first_frame`; for `use_previous_tail_frame`, require `entry_frame_source=null` and an exact runtime binding to the immediately previous segment's reserved `actual_tail_frame`; completion means every mapping closes.
3. Emit `unified_controls` from actual mappings, never from narrative text or a legacy mode label; completion means `entry_source`, last-frame control, and ordered references match the manifest exactly.
4. Compile each segment independently with local start `0` and local duration `end - start`. Use exactly three sections in order: `integrated_multimodal_description:`, `overall_soundscape:`, and `non_diegetic_music:`. Do not emit a legacy alignment preamble or the six-section Ref2VA schema; completion means Unified syntax is the only syntax present.
5. For `new_first_frame`, begin Shot 1's description with `以输入首帧作为视频的准确起始画面，保持首帧中的镜头角度、构图、人物位置、环境布局和光照关系。`; completion means the prompt develops forward without redescribing the input as a separate reference picture.
6. Bind each reference by its declared role. For a character reference, use wording equivalent to `主角身份和外观参考 <Picture 1>，保持 <Picture 1> 中人物的面部特征、发型、服装款式和身体特征一致，但不要复制 <Picture 1> 的背景、构图和姿势。`; completion means references constrain only declared attributes. The clause `不要复制 <Picture N>` is matched verbatim by the deterministic gate whenever a character reference declares `do_not_copy`, so keep that exact prefix and label.
7. For `use_previous_tail_frame`, begin Shot 1's description with `从当前首帧自然连续，保持人物身份、服装、场景、光线、机位、构图、空间关系和运动方向不变。` Describe only subsequent action and continuing camera motion, then include `不要重置动作、不要重复前一动作、不要突然换机位或重新构图、不要切镜。`; completion means no previous action is recapped or restaged.
8. When a last-frame target exists, describe the observable path toward that target in the final shot without adding a legacy FL2VA alignment line; completion means the target remains a node control and the prompt only describes motion and arrival.
9. Render every shot the segment covers. A segment carries `shot_ids` and `shot_bindings`; emit one `[Shot N]` block per binding, numbered from 1 in `prompt_shot_index` order — this numbering is local to the segment and unrelated to Shot IR IDs. Open every block after the first with `At MM:SS.mmm, the camera cuts to`, where the timestamp is that binding's `local_start` formatted as two-digit minutes, two-digit seconds, and three-digit milliseconds. Never add a cut the bindings do not list, and never merge two bound shots into one block; completion means the marker count and every cut time match `shot_bindings` exactly.
10. Preserve dialogue, lyrics, and visible text exactly. Keep the prompt at or below 7,000 Unicode characters; completion means deterministic prompt checks pass.
11. Read `../../schemas/h3-segment-package.schema.json` and verify every required field and value shape before returning. Return one raw JSON object with no Markdown fence, commentary, or embedded media records.

## Draft Mode

When the Orchestrator passes `compile_mode=draft`, required static media is still unresolved. Compile the same prompts, but against `../../schemas/h3-draft-prompts.schema.json` with `schema_version=1.0` and `status=draft`. A draft is inspectable, never executable.

Everything above still applies — the three sections, the directives, the reference bindings, and rule 9's shot markers and cut times. Only the media-facing names and values change:

| Executable | Draft | Difference |
| --- | --- | --- |
| `unified_controls` | `planned_controls` | `entry_source` uses `planned_first_frame` where the executable form would say `resolved_first_frame` |
| `media_mapping` | `symbolic_media_mapping` | `entry_frame_source_type` uses `planned_media` in place of `resolved_media`, and the object carries an extra `unresolved_media_ids` |

`symbolic_media_mapping.unresolved_media_ids` lists exactly this segment's referenced media that the manifest has not resolved — entry frame, last-frame target, and reference media — in mapping order.

The top level adds `pending_media_ids`: every unresolved medium in the manifest that is not an `actual_tail_frame`, in manifest order. A reserved `actual_tail_frame` is never listed; it resolves at video runtime by design.

Keep every media ID stable between draft and executable output. The draft is the same compilation with unresolved assets named rather than resolved, not a different plan.

## Output Contract

Return `schema_version=1.3`. Use this exact structural shape:

```json
{
  "schema_version": "1.3",
  "status": "complete",
  "packages": [{
    "segment_id": "SEG001",
    "shot_ids": ["S01", "S02"],
    "shot_bindings": [
      { "prompt_shot_index": 1, "shot_id": "S01", "local_start": 0 },
      { "prompt_shot_index": 2, "shot_id": "S02", "local_start": 3 }
    ],
    "start": 0,
    "end": 8,
    "local_duration": 8,
    "prompt_schema": "unified_multimodal",
    "execution_node": "MiniMax H3 Unified to Video",
    "unified_controls": {
      "entry_source": "resolved_first_frame",
      "last_frame_target": null,
      "reference_media": ["REF001"]
    },
    "prompt": "integrated_multimodal_description: [Shot 1] ... [Shot 2] At 00:03.000, the camera cuts to ...",
    "media_mapping": {
      "entry_frame": "FF001",
      "entry_frame_source_type": "resolved_media",
      "runtime_entry_binding": null,
      "last_frame_target": null,
      "expected_actual_tail_frame": null,
      "reference_media": ["REF001"],
      "reference_bindings": [{
        "label": "Picture 1",
        "media_id": "REF001",
        "role": "character_reference",
        "preserve": ["identity", "face", "hair", "wardrobe", "body"],
        "do_not_copy": ["background", "composition", "pose"]
      }]
    }
  }],
  "errors": []
}
```

The example documents shape, not content. Copy IDs, timing, controls, and role data from the approved artifacts. Keep `entry_frame`, `last_frame_target`, `expected_actual_tail_frame`, and `reference_media` as media IDs or null; never replace them with embedded objects, paths, or runtime handles. Store labels without angle brackets in `reference_bindings.label`, and use them with angle brackets only inside the prompt. Do not include `h3_mode`.

On failure return `status=compile_error`, empty `packages`, and structured errors with `code`, `path`, `message`, and nullable `segment_id`.
