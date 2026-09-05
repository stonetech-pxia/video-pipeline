# TODO：SHOT → FRAME 内容契约

## 这份文档是什么

`DESIGN-DECISIONS.md` 的续篇，编号接续（C32 起）。那份文档的 31 个条目解决的是**结构契约**——字段形状、时间轴、装箱、媒体链接。本文档解决的是它没有覆盖的**内容契约**：frame-designer 写进提示词和参考图清单的东西，和 shot-director 写的是不是同一回事。

条目格式、状态标记、验收写法与 `DESIGN-DECISIONS.md` 一致。实施完成后可整体并入该文档的批次序列。

**全部条目状态：未实施。**

---

# 第 1 部分：证据

来源：`workspace-video-pipeline/outputs/2026-09-05-elevator-kitchen-retest/`。该次运行产生于 2026-09-05 改造之前，按 `DESIGN-DECISIONS.md` 6.9 不作为契约样例；此处仅用作**缺陷证据**。

复盘发现五处 SHOT 与 FRAME 的冲突：

| # | 冲突 | 归属 |
| --- | --- | --- |
| ① | `JOB_FIRST_SEG001` 写 "C01 centered / C02 reflected behind her shoulder"，`SHOT.json` S01 的 `blocking` 写「女主居画面左侧,邻居居右稍近镜头」 | 批次 H |
| ② | `JOB_FIRST_SEG001` 与 `JOB_REF_L01` 写 "mirrored elevator / warm overhead lighting"，S01 的 `environment` 写「金属壁面」、`lighting` 写「冷白荧光」 | 批次 H |
| ③ | SEG004 的 `character_reference_ids` 含 C01/C02/C03，S03 的 `blocking` 只有女主一人走在走廊 | 批次 G |
| ④ | SEG005 的 `character_reference_ids` 含 C01/C02，S04 的 `blocking` 只有女主进玄关 | 批次 G |
| ⑤ | SHOT 的 S03/S04 分界在 20 秒，FRAME 的 SEG004/SEG005 分界在 19 秒 | **已由 C11 解决** |

⑤ 不再需要处理：段边界现由 `plan_segments.py` 从 shot 切点搜索得出，LLM 无权拟定。

## 1.1 共同成因

三处缺口，`DESIGN-DECISIONS.md` 4.1 / 4.2 已记录其中两处：

1. **没有内容比对**。`validate_frame_design.py` 校验形状、时间、链接，不校验语义。提示词里写什么，与 Shot IR 无任何约束关系。
2. **`reference_strategy` 的角色分类不起作用**。`validate_frame_design.py:147,161` 是 `for group in reference_strategy.values()` 整组遍历，从不区分 `character_reference_ids` 与 `location_reference_ids`。把场景图填进角色槽今天也全绿通过。
3. **「这个镜头里有谁、在哪」在全管道不存在结构化表达**（本次复盘新发现，见 1.2）。

## 1.2 关键发现：人物与地点没有机器可读的来源

已核对三层 schema：

- **Story IR** `beats[]` 的属性只有 `id` / `start` / `end` / `action` / `emotion` / `cause` / `effect`。`characters` 与 `locations` 是顶层实体表，没有任何字段把它们绑到 beat 上。
- **Shot IR** `shot` 的 22 个属性里没有人物或地点字段。只有散文的 `blocking` 与 `environment`。
- **Shot IR** `continuity_exit_state.by_shot[]` 只有一个散文 `staging`。

全管道唯一的间接线索是 `dialogue_ids` → `dialogue[].speaker_id`，只覆盖有台词的人。本次 S03/S04 的 `dialogue_ids` 为空数组，因此「走廊只有女主」这件事结构上无从得知——**冲突 ③④ 在今天不是「没查」，是「查不了」**。

值得注意：即便只用这条弱线索也能抓到最严重的症状——S05 的说话人集合是 {C01, C03}，而 FRAME 给 SEG006/SEG007 的 `character_reference_ids` 只有 `["M_REF_C01"]`。丈夫在他有四句台词的两段里没有角色参考图。

## 1.3 本文档不处理的一项

**首帧图与角色参考图的脸不一致**（`DESIGN-DECISIONS.md` 3.4）。`imageJob.input_media_ids` 由 C10 加入，但 `validate_frame_design.py:220-232` 只校验「该 ID 存在」与「已解析」，不校验「该填的填了没」。应补一条：某段首帧 job 的 `input_media_ids` 必须包含该段 `character_reference_ids` 的全部。

**不放进本文档的理由**：这条与五处冲突正交，且**必须在批次 G 之后做**。它保证的是「清单被忠实执行」，清单本身错时它会加固错误——SEG004 清单误含 C03，这条一上就会把丈夫的脸真的送进走廊首帧的输入。批次 G 完成后单独处理。

该缺陷本次运行尚未暴露，因为流程停在 `MEDIA_WAIT`，13 个 image job 全部 `pending`，静态图一张未生成。

---

# 第 2 部分：执行顺序与依赖

```text
批次 G（人物与地点名单）── 修 ③④
   C32 → C33 → C34
   C32 → C35 → C36 → C37
   ↓
批次 H（提示词原文复述）── 修 ①②，不依赖 G，可并行
   C38 → C39
   ↓
批次 I（测试）── 每批次完成后同步进行
   C40、C41
```

批次 G 与 H 之间无依赖，可并行推进。C32 是破坏性变更，落地后所有既有 Shot IR 立即失效——包括 `workspace-video-pipeline/tests/fixtures/shot.json`，由 C40 修复。

## 同文件多处改动

| 文件 | 条目 | 顺序 |
| --- | --- | --- |
| `workspace-frame-designer/scripts/validate_frame_design.py` | C37、C39 | 先改行号大的 |
| `workspace-frame-designer/AGENTS.md` | C36、C38 | 无冲突，任意 |

## 改动总览

| 编号 | 文件 | 性质 | 状态 |
| --- | --- | --- | --- |
| C32 | `workspace-shot-director/schemas/shot-ir.schema.json` | 破坏性 | 未实施 |
| C33 | `workspace-shot-director/AGENTS.md` | 文档 | 未实施 |
| C34 | `workspace-video-pipeline/scripts/validate_pipeline.py` | 新增校验 | 未实施 |
| C35 | `workspace-frame-designer/schemas/frame-design-output.schema.json` | 新增字段 | 未实施 |
| C36 | `workspace-frame-designer/AGENTS.md` | 文档 | 未实施 |
| C37 | `workspace-frame-designer/scripts/validate_frame_design.py` | 新增校验 | 未实施 |
| C38 | `workspace-frame-designer/AGENTS.md` | 文档 | 未实施 |
| C39 | `workspace-frame-designer/scripts/validate_frame_design.py` | 新增校验 | 未实施 |
| C40 | `workspace-video-pipeline/tests/` | 跟随 | 未实施 |
| C41 | `workspace-frame-designer/tests/test_validate_frame_design.py` | 跟随 | 未实施 |

---

# 第 3 部分：批次 G —— 人物与地点名单

## C32 — shot 新增 `character_ids` 与 `location_ids` **[未实施]**

**文件** `workspace-shot-director/schemas/shot-ir.schema.json`

**现状** `$defs.shot` 的 `required`（`:109-131`）与 `properties`（`:137` 起）共 22 项，无人物与地点字段。

**改法** 两个字段都加进 `required` 与 `properties`：

```json
"character_ids": {
  "type": "array",
  "uniqueItems": true,
  "items": { "type": "string", "minLength": 1 }
},
"location_ids": {
  "type": "array",
  "minItems": 1,
  "uniqueItems": true,
  "items": { "type": "string", "minLength": 1 }
}
```

`character_ids` 允许空数组——纯空镜头合法。`location_ids` 至少一项，且**必须是数组而非单值**：一个 shot 可以横跨两个地点，本次留档的 S02 就是电梯门开、人走出到走廊，其 `scene_continuity` 正是 `location_change`。数组形态也与下游 `location_reference_ids` 对齐。

**理由** 见 1.2。这是三处冲突里唯一「今天想查也查不了」的一处，其余条目全部依赖本条提供数据。

**验收** 缺任一字段的 Shot IR 被 schema 拒绝；`location_ids: []` 被拒绝；`character_ids: []` 通过。

---

## C33 — shot-director 输出说明跟随 **[未实施]**

**文件** `workspace-shot-director/AGENTS.md`

**改法** 在 `## Continuity Labels`（`:45`）之前新增一节，规定：

1. `character_ids` 列出**在该 shot 画面中可见**的全部人物，`location_ids` 列出该 shot 覆盖的全部地点。
2. 两者的取值必须来自 Story IR 的 `characters[].id` 与 `locations[].id`，**不得新造 ID，不得使用 Story IR 中不存在的实体**。
3. 该 shot 的 `dialogue_ids` 所对应台词的 `speaker_id`，必须全部出现在 `character_ids` 中。
4. 判据是画面可见性，不是叙事相关性：被谈论到但不在画面里的人不写进去。

**理由** schema 加了字段而文档不说填法，模型会按叙事相关性而非画面可见性来填——那正是本次 C03 出现在走廊段的错误模式。第 4 条是防复发的关键一句。

**验收** 文档中出现「画面可见」与「取值必须来自 Story IR」两条明确表述。

---

## C34 — `validate_pipeline.py` 实体引用与说话人覆盖校验 **[未实施]**

**文件** `workspace-video-pipeline/scripts/validate_pipeline.py`

**现状** `validate_shot()`（`:154`）已有 `unknown_source_beat`（`:176-178`）与 `unknown_dialogue`（`:179-181`）两组引用校验，`dialogue_by_id` 已在手边（`:163`）。

**改法** 在同一循环内追加三条，复用现有 `error()` 写法：

1. `unknown_character`——`character_ids` 中每个 ID 必须存在于 `story.characters[].id`（`story is not None` 时才查，与现有两条一致）
2. `unknown_location`——`location_ids` 中每个 ID 必须存在于 `story.locations[].id`
3. `missing_speaker`——该 shot 每个 `dialogue_ids` 对应台词的 `speaker_id`（非 `null` 时）必须出现在 `character_ids` 中

三条的 `error_class` 用 `SHOT_DESIGN`，`owner` 用 `shot-director`。

**理由** 前两条堵住「填一个不存在的实体 ID」。第 3 条是白送的交叉校验——`dialogue_by_id` 已经加载好，多写四行。若当时存在，本次 SEG006/SEG007 丈夫缺席的问题会在 SHOT 门就被拦下，不会流到 FRAME。

**验收** 三条各有一个反例用例被拒绝（见 C40）。

---

## C35 — media 新增 `entity_id` **[未实施]**

**文件** `workspace-frame-designer/schemas/frame-design-output.schema.json`

**现状** `$defs.media` 没有任何字段说明一张参考图画的是谁或哪里。`M_REF_C01` 这类命名是约定俗成，**不可作为程序判据**。

`DESIGN-DECISIONS.md` C23 曾以「管道内外都无人读」为由删除 `entity_bindings`。本条给了读它的人，因此把该能力以收窄形态接回来。

**改法** `$defs.media` 新增可选属性：

```json
"entity_id": { "type": "string", "minLength": 1 }
```

并加条件约束：`role` 为 `character_reference` 或 `location_reference` 时 `entity_id` 必填；其余 role 不得出现该字段。取值必须是 Story IR 中对应实体的 ID。

**理由** C37 要把 `character_reference_ids`（一组 media ID）跟 shot 的 `character_ids`（一组实体 ID）比对，中间缺一张映射表。没有本条，C37 无法实现。

选单值 `entity_id` 而非恢复原 `entity_bindings` 数组：一张参考图对应一个实体，多对多没有已知用例，按最小形态加。

**验收** `character_reference` 缺 `entity_id` 被拒绝；`style_reference` 带 `entity_id` 被拒绝。

---

## C36 — frame-designer 媒体说明跟随 **[未实施]**

**文件** `workspace-frame-designer/AGENTS.md`

**改法** 修改媒体记录必填项那段（`:77`），加入：`character_reference` 与 `location_reference` 必须携带 `entity_id`，取值为 Story IR 中该实体的 ID。

同时在参考图相关表述处写明：**一段的 `character_reference_ids` 由该段所覆盖 shots 的 `character_ids` 并集唯一决定，不由 frame-designer 判断。** `location_reference_ids` 同理。

**理由** 与 C12 第 2 项同一治法——让下游读上游已经做过的判断，而不是重做一遍。C37 是兜底，本条是治本。

**验收** 文档中不再出现要求 frame-designer 自行判断某段涉及哪些人物或地点的表述。

---

## C37 — `validate_frame_design.py` 参考图名单比对 **[未实施]**

**文件** `workspace-frame-designer/scripts/validate_frame_design.py`

**改法** 新增一组检查，对每个 segment：

1. 期望集合 = 该段 `shot_ids` 所有 shot 的 `character_ids` 并集
2. 实际集合 = `character_reference_ids` 每个 media ID 在 manifest 中查到的 `entity_id` 集合
3. 两者**必须相等**（不是包含）——多一个报 `reference_character_extra`，少一个报 `reference_character_missing`
4. `location_reference_ids` 与 `location_ids` 同样处理，报 `reference_location_extra` / `reference_location_missing`
5. `character_reference_ids` 中出现 `role != character_reference` 的媒体，报 `reference_role_mismatch`；location 槽同理

`shot_ir is None` 时跳过 1–4，第 5 条不依赖 Shot IR，始终执行。

**与 C13 第 4 条的冲突处理**：参考图预算硬上限为 4。若某段人物与地点参考图之和超过 4，**不得静默丢弃**——返回 `blocked` 并在 `errors` 中说明，由 shot-director 拆分镜头解决。本次剧本每镜头最多 2 人，不触发。

**理由** 第 3 条要求集合相等而非包含，是因为 ③④ 两处冲突都是「多列了人」。只查包含关系抓不到。

第 5 条把 1.1 第 2 点记录的「角色分类不起作用」一并接上——这是 `reference_strategy` 五个子数组第一次真正产生约束。

**验收** 五条各有一个反例用例被拒绝（见 C41）。用本次留档的 FRAME.json 跑，SEG004 报 `reference_character_extra`、SEG006 报 `reference_character_missing`。

---

# 第 4 部分：批次 H —— 提示词原文复述

## C38 — 首帧提示词改为三段式 **[未实施]**

**文件** `workspace-frame-designer/AGENTS.md`

**现状** image job 的要求（`:79`）只说必须有 positive prompt 与 negative prompt，对内容与 Shot IR 的关系无任何约束。结果见冲突 ①②：frame-designer 从零描述场景，模型按自身先验写出了「镜面电梯 + 暖光」，与导演的「金属壁面 + 冷白荧光」直接冲突。

更能说明性质的是其余段落——`JOB_FIRST_SEG004` 写的是 "configured in approved blocking with C03 at the new composition"，`JOB_REF_L03` 写的是 "the approved S03/S04 intermediate scene environment"。这些是**占位符而非内容**，说明 frame-designer 并未把 Shot IR 的文字当作必须转写的素材。

**改法** 规定 `role = first_frame` 的 image job，其 `prompt` 必须由三块按序构成：

```text
第一块 · Shot IR 原文（逐字，不得改写、不得翻译、不得增删）
  段首 shot 的 environment / lighting / framing / camera_position / blocking

第二块 · 上一个 shot 的 continuity_exit_state
  （C13 第 5 条已在校验，规则不变）

第三块 · frame-designer 自己的设计
  身份锚定、do_not_copy 指令、参考图绑定说明、negative prompt
```

同时写明**只复述段首 shot**：按 2.6 与 C12 第 3 项，首帧图只锚定段内第一个 shot，段内后续 shot 由视频模型自由构图。对后续 shot 强制复述构图与机位是自相矛盾的。

**理由** 这是职责边界问题。frame-designer 的职责是分段、镜头连续性、人物一致性——三者都不需要它描述场景长什么样。给了创作权，模型必然行使；收掉创作权，冲突 ①② 结构上不可能再发生。

第三块保留给它，因为那才是它的活儿。

**验收** 文档中出现「逐字」「不得改写」与「只复述段首 shot」的明确表述。

---

## C39 — `validate_frame_design.py` 原文复述校验 **[未实施]**

**文件** `workspace-frame-designer/scripts/validate_frame_design.py`

**改法** 复用 C13 第 5 条的实现手法（`:234-260` 的 `exit_state_not_carried` 循环），在同一入口追加：

对每个 `entry_strategy == "new_first_frame"` 的 segment，取 `entry_frame_source` 指向的 image job，其 `prompt` 必须包含 `shot_ids[0]` 对应 shot 的这五个字段原文：`environment`、`lighting`、`framing`、`camera_position`、`blocking`。缺任一项报 `shot_text_not_carried`，消息中列出缺失字段名。

**标点归一化**：比对前对两侧做一次归一——全角/半角逗号与句号统一、连续空白折叠。Shot IR 中的中文使用半角逗号（本次留档 S01 的 `environment` 即为 `现代住宅楼电梯轿厢,金属壁面与楼层数字显示`），复制过程中极易被改成全角而导致误判。C13 第 5 条存在同样隐患，本条一并修正。

**理由** 子串比对是笨办法，但正是 C13 第 5 条已经在用的办法，机器已经具备，不需要新机制。

**验收** 用本次留档的 FRAME.json 跑，`JOB_FIRST_SEG001` 报 `shot_text_not_carried` 且列出全部五个字段。归一化用例：原文半角逗号、提示词全角逗号，判定为通过。

---

# 第 5 部分：批次 I —— 测试

## C40 — `validate_pipeline.py` 测试与夹具跟随 **[未实施]**

**文件** `workspace-video-pipeline/tests/test_validate_pipeline.py`、`workspace-video-pipeline/tests/fixtures/shot.json`

**改法** 夹具 `shot.json` 的每个 shot 补 `character_ids` 与 `location_ids`；新增 C34 三条检查各一个反例用例。

**注意** C32 落地后夹具立即失效，SHOT 门全红。这是预期行为，不要因此回滚 C32。

---

## C41 — `validate_frame_design.py` 测试跟随 **[未实施]**

**文件** `workspace-frame-designer/tests/test_validate_frame_design.py`、`workspace-video-pipeline/tests/fixtures/frame.json`

**改法** 夹具的 `character_reference` / `location_reference` 媒体补 `entity_id`；新增 C37 五条与 C39 一条各一个反例用例，外加 C39 的标点归一化用例。

---

# 第 6 部分：待决与风险

## 6.1 中文原文进入英文提示词的模型遵循度未验证

提示词按 1.5 为中英混写：强制锚定句是中文固定模板，画面正文为英文。C39 要求把 Shot IR 的中文 `environment` / `lighting` / `blocking` 逐字塞进以英文为主的首帧提示词，图像模型对这部分中文的遵循度**没有实测数据**。

需要说明的是：**这个风险不是本条新引入的**。C13 第 5 条已经要求首帧提示词逐字复述 `continuity_exit_state`，而那些字段同样由 shot-director 用中文写。本条只是把同一做法扩大到五个字段。

**尚未被验证过**——本次运行停在 `MEDIA_WAIT`，静态图一张未生成，C13 第 5 条的实际效果也从未见过。

**观察指标**：首批静态图生成后，人工核对首帧图是否真的体现了 Shot IR 描述的环境与光线。若明显不遵循，退路是要求 frame-designer 同时给出中文原文与英文译文，校验只查中文原文那半——保住可校验性，把遵循度交给英文那半。

## 6.2 `character_ids` 的「画面可见」判据仍是主观的

C33 第 4 条要求按画面可见性而非叙事相关性填写，但这是散文指令，模型仍可能把「被谈论到的人」算进去。C34 的 `missing_speaker` 只能查漏，查不了多。

**观察指标**：同一剧本跑两次 shot-director，比较两次 `character_ids` 的差异。若稳定，说明判据够清晰；若某个 shot 反复摇摆，需要在文档中补具体反例。

## 6.3 批次 G 完成后应立即处理 1.3 所述缺陷

`input_media_ids` 的绑定校验在批次 G 之前做会加固错误，之后做才安全。批次 G 一旦落地，该条应尽快跟进——它防的问题会在第一次真正生成静态图时暴露，且届时没有任何下游环节能修复。
