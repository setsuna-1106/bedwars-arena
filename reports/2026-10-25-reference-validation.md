# 调研结果的轻量验证与参考优先级

日期：2026-10-25（北京时间）。基于[原调研报告](2026-10-25-project-survey.md)，结合目前 Python 工程骨架验证。以下是参考建议，尚未采用具体仿真底座。

## 1. 哪些内容最值得参考

| 优先级 | 项目 | 值得参考的具体内容 | 本次验证与结论 |
| --- | --- | --- | --- |
| 高 | PettingZoo | 多 Agent 的观测/行动字典、联合 step、终止与截断、接口合规测试 | 1.27.0 已运行；等待复活的接口样例通过官方 Parallel API 测试，错误的“终止后复活”被拒绝。适合优先借用接口约定 |
| 高 | Blockyard | 床→死亡→复活→永久淘汰→队伍终局的状态机，无头核心与展示分离 | 固定提交源码复核；机制具体、边界案例有价值。适合提炼规则，未试跑完整项目 |
| 高 | Lux S2 | 外部策略的进程生命周期、stdin/stdout 通信、同时收集动作的调度结构 | 原版 BotProcess 模块完成两个独立进程的 JSON 交互；适合借鉴运行器结构，整个运行器仍有 Lux/两方对局耦合 |
| 中高 | bots | 小型外部 Bot 协议、局部视野、跨语言策略入口 | 固定提交编译通过，两个 TCP 客户端收发 5×5 观测和行动成功。适合读懂最小接入闭环 |
| 条件性高 | Lab2D | 二维网格、Lua 定义机制、多玩家动作和观测 | 1.0.2 的 clean_up 双玩家环境无窗口运行 50 步，同种子和动作序列的被测输出一致。若确定采用格子世界，值得做底座对照 |
| 中 | MAgent2 | 局部观测通道、移动/攻击动作、同轮多 Agent 结算、战斗测试 | 0.3.4 的 battle_v4 四 Agent 环境跑通 40 步并通过官方 Parallel API 测试。战斗子模块参考价值明确，未验证完整 BedWars 改造 |

建议当前先读 **PettingZoo 的接口测试、Blockyard 的死亡/床状态机、Lux 的进程与对局代码**。bots 用于理解最简远程协议。暂不需要把这些项目都引入依赖。

## 2. 验证范围

- 本机：macOS 27.0、ARM64、Python 3.13.15、Apple Clang 17。
- 独立虚拟环境位于 artifacts/research-validation-2026-10-25/venv；未修改主环境或 pyproject.toml 的运行依赖。
- 安装固定发布版：PettingZoo 1.27.0、Gymnasium 1.4.0、dmlab2d 1.0.2、MAgent2 0.3.4。原调研核查的是默认分支提交；本轮二进制包验证不能替代对默认分支的构建验证。
- bots 固定为 3ce66349ee2e239dd0ac79d1d7ec455e682c5c64；Lux 模块固定为 5bcb3c775d536cecda32a3c041a9814279b79c5b；教程与 Blockyard 沿用原调研固定提交。
- 本轮是启动、交互、接口和短轨迹检查；没有测吞吐量、内存或训练效果，没有运行 BedWars 完整对局，也未证明跨平台或长期确定性。
- 机器可读证据见[验证结果](2026-10-25-validation-results.json)，探针见[验证脚本](../scripts/research_validation.py)。下载源码、完整日志和初次探针结果保留在本地 artifacts/research-validation-2026-10-25/，默认不提交。

## 3. 关键验证结果

### PettingZoo：接口值得采用，教程不能直接照搬

本轮编写了一个只有“行动—等待—返回—结束”的双 Agent 验证样例，它不包含 BedWars 规则。等待期间保留 Agent 并只允许 NOOP，最后统一终止；该样例通过官方 parallel_api_test。另一个故意在 termination=True 后重新加入相同 Agent 的错误样例，被测试以 agent cannot be revived once dead 拒绝。

**可参考的设计：** 暂时死亡/等待复活应与永久淘汰分开；具体动作、观测和耗时仍由本项目定义。接口合规测试适合成为未来引擎适配器的检查项。见[官方测试实现](https://github.com/Farama-Foundation/PettingZoo/blob/b0fe02166d2106f8fcb6a6e0ca8125765699bdba/pettingzoo/test/parallel_test.py)。

还实跑了调研中引用的[动作遮罩教程](https://github.com/Farama-Foundation/PettingZoo/blob/b0fe02166d2106f8fcb6a6e0ca8125765699bdba/tutorials/CustomEnvironment/tutorial3_action_masking.py)，确认两个问题：

1. 同一环境连续 12 次 reset(seed=17)，出现 **9 种不同初始位置组合**。源码使用全局 random.randint，未应用传入 seed；本次测试只在整组开始时调用一次 random.seed(123)。
2. 返回的观测是含 observation/action_mask 的字典，observation_space 却声明为 MultiDiscrete；实际 contains 返回 false。

因此推荐的是 Parallel API 与测试工具。教程中的遮罩思路可读，随机源和空间声明需修正，不能作为已经合规且可复现的完整模板。

### Lab2D：网格底座候选已具备本机运行证据

直接安装 ARM64 wheel，无需本地编译 C++。clean_up 设置 numPlayers=2，获得两组带 1./2. 前缀的动作，以及各玩家 POSITION、RGB 等观测；统一提交动作向量后推进一次世界。

固定动作生成方式，种子 17 重复两次的 50 步观测、奖励和状态标记轨迹一致；换种子 18 时被测轨迹不同。**这只验证这些输出，未覆盖引擎全部内部状态。** 使用方式参照[官方 Python 包装器](https://github.com/google-deepmind/lab2d/blob/f6de2d6e40e476093b6413cd496137ad8fd8d3d5/dmlab2d/__init__.py)和[运行示例](https://github.com/google-deepmind/lab2d/blob/f6de2d6e40e476093b6413cd496137ad8fd8d3d5/dmlab2d/random_agent.py)。

值得参考的是“关卡机制用 Lua 描述，外部算法经 Python 接口提交动作”。能否减少 BedWars 开发量，仍需一个包含床、复活和可建造地形的小关卡验证；本轮未完成这一步。

### MAgent2：战斗与局部观测值得参考

battle_v4 配置 map_size=12、max_cycles=40，初始四个 Agent，观测形状为 13×13×5，动作空间 Discrete(21)。通过官方 parallel_api_test，并可无窗口运行至 40 步结束。

两次 seed=17、同动作生成方式的观测、奖励、生命周期与公开 state() 轨迹一致。换 seed=18 也产生相同被测轨迹；这不是失败条件：该样例地图按固定几何位置放置双方，不能要求任何环境换 seed 必须变化。源码见[battle 的地图与规则](https://github.com/Farama-Foundation/MAgent2/blob/f3fca5a78504615986dfba37d85137c9e15d1db6/magent2/environments/battle/battle.py)。

发布包 0.3.4 的 PyPI 元数据要求 Python >=3.10；原调研所查默认分支要求 >=3.11。二者并不矛盾，选依赖时应以实际版本为准。见[固定发布元数据](https://pypi.org/pypi/magent2/0.3.4/json)。

### Lux S2：进程接入值得参考，整体移植仍需改造

在隔离目录加载未经改动的 process.py、logger.py 和 globals.py，启动两个真实 Python 子进程；每个子进程读取 JSON 行并返回行动，两个不同 PID 均正确响应。调用方增加 asyncio.wait_for 后，延迟响应的策略触发超时，随后清理子进程。**该超时保护来自验证脚本，不能说 BotProcess 本身已提供完整超时策略。** 见[进程模块](https://github.com/Lux-AI-Challenge/Lux-Design-S2/blob/5bcb3c775d536cecda32a3c041a9814279b79c5b/luxai_s2/luxai_runner/process.py)。

值得参考的顺序是：先理解进程通信，再读[Episode 的动作收集与 step](https://github.com/Lux-AI-Challenge/Lux-Design-S2/blob/5bcb3c775d536cecda32a3c041a9814279b79c5b/luxai_s2/luxai_runner/episode.py)。其中硬编码两位参赛者、Lux 专用观测差分和状态结构仍需抽离；本轮未安装或运行完整 Lux 游戏、锦标赛和回放。

### bots：最小外部策略闭环确实可用

使用原 Makefile 编译服务端，启动 training 模式，以两个本机 TCP 客户端接入，读取各自 5×5 视野，分别发送转向指令并收到下一次视野。见[服务端构建文件](https://github.com/markusfisch/bots/blob/3ce66349ee2e239dd0ac79d1d7ec455e682c5c64/server/Makefile)、[观测发送](https://github.com/markusfisch/bots/blob/3ce66349ee2e239dd0ac79d1d7ec455e682c5c64/server/player.c)、[命令与回合推进](https://github.com/markusfisch/bots/blob/3ce66349ee2e239dd0ac79d1d7ec455e682c5c64/server/game.c)。

它的协议足够小，适合作为第一个外部策略接口的阅读材料。但没有 match_id、tick、结构化行动或完整版本协商；按到达命令执行与墙钟超时也不同于固定批次结算。本轮未验证 WebSocket、锦标赛或全局确定性。

## 4. Blockyard 中最有价值、也最需要筛选的规则

复核固定提交的[BedWars 服务端](https://github.com/Potrock/blockyard/blob/7daddbec178997236d664bc29975d49801574332/src/games/bedwars/server.ts#L133-L251)，以下逻辑可以用来整理本项目规则表和边界测试：

- 床仍存在时死亡，安排 respawnAt；床已不存在时死亡，标记永久出局。
- 玩家处于复活等待中也计入 standing，避免把暂时无人存活的队伍直接淘汰。
- 床被拆除时，取消本队仍在等待中的复活，再检查队伍是否淘汰。
- 区分玩家永久淘汰与队伍淘汰，床数不能独立决定胜者。

这些是 **Blockyard 当前版本的规则选择**，不是本项目已确认规则，也未据此断言与 Hypixel 完全一致。

后续用户明确以 Hypixel 为现实参照，新增[规则调研](2026-10-25-hypixel-bedwars-rules.md)发现：Hypixel v0.3 官方补丁明确不再因等待复活期间床被拆而淘汰玩家，与上述 Blockyard 取消复活的做法有差异。该段只能作为状态机参考；当前 Hypixel 的边界时序还需实测。[Hypixel 原始补丁](https://hypixel.net/threads/new-bed-wars-patch-v0-3-now-live-in-the-ptl.979320/)

还发现一个面向真人游戏的终局捷径：eliminate 在剩余队伍中已经没有真人 Player 时也会结束对局，即使剩余队伍超过一支。用于纯 Bot 实验时需要重新审视这个条件，不能原样沿用。[对应源码](https://github.com/Potrock/blockyard/blob/7daddbec178997236d664bc29975d49801574332/src/games/bedwars/server.ts#L187-L201)

原调研指出的爆炸路径 Math.random、短片段回放与当前方块状态限制仍然存在，本轮未实测相关差异。其三维物理与表现系统也无需随规则参考一起引入。

## 5. 其余资料如何处理

| 项目 | 当前用途 |
| --- | --- |
| BedWars1058、Screaming BedWars | 规则细节和事件清单的交叉对照；本轮未启动 Minecraft 服务端，参考价值沿用原调研证据 |
| Grid Universe | 阅读 Python 状态/组件组织；现成接口偏单 Agent，暂不优先改造 |
| Minecraft-Bedwars-AI | 不作为核心起点；前向模拟空实现、空间抽象和许可不明问题未解除 |
| MicroRTS 系列 | 历史设计参考；未启动旧依赖栈 |
| FastAPI、OpenEnv、PixiJS | 远程接入、部署或展示出现具体需求时再选；本轮未试跑 |

## 6. 复核方式与剩余问题

依赖冻结记录在本地 artifacts/research-validation-2026-10-25/requirements.freeze.txt；验证结果 JSON 保留包版本、源文件和归档哈希。当前环境可重复执行：

```bash
artifacts/research-validation-2026-10-25/venv/bin/python scripts/research_validation.py
```

脚本依赖已下载至该 artifacts 目录的上游文件；全新检出需要按 JSON 中的固定来源重新准备，不能只在主环境直接运行。运行 bots 部分需要本地监听端口。

初次探针中的两处检查已修正：TCP 客户端最初只等一秒，与服务端的一秒开局等待冲突；MAgent2 最初被错误要求换 seed 后必须改变轨迹。这两项属于验证脚本问题，未作为上游缺陷。

下一步最有区分力的是：确定二维模型后，用同一份最小规则和接口，比较自建 Python 核心与 Lab2D 小关卡的实现复杂度。当前没有理由仅凭这些冒烟结果决定整体移植任何一个项目。
