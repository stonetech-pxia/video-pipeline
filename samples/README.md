# 测试固定件

| 文件 | 用途 |
|---|---|
| `envelope-short.json` | 短片：5 场 / 240 秒 / 便利店重逢。走单次调用 `run-story-analyst.sh` |
| `envelope-long.json` | 长片：14 场 / 1200 秒 /《回声》。走分块 `run-story-analyst-chunked.sh` |
| `story-ir-v2-sample.json` | 短片的合格输出（validator 通过），作为 v2 契约的参考样例 |
| `runs/` | 历史运行的中间产物，用于排查 |

跑法：

    ./run-story-analyst.sh          samples/envelope-short.json out.json
    ./run-story-analyst-chunked.sh  samples/envelope-long.json  out.json
