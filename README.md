# 频谱观测与覆盖统计

主子方向为数据分析与数据应用。工程测量团队需要区分某个频段的可观测活动、仪器设置导致的观测盲区和现场测试信号。仓库使用离线模拟扫频产物、站点检查记录与人工复核标签，交付覆盖事实和分析结果。

这是可运行的最小数据基线，只实现下表列明的能力。仅处理合成扫频记录和人工标注，不调用设备、访问站点或发射信号。

| 数据链 | 基线能力 | 离线样例 | 可核验结果 |
|---|---|---|---|
| `sweep-coverage` | 把模拟扫频批次拆成覆盖来源一致的频段，保留漏扫与粗测区间。 | [输入](examples/sweep-coverage.json) | [结果](tests/expected/sweep-coverage.json) |
| `scheduled-occupancy` | 仅用定时等间隔采样估计占用率，另留触发采样记录。 | [输入](examples/scheduled-occupancy.json) | [结果](tests/expected/scheduled-occupancy.json) |
| `site-check` | 以离线校验标记与对应读数区分通过、失败、无读数和未执行。 | [输入](examples/site-check.json) | [结果](tests/expected/site-check.json) |
| `event-windows` | 按人工事件标记归并频段范围，保留与其他事件交叠的复核线索。 | [输入](examples/event-windows.json) | [结果](tests/expected/event-windows.json) |
| `receiver-range` | 按接收设置核对同标度读数，分开可用背景、过载和低于有效量程的读数。 | [输入](examples/receiver-range.json) | [结果](tests/expected/receiver-range.json) |

## 运行

在仓库根目录使用 Python 3.11 及以上版本，无需安装运行依赖：

```sh
python3 -m spectrum_observation_evidence sweep-coverage examples/sweep-coverage.json
python3 -m spectrum_observation_evidence sweep-coverage examples/sweep-coverage.json --sqlite facts.sqlite
python3 -m unittest discover -s tests -v
```

每个输入文件包含 `records` 数组，记录的 `id` 在批内唯一。各数据链校验自己的业务字段，输出按 `fact_id` 标识的事实。起止范围若无另行说明均为左闭右开；日期、深度、金额和持续时间等单位由字段标明。

加上 `--sqlite` 时，`runs` 表保存规范化的来源 JSON 与 SHA-256，`facts` 表保存同一批次的事实。原样重放不新增事实；写入失败回滚整批。既有数据库不会被自动改写为不同版本的处理结果。JSON 接口和入库只是数据处理的运行入口，不是仓库的业务主体。
