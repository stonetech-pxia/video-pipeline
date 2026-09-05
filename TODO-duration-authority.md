# TODO：时长归属改造（秒数交给导演）

## 这份文档是什么

一个已经拍板的设计决定，加上落地方案，供**新会话冷启动**使用。与 `TODO-frame-designer-no-first-frame.md` 并列，两者互不依赖，可以并行做。

**当前状态：未实施。** 下面第 3 部分的 D1–D6 一条都没动。

参照文档：`DESIGN-DECISIONS.md`（结构契约）、`TODO-shot-frame-content-contract.md`（内容契约）。

---

# 第 1 部分：决定

**每个镜头的时长由导演拍板，不由 story-analyst 也不由用户拍板。** story-analyst 只给推荐值。

但形状不是"完全不控制"，而是：

> **推荐进，实际出，偏差上报。**

导演可以偏离推荐时长，但偏离必须被看见，不能静默漂移。理由是成本：段落 4–15 秒，540 秒的片子是 50 多次生成，超出 40% 就是多 20 次。

---

# 第 2 部分：为什么（证据，不是主张）

## 2.1 `duration_budget` 是虚假权威

追这个数字的来源：

```
用户在 envelope 第一行写「《回声》——二十分钟短片。」
  → envelope.duration = 1200
    → story-analyst 把 1200 摊到 14 个场次
      → 导演必须填满每一场
```

**这条链上没有一个环节是从素材推出来的。** 1200 秒是叙述文本自己声明的，不是 14 段大纲的内容量。

## 2.2 后果实测过

原始 run4（1200 秒，27 beats，平均 44.4 秒每 beat），S01 的第一个 beat「清晨，周砚在邮局分拣台前分拣信件」拿到 **30 秒 3 个镜头**：

```
K1-01  有节奏地分拣 morning mail 到格位中
K1-02  拿起信件，一眼扫过，把它们放进格子里，保持稳定的节奏
K1-03  分拣的过程继续；信件开始逐格填满
```

同一个动作说了三遍。导演在 `dramatic_purpose` 里自己承认：「在这种节奏中延长『普通的一天』的感觉」。

把总长改成 540 秒（按内容量估算，两种独立方法收敛在 540–555）之后，**同一个 agent、同一份故事**，story-analyst 产出 33 个 beat（比 1200 秒那次还多 6 个）、平均 16.4 秒每 beat，同一个 beat 变成 **10 秒 1 个镜头**，注水消失。

**时间少了一半，beat 反而更多** —— 不用撑时长，素材就被拆得更细。

## 2.3 导演自己分配比机械分配好

run5 的 K1，计划给了 70 秒 5 个 beat，脚本**没有**告诉它每个 beat 该占多久。它自己分成：

| beat | 内容 | 导演给的 | 镜头数 |
| --- | --- | --- | --- |
| B001 | 清晨分拣信件（例行） | 10s | 1 |
| B002 | 抽出无名信，收件人是自己，塞进口袋（激励事件） | **25s** | 3 |
| B003 | 后巷拆信，倒出照片 | 10s | 1 |
| B004 | 看照片，翻背面，读到那行字 | 16s | 2 |
| B005 | 认不出她，收起 | 9s | 1 |

轻重完全正确。而 `plan_chunks.py` 的均分会给 14/14/14/14/14。

## 2.4 story-analyst 确实在做戏剧判断，只是用错了单位

run5 每场的「秒 / beat」并不均匀：

```
S05 灯塔   55秒 / 3 beat = 18.3      S09 车站  25秒 / 1 beat = 25.0
S06 卫生所 50秒 / 3 beat = 16.7      S13 车上  30秒 / 1 beat = 30.0
S01 邮局   35秒 / 2 beat = 17.5      S04 公路  30秒 / 1 beat = 30.0
```

12.5 到 30 秒不等。它在说「哪场重、哪场是过场」—— **这正是它该做的事**（戏剧结构）。不该做的是把这个判断翻译成秒。

---

# 第 3 部分：改动清单

分两步。**第一步单独就能验证收益**，且不触碰 story-analyst；第二步要先破 `DESIGN-DECISIONS.md` 的原则 1（本方案不改 story-analyst），需要用户明确同意。

## 第一步：只改 shot-director 侧

### D1 — 分块改用相对时间轴

**文件** `workspace-shot-director/scripts/plan_chunks.py`

现状：`read_scenes()` 断言 `sum(duration_budget) == duration`，`read_units()` 把每场预算均分到 beat，`plan()` 累加出每块的 `start` / `end` / `duration`。

改法：块**不再携带绝对时间窗**。每块只声明它覆盖哪些 beat；导演在块内**从 0 开始**排时间轴。

**这个改动让"重跑一块只赔一块"变强，不是变弱** —— 今天窗口是钉死的，一块的长度变了就违约；相对时间轴下，一块长度变了，其他块的内容一个字都不用动，只有合并时的偏移量变。

### D2 — 分块大小依据从秒换成 beat 数

**文件** 同上

现状：`TARGET_DURATION = 70`、`MAX_DURATION = 80`、`SIZE_WEIGHT` 的平方惩罚，全部按秒。

改法：换成 beat 数。实测依据（run5 的八块）：

```
块  beats  实际shots  回复大小
K1    5        6       ~14KB
K2    4        7       ~14KB
K3    3        6       ~16KB
K5    6        8       ~20KB
K7    5        8       ~19KB
K8    4        6       ~17KB
```

**4–5 个 beat 一块**是可用的目标，上限 6。比秒数噪声大（3 beat 出 6 镜、6 beat 出 8 镜），所以上限要留余量。

真正的约束仍然是模型输出上限：实测 240 秒的块在第 17 个镜头处被截断，完整回复的安全上限约 20KB。

`SAME_LOCATION`（8.0）、`MID_SCENE`（25.0）、跨越约束计数这几项代价**原样保留** —— 它们跟秒数无关。

### D3 — 块级校验的窗口约束改写

**文件** `workspace-shot-director/scripts/validate_chunk.py`

删掉（`check_timeline` 里）：

- `the plan fixed its window at {start}-{end}`
- `shots[0].start is X, expected {planned start}`
- `shots[-1].end is X, expected {planned end}`

换成：

- `shots[0].start` 必须是 `0`
- 镜头连续、无缝、无重叠（这条原样保留）
- 单镜不超过 15 秒（原样保留）

beat 覆盖、台词逐字、`characters_in_frame ⊆ 场次在场者`、exit state 逐镜、开场标签这几组**全部原样保留**。

### D4 — 合并时求累积偏移

**文件** `workspace-shot-director/scripts/merge_shots.py`

现状：断言 `chunk.start == clock`（`chunk {id} starts at X, but the film reached Y`），并断言末镜等于 plan 的 `duration`。

改法：块内时间轴是相对的，合并时给第 N 块加上前 N-1 块的总时长偏移，同时改写每个镜头的 `start` / `end`（和现在改写 `id` 一样）。全片 `duration` 由合并**算出**，不再由 plan 给定。

`continuity_exit_state` 的 `shot_id` 改写原样保留。

### D5 — 把推荐时长告诉导演，并上报偏差

**文件** `workspace-shot-director/scripts/build_chunk_message.py`、`workspace-shot-director/AGENTS.md`

- 消息里给出这一块的**推荐时长**（由 story-analyst 的 `duration_budget` 累加得出）与它覆盖的 beat
- `AGENTS.md` 写明：推荐值是参考，节奏由你定；显著偏离时在 `warnings` 里说明理由

**顺带解决一个悬了很久的问题**：Shot IR 顶层的 `warnings` 至今没有任何消费者。这是它的第一个真实用途。

### D6 — STORY 门的求和校验降级为警告

**文件** `workspace-video-pipeline/scripts/validate_pipeline.py`

`duration_budget_mismatch` 目前是 error（`validate_story` 里，本会话新加）。budget 变成推荐值之后它不该再阻断，但仍要可见 —— 改成 warning，或保留 error 但只在 budget 非空时生效。

**注意**：`workspace-video-pipeline/AGENTS.md` 里的分块小节（"Directing a Film in Chunks"）描述的是绝对时间窗，D1–D4 做完要跟着改。

## 第二步：改 story-analyst 侧（需先获得破例许可）

### D7 — `duration_budget` 换成场次权重

**文件** `workspace-story-analyst/schemas/story-ir.schema.json`、`skills/script-*/`

`scenes[].duration_budget`（秒）→ `scenes[].weight`（`major` / `normal` / `transit` 之类），加一个全片**推荐**总长。导演把权重换算成秒。

**为什么不能直接删掉不给**：8 个互不相识的会话各自定长，**没有谁知道第 11 场是高潮**。今天这个全片形状是靠秒数偷偷携带的，拿掉秒数必须有东西接手。权重是唯一能跨块传递戏剧形状的载体。

**一个有利条件**：`story-ir.schema.json` 里 `scenes[].duration_budget` 与顶层 `duration` **已经是可空的**（`oneOf: [integer, null]`）。所以"推荐值可以缺省"不需要改 schema，只需要改产出规则与下游的空值处理。

---

# 第 4 部分：会破什么 / 风险

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| **全片节奏失衡** | 8 个独立会话各自定长，无人纵览 | D7 的场次权重。缓解不完全 |
| **成本不可预估** | 秒数直接等于生成次数与钱 | D5 的偏差上报，让人在开拍前看见 |
| **反向失控** | 9 分钟的素材拍成 25 分钟 | 同上。能看见，拦不住 |
| **场次短于 4 秒** | `plan_segments.py` 的段长下限是模型限制，导演给某场 3 秒就装不下 | 在 D3 里加一条：一个场次的总时长不得低于 4 秒 |
| **块与块之间时长风格不一** | 一块偏快一块偏慢 | 无机制。属于接受的代价 |

---

# 第 5 部分：怎么验证

第一步做完后，用现成素材直接对照：

```bash
# 现成输入
samples/runs/long-run5-merged.json     # 540 秒，33 beats，14 场
samples/runs/run5-chunks/plan.json     # 今天按秒切出来的 8 块
samples/runs/run5-chunks/K1..K8.json   # 今天导演在钉死窗口下的产出

# 改完之后重跑同一份 story
./run-shot-director-chunked.sh samples/runs/long-run5-merged.json <新目录>
```

**要看的三件事：**

1. **导演自己定的总长是多少** —— 与推荐的 540 秒差多少。这是这次改造唯一真正想知道的数字。
2. **轻重分配有没有变好** —— 拿 B001（例行分拣）与 B002（激励事件）的秒数比对照 2.3 那张表。
3. **注水有没有回来** —— 检查有没有连续镜头的 `subject_action` 在说同一件事。

回归项：八块仍应逐块通过 `validate_chunk.py`；合并后仍应通过 `shot-ir.schema.json` 与 SHOT 门；`workspace-shot-director/tests` 全绿。
