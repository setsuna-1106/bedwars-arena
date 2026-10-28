# 接入示例

[L1 受控对局预置](l1-controlled-2v2.json)用于验证购物、搭桥、破床和最终淘汰：红队预持铁和一档防具，蓝队初始 HP 降低，属于不对称功能测试。运行命令和标准对局入口见 [P6 Runner](../docs/l1/p6-runner.md)。

策略使用公开观测并返回请求列表，Runner 负责对局身份、轮次封口和逐 tick 推进。[P7 受控演示](l1-p7-showcase.py)生成可定位回收、失床后淘汰与碰撞的离线回放；[四样本重放脚本](l1-p7-four-matches.py)按计划检查不同席位和快照边界。[PPO 受控 2v2 预置](l1-ppo-controlled-2v2.json)及[单世界吞吐测量](l1-benchmark.py)用于 P8 功能验收；训练、恢复命令和不对称预置限制见 [P8 说明](../docs/l1/p8-training.md)。独立进程策略接入仍待后续工作。

P9 的[矩阵运行](l1-p9-matrix.py)、[双进程调度](l1-p9-parallel.py)、[快照重放](l1-p9-verify.py)和[结果审计](l1-p9-report.py)示例及实际结果见 [P9 说明](../docs/l1/p9-delivery.md)。并行仅用于独立世界，不改变同局内规则顺序。
