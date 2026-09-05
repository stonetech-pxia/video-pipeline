# TODO：FRAME-DESIGNER 改造（无首帧管线）

## 这份文档是什么

`DESIGN-DECISIONS.md` 与 `TODO-shot-frame-content-contract.md` 的续篇，供**新会话冷启动**使用。它记录一个已经拍板的设计决定、为此已经改完的代码、以及 frame-designer 侧尚未跟上的部分。

**当前状态：管线处于半程。** `plan_segments.py` 已按新设计重写，它现在产出的 `segment_plan` **过不了** `frame-design-output.schema.json` 与 `validate_frame_design.py`。补齐这一侧就是本文档的全部任务。

已完成部分见 git 分支 `shot-director-chunking`，相关提交：`dd7d11a`、`0290c23`、`9219dfa`、`2987b23`。

---

# 第 1 部分：已拍板的设计决定

## 1.1 没有首帧

**用户决定：全片不生成任何首帧。** 场次开场也没有。一个生成段的输入只有两样东西：

1. 提示词
2. 参考图（人物、地点、风格）

场内的连续性靠**尾帧续接**，不靠重新生成一张图去对齐。

## 1.2 由此推出的切段策略（已实现）

没有首帧就改变了"边界该落在哪"。

- 边界落在**剪辑点**上 → 下一段拿到的尾帧是刚结束那个镜头的画面，而它要拍的是下一个镜头。**方向错了。**
- 边界落在**镜头内部** → 交出去的那一帧已经在这个镜头里，下一段接着往下拍。**对的。**

所以段落**故意跨过剪辑点**，在镜头中间断开。

另外两条硬规则：

- **段不跨场次。** 换场重置地点，而绑在段上的参考图就是它所拍那个地方的图。
- **每场第一段冷启动**（`references_only`），其余全部 `use_previous_tail_frame`。

真实数据（run5 的 K1，镜头 0-12 / 12-24 / 24-35 / 35-47 / 47-58 / 58-70）：

```
SEG001 S01  0-5    5s  [K1-01]          references_only
SEG002 S01  5-20  15s  [K1-01, K1-02]   use_previous_tail_frame
SEG003 S01 20-35  15s  [K1-02, K1-03]   use_previous_tail_frame
SEG004 S02 35-40   5s  [K1-04]          references_only
SEG005 S02 40-55  15s  [K1-04, K1-05]   use_previous_tail_frame
SEG006 S02 55-70  15s  [K1-05, K1-06]   use_previous_tail_frame
```

四个真剪辑点（12、24、47、58）**一个都没被用作边界**；冷启动从 5 段降到 2 段。

## 1.3 参考图与提示词的分工

因为有了人物图和地点图，**提示词不需要详细描述人物长相和环境陈设**：

- 导演写的环境细节 → 进 `assets.json` 的 `settled` → 成为**参考图**的依据
- 视频提示词 → **点名**主体（"周砚"、"分拣室"）+ 描述**变化的东西**（动作、运镜、情绪、声音）

这条规则要落进 frame-designer 与 h3-compiler 的 `AGENTS.md`。

## 1.4 frame-designer 的新职责

- **不再管理 `image_jobs`**，整块搁置
- 产出：`segment_plan`（脚本给的，原样采用）+ **初步 prompt** + 参考图与尾帧的绑定
- 提示词由 h3-compiler 优化

## 1.5 不能动的硬限制

`DESIGN-DECISIONS.md` 6.4：**4–15 秒段长是 MiniMax H3 的模型限制，不是设计选择。** 不存在 16 秒。

镜头上限 15 秒（`shot-director/AGENTS.md`），一条不间断的长镜头写成连续多个 shot，后续的打 `boundary_type=same_shot_continuation`。

---

# 第 2 部分：已经改完的部分（不要重做）

| 文件 | 状态 |
| --- | --- |
| `workspace-video-pipeline/schemas/assets.schema.json` | **新增**。`id → {name, image, description, settled[]}`，角色与地点两组 |
| `workspace-video-pipeline/scripts/resolve_assets.py` | **新增**。给每个 shot 补 `scene_id` / `location_id` / `reference_assets`；把导演写的 `environment`+`lighting` 按 shot 追加进 assets。幂等，可对每个 chunk 逐块运行 |
| `workspace-video-pipeline/tests/test_resolve_assets.py` | 新增，8 测试 |
| `workspace-frame-designer/scripts/plan_segments.py` | **已按 1.2 重写**。输入改为 `resolve_assets.py` 处理过的 Shot IR（依赖 `scene_id`） |
| `workspace-frame-designer/tests/test_plan_segments.py` | 已重写，11 测试 |
| `workspace-shot-director/schemas/shot-ir.schema.json` | `split_hints` 已删；shot 上限 15 秒 |
| `workspace-frame-designer/AGENTS.md` | 锚点规则已部分更新（尾帧复用不再只发生在"段落从镜头中间开始"时） |

`plan_segments.py` 现在多输出一个 `scene_id` 字段，并把 `entry_strategy` 写成 `references_only`。

---

# 第 3 部分：待做的改动清单

## F1 — `entry_strategy` 枚举替换

**文件** `workspace-frame-designer/schemas/frame-design-output.schema.json`

`["new_first_frame", "use_previous_tail_frame"]` → `["references_only", "use_previous_tail_frame"]`。

## F2 — `segment` 增加 `scene_id`

**文件** 同上。`$defs.segment` 是 `additionalProperties: false`，`plan_segments.py` 已经在输出 `scene_id`，不加就整份被拒。

## F3 — 校验器的入口分支重写

**文件** `workspace-frame-designer/scripts/validate_frame_design.py:113-141`

`new_first_frame` 分支（要求 `entry_frame_source` 指向一张 `first_frame` 媒体、要求 `frame_plan.first_frame_media_id` 匹配）整段替换为 `references_only`：

- `entry_frame_source` 必须为 `null`
- `runtime_entry_dependency` 必须为 `null`
- `frame_plan[...].first_frame_media_id` 必须为 `null`
- 必须是所在场次的第一段（可用新的 `scene_id` 判断）

`use_previous_tail_frame` 分支的尾帧链接与 `exit_frame_required` 检查保留。

## F4 — `frame_plan` 与媒体角色清理

**文件** 同上两处

- `framePlanItem` 的 `first_frame_media_id`：无首帧后恒为 null，考虑整个删掉
- `media.role` 枚举里的 `first_frame`、`last_frame_target` 失去用途
- `image_jobs`：按 1.4 搁置。注意 `MEDIA` 门（`validate_pipeline.py`）与 `pipeline-result` 的 `MEDIA_WAIT` 分支都依赖 `image_jobs`，动它要连带看

## F5 — 初步 prompt 进 frame-design 产物

**新字段**，形状未定（见第 5 部分）。至少要能承载 F7 说的那条检查。

## F6 — 提示词规则写进 AGENTS.md

**文件** `workspace-frame-designer/AGENTS.md`、`workspace-h3-compiler/AGENTS.md`

落实 1.3：点名主体、不复述外观；外观由参考图承担。

## F7 — `continuity_exit_state` 的消费者迁移

原来的检查（`validate_frame_design.py:256-282`，诊断码 `exit_state_not_carried`）是：**场内新首帧的提示词必须复述上一镜的 exit state**。

**这条已经作废** —— 场内不再有冷启动，每个场内段都从真实尾帧接上，问题在构造上消失。那 25 行代码与 `test_validate_frame_design.py` 里两个对应测试可以删。

**但 `continuity_exit_state` 本身不能删。** 它的消费者要**迁到场次开场那一段**：换场是冷启动，跨场次仍然存活的状态必须由提示词说出来 —— 具体就是 `wardrobe_state`（外套还穿着）与 `held_props`（照片还在口袋里）。`staging` / `scene_state` / `lighting_state` 是地点相关的，换场本来就重置，不必带。

---

# 第 4 部分：路上发现的两个矛盾

## 4.1 `continuity_decision` 的映射会失效（必须解决）

尾帧复用分支（`validate_frame_design.py:135`）要求 `continuity_decision` 的八项全为 `true`；而标签一致性检查（`:289-302`）是从**开场镜头的 `boundary_type`** 推 `is_same_shot`。

新切法下续接段**从镜头中间开始**，它的"开场镜头"是上一个还在跑的镜头，`boundary_type` 是 `shot_change` —— 两个检查会互相打架，同一份合法产物会同时触发 `invalid_tail_reuse` 和 `continuity_label_conflict`。

**根子**：`continuity_decision` 原本描述"开场镜头那个剪辑点的关系"，而现在段落根本不在剪辑点开场。

**新模型下它其实是可推导的**：

- 续接段 → 永远全连续（段在镜头内部开场，什么都没变）
- 场次开场段 → 永远全不连续

所以它不再是一个需要判断的字段。建议：要么由 `plan_segments.py` 直接算出来，要么整个删掉，由 `entry_strategy` 承担全部语义。

## 4.2 两个 Shot IR 字段失去了消费者

| 字段 | 原用途 | 现状 |
| --- | --- | --- |
| `composition_control` | `plan_segments.py` 里「critical 的镜头必须开段，好让生成的首帧锚定构图」 | **没有首帧了**，这条规则在重写时已去掉。字段悬空 |
| `boundary_risk` | 衡量"这个剪辑点上有多少世界状态必须挺过一次冷启动" | 场内不再冷启动；换场是强制边界，评分不影响任何选择。字段悬空 |

两个都是 C8 加的必填字段。**不要自行删除** —— 用户对这类字段的处理有明确态度（参见 `split_hints` 的处理过程：先确认没有消费者，再二选一"接线或删除"）。

---

# 第 5 部分：未决问题（需要人拍板）

1. **初步 prompt 的形状**：一个字符串？还是按 H3 三段（`integrated_multimodal_description` / `overall_soundscape` / `non_diegetic_music`）预分段？后者能让 h3-compiler 只做优化不做结构。
2. **`frame_plan` 留不留**：无首帧之后它只剩 `actual_tail_frame_media_id` 与 `reference_media_ids`，是否并进 `segment_plan`。
3. **`image_jobs` 的最终去向**：schema 里保留空数组，还是从产物中彻底移除（会牵动 MEDIA 门与 `pipeline-result` 的 MEDIA_WAIT 分支）。
4. **`composition_control` / `boundary_risk`**：接线还是删除。
5. **参考图从哪来**：`assets.json` 的 `image` 目前全是 `null`，由谁生成、何时填路径，尚未定。

---

# 第 6 部分：怎么验证

```bash
# 1. 分块 → 导演逐块产出 → 逐块校验（已可跑）
python3 workspace-shot-director/scripts/plan_chunks.py <story-ir.json> > plan.json
python3 workspace-shot-director/scripts/validate_chunk.py plan.json K1 K1.json

# 2. 每块产出后累积进 assets（已可跑，幂等）
python3 workspace-video-pipeline/scripts/resolve_assets.py K1.json <story-ir.json> assets.json > K1-resolved.json

# 3. 合并所有块 → 完整 Shot IR（已可跑）
python3 workspace-shot-director/scripts/merge_shots.py plan.json head.json K1.json K2.json ... > SHOT.json

# 4. 补溯源 → 切段（已可跑，但产物过不了 frame-design 的 schema，即本文档的任务）
python3 workspace-video-pipeline/scripts/resolve_assets.py SHOT.json <story-ir.json> assets.json > SHOT-resolved.json
python3 workspace-frame-designer/scripts/plan_segments.py SHOT-resolved.json
```

现成的真实样例：

- `samples/runs/long-run5-merged.json` —— 540 秒 Story IR，33 beats，14 场
- `samples/runs/shot-run7-K1.json`、`shot-run7-K2.json` —— 导演的真实产出，均通过校验
- `samples/runs/shot-run6-plan.json` —— 8 块的分块计划
- `samples/assets-run5.json` —— 由 K1 生成的注册表样例

验收标准：F1–F7 做完之后，上面第 4 步的产物能通过 `validate_frame_design.py`，且 `workspace-frame-designer/tests` 全绿。
