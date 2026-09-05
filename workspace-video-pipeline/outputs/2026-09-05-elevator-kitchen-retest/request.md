# Video Pipeline Real Regression Test

对现有 H3 video-pipeline 做一次从头到尾的真实回归测试。严格遵守你 workspace 的 AGENTS.md 和所有 deterministic gates。

## 用户故事

一位成年已婚年轻女性在住宅电梯里与女邻居简短对话；电梯到达她所在楼层，门开后她走出电梯；她沿走廊来到自家门前；用钥匙开门并进入家中；随后走进厨房，与丈夫对话。

## 固定参数

- 总时长：36 秒
- 画幅：16:9
- 风格：现代中国城市住宅，写实电影感，克制自然，不夸张
- 语言：普通话
- 连续性：女主的脸、发型、米色风衣、黑色手提包从电梯到家中保持一致；女主出电梯后移动方向一致；家门内外空间关系和光线衔接合理
- 人物均为成年人

## 必须逐字保留的对白

1. 女邻居：“刚下班？”
2. 女主：“嗯，今天有点晚。”
3. 女邻居：“你家那位已经回来啦。”
4. 女主：“是吗？那我得快点。”
5. 丈夫：“回来啦？汤马上好。”
6. 女主：“电梯里碰见王姐，她说你早就回来了。”
7. 丈夫：“想给你个惊喜。”
8. 女主：“那我就等着尝了。”

## 执行要求

1. 实际依次调用 story-analyst、shot-director、frame-designer、h3-compiler、h3-validator；不得虚构任何 worker 输出。
2. 每阶段运行本地 deterministic gate 并保存 gate 报告。
3. 若静态媒体尚未生成，按契约返回 MEDIA_WAIT，不要伪造媒体；仍需保存所有已通过的中间产物和 image jobs。
4. 此次运行独立目录固定为：`/home/openclaw/.openclaw/workspace-video-pipeline/outputs/2026-09-05-elevator-kitchen-retest/`
5. 将每个阶段的原始 JSON、gate 报告、pipeline state，以及最终经过 result gate 的 JSON 全部复制或写入该目录；最终文件固定为 `final-result.json`。
6. 结束前确认 `final-result.json` 可读且通过 result gate。
7. 最终只返回 AGENTS.md 所要求的单个原始 JSON 对象。
