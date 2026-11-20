# 频谱观测与覆盖统计

主子方向为数据分析与数据应用。工程测量团队需要区分某个频段的可观测活动、仪器设置导致的观测盲区和现场测试信号。仓库使用离线模拟扫频产物、站点检查记录与人工复核标签，交付覆盖事实和分析结果。

这是可运行的最小数据基线，只实现下表列明的能力。仅处理合成扫频记录和人工标注，不调用设备、访问站点或发射信号。

| 数据链 | 基线能力 | 离线样例 | 可核验结果 |
|---|---|---|---|
| `sweep-coverage` | 把模拟扫频批次拆成覆盖来源一致的频段，保留漏扫与粗测区间及其分辨率。 | [输入](examples/sweep-coverage.json) | [结果](tests/expected/sweep-coverage.json) |
| `scheduled-occupancy` | 以计划时频范围为分母，用定时读数的量程证据给出占用上下界，另留触发采样记录。 | [输入](examples/scheduled-occupancy.json) | [结果](tests/expected/scheduled-occupancy.json) |
| `site-check` | 以离线校验标记与对应读数区分通过、失败、无读数和未执行。 | [输入](examples/site-check.json) | [结果](tests/expected/site-check.json) |
| `event-windows` | 按人工事件标记归并频段范围，保留与其他事件交叠的复核线索。 | [输入](examples/event-windows.json) | [结果](tests/expected/event-windows.json) |
| `receiver-range` | 按接收设置核对同标度读数，为每条读数保留可比较测值或有依据的单侧界限。 | [输入](examples/receiver-range.json) | [结果](tests/expected/receiver-range.json) |

## 量程证据与占用界限

离线量程核查（`receiver-range`）为每条读数给出 `status`、`comparable_level` 和
`lower_bound`/`upper_bound`：

- `usable`：量程内，读数本身就是精确可比较测值，上下界都等于它。
- `clipped`：过载或读数达到量程上限，不能当精确值；只有量程上限给出的下界。
- `below-range`：低于有效量程；只有量程下限给出的上界。
- `no-range-basis`：没有同标度的接收设置，不能猜界限，三项证据都为空。

`scheduled-occupancy` 在计划范围 `plan`（起止秒与起止 kHz）上按读数边界切分时频
单元，分母是 `(end_s - start_s) × (high_khz - low_khz)`。同一部分即使被重叠测到
多次也只计一次。读数可用 `range_evidence` 引用上面的量程核查结果，也可自带
`lower_bound`/`upper_bound`，或按自带 `setup` 与 `settings` 换算。每个单元归为：

| 状态 | 含义 | 计入下界 | 计入分母后扣除 |
|---|---|---|---|
| `occupied` | 分辨率足够的定时读数一致肯定占用（下界严格大于门槛） | 是 | — |
| `not-occupied` | 分辨率足够的定时读数一致肯定未占用（上界不超过门槛） | — | 是 |
| `conflict` | 肯定占用与肯定未占用相撞，保留冲突 | — | — |
| `insufficient-resolution` | 定时读数粗于 `required_bin_khz`，不能证明其未分辨的子带 | — | — |
| `inconclusive` | 有定时读数但量程或界限不足；读数逐条给出 `reasons` | — | — |
| `trigger-only` | 只有触发补测覆盖，不能代替定时样本 | — | — |
| `no-scheduled-evidence` | 计划内没有定时读数覆盖 | — | — |

因此 `lower` 只累计一致证据的确定占用，`upper = 分母 − 一致证据的确定未占用`。
`conflict`、`insufficient-resolution`、`inconclusive`、`trigger-only` 和
`no-scheduled-evidence` 都留在上下界之间，不会因缺值被算成空闲。输出按状态与
分辨率合并成时频矩形，每个矩形带 `area_khz_s` 和可追溯的读数、分辨率或原因，
不展开为逐时刻逐频点明细。触发读数另列在 `trigger_readings`，只解释活动。

`sweep-coverage` 的每个频段给出 `resolution_khz`、`fine_sweeps`、`coarse_sweeps`
和 `reason`。粗扫覆盖的频段仍保留在 `sweeps` 与 `coarse_sweeps` 里，不能证明它
未分辨的指定子带；`missing` 表示整段没有扫到。

## 运行

在仓库根目录使用 Python 3.11 及以上版本，无需安装运行依赖：

```sh
python3 -m spectrum_observation_evidence sweep-coverage examples/sweep-coverage.json
python3 -m spectrum_observation_evidence sweep-coverage examples/sweep-coverage.json --sqlite facts.sqlite
python3 -m unittest discover -s tests -v
```

每个输入文件包含 `records` 数组，记录的 `id` 在批内唯一。各数据链校验自己的业务字段，输出按 `fact_id` 标识的事实。起止范围若无另行说明均为左闭右开；日期、深度、金额和持续时间等单位由字段标明。

`scheduled-occupancy` 的旧版输入（只有 `slot` 与 `occupied`、没有 `plan`）仍按等间隔计数
输出 `scheduled_count`/`occupied_count`/`observed_fraction`；提供 `plan` 时给出上述
时频界限。

加上 `--sqlite` 时，`runs` 表保存规范化的来源 JSON 与 SHA-256，`facts` 表保存同一批次的事实。原样重放不新增事实；写入失败回滚整批。既有数据库不会被自动改写为不同版本的处理结果。JSON 接口和入库只是数据处理的运行入口，不是仓库的业务主体。
