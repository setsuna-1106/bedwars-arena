# L1 P9：集成验收（进行中）

P9 按[固定清单](acceptance-scenarios.md)运行标准初始状态的 40 局：seed 101–110，各 seed 的 A–D 四种独立席位配置。用户选择每局外部上限 1100 tick；到达上限没有自然结果的局按截断记录，不能当作平局或胜负。此上限仅用于本次矩阵，不改变规则档案的 Game End 时刻。

```bash
# 新目录；每局顺序运行，保留完整 P7 记录和逐局性能数据
python examples/l1-p9-matrix.py artifacts/l1-p9-matrix --limit 1100

# 如果进程中断，只有匹配原配置和运行时的已完成记录会被复用
python examples/l1-p9-matrix.py artifacts/l1-p9-matrix --limit 1100 --resume

# 可在串行进程停止后继续：最多两个独立世界进程，不修改局内顺序
python examples/l1-p9-parallel.py artifacts/l1-p9-matrix

# 从两个索引快照核对同一局剩余的输入、状态和事实
python examples/l1-p9-verify.py artifacts/l1-p9-matrix/101-A artifacts/l1-p9-matrix/101-A-replay-check.json

# 40 局和四个预选样本重放均完成后，重新核对输入哈希及事实计数并汇总
python examples/l1-p9-report.py artifacts/l1-p9-matrix artifacts/l1-p9-matrix/audit.json
```

每局的 `manifest.json` 保留策略名称/版本、seed、定义和代码哈希；`matrix-row.json` 另记会话席位、外部截断、故障/备用动作、事实计数、完整决策序列哈希、模拟/写盘墙钟、进程峰值内存和记录大小。`matrix-summary.json` 逐局更新。配置及运行时不匹配、或已存在的局缺少完整记录时不继续复用；中断后尚未发布的局需重新运行。E1/E2、D1/D2 分别是同一种确定性策略的独立会话，即使完整执行了两个配置，完全相同的决策序列也不视为独立随机样本。

先按固定顺序串行运行标准局和快照重放；随后允许两个不同案例同时运行，以缩短 40 局墙钟。每个案例仍由单进程逐 tick 模拟并执行全部规则校验。独立短测中，同一 seed/席位的一个串行进程与两个同时运行的进程各推进 50 tick，输入、轮次、事实、逐 tick 帧和最终快照的文件哈希一致，且无备用动作；该检查不承诺在所有系统负载下逐位一致。并发期间的逐局墙钟和峰值内存是单进程测量，不应相加作为整机精确峰值；同步运行其他重放/测试也可能影响墙钟。

## 受控功能验收

当前代码的 [P6 受控预置](../../examples/l1-controlled-2v2.json)在 seed 101 于 tick 752 自然结束，红队获胜；发生 6 次购买、22 次放置、1 次玩家破床、2 次最终淘汰。该预置双方初始资源、护甲和生命值不对称，不是策略强度对比。完整记录已从初始快照逐 tick 核对至终局（752 tick、226 条后续事实），并导出离线页面；本机输出为 `artifacts/l1-p9-controlled-101-v2/`，按项目约定不提交。

世界级无效任务和工作量超限故障注入见 `tests/test_l1_delivery_faults.py`；策略异常、错误输入、容量超限与提交故障、已封口输入、等待复活、持续拆除和满包回收分别有其他既有测试，详见[验收场景](acceptance-scenarios.md)。故障不发布半个 tick；先前阶段可能已经在内部提交，不能误称整 tick 回滚。

2026-10-28 从仓库外 Python 3.12 独立环境安装 wheel 后，成功加载三份定义；标准开局运行 4 tick 后按时限截断。另从绝对路径加载 [P8 受控预置](../../examples/l1-ppo-controlled-2v2.json)，脚本对局在 tick 11 自然终结，11 tick 重放通过并导出 HTML；预置的蓝床开局已毁且双方条件不对称。训练依赖的独立环境和限制见 [P8](p8-training.md)。真实浏览器视觉验收仍受应用内浏览器本地文件安全限制；离线 UI 逻辑检查通过，不宣称真人浏览器已验证。

## 待完成

标准矩阵、四个预选样本的早/中快照重放和最终汇总尚在执行；完成前不宣称 G4 已通过。
