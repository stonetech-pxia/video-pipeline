# openclaw video pipeline 改造方案

- 日期：2026-09-05（已按当日线上修复重新校准）
- 对象：从 WSL `OpenClawGateway` 的 `~/.openclaw/workspace-*` 导出的 6 个 agent workspace
- 状态：**方案已定，尚未动工**。本文档撰写期间未修改任何代码或 schema。
- 基线：2026-09-05 10:45 的导出快照，含 draft compile 分支、MEDIA 门、result 门、validation 门加强等修复。所有行号、审计结论、条目状态均以此快照为准。

---

## 给实施者的说明

**唯一权威的改动清单是第 5 部分。** 第 1–4 部分是背景、决策依据和审计结果，用于理解「为什么」；真正要执行的是第 5 部分的 C 编号条目。第 6 部分列出明确**不要**改的东西。

**条目编号（C1、C2……）是稳定标识**，条目之间的依赖用编号引用。请按批次顺序执行：批次内条目可并行，跨批次有依赖。

**每个条目包含**：目标文件、现状（含行号）、改法、理由、验收标准。验收标准是可执行的判定条件——改完请逐条对照。

**行号基于本文档撰写时的代码状态。** 同一文件内有多个条目时，先改行号大的，避免前面的改动导致后面的行号偏移。

**两个原则**：

1. 本方案不改动 `story-analyst` 的任何内容，也不改动 MiniMax H3 的 Unified 提示词三段式结构。
2. 遇到本文档没覆盖的判断，优先保持现状，并在实施报告里记下来，不要自行扩大改动范围。

---

# 第 1 部分：现状

## 1.1 素材来源

WSL 发行版 `OpenClawGateway` 的 `/home/openclaw/.openclaw/`：

| workspace | 角色 |
| --- | --- |
| `workspace-video-pipeline` | orchestrator（确定性编排 + 校验门） |
| `workspace-story-analyst` | 剧本结构化 |
| `workspace-shot-director` | 分镜 |
| `workspace-frame-designer` | 段落规划 + 关键帧/参考图规划 |
| `workspace-h3-compiler` | 提示词编译 |
| `workspace-h3-validator` | 语义审核（review-only） |
| `workspace-attestations` | 空 |

该发行版的 `/etc/wsl.conf` 设了 `automount=false` / `interop=false`，`/mnt/c` 不是 Windows C 盘而是 rootfs 里的空占位目录。

## 1.2 链路

```text
USER → story-analyst → STORY 门
     → shot-director  → SHOT 门
     → frame-designer → FRAME 门
     → 媒体解析        → MEDIA 门
        ├ 媒体未就绪 → h3-compiler 草稿模式 → DRAFT_COMPILE 门 → MEDIA_WAIT
        └ 媒体就绪   → h3-compiler 可执行模式 → COMPILE 门
     → h3-validator   → REPORT 门（仅语义复核）
     → RESULT 门 → 输出 / 按序执行 MiniMax H3 Unified to Video
```

八个确定性门，全部由 orchestrator 自己跑 `scripts/validate_pipeline.py <stage>`，要求 `exit 0` 且 `status=PASS`：

```text
story  shot  frame  media  draft_compile  compile  validation  result
```

几处值得注意的现有能力：

- **MEDIA 门会真的去查文件**：`validate_media`（`validate_pipeline.py:195`）对每个 `status=resolved` 的媒体跑 `Path(path).is_file()` 与 `os.access(path, os.R_OK)`，非本地资产须改用 `runtime_handle`。
- **DRAFT_COMPILE 门复用可执行校验**：`validate_draft_compile`（`:322`）把草稿变形成可执行形状后调用 `validate_unified_package`。**因此凡是加在 `validate_unified_package` 里的检查，草稿路径自动继承**——这一点对本方案很重要，见 C16。
- **VALIDATION 门校验报告新鲜度**：`validate_validation`（`:385`）要求传入 `--deterministic-report`，并核对它是 compile 阶段的 PASS、`report_id` 匹配、且其 `artifact_hashes.artifact` 等于当前 packages 文件的哈希。拿旧报告糊弄不过去。
- **RESULT 门目前只做 schema 校验**：`validate_result`（`:415`）仅调用 `schema_errors("result", value)`，没有任何交叉一致性检查。

修复按 `error_class + code + path + segment_id` 指纹路由回最上游责任方，同指纹最多自动修 2 次。

## 1.3 契约版本

Story IR `1.1` / Shot IR `1.1` / frame-design `1.2` / **H3 draft prompts `1.0`** / H3 package `1.3` / validation report `1.3` / pipeline-state **`1.3`** / pipeline-result `1.0`。全线禁用 legacy 的 `generation_mode` 与 `h3_mode`。

`h3-draft-prompts.schema.json` 是草稿契约，与 `h3-segment-package.schema.json` 结构平行但字段名不同：`planned_controls`（`entry_source` 允许 `planned_first_frame`）对应 `unified_controls`，`symbolic_media_mapping`（`entry_frame_source_type` 允许 `planned_media`，且多一个 `unresolved_media_ids`）对应 `media_mapping`。**两份 schema 都定义了 `shot_id`，本方案的字段改动必须同时覆盖。**

## 1.4 shot 与 segment 的现状

- **shot**（shot-director）：导演意义上的镜头，时长不限
- **segment**（frame-designer）：一次 H3 生成调用，**硬性 4–15 秒整数**

Shot IR 每个 shot 有必填的 `segments` 建议数组（`segmentHint`），语义是「这个 shot 内部该怎么拆」。

同 shot 内的后续 segment 必须走 `entry_strategy = "use_previous_tail_frame"`，触发 `validate_frame_design.py:109-111` 的八项检查：`is_same_shot`、`continuous_action`、`continuous_camera`、`same_scene`、`same_framing`、`same_camera_position`、`same_time`、`same_visual_focus` 全为 `true`，`requires_recomposition` 为 `false`，`change_triggers` 为空。且 prompt 必须逐字包含「不要重置动作、不要重复前一动作、不要突然换机位或重新构图、不要切镜。」

跨 shot 边界必然走 `new_first_frame`——因为 `is_same_shot` 为 false 走不了 tail 复用。**shot 边界是靠 entry 策略编码的，不是靠 `shot_id` 比对。**

## 1.5 最终产物形态

不是视频，是一份可投喂 MiniMax H3 的 JSON 生产包：

- 外层 `pipeline-result`：`status` ∈ `COMPLETE | MEDIA_WAIT | BLOCKED | FAILED`
- 核心 `h3-segment-package`：每段一个 package，含 `unified_controls`、三段式 `prompt`（≤7000 字符）、`media_mapping`
- 审核 `h3-validation-report`：`segment_checks` 七项布尔 + `deterministic_gate.report_id`
- 待办 `image_jobs`：需自行生成的参考图/首帧。orchestrator **不会自动接图像 API**，缺料则返回 `MEDIA_WAIT`

提示词为中英混写：强制锚定/约束句是中文固定模板（逐字比对），画面与声音正文为英文，台词与屏幕文字逐字保留不翻译。

---

# 第 2 部分：目标设计

## 2.1 各 agent 职责

**story-analyst** — 讲故事剧本化。组织场景、剧情、对白、人物状态。不做任何镜头决策。**本次不改动。**

**shot-director** — 像导演一样把剧本切成镜头，每个镜头时长可长可短，同时输出每个 shot 的时间和整体时间线（**此项现状已满足**，见 2.4）。新增职责：输出每个 shot 的退出状态与两项风险评分（见 2.5）。

**frame-designer** — 根据 shot 序列和模型限制（单段 ≤15 秒）组织每段的长短，为每段选择生成方式，并产出每段的初步 prompt 与参考图规划。改造后段边界由脚本决定，它专注创作决策。

**h3-compiler + h3-validator** — 只负责 prompt 的优化和审核，不做设计决策。

## 2.2 段落装箱规则

**不希望一个 shot 包含多个 segment。**

- 短 shot：**一个 segment 可以包含 2–3 个 shot**（段内允许剪辑）
- 长 shot：超过 15 秒没办法，只能拆成多段
- 段边界应尽量落在 shot 的剪辑点上

## 2.3 为什么打包比拆分好——两层理由

**表层理由**：段边界落在剪辑点时，观众本来就预期画面跳变，尾帧续接的接缝被剪辑掩盖；落在镜头中间时，两次独立生成的接缝会直接暴露，误差逐段累积。

**更强的理由**：**段内的剪辑是视频模型在一次生成里完成的**，人物位置、服装、道具等世界状态由模型内部保证；跨段的剪辑则要经过「截尾帧 → 文字描述 → 重新生成首帧图 → 喂给下一次生成」这条每步都在丢信息的链路。

推论：**同场景、动作连贯的 cut（正反打）恰恰是最不该当段边界的位置**，应当被打包进同一段内部。这是代价函数把该类切点定为高代价的依据。

## 2.4 现有机制中已经正确、无需改动的部分

**连续性机制的抽象是对的。** `continuity_decision` 那套八项检查约束的是「段边界处」的连续性：边界落在剪辑点走 `generate_new_first_frame`（八项不触发），落在镜头中间才走 `reuse_previous_tail`（八项全 true）。目标设计只是让前者成为常态、后者退化为长 shot 拆分时的兜底，**校验逻辑本身不需要改**。

**shot 时间 + 整体时间线已经有了。** `shot-ir.schema.json` 顶层有 `duration`，每个 shot 有 `start`/`end`，`validate_pipeline.py:152-181` 强制校验首个 shot 从 0 起、shot 间连续无空隙、末尾等于总时长（`shot_timeline_start` / `shot_timeline_gap` / `shot_timeline_coverage`）。

## 2.5 分工：模型做估值，脚本做搜索

装箱的**搜索**部分是纯组合优化（给定代价求满足 4–15 秒、覆盖完整时间线、段内 ≤3 shot 的最优切分），必须确定性化，理由：

1. **不可复现。** LLM 切段时同一份 Shot IR 每次结果不同，下游全变，无法回归测试。
2. **会在刁钻情况下出错。** 典型反例：一个 2 秒短 shot 夹在两个 20 秒长 shot 之间，自身够不到 4 秒下限、左右又都必须拆分。贪心和直觉都会卡住，DP 会自动把它并入左邻长 shot 的最后一个分片（`13 + 2 = 15`）。
3. **与架构哲学冲突。** 这套 pipeline 已把所有可判定的东西做成确定性门。

但代价**从哪来**不能只靠标签查表：

- 同一个 `action_continuity=continuous` 的 cut，风险可差十倍——空镜切到人物几乎没有世界状态要传，三人围坐各持道具的对话切镜传递压力极大。二值标签编码不了量级。
- 哪个 shot 需要精确构图控制是纯创作判断。
- 代价常数本身需要按内容标定。

**结论**：shot-director 输出评分（`boundary_risk` / `composition_control`），脚本吃评分做搜索。这保住了可复现性（评分是 Shot IR 的一部分，会进 `last_valid_artifacts`），也让模型只做它擅长的局部判断。

## 2.6 打包的代价：控制力换无缝

**首帧图只锚定段内第一个 shot。** 段内第 2、3 个 shot 是模型纯靠文字 + 参考图自由发挥的，无法指定构图、机位、人物位置。

- 需要精确构图控制的 shot（关键情绪特写、复杂调度、有硬性视觉要求）→ 应作为段首或独占一段
- 过渡、反应镜头、空镜 → 可以放心打包

`last_frame_target` 同理，只能钉住整段最后一帧。此外打包 N 个 shot 意味着要塞进这 N 个 shot 的参考图并集，`<Picture N>` 越多模型遵循度越差。

**这个代价在产物 JSON 里完全看不出来**——只有成片出来才会发现某个关键特写的机位不对。因此必须写进 frame-designer 的规则并落成硬约束。

## 2.7 术语：ref2va / fl2va 保留为口头简称，不回退 legacy 语法

**结论：保留 Unified 契约。**

legacy 那套的模式选择本质是「根据媒体输入组合查表选模式」，而 Unified 把它拆成三个正交控制位，严格更强。legacy 的 `base-modes.md` 明写着 "Do not mix keyframe inputs with reference media"——首帧和参考图不能共存；而「新场景用 ref2va 生成」恰恰需要首帧 + 角色参考图同时存在，legacy 语法表达不了。

对应关系：

| 口头说法 | Unified 表达 |
| --- | --- |
| ref2va（新场景 / 位置调整） | `entry_source: resolved_first_frame` + `reference_media: [...]` |
| fl2va（衔接上段尾帧） | `entry_source: previous_segment_actual_tail` |
| fl2va 且钉死结尾画面 | 上者 + `last_frame_target: <media_id>` |

精度提醒：严格意义上 FL2VA 是首帧+尾帧双锚，「参考上段尾帧」只锚首帧，更接近 I2VA。

---

# 第 3 部分：跨剪辑点的世界状态连续性

## 3.1 问题

段边界落在剪辑点上，只掩盖了**画面内位置**（人物在取景框里靠左还是靠右）的变化。**世界内位置**（人物站在房间哪个位置、朝向哪、手里拿什么、外套脱了没）剪辑一点都藏不住——观众恰恰会在剪辑后下意识核对这些。

## 3.2 现有契约里三样东西都指望不上（已核实）

| 本该管这件事的地方 | 实际状况 |
| --- | --- |
| Shot IR 的 `continuity_exit_state`（顶层必填） | schema 里就是 `{"type": "object"}`，**没有任何字段定义**，且下游无人读 |
| Story IR 的 `continuity_constraints` | 是**全局规则**不是**状态快照**。能表达「他全程穿红外套」，表达不了「第 12 秒时他站在门左侧、右手端着杯子」。且下游无人读（见 4.2） |
| frame-design 的 `image_jobs` | `imageJob` 有 `additionalProperties: false` 且**没有任何输入图片字段**，是纯文生图，首帧图无法参考上一段尾帧生成 |

## 3.3 两层兜底

**兜底一（推荐先做，对应 C7）**：给 `continuity_exit_state` 补结构，定义为逐 shot 的世界状态快照，由 shot-director 输出，frame-designer 把上一个 shot 的退出状态逐字写进该段首帧图的 image prompt 与 segment prompt 开头。

这是**文字级**传递，精度有限，但覆盖了服装、道具、朝向、光线这些最容易穿帮的项，成本低——首帧图仍可预生成、可并行，不破坏「静态素材必须在 COMPILE 前解析完毕」的现有流程。而且可校验。

**兜底二（对应 C10，运行时部分建议推迟）**：给 `imageJob` 加 `input_media_ids`，允许首帧图以已解析媒体作为参考输入。

代价必须说清楚：若输入是运行时才存在的尾帧，该 image job 本身也变成运行时任务，链路变成 `生成视频段 → 截尾帧 → 生成首帧图 → 生成下一段`，完全串行且多一次图像生成。而且图像模型要从新机位重绘同一场景，本质是新视角合成，**对空间位置的准确性不保证**——能稳住服装、道具、光线，稳不住「人到底站在哪」。

因此建议只在高风险边界启用，而非所有剪辑点。

## 3.4 一个更直接的缺口：首帧图与角色参考图无法保证一致

`imageJob` 没有输入图字段，还意味着**首帧图无法参考 `character_reference` 图生成**。首帧图（视频的实际起始画面）里的人脸，和角色参考图里的人脸，是两次独立的文生图产物，只靠 prompt 文字描述保持一致——实际上不可能一致。而 H3 生成时首帧图作为节点输入、角色参考图作为 `<Picture N>`，两张脸不同的图同时喂进去，模型行为未定义。

**这部分不涉及运行时**——角色参考图是静态的，可以先生成好再拿去生成首帧图，纯粹是静态媒体解析内部的先后顺序问题。因此 C10 的静态用法应与批次 A 同步落地，运行时部分可推迟。

---

# 第 4 部分：字段消费审计

审计方法：从 8 个 schema 抽出全部字段，分别查「确定性校验代码是否读取」与「下游 agent 的 AGENTS.md / SKILL.md 是否引用」，再对可疑项人工核对散文表述，避免「字段名没提但概念提了」的误判。**已按 2026-09-05 快照重跑。**

分类口径——「没被引用」分三种，性质完全不同：

- **出口消费**：管道内无人读，但管道外的人/工具要用（如 `image_jobs` 的 prompt、媒体 `path`）→ 合理，不动
- **隐式消费**：下游 LLM 读整份 JSON 时会看到，只是指令未点名（如 `subject_action`、`visible_emotion`）→ 弱契约，可接受，不动
- **真断链 / 真冗余**：上游产出、管道内外都无人读，或下游本该用却重新判断了一遍 → 问题

## 4.1 最严重的一处断链：`continuityLabels` 整组无人读

Shot IR 每个 shot 必填这 6 个字段：

```text
boundary_type / camera_continuity / action_continuity
framing_continuity / scene_continuity / recomposition_needed
```

**下游没有任何一处读它们**——不在 `validate_pipeline.py`（含新增的 media / draft_compile / result 三个门），不在 `validate_frame_design.py`，也不在 frame-designer 或 h3-compiler 的 AGENTS.md 里。2026-09-05 的修复没有触及这一点。

而 frame-designer 的 Anchor Frame Rules 第 2 条在用自然语言重新判断同一批东西：

> When there is a clear **shot change, framing change, camera-position change, scene change, location change, time change**, visual-narrative-focus change, or any need to reset character position... use `new_first_frame`.

然后填进自己的 `continuity_decision`（10 个字段）。**两边判断打架时，没有任何检查会发现。**

这条也影响 2.5 的方案：如果 `continuityLabels` 都没人读，新加的 `boundary_risk` 会被同样忽略。所幸新设计里读它的是 `plan_segments.py` 脚本而非 LLM，顺带把这条链接上了（对应 C12、C14）。

## 4.2 各层真断链 / 真冗余字段清单

| 层 | 字段 | 说明 |
| --- | --- | --- |
| **Story IR** | `category`、`locked_constraints`、`subject_id` | 范围已缩小——2026-09-05 修改后的 `validate_output.py` 现在读取 `continuity_constraints`、`ambiguities`、`marker_id`、`transition_markers`，这四项已脱离死字段 |
| **Shot IR** | `continuityLabels` 六项、`continuity_exit_state`、`action_phase` | 见 4.1 与 3.2。`action_phase` 完全无人提及 |
| **Shot IR** | `aspect_ratio`、`visual_style`、`music`、`diegetic_audio`、`dramatic_purpose`、`subject_action`、`visible_emotion` | 后五项属「隐式消费」（编译器读整份 Shot IR 写提示词），不处理。**前两项是真缺口**——它们根本没传到最终输出，见 4.4 |
| **frame-design** | `entity_bindings`、`use_for`、`generate_first_frame`、`generate_last_frame_target`、`capture_actual_tail_frame`、`character_ids`、`location_ids`、`extraction_status`、`capture_time`、`source_video_media_id`、`source_id`、`supports_mixed_keyframes_and_references` | AGENTS.md 明确要求必填、schema 强制 required，但**管道内外都无人读**。三个 `generate_*` 布尔尤其典型：校验器只读 `first_frame_media_id` 等 ID 字段，从不看布尔，两者矛盾时以 ID 为准且无人报警。`runtime_handle` 已因新增的 MEDIA 门脱离此列 |
| **frame-design** | `reference_strategy` 的五个子数组 | 半死。`validate_frame_design.py` 是 `for group in reference_strategy.values()` 整组遍历，从不按 `character_reference_ids` / `style_reference_ids` 区分。**参考图的角色分类在管道内不起任何作用**，只在编译成 `<Picture N>` 时靠 LLM 判断 |
| **H3 package + H3 draft** | `resolution_stage` | 两份 schema 的 `runtimeEntryBinding` 里都有，`const: "unified_video_runtime"`，永远同一个值，无人读取。纯占位——`kind: "previous_actual_tail_frame"` 已表达同样信息 |
| **H3 package + H3 draft** | `expected_actual_tail_frame` | 表达「这段要截尾帧供下一段用」，但**校验代码不读**。orchestrator 靠散文指令知道要截尾帧 |
| **H3 package + H3 draft** | `do_not_copy` | 编译器写 prompt 时的输入备忘。`validate_pipeline.py` 校验了 `preserve`/`label`/`role` 的绑定关系，但**从不检查 `do_not_copy` 的内容是否真的出现在 prompt 里** |

H3 package 其余 31 个字段用途明确，这部分是健康的。draft schema 新增的 `pending_media_ids`、`unresolved_media_ids`、`planned_controls`、`symbolic_media_mapping` 全部被 `validate_draft_compile` 严格校验，健康。

## 4.3 `COMPLETE` 分支的 result 仍无结构约束

2026-09-05 的修复给 `MEDIA_WAIT` 分支加上了结构：

```json
"result": {
  "type": "object",
  "required": ["draft_video_prompts", "image_jobs"],
  ...
}
```

**但 `COMPLETE` 分支没有对应约束**——顶层 `"result": { "type": ["object", "null"] }` 依旧，`status = COMPLETE` 的 `allOf` 分支只写了 `"result": { "type": "object" }`。成功路径上，交到用户手里的那个对象仍然是任意形状的。

`validate_result`（`:415`）也只做 schema 校验，没有任何交叉一致性检查——不验证 result 里的 packages 是否等于 PACKAGES.json，不验证媒体是否全部覆盖。

**注意**：`outputs/2026-09-05-elevator-kitchen-retest/final-result.json` 是这次修复**之前**的产物，用当前 result 门跑会 FAIL（缺 `draft_video_prompts` 和 `image_jobs`），其 `pending_static_jobs` / `pending_media` / `segment_plan_boundaries` 等字段已不在契约内。**不要把它当作当前契约的样例。**

## 4.4 输出缺少生成视频所需的信息

按「拿着这份 JSON 就能跑完整条生产」的标准，成功路径仍缺 5 项：

| # | 缺口 | 细节 |
| --- | --- | --- |
| 1 | **媒体 ID → 文件路径的映射不保证在输出里** | 已部分缓解：新增的 MEDIA 门保证 manifest 里 `resolved` 的媒体确实有可读文件。但 `media_mapping.entry_frame` 给的仍是 ID，path 在 frame-design 的 manifest 里，而 `COMPLETE` 的 result 无结构约束，没有机制保证 orchestrator 把它带进最终输出。**拿到成功输出仍然不知道该把哪个文件喂给 H3 节点** |
| 2 | **`aspect_ratio` 没传下去** | Shot IR 顶层有，package 与 draft 里都没有，`COMPLETE` 的 result 不保证带。orchestrator 的 Input Normalization 明确要求保留用户指定的宽高比——保留到 Shot IR 就断了 |
| 3 | **`visual_style` 没传下去** | 同上。编译器会把风格写进 prompt 正文，但那是 LLM 自行判断，无字段级传递和校验，同批 segment 的风格描述漂移了不会被发现 |
| 4 | **完全没有模型参数** | 分辨率、帧率、seed、生成次数——一个都没有 |
| 5 | **尾帧截取的操作定义缺失** | 散文说 "capture the preceding segment's actual tail"，但**截哪一帧没定义**：最后一帧？倒数第二帧（末帧常有压缩伪影）？截出来存到哪、用什么命名？`expected_actual_tail_frame` 本可承载这个，但校验代码不读它 |

**已经够用、无需补的部分**：执行顺序（`packages` 数组顺序 + `runtime_entry_binding.previous_segment_id` 表达依赖）、段时长（`local_duration`）、参考图的角色与约束（`reference_bindings` 的 `label` / `role` / `preserve` / `do_not_copy` 结构完整）。

---

# 第 5 部分：改动清单（权威）

## 状态标记

**全部 31 个条目已于 2026-09-05 实施完毕并通过测试（50 passed，实施前为 18）。**

条目正文保留原样作为改动依据与验收记录。实施发生在本机的下载副本上；WSL `OpenClawGateway` 的 `~/.openclaw/workspace-*` 需要同步后才生效。

实施过程中相对本清单的三处偏差，见第 8 部分。

## 执行顺序与依赖

```text
批次 A（结构与字段）── 必须最先完成，否则 B/C/D 全部无从谈起
   ↓
批次 B（装箱与校验）── 依赖 A
   ↓
批次 C（提示词）───── 依赖 A、B
批次 D（输出契约）─── 依赖 A，可与 C 并行
   ↓
批次 E（清理）────── 依赖 A~D 全部完成
批次 F（测试）────── 每批次完成后同步进行，不要留到最后
```

**批次 A 完成后整套测试会全红**（实施前 18 passed），这是预期行为——C26/C27 会修复。不要因为测试变红而回滚 A。

## 三份 schema 的连带关系

`shot_id` 存在于**三份** schema，字段改动必须同时覆盖，漏一份就会在对应的门上失败：

| schema | 位置 | 对应条目 |
| --- | --- | --- |
| `frame-design-output.schema.json` | `:78` required、`:81` 属性 | C1 |
| `h3-segment-package.schema.json` | `:102` required、`:105` 属性 | C2 |
| `h3-draft-prompts.schema.json` | `:119` required、`:122` 属性 | **C29** |

## 改动总览

| 编号 | 文件 | 性质 | 状态 |
| --- | --- | --- | --- |
| C1 | `workspace-frame-designer/schemas/frame-design-output.schema.json` | 破坏性 | 已实施 |
| C2 | `workspace-h3-compiler/schemas/h3-segment-package.schema.json` | 破坏性 | 已实施 |
| C29 | `workspace-h3-compiler/schemas/h3-draft-prompts.schema.json` | 破坏性 | 已实施 |
| C3 | `workspace-video-pipeline/scripts/validate_pipeline.py` | 跟随 | 已实施 |
| C4 | `workspace-frame-designer/AGENTS.md` | 文档 | 已实施 |
| C5 | `workspace-shot-director/schemas/shot-ir.schema.json` | 语义反转 | 已实施 |
| C6 | `workspace-shot-director/AGENTS.md` | 文档 | 已实施 |
| C7 | `workspace-shot-director/schemas/shot-ir.schema.json` | 新增结构 | 已实施 |
| C8 | `workspace-shot-director/schemas/shot-ir.schema.json` | 新增字段 | 已实施 |
| C9 | `workspace-shot-director/AGENTS.md` | 文档 | 已实施 |
| C10 | `workspace-frame-designer/schemas/frame-design-output.schema.json` | 新增字段 | 已实施 |
| C11 | `workspace-frame-designer/scripts/plan_segments.py` | 新建 | 已实施 |
| C12 | `workspace-frame-designer/AGENTS.md` | 文档 | 已实施 |
| C13 | `workspace-frame-designer/scripts/validate_frame_design.py` | 新增校验 | 已实施 |
| C14 | `workspace-frame-designer/scripts/validate_frame_design.py` | 新增校验 | 已实施 |
| C15 | `workspace-h3-compiler/skills/h3-prompt-writing/SKILL.md` | 新增规则 | 已实施 |
| C30 | `workspace-h3-compiler/skills/h3-prompt-writing/SKILL.md` | 新增规则 | 已实施 |
| C16 | `workspace-video-pipeline/scripts/validate_pipeline.py` | 校验升级 | 已实施 |
| C17 | `workspace-h3-validator/AGENTS.md` | 文档 | 已实施 |
| C18 | `.../h3-prompt-writing/references/base-en.txt` | 删除 | 已实施 |
| C19 | `workspace-video-pipeline/schemas/pipeline-result.schema.json` | 新增结构 | 已实施 |
| C31 | `workspace-video-pipeline/schemas/pipeline-result.schema.json` | 新增字段 | 已实施 |
| C20 | `workspace-video-pipeline/scripts/validate_pipeline.py` | 交叉校验 | 已实施 |
| C21 | `workspace-video-pipeline/AGENTS.md` | 文档 | 已实施 |
| C22 | 多处 | 字段传递 | 已实施 |
| C23 | `workspace-frame-designer/schemas/frame-design-output.schema.json` | 删字段 | 已实施 |
| C24 | 两份 H3 schema | 删字段 | 已实施 |
| C25 | `workspace-video-pipeline/scripts/validate_pipeline.py` | 新增校验 | 已实施 |
| C26 | `workspace-frame-designer/tests/test_validate_frame_design.py` | 跟随 | 已实施 |
| C27 | `workspace-video-pipeline/tests/` | 跟随 | 已实施 |
| C28 | `workspace-frame-designer/tests/test_plan_segments.py` | 新建 | 已实施 |

`validate_pipeline.py` 有 C3 / C16 / C20 / C25 四处改动，`shot-ir.schema.json` 有 C5 / C7 / C8 三处，`frame-design-output.schema.json` 有 C1 / C10 / C23 三处——同文件内**先改行号大的**。

---

## 批次 A：结构与字段

### C1 — frame-design segment 的 `shot_id` 改复数 **[已实施]**

**文件** `workspace-frame-designer/schemas/frame-design-output.schema.json`

**现状** `:78` required 列表含 `"shot_id"`；`:81` 定义 `"shot_id": { "$ref": "#/$defs/id" }`

**改法** required 中 `"shot_id"` 替换为 `"shot_ids", "shot_bindings"`，属性定义替换为：

```json
"shot_ids": {
  "type": "array", "minItems": 1, "uniqueItems": true,
  "items": { "$ref": "#/$defs/id" }
},
"shot_bindings": {
  "type": "array", "minItems": 1,
  "items": {
    "type": "object",
    "additionalProperties": false,
    "required": ["prompt_shot_index", "shot_id", "local_start"],
    "properties": {
      "prompt_shot_index": { "type": "integer", "minimum": 1 },
      "shot_id": { "$ref": "#/$defs/id" },
      "local_start": { "type": "integer", "minimum": 0 }
    }
  }
}
```

**理由** `shot_id` 是单数，一个 segment 只能归属一个 shot，装不下 2–3 个短 shot。这是唯一的硬阻塞。

`shot_bindings` 不是冗余：`shot_ids` 回答「这段包含哪些镜头」，`shot_bindings` 回答「提示词里第 N 个 `[Shot N]` 标记对应哪个镜头、在段内第几秒切入」。没有后者，C16 的剪辑点校验无法成立。`local_start` 等于 `全局 shot.start − segment.start`，首项恒为 0；用整数是因为 segment 的 `start`/`end`/`duration` 本就都是整数（`validate_frame_design.py:63` 的 `integer_timing`）。

**验收** 用一个含 3 个 shot 的 segment 样例过 schema 校验通过；旧的单数 `shot_id` 样例被拒绝。

---

### C2 — H3 package 同步改复数 **[已实施]**

**文件** `workspace-h3-compiler/schemas/h3-segment-package.schema.json`

**现状** `:102` required 含 `"shot_id"`；`:105` 定义单数 `shot_id`

**改法** 与 C1 完全相同的 `shot_ids` + `shot_bindings`。

**理由** 编译产物必须原样携带这两个字段，`h3-validator` 和确定性门才能拿它核对提示词内容。只在 frame-design 侧加不在 package 侧加，信息在编译这一步就丢了。

**验收** 同 C1。

---

### C29 — H3 draft prompts 同步改复数 **[已实施]**

**文件** `workspace-h3-compiler/schemas/h3-draft-prompts.schema.json`

**现状** `:119` required 含 `"shot_id"`；`:122` 定义 `"shot_id": { "$ref": "#/$defs/id" }`，位于 `$defs.draftPrompt`

**改法** 与 C1 完全相同的 `shot_ids` + `shot_bindings`。

**理由** 2026-09-05 新增的草稿分支引入了第三份带 `shot_id` 的 schema。漏掉它会造成两种后果：

1. 草稿路径的 DRAFT_COMPILE 门与可执行路径行为不一致，媒体未就绪时的产物仍是旧的单数结构；
2. `validate_draft_compile`（`validate_pipeline.py:322`）会把草稿变形后调用 `validate_unified_package`，而后者经 C3 改动后比对的是 `shot_ids` / `shot_bindings`——草稿 schema 不同步的话，这里会因字段缺失而恒定报错。

**验收** 一个含 3 个 shot 的草稿样例过 `draft_compile` 门通过。

---

### C3 — `validate_pipeline.py` 字段比对跟随改名 **[已实施]**

**文件** `workspace-video-pipeline/scripts/validate_pipeline.py:230`（在 `validate_unified_package` 内）

**现状**

```python
for field in ("shot_id", "start", "end"):
    if package.get(field) != segment.get(field):
```

**改法**

```python
for field in ("shot_ids", "shot_bindings", "start", "end"):
    if package.get(field) != segment.get(field):
```

**理由** 这段校验确保编译器没篡改 segment_plan 的归属和时间。字段改名后不跟着改，比对的就是两个都不存在的 `shot_id`（`None == None` 恒真），校验静默失效。Python 的 `!=` 对 list 和 dict 是深比较，无需改比对逻辑。

**额外收益**：`validate_unified_package` 被可执行路径（`validate_compile`）与草稿路径（`validate_draft_compile`）共用，**这一处改动同时覆盖两条路径**。

**验收** 构造一个 package 的 `shot_ids` 与 segment 不一致的用例，`compile` 与 `draft_compile` 两个门都必须报 `segment_mapping`。

---

### C4 — frame-designer 字段清单跟随 **[已实施]**

**文件** `workspace-frame-designer/AGENTS.md:58`

**现状** `- segment_id, shot_id, start, end;`

**改法** `- segment_id, shot_ids, shot_bindings, start, end;`

**理由** 这是写给 frame-designer 看的输出契约。不改，agent 会继续按单数字段输出，schema 校验直接失败。

**验收** 文件中不再出现单数 `shot_id`（`shot_bindings` 内部的 `shot_id` 子字段除外）。

---

### C5 — `segmentHint` 语义反转 **[已实施]**

**文件** `workspace-shot-director/schemas/shot-ir.schema.json`（`:67` 定义、`:107` required、`:135` 引用）

**现状** 每个 shot 有必填的 `segments` 数组，语义是「shot 内部应该怎么拆成生成段」。

**改法** 字段更名为 `split_hints`，`$defs` 中 `segmentHint` 更名为 `splitHint`。语义改为「此 shot 是否长到必须拆分，以及建议的拆分点」，并加约束：仅当 shot 时长 > 15 秒时允许非空，否则必须为空数组。

**理由** 现有语义有两个问题：（1）**职责错位**——切段依赖模型的 4–15 秒限制，是生产约束不是导演决策；（2）**视野不足**——目标设计要跨 shot 合并短镜头，需要看到整条时间线的时长分布，shot-director 逐个 shot 输出看不到全局，其建议对装箱无用甚至有害。

保留「长 shot 必须拆」这一半是有意义的：只有 shot-director 知道一个 20 秒长镜头内部哪里是动作阶段的自然分界（`action_phase`），在那里拆比在第 15 秒硬切要好。

**注意** `shots[].segments` **没有任何 Python 消费者**（已按当前快照复核），只被 schema 和 AGENTS.md 引用，更名不会牵动校验代码。

**验收** 全库搜索 `segmentHint` 与 `shots[].segments` 无残留（`.bak`、`.skill-backups` 除外）。

---

### C6 — shot-director 文档跟随 C5 **[已实施]**

**文件** `workspace-shot-director/AGENTS.md`

| 行 | 现状 | 改法 |
| --- | --- | --- |
| 23 | `identify optional internal segments inside one continuous shot when generation limits or action phases require them` | 改为：仅当 shot 超过 15 秒时标注建议拆分点 |
| 24 | `label shot and internal-segment boundaries` | 删除 internal-segment 部分 |
| 41 | `boundary_type=same_shot_continuation` 的定义 | 保留，但注明仅用于超长 shot 的内部拆分点 |
| 46 | `Every shot, and every item in segments when a shot is subdivided` | `segments` → `split_hints` |
| 55 | `A same-shot internal segment must preserve the parent shot ID and use a stable segment hint ID` | `segment hint` → `split hint` |
| 95 | 示例中的 `"segments": []` | → `"split_hints": []` |
| 106 | `shots and internal segments must be ordered, contiguous...` | 保留 shot 部分，internal segment 部分改为仅约束 `split_hints` |

**理由** 与 C5 是同一件事的两面。schema 改了而 AGENTS.md 没改，agent 会按旧描述输出，schema 校验失败。

**验收** 同 C5。

---

### C7 — `continuity_exit_state` 补结构 **[已实施]**

**文件** `workspace-shot-director/schemas/shot-ir.schema.json`（`:16` required、`:33` 定义）

**现状** `"continuity_exit_state": { "type": "object" }`——无任何字段约束，且下游无人读。

**改法**

```json
"continuity_exit_state": {
  "type": "object",
  "additionalProperties": false,
  "required": ["by_shot"],
  "properties": {
    "by_shot": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["shot_id", "staging", "wardrobe_state", "held_props", "scene_state", "lighting_state"],
        "properties": {
          "shot_id":        { "type": "string", "minLength": 1 },
          "staging":        { "type": "string", "minLength": 1 },
          "wardrobe_state": { "type": "string" },
          "held_props":     { "type": "array", "items": { "type": "string" } },
          "scene_state":    { "type": "string" },
          "lighting_state": { "type": "string" }
        }
      }
    }
  }
}
```

字段含义：`staging` = 人物在场景中的位置与朝向；`wardrobe_state` = 服装当前状态（袖子、外套、凌乱度）；`held_props` = 手持道具；`scene_state` = 场景中物体的状态；`lighting_state` = 光线与时间。

**理由** 见第 3 部分。这是跨剪辑点传递世界状态的**文字级**通道，成本低、不破坏静态媒体预生成流程，且可被 C13 校验。

**验收** `by_shot` 必须覆盖 `shots` 中的每一个 `shot_id`，缺一个则 schema 或 C13 报错。

---

### C8 — shot 新增 `boundary_risk` 与 `composition_control` **[已实施]**

**文件** `workspace-shot-director/schemas/shot-ir.schema.json`，`$defs.shot`

**改法** 在 shot 的 required 与 properties 中新增：

```json
"boundary_risk": {
  "type": "object",
  "additionalProperties": false,
  "required": ["state_transfer_load", "reason"],
  "properties": {
    "state_transfer_load": { "type": "integer", "minimum": 0, "maximum": 10 },
    "reason": { "type": "string", "minLength": 1 }
  }
},
"composition_control": { "enum": ["critical", "normal", "free"] }
```

`boundary_risk` 描述**此 shot 与前一个 shot 之间那个切点**跨段时需要传递多少世界状态；第一个 shot 的 `state_transfer_load` 恒为 0。`composition_control` 描述 shot 自身是否需要精确构图控制。

**理由** 见 2.5。二值标签编码不了风险量级，DP 的代价函数需要模型给的评分作为输入。

**验收** C11 能从 Shot IR 读到这两个字段并影响切分结果；缺字段时 C11 应报错而非静默用默认值。

---

### C9 — shot-director 输出说明补充 **[已实施]**

**文件** `workspace-shot-director/AGENTS.md`

**改法** 新增两段说明：

1. **退出状态**（C7）：每个 shot 结束时的世界状态快照，逐 shot 输出，覆盖 `shots` 中每一个 ID。
2. **两项评分**（C8），含评分锚点：

```text
state_transfer_load 评分锚点：
  0    空镜，或场景/地点切换（世界状态本就重置）
  2-3  单人同场景换机位，无手持道具
  5    单人同场景，有手持道具或动作正在进行
  8+   多人对话，各自有手持道具、视线关系需保持

composition_control：
  critical  关键情绪特写、复杂调度、有硬性视觉要求 —— 必须精确控制构图
  normal    常规叙事镜头
  free      过渡、反应镜头、空镜 —— 构图可由模型自由发挥
```

**理由** `state_transfer_load` 是主观分，模型给分会漂。锚点缓解但不根除——不过这比现状好：现在这个判断根本不存在，代价对所有同场景 cut 一视同仁，连漂都谈不上。

**验收** 文档中包含上述锚点表。

---

### C10 — `imageJob` 新增 `input_media_ids` **[已实施]**

**文件** `workspace-frame-designer/schemas/frame-design-output.schema.json`，`$defs.imageJob`

**现状** `imageJob` 有 `additionalProperties: false` 且无任何输入图片字段，是纯文生图。

**改法**

1. 新增可选属性 `"input_media_ids": { "type": "array", "items": { "$ref": "#/$defs/id" }, "uniqueItems": true }`（有序，语义为参考输入）
2. `imageJob.status` 的 enum 增加 `"runtime_pending"`

**理由** 见 3.3、3.4。两个用途，**静态用途优先落地**：

- **静态（本批次必做）**：`first_frame` 角色的 image job 必须把对应的 `character_reference` 媒体列入 `input_media_ids`，否则首帧图和角色参考图是两张不同的脸。
- **运行时（建议推迟）**：以上一段的 `actual_tail_frame` 为输入生成新首帧图，此时该 job 的 `status` 为 `runtime_pending`。代价见 3.3。

**与现有 MEDIA 门的关系**：`validate_media`（`validate_pipeline.py:195`）已经会检查 `resolved` 媒体的文件可读性。`input_media_ids` 引入的是**媒体之间的生成依赖**，MEDIA 门管不到——需要 C13 第 6 条补上。

**验收** 一个 `first_frame` job 引用了 `character_reference` 媒体 ID 时 schema 通过；C13 会进一步强制这一点。

---

## 批次 B：装箱与校验

### C11 — 新建 `plan_segments.py` **[已实施]**

**文件** `workspace-frame-designer/scripts/plan_segments.py`（新建）

**现状** 不存在。段边界目前由 frame-designer 这个 LLM 自行决定，无任何算法约束。

**改法** 输入 Shot IR，输出 `segment_plan` 的时间骨架（`start` / `end` / `shot_ids` / `shot_bindings` / `entry_strategy` / `previous_segment_id`）。一维分段 DP：

```text
候选边界集 B = {0} ∪ {所有 shot 切点} ∪ {超长 shot 内部的 1 秒粒度点} ∪ {T}

f(0) = 0
f(t) = min over s ∈ B, 4 ≤ t−s ≤ 15, 段内 shot 数 ≤ 3:
         f(s) + cost(s)
      约束：composition_control = "critical" 的 shot 必须是段首或独占一段

cost(s) = base(s) + state_transfer_load(s) × 3

base(s) = 0    scene_continuity ∈ {scene_change, location_change}
        = 1    scene_continuity = time_change
        = 5    same_scene 且 action_continuity = discontinuous
        = 25   same_scene 且 action_continuity = continuous
        = 50   s 是 shot 内部点
```

回溯路径即段边界。边界落在 shot 切点 → `entry_strategy = new_first_frame`；落在 shot 内部 → `use_previous_tail_frame`。

CLI 形态与 `validate_frame_design.py` 保持一致：位置参数为 Shot IR 路径，stdout 输出 JSON，异常时非零退出码。

**理由** 见 2.5。

**为什么 base 里同场景连贯 cut 是 25 而不是 3**：见 2.3。同场景、动作连贯的 cut（正反打）是最不该当段边界的位置，应被打包进同一段内部。25 与 50 的关系保证：宁可在正反打处断，也不切进镜头中间；但只要能把整组正反打包进一段（≤15 秒、≤3 shot），DP 就会那么做。

**成本** T 通常几十到几百秒，1 秒粒度下候选点 O(300)，DP 为 O(n²) ≈ 9 万次转移，瞬时完成。约 50 行。

**输入依赖** `scene_continuity` 与 `action_continuity` 已是 `continuityLabels` 必填字段；`boundary_risk` / `composition_control` 来自 C8。

**验收**（见 C28 的用例）

1. 三个 4 秒短 shot 且切点均为 `scene_change` → 应合并为一段 12 秒，`shot_ids` 长度 3
2. 一个 20 秒 shot → 应拆为两段且均在 4–15 秒内
3. 2 秒短 shot 夹在两个 20 秒长 shot 之间 → 不得产生 <4 秒的段
4. 同一输入跑两次，输出逐字节一致
5. 某 shot 的 `composition_control = critical` → 该 shot 必为某段的首个 shot

---

### C12 — frame-designer 职责改写 **[已实施]**

**文件** `workspace-frame-designer/AGENTS.md`

**改法** 四处：

1. **流程约束**：段边界必须来自 `scripts/plan_segments.py` 的输出，不得自行拟定。创作职责从「划分段落」改为「为已定的段落做媒体与提示词设计」。
2. **删除重复判断**：Anchor Frame Rules 第 1–4 条现在用自然语言重新判断 shot 边界（见 4.1），改为**直接读取 Shot IR 的 `continuityLabels`**，不再自行判断。第 5–8 条（媒体记录如何填写）保留。
3. **新增打包权衡规则**（见 2.6）：首帧图只锚定段内第一个 shot，段内后续 shot 由模型自由发挥，无法控制构图、机位、人物位置。`composition_control = critical` 的 shot 应作为段首或独占一段。`last_frame_target` 只能钉住整段最后一帧。
4. **新增连续性传递规则**（见 3.3、3.4）：首帧图的 image prompt 必须逐字包含上一个 shot 的 `continuity_exit_state` 全部条目；`first_frame` 的 image job 必须把对应 `character_reference` 媒体列入 `input_media_ids`。

**理由** 脚本写了但 AGENTS.md 不改，agent 不会去调用它，等于白写。分工边界需写明：段边界的**搜索**归脚本，切点风险的**评估**归 shot-director，frame-designer 两者都不做。

第 2 项是修复 4.1 的断链——让下游读上游已经做过的判断，而不是重做一遍。

**验收** 文档中不再出现要求 frame-designer 自行判断 shot / framing / scene 变化的表述。

---

### C13 — `validate_frame_design.py` 新增校验组 **[已实施]**

**文件** `workspace-frame-designer/scripts/validate_frame_design.py`

**现状** `validate()` 对 shot 的校验只有 `:158-161` 一条，即末段结束时间等于总时长。

**改法** 新增六组检查：

1. **`shot_ids` 覆盖**：每段的 `shot_ids` 必须在 Shot IR 中真实存在，按时间有序，其区间并集精确等于 `[segment.start, segment.end)`——无重叠、无遗漏、无越界
2. **`shot_bindings` 一致性**：与 `shot_ids` 一一对应且同序；`prompt_shot_index` 从 1 连续递增；`local_start == 全局 shot.start − segment.start`；首项 `local_start == 0`
3. **段内 shot 数上限**：`len(shot_ids) ≤ 3`
4. **参考图预算**：`reference_strategy` 五类 ID 去重后总数 ≤ 4
5. **退出状态覆盖**：`entry_strategy = new_first_frame` 的段，其首帧 image job 的 prompt 必须包含**上一个 shot** 的 `continuity_exit_state` 各条目（`staging` / `wardrobe_state` / `held_props` / `scene_state` / `lighting_state`）的内容。**例外**：全片第一个段没有上一个 shot，跳过此检查；若该段所含首个 shot 的 `scene_continuity ∈ {scene_change, location_change}`，世界状态本就重置，同样跳过
6. **`input_media_ids` 解析**：其指向的媒体必须存在于 manifest；若该媒体为 `actual_tail_frame`，则该 image job 的 `status` 必须为 `runtime_pending`，否则必须为已解析的静态媒体

**理由**

第 1 条堵的是一个真实缺口：目前 `segment.shot_id` 完全没有被约束回 Shot IR，可以填一个根本不存在的值而全绿通过。新设计下段可以跨 shot，危害更大——一段声称包含 shot 3/4/5，实际区间却只覆盖 3/4，编译器会照着写三个 `[Shot N]`，多出来的内容凭空捏造。

第 2 条是 C16 的前提：剪辑时间戳要能被校验，先得保证 `shot_bindings` 本身可信。

第 3、4 条把 2.6 的权衡落成硬约束。上限不写进校验就只是一句会被忽略的建议——参考图堆到七八张时模型遵循度明显下降，而这个退化是渐进的、不报错的，只能靠硬上限拦。

第 5、6 条落实第 3 部分的两层兜底。

**验收** 六条各有一个反例用例被拒绝（见 C26）。

---

### C14 — `continuity_decision` 与 `continuityLabels` 一致性校验 **[已实施]**

**文件** `workspace-frame-designer/scripts/validate_frame_design.py`

**改法** 新增检查：当段边界落在 shot 切点上时，该段 `continuity_decision` 的 `is_same_shot` / `same_scene` / `same_framing` / `same_camera_position` 必须与 Shot IR 中对应切点的 `continuityLabels`（`boundary_type` / `scene_continuity` / `framing_continuity` / `camera_continuity`）语义一致。

**理由** 见 4.1。两套判断并存且互不校验，打架时无人发现。C12 让 frame-designer 直接读 `continuityLabels` 是治本，这条校验是兜底。

**验收** 构造一个 `continuityLabels` 说 `scene_change` 而 `continuity_decision.same_scene = true` 的用例，必须报错。

---

## 批次 C：提示词

### C15 — SKILL.md 新增段内多 shot 编排规则 **[已实施]**

**文件** `workspace-h3-compiler/skills/h3-prompt-writing/SKILL.md`

**现状** Procedure 第 4–8 条只规定了段**开头**怎么写（首帧锚定句、续接句、参考图绑定句），完全没有涉及段内出现多个 shot 的情况。

**改法** 新增一条规则：

- 段内每个 shot 对应一个 `[Shot N]` 标记，`N` 为段内局部编号，从 1 连续递增，取自 `shot_bindings.prompt_shot_index`
- 第 2 个及之后的 `[Shot N]` 必须以 `At MM:SS.mmm, the camera cuts to` 开头，时间取自 `shot_bindings.local_start`，格式化为两位分、两位秒、三位毫秒
- 段内 shot 数必须等于 `len(shot_bindings)`，不得增删

同时更新 SKILL.md 的「Output Contract」示例（2026-09-05 新增的那段 JSON 样例），把 `"shot_id": "S01"` 换成 `shot_ids` + `shot_bindings` 的形态，并在示例的 prompt 字段里体现多个 `[Shot N]`。

**理由** 目前编译器在段内多 shot 这件事上无规则可循，既可能把三个 shot 揉成一段连续描述（丢失剪辑，成片变成怪异的长镜头），也可能自行添加 Shot IR 里不存在的剪辑（凭空多出镜头）。两种都是静默失败。

格式必须写死是因为 C16 要用正则精确比对，措辞浮动就没法校验。

**验收** 文档中给出了一个包含 3 个 `[Shot N]` 的完整段内示例，且 Output Contract 示例与 C2 后的 schema 一致。

---

### C30 — SKILL.md 补充草稿模式的对应说明 **[已实施]**

**文件** `workspace-h3-compiler/skills/h3-prompt-writing/SKILL.md`

**现状** SKILL.md 只描述可执行模式（`unified_controls` / `media_mapping` / `schema_version=1.3`），完全没有提到 2026-09-05 新增的草稿模式。而 orchestrator 的 AGENTS.md 已经在 Stage Contracts 里要求「call `h3-compiler` with `compile_mode=draft`」。

**改法** 新增一节说明草稿模式：

- 触发条件：orchestrator 传入 `compile_mode=draft`（媒体未就绪时）
- 输出 schema 为 `../../schemas/h3-draft-prompts.schema.json`，`schema_version=1.0`，`status=draft`
- 字段对应：`planned_controls` ↔ `unified_controls`（`entry_source` 多一个 `planned_first_frame`）、`symbolic_media_mapping` ↔ `media_mapping`（`entry_frame_source_type` 多一个 `planned_media`，且必填 `unresolved_media_ids`）
- 顶层多一个 `pending_media_ids`，必须等于 manifest 中所有非 `actual_tail_frame` 的未解析媒体 ID，且**保持 manifest 顺序**
- **C15 的段内多 shot 规则同样适用于草稿模式**，`shot_ids` / `shot_bindings` 的填写方式完全相同

**理由** 草稿模式是 2026-09-05 新增的分支，但编译器的 skill 文档从未提及它——agent 只能靠 orchestrator 的调用参数临场推断输出结构。`validate_draft_compile` 对 `pending_media_ids` 和 `unresolved_media_ids` 的要求相当严格（必须等于特定的过滤结果且保持顺序），靠猜很难一次对。

这条与本方案的段落装箱改造没有直接依赖，但既然要动 SKILL.md，一并补上成本很低。**若判断为超出本次范围，可单独拆出执行，不影响其他条目。**

**验收** 文档中有草稿模式一节，且字段对应表完整。

---

### C16 — 剪辑点校验升级 **[已实施]**

**文件** `workspace-video-pipeline/scripts/validate_pipeline.py:294-297`（在 `validate_unified_package` 内）

**现状**

```python
for minute, second, millisecond in TIMESTAMP_PATTERN.findall(prompt):
    timestamp = int(minute) * 60 + int(second) + int(millisecond) / 1000
    if timestamp >= duration:
        errors.append(error("TIMELINE", "timestamp_range", ...))
```

只检查时间戳小于本段时长。

**改法** 与 `shot_bindings` 精确比对：

- 提示词中 `[Shot N]` 标记的数量 == `len(shot_bindings)`，编号从 1 连续递增
- 第 k 个 `At MM:SS.mmm` 解析出的秒数 == `shot_bindings[k].local_start`
- 保留原有的 `timestamp < local_duration` 检查作为兜底

**理由** 现有检查形同虚设——只要不写出「第 30 秒切一刀」这种荒谬值就能通过，对「该切几刀、切在哪」一无所知。C15 定的规则若无对应校验，就只是一段模型可能遵守也可能不遵守的自然语言说明。

这条落地后，「提示词里的剪辑点必须对应真实 shot 边界」从软约束变成确定性不变量。

**额外收益**：与 C3 同理，`validate_unified_package` 被 `validate_compile` 与 `validate_draft_compile` 共用，**这一处改动同时覆盖草稿与可执行两条路径**，不需要在 `validate_draft_compile` 里重复实现。

**验收** 构造 `[Shot N]` 数量与 `shot_bindings` 不符、以及时间戳与 `local_start` 不符的用例，`compile` 与 `draft_compile` 两个门都必须报错。

---

### C17 — h3-validator 语义审核补一项 **[已实施]**

**文件** `workspace-h3-validator/AGENTS.md`，Review Rules 段落

**改法** 新增一条：确认段内每个 `[Shot N]` 的画面内容确实对应 Shot IR 中该 shot 的 `framing` / `angle` / `subject_action` / `dramatic_purpose`，而非编译器自行编造或张冠李戴。

**理由** C16 只能验证剪辑点的**数量和位置**，验证不了**内容**——提示词可以在正确的时间点切换，却把 shot 4 的内容写成了 shot 5 的。这类语义漂移正是 h3-validator 存在的意义。

**验收** Review Rules 中新增该条。

---

### C18 — 删除 legacy 参考文档 **[已实施]**

2026-09-05 的线上修复已执行：`h3-prompt-writing/references/`（含 `base-en.txt`、`ref-en.txt`）已整体移入 `workspace-h3-compiler/.skill-backups/20260905-unified-cleanup/`；`minimax-h3-prompting` 的 `references/`、`docs/`、`scripts/`、`tests/`、`README*` 同样移入 `workspace-h3-validator/.skill-backups/20260905-unified-cleanup/`。

**无需再做。** 保留条目用于说明：`validate_pipeline.py:277` 的 `LEGACY_MARKERS` 检查会拒绝 legacy 语法，而那些文档描述的正是被拒绝的写法，留在 skill 目录里有被检索到的风险。

**注意** 归档目录里的 `.py` 文件（`validate_h3_prompt.py`、`_h3_validation_rules.py`）已不再是活跃校验器。若后续需要恢复其中的检查逻辑，应移植进 `validate_pipeline.py`，而不是把目录移回去。

---

## 批次 D：输出契约

这批解决第 4.3、4.4 节的问题。2026-09-05 的修复已经建立了 result 门的骨架，本批补齐成功路径与交叉校验。

### C19 — 给 `COMPLETE` 分支的 `result` 补 schema **[已实施]**

**文件** `workspace-video-pipeline/schemas/pipeline-result.schema.json`

**已完成部分** `MEDIA_WAIT` 分支已有结构约束（`required: ["draft_video_prompts", "image_jobs"]`，配套 `$defs.draftPromptResult` 与 `$defs.imageJobResult`）。

**剩余工作** `COMPLETE` 分支的 `result` 仍是 `{ "type": "object" }`，无字段约束。新增 `$defs.successResult` 并在该分支引用：

```json
"successResult": {
  "type": "object",
  "additionalProperties": false,
  "required": ["total_duration", "aspect_ratio", "visual_style", "packages",
               "resolved_media", "execution_order", "tail_capture_spec", "technical_warnings"],
  "properties": {
    "total_duration": { "type": "integer", "minimum": 1 },
    "aspect_ratio":   { "type": ["string", "null"] },
    "visual_style":   { "type": "object" },
    "packages":       { "type": "array", "minItems": 1, "items": { "type": "object" } },
    "resolved_media": {
      "type": "array", "minItems": 1,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["media_id", "role", "status", "location"],
        "properties": {
          "media_id": { "type": "string", "minLength": 1 },
          "role":     { "type": "string", "minLength": 1 },
          "status":   { "enum": ["resolved", "runtime_pending"] },
          "location": { "type": ["string", "null"] }
        }
      }
    },
    "execution_order": {
      "type": "array", "minItems": 1,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["order", "segment_id", "depends_on"],
        "properties": {
          "order":      { "type": "integer", "minimum": 1 },
          "segment_id": { "type": "string", "minLength": 1 },
          "depends_on": { "type": ["string", "null"] }
        }
      }
    },
    "tail_capture_spec": {
      "type": "object",
      "additionalProperties": false,
      "required": ["frame_selection", "format", "naming"],
      "properties": {
        "frame_selection": { "const": "last_complete_frame" },
        "format":          { "const": "png" },
        "naming":          { "const": "{segment_id}_tail.png" }
      }
    },
    "technical_warnings": { "type": "array", "items": { "type": "object" } }
  }
}
```

**理由** 见 4.3、4.4。`resolved_media` 补的是 4.4 第 1 项，最硬的缺口——新增的 MEDIA 门保证了 manifest 里的路径可读，但没有任何机制把这些路径带进最终输出，拿到成功结果仍不知道该喂哪个文件给 H3。`location` 允许为 null 是为了容纳 `runtime_pending` 的尾帧。

`tail_capture_spec` 用三个 const 把 4.4 第 5 项的操作定义写死：取渲染视频的最后一个完整帧、PNG 无损、命名 `{segment_id}_tail.png`。用 const 而非自由字符串，是因为这是全局约定而非每次可变的参数。

**不包含模型参数**（4.4 第 4 项：分辨率、帧率、seed）。这些取决于调用方实际使用的 H3 接入方式，本方案不替其决定。

**验收** 一个缺 `resolved_media` 的 `COMPLETE` 结果被 schema 拒绝；现有的 `MEDIA_WAIT` 用例不受影响。

---

### C31 — `MEDIA_WAIT` 的草稿结果携带 `shot_bindings` **[已实施]**

**文件** `workspace-video-pipeline/schemas/pipeline-result.schema.json`，`$defs.draftPromptResult`

**现状**

```json
"draftPromptResult": {
  "required": ["segment_id", "prompt", "symbolic_media_mapping"],
  ...
}
```

**改法** required 增加 `"shot_bindings"`，properties 增加与 C1 相同的 `shot_bindings` 定义。

**理由** `MEDIA_WAIT` 是用户实际会拿到手的产物之一——他们据此去生成图片，并预览提示词。段内含多个 shot 时，若结果里没有 `shot_bindings`，用户无法核对提示词里的 `[Shot N]` 分别对应哪个镜头，草稿的可检查性打折。

`draftPromptResult` 是 `pipeline-result` 自己的精简定义（不是引用 draft schema），所以 C29 改了 draft schema 不会自动传导到这里，必须单独改。

**验收** 一个含 3 个 shot 的草稿结果，其 `draft_video_prompts[].shot_bindings` 长度为 3 且过 result 门。

---

### C20 — `result` 门补交叉校验 **[已实施]**

**文件** `workspace-video-pipeline/scripts/validate_pipeline.py:415`

**已完成部分** `result` 子命令已存在，`validate_result` 已接入 `main()`。

**剩余工作** 当前 `validate_result` 只有一行 `return schema_errors("result", value)`，没有任何交叉校验。改为接收额外上下文并校验：

```text
python3 scripts/validate_pipeline.py result --artifact RESULT.json --packages PACKAGES.json --frame FRAME.json --shot SHOT.json
```

1. `result.packages` 与 `PACKAGES.json` 的 `packages` 逐字段一致
2. `result.resolved_media` 覆盖所有 package 的 `media_mapping` 引用到的每个 media ID，无遗漏
3. 所有 `status = resolved` 的媒体，其 `location` 非 null
4. `result.total_duration` == Shot IR 的 `duration`
5. `result.aspect_ratio` / `visual_style` == Shot IR 对应字段
6. `execution_order` 是 `packages` 的一个拓扑序，且 `depends_on` 与 `runtime_entry_binding.previous_segment_id` 一致

**兼容性要求**：三个新参数必须是可选的。`MEDIA_WAIT` / `BLOCKED` / `FAILED` 路径不带 packages，此时跳过 1–3、6，只做 schema 校验与 4、5（若 shot 可用）。orchestrator 现有的「写入 `.pipeline-runtime/final-result.json` 后跑 `result --artifact` 单参数形式」不能被破坏。

**理由** schema 只能约束形状，交叉一致性必须靠代码。第 2 条尤其关键——它是「拿到输出就能跑」这个目标的唯一保证。

**验收** 六条各有一个反例被拒绝；不带可选参数调用时行为与现在一致。

---

### C21 — orchestrator 文档更新 **[已实施]**

**文件** `workspace-video-pipeline/AGENTS.md`

**已完成部分** Deterministic Gates 的命令清单已含 `media` / `draft_compile` / `result` 三个门与 `--deterministic-report` 参数；Final Response 已要求先写 `.pipeline-runtime/final-result.json` 再跑 result 门；State Machine 已含 `DRAFT_COMPILE_*` 状态。

**剩余工作** 两处：

1. **Deterministic Gates**：`result` 门的命令改为带上 C20 的可选参数：

   ```text
   python3 scripts/validate_pipeline.py result --artifact PIPELINE_RESULT.json --packages PACKAGES.json --frame FRAME.json --shot SHOT.json
   ```

   并说明 `MEDIA_WAIT` 等路径可省略这些参数。

2. **Media Resolution**：补两条

   - 静态媒体解析顺序：`character_reference` / `location_reference` / `style_reference` 必须先于依赖它们的 `first_frame` 解析（见 3.4）
   - 尾帧截取规格：取渲染视频的最后一个完整帧，PNG 无损，命名 `{segment_id}_tail.png`（与 C19 的 `tail_capture_spec` 一致）

3. **Final Response**：`COMPLETE` 的散文描述替换为对 `$defs.successResult` 必填字段的引用。

**理由** C19/C20 扩展了契约，orchestrator 的指令必须跟上，否则它不会传新参数，也不会按新结构组装成功路径的 result。

**验收** 文档中 `result` 门的命令带上了交叉校验参数，Media Resolution 有解析顺序与尾帧规格两条。

---

### C22 — `aspect_ratio` / `visual_style` 传递链 **[已实施]**

**文件** 多处

**现状** 两者只存在于 Shot IR 顶层，`validate_pipeline.py` 不读，下游 AGENTS.md 不提，package 与 draft 里都没有，`COMPLETE` 的 result 不保证带——传到 Shot IR 就断了。

**改法** 由 C19 的 `successResult` 承接（已含这两个必填字段），由 C20 第 5 条校验其等于 Shot IR 的对应值。

**不做**的选择：不把它们下放到每个 package 或每条 draft prompt。它们是全片级属性，逐段重复既冗余又制造不一致的机会。

**理由** 见 4.4 第 2、3 项。

**验收** 包含在 C20 第 5 条中。

---

## 批次 E：清理

**前置条件：批次 A–D 全部完成并通过测试后再执行本批。** 删字段是不可逆操作，必须确认没有新增代码依赖它们。

### C23 — 删除 frame-design 冗余字段 **[已实施]**

**文件** `workspace-frame-designer/schemas/frame-design-output.schema.json` 及 `workspace-frame-designer/AGENTS.md` 中对应的填写要求

**删除**：`entity_bindings`、`use_for`、`generate_first_frame`、`generate_last_frame_target`、`capture_actual_tail_frame`、`character_ids`、`location_ids`、`extraction_status`、`capture_time`、`source_video_media_id`、`source_id`、`supports_mixed_keyframes_and_references`

**保留**（已按当前快照复核，不再属于死字段）：`runtime_handle`——2026-09-05 新增的 `validate_media`（`validate_pipeline.py:195`）读取它作为非本地资产的替代路径。

**理由** 见 4.2。这些字段 AGENTS.md 明确要求必填、schema 强制 required，但管道内外都无人读取。每一个都在消耗 LLM 的输出预算并增加出错面。三个 `generate_*` 布尔尤其典型——校验器只读 `first_frame_media_id` 等 ID 字段，从不看布尔，两者矛盾时以 ID 为准且无人报警。

**执行前必须确认**：C13 新增的六组校验没有用到上述任何字段。若用到了，从删除清单中移除该字段并在实施报告中说明。

**验收** 删除后整套测试仍通过。

---

### C24 — 删除两份 H3 schema 的 `resolution_stage` **[已实施]**

**文件**

- `workspace-h3-compiler/schemas/h3-segment-package.schema.json`，`$defs.runtimeEntryBinding`
- `workspace-h3-compiler/schemas/h3-draft-prompts.schema.json`，`$defs.runtimeEntryBinding`

**删除** 两处的 `resolution_stage`（`const: "unified_video_runtime"`）

**理由** 永远同一个值，两份 schema 里都无人读取，纯占位。`kind: "previous_actual_tail_frame"` 已经表达了同样的信息。

**注意** 草稿 schema 是 2026-09-05 新增的，它照抄了 package 的 `runtimeEntryBinding` 定义，因此把这个冗余字段也复制了一份。两处必须一起删，否则两条路径的绑定结构不一致。

**验收** 删除后整套测试仍通过，`compile` 与 `draft_compile` 两个门均正常。

---

### C25 — `do_not_copy` 落到校验 **[已实施]**

**文件** `workspace-video-pipeline/scripts/validate_pipeline.py`，`validate_unified_package` 内

**现状** 校验了 `reference_bindings` 的 `preserve` / `label` / `role` 绑定关系，但从不检查 `do_not_copy` 的内容是否真的出现在 prompt 里。

**改法** 二选一：

- **A（推荐）**：新增校验——`role = character_reference` 的绑定，其 prompt 中必须出现约束该参考图不要复制 `do_not_copy` 所列项的表述
- **B**：若判定 A 的措辞难以稳定匹配，则在两份 H3 schema 中把 `do_not_copy` 标注为「编译期输入备忘，不参与产物校验」，并在 SKILL.md 中说明

**理由** 见 4.2。这是 H3 package 里唯一一个「有意义但完全不被验证」的字段。参考图污染构图和背景是实际会发生的问题，值得有一道检查；但若措辞无法稳定匹配，明确降级为备忘也比现在的暧昧状态好。

选 A 时同样自动覆盖草稿路径（`validate_unified_package` 共用）。

**验收** 选 A 则有反例用例被拒绝；选 B 则文档中有明确说明。

---

## 批次 F：测试

**每批次完成后同步进行，不要留到最后。** 当前基线：18 passed。

### C26 — `test_validate_frame_design.py` **[已实施]**

**文件** `workspace-frame-designer/tests/test_validate_frame_design.py`

**现状** `:57-58` 两个 segment 夹具使用单数 `"shot_id": "S01"`

**改法**

1. 夹具全部替换为 `shot_ids` + `shot_bindings`
2. 为 C13 的六组校验各补一个正例、一个反例
3. 为 C14 补一个不一致反例

**理由** C1 落地后现有用例会因缺少 required 字段全线报错。C13/C14 新增的校验若无用例等于没验证过——尤其第 1 条（`shot_ids` 覆盖）和第 5 条（退出状态覆盖），它们的正确性直接决定新设计是否真被约束住。

---

### C27 — `test_validate_pipeline.py` 与测试夹具 **[已实施]**

**文件**

- `workspace-video-pipeline/tests/test_validate_pipeline.py`：`:46`、`:96`、`:117`、`:122` 使用单数 `shot_id`
- `workspace-video-pipeline/tests/fixtures/frame.json:6`
- `workspace-video-pipeline/tests/fixtures/compiler-glm-output.json:6`

**改法**

1. 上述五处夹具全部替换为 `shot_ids` + `shot_bindings`
2. 为 C16 补正反例（`[Shot N]` 数量不符、时间戳与 `local_start` 不符），且**必须同时覆盖 `compile` 与 `draft_compile` 两个门**
3. 为 C20 的六条交叉校验各补一个反例，并补一个「不带可选参数调用」的兼容性用例
4. 为 C31 补一个含多 shot 的 `MEDIA_WAIT` 结果用例
5. 若 C25 选 A，补一个 `do_not_copy` 反例

**注意** `tests/fixtures/` 是 2026-09-05 新增的目录，之前的方案没有覆盖它。`compiler-glm-output.json` 是编译器真实输出的样例，改动时保持其余字段原样，只替换 `shot_id`。

---

### C28 — 新建 `test_plan_segments.py` **[已实施]**

**文件** `workspace-frame-designer/tests/test_plan_segments.py`（新建）

**改法** 覆盖 C11 验收标准的五条：短 shot 合并、长 shot 拆分、短 shot 夹在长 shot 之间、可复现性（同输入两次输出逐字节一致）、`composition_control = critical` 约束。

---

# 第 6 部分：明确不改的部分

列出来是为了防止改动扩散。**以下内容即使看起来可以顺手优化，本次也不要动。**

### 6.1 `validate_frame_design.py:109-111` 的八项连续性检查

```python
required_true = ("is_same_shot", "continuous_action", "continuous_camera", "same_scene",
                 "same_framing", "same_camera_position", "same_time", "same_visual_focus")
```

**保持原样。** 这组检查只在 `entry_strategy == "use_previous_tail_frame"` 时触发，而在新设计下该分支恰好只对应「长 shot 被迫拆分」这唯一场景——此时要求八项全 true 语义完全正确。段边界落在剪辑点时走 `new_first_frame` 分支，这组检查根本不触发。

如 2.4 所述，这套机制本来就是对的，需要改变的只是哪条路径是常态。

### 6.2 `validate_pipeline.py:317` 总时长覆盖校验

无论怎么装箱，段序列覆盖完整时间线这一点不变。C13 第 1 条新增的是更细粒度的逐段覆盖校验，与这条是包含关系，不冲突。

### 6.3 `continuityLabels` 的六个字段定义

**字段定义保持原样**，其中 `scene_continuity` 与 `action_continuity` 正是 C11 代价函数的输入，`boundary_type` 用于区分真实剪辑点与超长 shot 的内部拆分点。只有 shot-director 何时填 `same_shot_continuation` 的**说明**需要收窄（C6 第 41 行）。

### 6.4 4–15 秒段长限制

这是 MiniMax H3 的模型限制，不是设计选择。

### 6.5 Unified 三段式提示词结构

`integrated_multimodal_description:` / `overall_soundscape:` / `non_diegetic_music:` 三段及其顺序、以及禁用 legacy 前导句的规则全部保留。理由见 2.7。

### 6.6 `story-analyst` 的全部内容

本次设计调整完全发生在 shot 与 segment 之间，剧本结构化这一层未受影响。

**注意**：4.2 列出的 Story IR 死字段（现为 `category`、`locked_constraints`、`subject_id`）**本次不处理**。2026-09-05 修改后的 `validate_output.py` 已经读取 `continuity_constraints`、`ambiguities`、`marker_id`、`transition_markers`，这四项不再是死字段。剩下三个数量少、风险低，且 `locked_constraints` 与锁定约束的传递有潜在关联，留待观察。

### 6.7 `workspace-attestations`

空目录，用途未知，不动。

### 6.8 2026-09-05 修复引入的机制

以下均为本方案的**依赖**而非改造对象，不要回退或重构：

- **draft compile 分支**（`validate_draft_compile`、`h3-draft-prompts.schema.json`、`DRAFT_COMPILE_*` 状态）。本方案只在其上追加 `shot_ids` / `shot_bindings`（C29）与文档说明（C30）。
- **`validate_draft_compile` 复用 `validate_unified_package` 的手法**。C3、C16、C25 都依赖这一点来同时覆盖两条路径；若把它改成两套独立实现，这三个条目的工作量会翻倍。
- **MEDIA 门的文件可读性检查**（`validate_media`）。
- **VALIDATION 门的报告新鲜度校验**（`--deterministic-report` 及三项核对）。
- **输出格式约束**（裸 JSON、首字符 `{`、末字符 `}`、禁止 markdown 代码块）与 `.pipeline-runtime/final-result.json` 的先验证后返回流程。

### 6.9 `outputs/2026-09-05-elevator-kitchen-retest/`

一次真实运行的留档，产生于 2026-09-05 修复**之前**，其 `final-result.json` 用当前 result 门跑会 FAIL。**不要拿它当契约样例，也不要为了让它通过而回退 schema。** 需要真实样例时，用当前代码重新跑一次。

---

# 第 7 部分：待决与风险

### 7.1 `state_transfer_load` 的评分漂移

0–10 的主观分，模型给分会漂。C9 的锚点缓解但不根除。

**观察指标**：同一份剧本跑两次 shot-director，比较两次评分的差异；若某切点的评分差 ≥3，说明锚点不够具体，需要补充更多示例。

### 7.2 C11 的代价常数需要按实际内容标定

`base` 表里的 0 / 1 / 5 / 25 / 50 和 `state_transfer_load × 3` 的权重 3，都是基于推理而非实测。

**建议**：先按本文档的值实现，跑通 2–3 个真实剧本后，检查切分结果是否符合直觉，再调整。调整时优先动权重 3 而不是 base 表——base 表的相对次序是有依据的（见 2.3），权重才是标定项。

### 7.3 C10 运行时部分的启用时机

以尾帧为输入生成新首帧图会把链路变成完全串行，代价实打实。

**建议**：批次 A–D 跑通后，先统计实际剧本里 `base = 25` 的高风险边界有多少个、其中多少被 DP 成功打包消化。若剩余数量很少（比如全片 1–2 处），手工处理即可，不必启用运行时链路。

### 7.4 首帧图与实际生成画面的一致性无人保证

编译器写 prompt 时**看不到首帧图**——它的输入门是 Shot IR + segment_plan + media_manifest，不含 `frame_plan` 和 `image_jobs`。所以「以输入首帧作为视频的准确起始画面」这句话是在不知道首帧长什么样的情况下写的，依赖首帧图与 Shot IR 描述本来就一致。

本次不处理。若后续发现问题，方向是把 `image_jobs` 中对应的首帧 prompt 一并传给编译器。

### 7.5 段内多 shot 对参考图预算的压力

C13 第 4 条把参考图上限定为 4 张。这个数字同样是推理而非实测——若实际发现 5–6 张仍可用，可放宽；若 4 张就已经开始漂移，应收紧到 3 并让 C11 相应减少每段的 shot 数上限。

---

# 第 8 部分：实施记录（2026-09-05）

全部 31 个条目已实施。测试从 18 passed 增至 50 passed。以下记录实施时相对清单的偏差与新发现。

## 8.1 三处偏差

**C20 的参数改为带默认值而非必填。** 清单要求三个新参数可选，实现上给了 `packages=None, frame=None, shot=None` 默认值。原因是 orchestrator 现有流程会以单参数形式调用 `result` 门（`AGENTS.md` 的 `.pipeline-runtime/final-result.json` 校验步骤），现有测试也如此调用。非 `COMPLETE` 状态直接返回 schema 校验结果，不做交叉校验。

**C23 的删除清单多了一处连带修改。** `extraction_status` 不只是 `media` 的可选属性——`media` 的 `allOf` 分支里，`role=actual_tail_frame` 的记录**必填**它。清单把它列为死字段是对的（无代码读取，且 `media.status` 的 `runtime_pending/resolved/failed` 完全覆盖同一语义），但删除时必须同步把它从那条 `required` 里移除，否则 schema 自相矛盾。

**C25 选了方案 A 并把措辞钉死。** 校验规则是：`role=character_reference` 且 `do_not_copy` 非空的绑定，prompt 必须包含 `不要复制 <Picture N>`。同时在 `SKILL.md` 里补了一句说明该前缀与标签被逐字匹配，使这条校验有据可依。原有测试的提示词不含该从句，已一并补上。

## 8.2 实施中确认的两件事

**C3 与 C16 确实同时覆盖草稿与可执行两条路径。** `test_draft_path_shares_the_same_checks` 用一个剪辑时间错误的草稿走 `validate_draft_compile`，确认报出 `shot_cut_timing`。第 6.8 节关于「不要拆散 `validate_unified_package` 复用」的告诫由此得到实测支持。

**装箱 DP 的行为符合设计意图。** 端到端串联（3s + 3s + 4s + 16s 四个 shot，总长 26s）产出：

```text
SEG001   0-6    6s  new_first_frame          shots=[S01, S02]
SEG002   6-11   5s  new_first_frame          shots=[S03, S04]
SEG003  11-26  15s  use_previous_tail_frame  shots=[S04]
```

短 shot 被打包，超长 shot 被拆开且拆点落在段内而非段首，尾帧续接只在被迫处出现——与 2.3 的意图一致。

## 8.3 遗留观察（未处理）

**`provenance` 现在只剩一个字段，且与 `media.source_type` 完全重复。** C23 删掉 `provenance.source_id` 后，`provenance` 退化为 `{source_type}`，而 `media` 顶层本就有必填的同名同值字段。它没有进删除清单是因为 `h3-validator/AGENTS.md` 提到了 `provenance`，删除会超出授权范围。建议下一轮一并清理，或反过来把 `media.source_type` 收进 `provenance`。

**`workspace-*/memory/` 与 `DREAMS.md` 未纳入审计。** 这些是 openclaw 自身的 agent 记忆文件，其中 `memory/dreaming/light/2026-09-05.md` 存有旧契约的样例片段（含 `h3_mode`、单数 `shot_id`）。它们不是契约文件，但若 agent 在运行时检索到，可能被旧样例带偏。是否清理需要你判断。
