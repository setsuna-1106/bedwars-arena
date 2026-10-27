# BedWars Arena：现有项目调研与适配性评估

调研时间：2026-10-24—2026-10-25（北京时间）  
输入：项目根目录的 bedwars_sim_research_resources.md 与用户确认的核心目标。  
状态：技术调研；以下选型建议尚未作为项目实现方案。

后续已完成一轮[轻量运行验证与参考筛选](2026-10-25-reference-validation.md)。本文保留原轮文档/源码调研的证据范围，运行结果以该补充报告为准。

## 1. 结论

在本次核查的范围内，**尚未找到能够直接满足“二维 BedWars 规则 + 外部多智能体决策接口 + 可重复批量实验”的完整现成平台**。可以直接采用的部分主要是接口库、通信库和渲染库；BedWars 规则与多智能体对局调度仍需开发或显著改造。

我的建议是将后续验证集中在两条路线：

1. **自行实现规则核心，接 PettingZoo Parallel API。** 适合需要掌握规则、观测边界和复现机制的项目。可先用 Python 验证；实际性能达不到目标时，再定位和替换热点。这里的优先级是工程判断，并无本次实测吞吐量支持。
2. **若二维最终采用格子世界，验证 Lab2D 能否降低底层开发量。** 它有现成二维世界与多智能体接口，但 BedWars 规则要用 Lua 等机制实现，仍需自行补运行器、协议和回放。

架构参考优先读 Lux S2 的进程运行器与 bots 的远程 Bot 协议；BedWars 机制优先参考 Blockyard 和两个 Minecraft 服务端插件。MAgent2 可用于战斗子问题，当前证据不足以把它列为完整 BedWars 的首选底座。

这份结论只覆盖下列仓库与补充检索，不代表穷尽全网项目。

## 2. 核查方法与证据边界

- 核查原索引对应的 **16 个仓库**；另外检查 2 个名称直接相关的二维候选，以及 MicroRTS-Py 实际引用的 Farama MicroRTS 仓库，共 **19 个仓库**。
- 使用仓库元数据、默认分支提交、README、许可证文件、关键源文件和官方 API 文档。核心候选按关键路径抽查，未逐行审计整个代码库。
- 文中“源码确认”表示检查了所引文件中的相关逻辑；“文档说明”表示维护者的公开描述；“适配判断”是针对本项目的推断。
- **本次没有安装这些项目、运行其测试或执行性能基准。** 上游存在测试文件、CI 配置和发布包，不代表这些测试已在本机通过。
- 提交日期采用 UTC；固定链接指向核查时默认分支的提交。GitHub 的 pushed_at 可能受其他分支或标签推送影响，表中采用默认分支最新提交日期。
- 19 个仓库本次均未被 GitHub 标记为 archived；MicroRTS 系列仍在 README 中明确宣布停更，不能用“未归档”判断维护状态。

完整元数据、提交哈希和已获取文件清单见 [来源清单](2026-10-25-source-manifest.json)。

## 3. 对原资料索引的主要修正

| 原判断需要补充之处 | 本次证据 | 对本项目的影响 |
| --- | --- | --- |
| Minecraft-Bedwars-AI 被列为优先复用候选 | 岛屿连接图；两个 minimax 行动模拟函数直接返回原状态；无明确许可证 | 降为规则抽象反例与教学参考，暂不作为核心移植起点 |
| Blockyard 有 seed 和回放 | 爆炸拆块路径仍使用 Math.random；回放主要保留短时间历史，世界方块不恢复到历史时刻 | 不能据此认定其满足确定性实验和完整对局回放 |
| MicroRTS-Py 被列为一般候选 | 2025-08-11 宣布停止更新支持；其引用的 Farama MicroRTS 同样宣布停更 | 降为历史设计参考 |
| Grid Universe 被归入多智能体引擎候选 | ECS 可存多个 agent，但默认 Gymnasium 包装器控制单个 agent，每次 step 推进世界 | 多个实体不等于已有同时行动的多智能体环境 |
| Lux S2 运行器看似可直接换游戏 | 对局代码限制两位参赛者，并读取 Lux 专用 state/env_cfg/观测差分 | 可借鉴，替换环境需要抽离游戏耦合 |
| OpenEnv 的多连接能力 | 每个客户端会话创建独立环境实例；OpenSpiel 示例向外暴露单智能体接口 | 同一场对局内的多 Agent 协调仍需设计 |
| MAgent2 README 写 Python 3.8+ | 当前默认分支 pyproject.toml 要求 Python >=3.11，CI 也已更新 | 安装和版本选择应核对构建元数据与发布版 |
| bots 的网页回放 | README 指向独立的 bots_spectator 仓库 | 回放前端并非核心仓库自带的统一 BedWars 工具 |

各项的固定源码链接见下文。

## 4. BedWars 相关项目

### 4.1 Minecraft-Bedwars-AI：不建议直接作为模拟核心

**确认的内容。** C# 项目，目标框架为 .NET 9；GameEngine 按 tick 更新世界并逐个调用玩家逻辑。Connection 仅保存桥梁当前长度与目标长度；Move 在桥完成后直接将 CurrentIsland 改为目标岛。因此这是岛屿连接图上的策略抽象，尚非可表达逐格走位、地形与搭桥路径的二维空间模型。见 [项目配置](https://github.com/tilakpatell/Minecraft-Bedwars-AI/blob/cae52f597cdbc7e69b8e817c554116c1b8b4e64d/BedwarsAI/BedwarsAI.csproj)、[Connection](https://github.com/tilakpatell/Minecraft-Bedwars-AI/blob/cae52f597cdbc7e69b8e817c554116c1b8b4e64d/BedwarsAI/Connection.cs)、[Move](https://github.com/tilakpatell/Minecraft-Bedwars-AI/blob/cae52f597cdbc7e69b8e817c554116c1b8b4e64d/BedwarsAI/Commands/Move.cs)。

**源码中的实质问题。** SimulateAction 和 SimulateEnemyAction 都原样返回传入的 GameState，没有执行行动或生成后继状态；因此不能据 README 将其当成已实现有效前向模拟的 minimax 基线。另有终局逻辑在 tick > 500 且剩余床数不超过 1 时结束游戏，即使仍有多个玩家存活，GetWinner 又取存活列表首项；这与 README 的最后幸存者胜出描述存在差异。见 [行动模拟函数](https://github.com/tilakpatell/Minecraft-Bedwars-AI/blob/cae52f597cdbc7e69b8e817c554116c1b8b4e64d/BedwarsAI/BedwarsAIAgent.cs#L1280-L1288)、[终局与胜者逻辑](https://github.com/tilakpatell/Minecraft-Bedwars-AI/blob/cae52f597cdbc7e69b8e817c554116c1b8b4e64d/BedwarsAI/GameState.cs)。

**接口与复现。** 审查的引擎和入口直接绑定内置玩家类；未发现独立外部 Agent 协议。多个策略在各自类中使用未传 seed 的 Random；Program 的批量运行以控制台统计为主。完整仓库文件树未发现明确许可证，GitHub license 字段也为空。见 [引擎](https://github.com/tilakpatell/Minecraft-Bedwars-AI/blob/cae52f597cdbc7e69b8e817c554116c1b8b4e64d/BedwarsAI/GameEngine.cs)、[运行入口](https://github.com/tilakpatell/Minecraft-Bedwars-AI/blob/cae52f597cdbc7e69b8e817c554116c1b8b4e64d/BedwarsAI/Program.cs)。

**适配判断。** 可读其资源、商店、床和命令的抽象，但直接复用会同时承担空间模型、接口、复现与规则正确性的改造。原索引的“优先审代码”现已完成，应降低其复用优先级。

### 4.2 Blockyard：BedWars 机制参考价值高，纯二维移植成本高

**确认的内容。** TypeScript 模拟层搭配 Rust/WASM 体素引擎。Sim 与 DOM/WebGL 解耦，接受各玩家输入；协议区分测试主机的 tick 命令和实时服务器的 input 命令。仓库确有 BedWars 无浏览器测试，检查 Bot 破床以及闲置玩家一方被淘汰；CI 配置包含 headless 测试。见 [模拟核心](https://github.com/Potrock/blockyard/blob/7daddbec178997236d664bc29975d49801574332/src/platform/sim/sim.ts)、[协议](https://github.com/Potrock/blockyard/blob/7daddbec178997236d664bc29975d49801574332/src/platform/net/protocol.ts#L243-L255)、[BedWars 测试](https://github.com/Potrock/blockyard/blob/7daddbec178997236d664bc29975d49801574332/tests/headless/bedwars.ts)、[CI](https://github.com/Potrock/blockyard/blob/7daddbec178997236d664bc29975d49801574332/.github/workflows/ci.yml)。

**机制与限制。** 游戏有队伍、床、复活、商店、资源、搭桥、战斗和火球等机制；使用 x/y/z 坐标、三维碰撞和体素世界。现有网络输入服务于游戏客户端；未发现专门面向本项目所需“各 Agent 观测隔离、批次动作结算、终止信号”的统一实验适配层。见 [BedWars 服务端](https://github.com/Potrock/blockyard/blob/7daddbec178997236d664bc29975d49801574332/src/games/bedwars/server.ts)、[世界与玩家配置](https://github.com/Potrock/blockyard/blob/7daddbec178997236d664bc29975d49801574332/src/games/bedwars/shared.ts)。

**复现问题需特别关注。** Sim 虽有按 seed 初始化的 RNG，但 blowBlocks 的拆块判定使用全局 Math.random；BedWars 的火球会调用世界爆炸接口，且共享配置没有启用 destructible 模式。该路径提示 seed 并未统一覆盖所有会影响状态的随机性；是否在特定回合触发差异仍需运行验证。见 [拆块随机性](https://github.com/Potrock/blockyard/blob/7daddbec178997236d664bc29975d49801574332/src/platform/sim/sim.ts#L794-L820)、[火球逻辑](https://github.com/Potrock/blockyard/blob/7daddbec178997236d664bc29975d49801574332/src/games/bedwars/fireballs.ts)、[共享配置](https://github.com/Potrock/blockyard/blob/7daddbec178997236d664bc29975d49801574332/src/games/bedwars/shared.ts)。

**回放边界。** 平台文档描述的是默认最近 8 秒、可调到 30 秒的历史及高光片段；同时明确世界方块使用当前状态，不回退到片段开始时的历史状态。因此它不能直接充当完整对局的可复现存档。见 [回放说明](https://github.com/Potrock/blockyard/blob/7daddbec178997236d664bc29975d49801574332/docs/PLATFORM.md#L1598-L1653)。

**适配判断。** 若接受三维核心和俯视呈现，可进一步评估封装；若要求真正二维规则，参考其模块边界和 BedWars 规则通常更合适。MIT；无需引入账户、成就等与当前目标无关的外围系统。

### 4.3 BedWars1058：规则与事件的参考

文档要求运行在 Spigot/Paper 及 NMS 环境。IArena 直接使用 Bukkit World、Player、Block 等类型；API 文件树包括破床、击杀、复活、资源收集、隐身药水、商店购买和队伍淘汰事件。这里的 API 服务于 Minecraft 插件扩展。见 [README](https://github.com/andrei1058/BedWars1058/blob/669872626ec4160b6896755ba1d79bbed96787fb/README.md)、[IArena](https://github.com/andrei1058/BedWars1058/blob/669872626ec4160b6896755ba1d79bbed96787fb/bedwars-api/src/main/java/com/andrei1058/bedwars/api/arena/IArena.java)、[固定版本文件树](https://github.com/andrei1058/BedWars1058/tree/669872626ec4160b6896755ba1d79bbed96787fb)。

**适配判断。** 可用来整理规则状态机与事件表；迁移到独立二维环境要重新实现服务器所承担的空间、实体与时间推进。许可证为 GPL-3.0；本报告没有进行代码移植。

### 4.4 Screaming BedWars：可配置规则与游戏生命周期参考

README 展示床、队伍、商店、生成器及多种 BedWars 变体；当前主分支对应 0.3 系列，README 特别指出 0.2 用户应查看另外的版本分支。Game 等接口使用 ScreamingSandals 自身的玩家与组件体系，构建产物是服务器插件。见 [README 与分支说明](https://github.com/ScreamingSandals/BedWars/blob/168d8e24c76e2f8ad7bafcc4071b529bb69cd554/README.md)、[Game 接口](https://github.com/ScreamingSandals/BedWars/blob/168d8e24c76e2f8ad7bafcc4071b529bb69cd554/api/src/main/java/org/screamingsandals/bedwars/api/game/Game.java)。

**适配判断。** 适合参考可配置生成器、商店、阶段事件和游戏生命周期；仍不能直接替代独立二维核心。许可证为 LGPL-3.0；规则取舍仍应由本项目定义，不能把某一个插件版本自动视为 BedWars 唯一标准。

## 5. 二维引擎与竞赛平台

### 5.1 Lux AI Season 2：优先参考运行器，不能直接视作通用底座

运行器确有独立进程 Agent、并发收集动作、对局 seed、JSON/HTML 回放、锦标赛与 Elo 统计。进程通信通过 stdin/stdout，README 提供多语言 starter kits。见 [运行器说明](https://github.com/Lux-AI-Challenge/Lux-Design-S2/blob/5bcb3c775d536cecda32a3c041a9814279b79c5b/luxai_s2/luxai_runner/README.md)、[进程通信](https://github.com/Lux-AI-Challenge/Lux-Design-S2/blob/5bcb3c775d536cecda32a3c041a9814279b79c5b/luxai_s2/luxai_runner/process.py)。

Episode.run 明确要求两位参赛者，并依赖 env.state.env_cfg、get_compressed_obs、get_change_obs 等 Lux 专用结构；它能同时收集两方动作后调用一次 env.step，但不等于任意人数或任意游戏可直接接入。原项目是两方控制许多单位的竞赛，和“每位 BedWars 玩家各自接一个外部算法”也有接口粒度差别。见 [对局代码](https://github.com/Lux-AI-Challenge/Lux-Design-S2/blob/5bcb3c775d536cecda32a3c041a9814279b79c5b/luxai_s2/luxai_runner/episode.py#L92-L174)。

**适配判断。** 借鉴运行流程、超时处理与回放组织；要抽离 Lux 的状态结构和参赛人数假设。默认分支最新提交为 2023 年；README 仍建议 Python >=3.8 且 <3.11。根 LICENSE 为 Apache-2.0，但 setup.py 的 license 字段写 MIT，存在元数据不一致，复制具体模块前需要核对。见 [README](https://github.com/Lux-AI-Challenge/Lux-Design-S2/blob/5bcb3c775d536cecda32a3c041a9814279b79c5b/README.md)、[LICENSE](https://github.com/Lux-AI-Challenge/Lux-Design-S2/blob/5bcb3c775d536cecda32a3c041a9814279b79c5b/LICENSE)、[setup.py](https://github.com/Lux-AI-Challenge/Lux-Design-S2/blob/5bcb3c775d536cecda32a3c041a9814279b79c5b/luxai_s2/setup.py)。

### 5.2 DeepMind Lab2D：值得做格子世界原型

官方 README 确认 C++/Lua、文本地图、多智能体，以及 Python dm_env/C API。Lua 生命周期包括 start(episode, seed)、动作接收、advance(frame) 和观测规范，能承载独立游戏规则。见 [README](https://github.com/google-deepmind/lab2d/blob/f6de2d6e40e476093b6413cd496137ad8fd8d3d5/README.md)、[Lua API](https://github.com/google-deepmind/lab2d/blob/f6de2d6e40e476093b6413cd496137ad8fd8d3d5/docs/lua_levels_api.md)。

**适配判断。** 如果项目采用格子地图，它可提供世界与更新基础；床、复活、商店、资源、地形建造、外部多 Agent 调度及实验回放仍要实现。它不是现成 BedWars，也不是网络比赛服务。

**本机环境线索。** 当前构建工作流已包含 macOS ARM64 与 Python 3.11—3.14，README 也说明有 Linux/macOS wheel；具体 Python/系统组合能否安装和实际运行，本次未验证。见 [wheel 工作流](https://github.com/google-deepmind/lab2d/blob/f6de2d6e40e476093b6413cd496137ad8fd8d3d5/.github/workflows/make_wheel.yml#L18-L30)。许可证为 Apache-2.0。

### 5.3 MAgent2：大量 Agent 战斗适配好，完整 BedWars 需要较多扩展

源码确认原生二维 GridWorld、按组管理实体、局部观测及战斗参数；PettingZoo 包装器收集各 Agent 动作后调用一次底层 step。Battle 配置可设置生命、速度、视野、攻击范围和奖励。见 [GridWorld](https://github.com/Farama-Foundation/MAgent2/blob/f3fca5a78504615986dfba37d85137c9e15d1db6/magent2/gridworld.py)、[并行 step](https://github.com/Farama-Foundation/MAgent2/blob/f3fca5a78504615986dfba37d85137c9e15d1db6/magent2/environments/magent_env.py#L257-L290)、[Battle 配置](https://github.com/Farama-Foundation/MAgent2/blob/f3fca5a78504615986dfba37d85137c9e15d1db6/magent2/builtin/config/battle.py)。

**适配判断。** 适合先研究集群战斗、追逐和局部协作。库存、购买、复活、可建造地形与床的长期状态不在已审查的 Battle 模型中，是否需要改底层 C++ 要逐机制确认，不能当成几个配置项即可获得完整 BedWars。

默认分支 pyproject.toml 要求 Python >=3.11，和 README 的 3.8+ 描述不一致；CI 含 macOS ARM64，仍需区别开发分支和所安装发布版。见 [构建元数据](https://github.com/Farama-Foundation/MAgent2/blob/f3fca5a78504615986dfba37d85137c9e15d1db6/pyproject.toml)、[CI](https://github.com/Farama-Foundation/MAgent2/blob/f3fca5a78504615986dfba37d85137c9e15d1db6/.github/workflows/build-test-publish.yml)。许可证为 MIT。

### 5.4 MicroRTS-Py / microRTS：保留作历史参考，退出新项目核心候选

MicroRTS-Py README 首部明确宣布自 2025-08-11 起停止更新和支持。其 .gitmodules 引用 Farama-Foundation/MicroRTS，该仓库 README 同样宣布停更；原索引中的 vwxyzjn/microrts 是另一个较早的代码分支，并非此时包装器配置的子模块地址。见 [MicroRTS-Py 停更声明](https://github.com/Farama-Foundation/MicroRTS-Py/blob/91ae6f54c92d5f97abb34bcaff3013adc51cb687/README.md)、[实际子模块地址](https://github.com/Farama-Foundation/MicroRTS-Py/blob/91ae6f54c92d5f97abb34bcaff3013adc51cb687/.gitmodules)、[Farama MicroRTS 停更声明](https://github.com/Farama-Foundation/MicroRTS/blob/72f2fd94039adf3323f4591947e98661a572f927/README.md)、[原索引分支](https://github.com/vwxyzjn/microrts/tree/67664cb0f19d9bd1177d09dbea064dfd9b878ce7)。

**仍有参考价值。** 底层 RTS 有持续动作、同时发令、全局/局部观测等设计；可阅读动作表示、观测通道和批量评估思路。它的单位生产与基地经济仍需改成 BedWars 玩家生命周期。

**适配判断。** 不建议为本项目承担旧 Java/Python/Gym 依赖栈的维护成本。包装器 LICENSE 为 MIT；两个所查 Java 仓库为 GPL-3.0，不能把包装器的许可标签推广到全部代码。

### 5.5 Grid Universe：轻量 ECS 参考，现成接口侧重单智能体

README 与代码显示 Python ECS、可配置机制、Gymnasium 包装器和图像/符号观测。核心 step 接收一个 action 和可选 agent_id，默认选第一个 agent；每次调用推进世界。GridUniverseEnv 在 reset 时选定一个 agent_id，step 也是单个动作。见 [核心 step](https://github.com/grid-universe/grid-universe/blob/28615fa1b570b7ccdd5f56d86ca200baffa06d2c/grid_universe/step.py)、[Gymnasium 包装器](https://github.com/grid-universe/grid-universe/blob/28615fa1b570b7ccdd5f56d86ca200baffa06d2c/grid_universe/env.py)。

**适配判断。** 可以参考组件和系统的组织；将它改为同时行动的多智能体环境，需要重做批次动作处理、奖励/终局与观测接口。直接为每个玩家依次调用 step 会让世界在一轮内推进多次。项目要求 Python >=3.13；许可证为 MIT。见 [README](https://github.com/grid-universe/grid-universe/blob/28615fa1b570b7ccdd5f56d86ca200baffa06d2c/README.md)、[pyproject.toml](https://github.com/grid-universe/grid-universe/blob/28615fa1b570b7ccdd5f56d86ca200baffa06d2c/pyproject.toml)。

### 5.6 markusfisch/bots：远程多 Bot 接入的简洁参考

README 定义二维正交网格、局部视野、TCP/WebSocket 接入、单字符动作，以及超时后的回合推进；提供多语言模板。核心代码按收到的命令执行动作，包含墙钟超时，动作并非统一批次同时结算。源码有确定性 RNG 选项和 JSON 对局输出。见 [README](https://github.com/markusfisch/bots/blob/3ce66349ee2e239dd0ac79d1d7ec455e682c5c64/README.md)、[回合与命令处理](https://github.com/markusfisch/bots/blob/3ce66349ee2e239dd0ac79d1d7ec455e682c5c64/server/game.c#L402-L453)、[运行参数](https://github.com/markusfisch/bots/blob/3ce66349ee2e239dd0ac79d1d7ec455e682c5c64/server/main.c#L183-L192)。

**适配判断。** 很适合学习“小型独立引擎怎样让外部程序参赛”。不过网络到达顺序和墙钟超时会影响实际执行顺序，确定性 RNG 开关不足以单独保证整个异步对局可重现；本项目应明确动作批次、结算顺序并保存实际执行记录。

锦标赛脚本在仓库内；README 所指的 WebGL 旁观回放器为另一个项目 [bots_spectator](https://github.com/ChristianNorbertBraun/bots_spectator)，本次未进一步审查其代码。核心仓库采用 Unlicense。见 [锦标赛说明](https://github.com/markusfisch/bots/blob/3ce66349ee2e239dd0ac79d1d7ec455e682c5c64/tournament/README.md)。

## 6. API、网络与显示组件

### 6.1 PettingZoo Parallel API：最直接对应本项目的接口候选

官方接口支持每个 Agent 的观测、行动、奖励、termination、truncation 字典，以及动态 agents 列表和可选训练用全局 state。所有 Agent 提交动作后由环境一次 step 推进，符合多智能体对局的接口需求；并不自带 BedWars 引擎或网络服务。见 [官方 Parallel API](https://pettingzoo.farama.org/api/parallel/)。

**BedWars 适配中的关键点。** 当前 parallel_api_test 会检查已终止 Agent 不能重新出现。因床尚在而暂时死亡、等待复活的玩家，应在自己的环境契约里保持未终止状态，并定义等待阶段的观测和合法动作；真正永久淘汰才结束该 Agent。这是根据测试约束给出的设计建议。见 [生命周期测试](https://github.com/Farama-Foundation/PettingZoo/blob/b0fe02166d2106f8fcb6a6e0ca8125765699bdba/pettingzoo/test/parallel_test.py#L38-L64)、[动作遮罩示例](https://github.com/Farama-Foundation/PettingZoo/blob/b0fe02166d2106f8fcb6a6e0ca8125765699bdba/tutorials/CustomEnvironment/tutorial3_action_masking.py)。许可证为 MIT。

### 6.2 OpenEnv：有完整远程环境外壳，但要另做共享比赛协调

官方概念文档确认客户端—服务端模型、结构化 Action/Observation、reset/step/state、会话实例与部署方式；当前包名为 openenv。Environment 的 SUPPORTS_CONCURRENT_SESSIONS 是允许多个连接各自创建实例，不表示它们共同操作一场游戏。OpenSpiel 示例明确将多人游戏包装成单 Agent 对固定对手策略。见 [概念文档](https://github.com/openenv/OpenEnv/blob/6e5c73c0231dae82878c1a94c43e155527e26105/docs/source/guides/concepts.md)、[Environment 接口](https://github.com/openenv/OpenEnv/blob/6e5c73c0231dae82878c1a94c43e155527e26105/src/openenv/core/env_server/interfaces.py#L235-L301)、[OpenSpiel 示例](https://github.com/openenv/OpenEnv/blob/6e5c73c0231dae82878c1a94c43e155527e26105/envs/openspiel_env/server/openspiel_environment.py#L45-L59)。

**适配判断。** 如需容器隔离、远程部署和训练生态集成，它值得评估。为每名 BedWars 玩家建立独立普通会话会产生多份世界；需要共享 match controller 或单会话联合动作适配，再为各 Agent 分发观测。具体实现仍待设计。许可证为 BSD-3-Clause；它和 FastAPI 都属于外层服务方案，是否同时采用取决于实际需要。

### 6.3 FastAPI WebSocket：可直接用的通信组件

官方文档提供连接、消息收发与断开处理示例。它不定义观测、动作或游戏时钟；文档还明确示例的内存连接表只适用于单进程。见 [官方 WebSocket 文档](https://fastapi.tiangolo.com/advanced/websockets/)。

**适配判断。** 适合为自行实现的引擎提供远程接入。需要本项目另行定义 match_id、agent_id、tick、协议版本、超时与重复消息处理。单进程先验证可行；需要多进程时，再明确每场对局的状态所有权。MIT。

### 6.4 Gymnasium：随机性、空间与终局语义的基础

官方 Env 接口主要面向单智能体，明确 reset(seed)、action_space/observation_space，以及自然终止与外部时间限制的区别。还指出动作空间的随机采样需要独立设 seed。见 [官方 Env 文档](https://gymnasium.farama.org/api/env/)。

**适配判断。** 与 PettingZoo 配合使用空间类型和随机性约定；无需为了多玩家对局先强行打包成单个联合智能体。可参考其无渲染模式，但任何自定义规则中的随机源仍需自行统一。MIT。

### 6.5 PixiJS v8：可直接用的二维渲染组件

官方仓库和文档提供 WebGL/WebGPU 二维显示、精灵、图形和动画支持；当前默认分支为 dev，GitHub 最近列出的发布为 v8.22.0，二者应区分。见 [README](https://github.com/pixijs/pixijs/blob/b78ff35152f9b28fdf0289b54bc2deacd62956b6/README.md)、[v8 快速开始](https://pixijs.com/8.x/guides/getting-started/quick-start)。

**适配判断。** 适合画地图、玩家、床、资源和时间轴。它不负责 BedWars 规则、实验推进或存档；前端应消费引擎状态/事件。是否需要独立网页回放可在核心接口稳定后决定。MIT。

## 7. 补充检索：两个容易因名称而误判的项目

- **BaicaiBear/2DBedWars**：README 中的“2-Dimensional”指双维度战场（主世界与下界）和双基地，是依赖真实 Minecraft 的 Fabric 服务端模组；与纯二维空间模拟不同。GPL-3.0。见 [README](https://github.com/BaicaiBear/2DBedWars/blob/b37f6f2212db25fc409226a01417cdc6caf4326d/README.md)。
- **azuleamarelo91-cmyk/bedwars-2d**：根目录只有简短 README 与两个 HTML 文件。源码确有 Canvas 游戏、内置 Bot，另一个页面使用 PeerJS 同步玩家位置/生命；游戏循环依赖 requestAnimationFrame、DOM 和墙钟。本次未发现标准环境接口、独立无头核心或明确许可证，因此仅作为二维表现形式的参考。见 [单页源码](https://github.com/azuleamarelo91-cmyk/bedwars-2d/blob/e97e4c187e17ae23fc9841f4cb3b33bc99b1398c/index.html)、[PeerJS 页面](https://github.com/azuleamarelo91-cmyk/bedwars-2d/blob/e97e4c187e17ae23fc9841f4cb3b33bc99b1398c/bedwars%202d.html)。

补充检索使用了 Bedwars 2D、Bedwars simulator、Bedwars simulation 等查询。检索结果中的 Roblox 脚本和以真实 Minecraft 为前提的训练工具，没有纳入本项目候选排序。

## 8. 针对本项目的候选比较

下面是根据源码结构作出的适配判断；“改造量”是相对估计，并非工期或性能测量。

| 路线 | 能直接获得的能力 | 需要自行完成的主要部分 | 改造量与建议 |
| --- | --- | --- | --- |
| 自建核心 + PettingZoo | 标准多智能体接口、空间与合规检查工具 | 全部 BedWars 规则、运行器、网络适配、回放 | 自写规则多，但边界清楚；建议优先验证 |
| Lab2D + 自定义规则 | 二维格子世界、Lua 生命周期、dm_env/C API | BedWars 规则、PettingZoo/远程适配、批量运行与回放 | 中高；格子模型确定后可做对照原型 |
| MAgent2 扩展 | 网格战斗、大量 Agent、局部观测、Parallel API | 库存经济、复活、床、可建造地形等 | 对完整 BedWars 较高；战斗子环境更合适 |
| Blockyard 封装/移植 | 较完整 BedWars 玩法、3D 世界、无头架构、客户端网络 | 二维规则适配、实验 API、随机性统一、完整实验存档 | 纯二维时高；接受 3D 核心时再重评 |
| Lux S2 改造 | 外部进程调度、竞赛与回放样板 | 去除 Lux 状态耦合、扩展参赛者、全部 BedWars 规则 | 参考模块通常比整体替换更直接 |
| bots 改造 | 小型远程 Bot 服务器、局部观测、比赛输出 | 全部 BedWars 规则、动作批次和结算语义 | 协议教学与参考价值高 |
| Grid Universe 改造 | 轻量 Python ECS 与渲染 | 同时行动的多人 step、BedWars 规则及对局服务 | 可参考结构；尚无优势足以优先于自建 |
| C# Bedwars AI 改造 | 岛屿、资源、商店与命令示例 | 空间模型、规则修订、前向模拟、协议、复现 | 当前不建议作为移植起点 |
| Minecraft 插件移植 | 丰富的规则与事件实现 | 替换 Minecraft 运行时和所有世界依赖 | 只读规则参考优先 |
| MicroRTS 系列改造 | 旧 RTS 研究实现与实验思路 | 旧依赖维护及 BedWars 改造 | 不建议作为新核心 |

### 建议的下一轮验证（尚未执行）

1. 先明确二维含义：俯视格子、连续平面还是侧视带高度。这个决定直接改变 Lab2D、MAgent2 和 Blockyard 的适配价值。
2. 固定一份最小规则集和相同的观测/行动契约，再比较“自建核心”与“Lab2D 原型”。不要分别跑不同规则后比较速度。
3. 验证同 seed、同配置、同动作记录是否产生相同状态哈希；永久淘汰、等待复活、超时截断应分别覆盖。
4. 验证观测、info 和合法动作提示是否泄露视野外或隐身目标的信息。完整世界状态与发给参赛 Agent 的信息应有清晰边界。
5. 再测 2/8/16 Agent 的无界面吞吐量、100/1000 场批量开销，以及全量状态/增量事件的存储成本。当前没有这些测量结果，也未设定通过阈值。
6. 使用真实外部进程验证超时、异常退出、迟到动作和重复动作；回放需要检查床、玩家、资源与可建造地形，而不仅是画面中的玩家位置。

这些验证用于缩小实现风险，不是已确认的开发排期。

## 9. 固定版本与维护状态快照

“GitHub 最近发布”来自本次 releases 列表首项，不等于 PyPI/npm 的最新可安装包；“未列出”不表示项目没有任何分发渠道。许可证列记录根文件及 GitHub 标识，Lux 的包元数据冲突已单独列出。

| 仓库 | 默认分支 | 最新默认分支提交日期（UTC） | 固定提交 | 根许可证 | GitHub 最近发布 |
| --- | --- | --- | --- | --- | --- |
| [tilakpatell/Minecraft-Bedwars-AI](https://github.com/tilakpatell/Minecraft-Bedwars-AI) | master | 2025-04-22 | [cae52f59](https://github.com/tilakpatell/Minecraft-Bedwars-AI/tree/cae52f597cdbc7e69b8e817c554116c1b8b4e64d) | 未发现明确许可证 | 未列出 |
| [Potrock/blockyard](https://github.com/Potrock/blockyard) | main | 2026-10-23 | [7daddbec](https://github.com/Potrock/blockyard/tree/7daddbec178997236d664bc29975d49801574332) | [MIT](https://github.com/Potrock/blockyard/blob/7daddbec178997236d664bc29975d49801574332/LICENSE) | 未列出 |
| [andrei1058/BedWars1058](https://github.com/andrei1058/BedWars1058) | master | 2026-06-22 | [66987262](https://github.com/andrei1058/BedWars1058/tree/669872626ec4160b6896755ba1d79bbed96787fb) | [GPL-3.0](https://github.com/andrei1058/BedWars1058/blob/669872626ec4160b6896755ba1d79bbed96787fb/LICENSE) | [25.9](https://github.com/andrei1058/BedWars1058/releases/tag/25.9) |
| [ScreamingSandals/BedWars](https://github.com/ScreamingSandals/BedWars) | master | 2026-09-26 | [168d8e24](https://github.com/ScreamingSandals/BedWars/tree/168d8e24c76e2f8ad7bafcc4071b529bb69cd554) | [LGPL-3.0](https://github.com/ScreamingSandals/BedWars/blob/168d8e24c76e2f8ad7bafcc4071b529bb69cd554/LICENSE) | 未列出 |
| [Lux-AI-Challenge/Lux-Design-S2](https://github.com/Lux-AI-Challenge/Lux-Design-S2) | main | 2023-09-22 | [5bcb3c77](https://github.com/Lux-AI-Challenge/Lux-Design-S2/tree/5bcb3c775d536cecda32a3c041a9814279b79c5b) | [Apache-2.0](https://github.com/Lux-AI-Challenge/Lux-Design-S2/blob/5bcb3c775d536cecda32a3c041a9814279b79c5b/LICENSE) | [v3.0.1](https://github.com/Lux-AI-Challenge/Lux-Design-S2/releases/tag/v3.0.1) |
| [google-deepmind/lab2d](https://github.com/google-deepmind/lab2d) | main | 2026-10-05 | [f6de2d6e](https://github.com/google-deepmind/lab2d/tree/f6de2d6e40e476093b6413cd496137ad8fd8d3d5) | [Apache-2.0](https://github.com/google-deepmind/lab2d/blob/f6de2d6e40e476093b6413cd496137ad8fd8d3d5/LICENSE) | [release_v1.0.2-ubuntu22](https://github.com/google-deepmind/lab2d/releases/tag/release_v1.0.2-ubuntu22) |
| [Farama-Foundation/MAgent2](https://github.com/Farama-Foundation/MAgent2) | main | 2026-10-09 | [f3fca5a7](https://github.com/Farama-Foundation/MAgent2/tree/f3fca5a78504615986dfba37d85137c9e15d1db6) | [MIT](https://github.com/Farama-Foundation/MAgent2/blob/f3fca5a78504615986dfba37d85137c9e15d1db6/LICENSE) | [0.3.4](https://github.com/Farama-Foundation/MAgent2/releases/tag/0.3.4) |
| [Farama-Foundation/MicroRTS-Py](https://github.com/Farama-Foundation/MicroRTS-Py) | master | 2025-08-11 | [91ae6f54](https://github.com/Farama-Foundation/MicroRTS-Py/tree/91ae6f54c92d5f97abb34bcaff3013adc51cb687) | [MIT](https://github.com/Farama-Foundation/MicroRTS-Py/blob/91ae6f54c92d5f97abb34bcaff3013adc51cb687/LICENSE) | [v0.6.1](https://github.com/Farama-Foundation/MicroRTS-Py/releases/tag/v0.6.1) |
| [vwxyzjn/microrts](https://github.com/vwxyzjn/microrts) | master | 2022-11-16 | [67664cb0](https://github.com/vwxyzjn/microrts/tree/67664cb0f19d9bd1177d09dbea064dfd9b878ce7) | [GPL-3.0](https://github.com/vwxyzjn/microrts/blob/67664cb0f19d9bd1177d09dbea064dfd9b878ce7/LICENSE) | 未列出 |
| [grid-universe/grid-universe](https://github.com/grid-universe/grid-universe) | main | 2026-08-23 | [28615fa1](https://github.com/grid-universe/grid-universe/tree/28615fa1b570b7ccdd5f56d86ca200baffa06d2c) | [MIT](https://github.com/grid-universe/grid-universe/blob/28615fa1b570b7ccdd5f56d86ca200baffa06d2c/LICENSE) | 未列出 |
| [markusfisch/bots](https://github.com/markusfisch/bots) | master | 2025-11-27 | [3ce66349](https://github.com/markusfisch/bots/tree/3ce66349ee2e239dd0ac79d1d7ec455e682c5c64) | [Unlicense](https://github.com/markusfisch/bots/blob/3ce66349ee2e239dd0ac79d1d7ec455e682c5c64/UNLICENSE) | 未列出 |
| [Farama-Foundation/PettingZoo](https://github.com/Farama-Foundation/PettingZoo) | main | 2026-10-09 | [b0fe0216](https://github.com/Farama-Foundation/PettingZoo/tree/b0fe02166d2106f8fcb6a6e0ca8125765699bdba) | [MIT](https://github.com/Farama-Foundation/PettingZoo/blob/b0fe02166d2106f8fcb6a6e0ca8125765699bdba/LICENSE) | [1.27.0](https://github.com/Farama-Foundation/PettingZoo/releases/tag/1.27.0) |
| [openenv/OpenEnv](https://github.com/openenv/OpenEnv) | main | 2026-10-22 | [6e5c73c0](https://github.com/openenv/OpenEnv/tree/6e5c73c0231dae82878c1a94c43e155527e26105) | [BSD-3-Clause](https://github.com/openenv/OpenEnv/blob/6e5c73c0231dae82878c1a94c43e155527e26105/LICENSE) | [v0.10.0](https://github.com/openenv/OpenEnv/releases/tag/v0.10.0) |
| [fastapi/fastapi](https://github.com/fastapi/fastapi) | master | 2026-10-23 | [7a0a3f0b](https://github.com/fastapi/fastapi/tree/7a0a3f0b286c6c865cf4398ea0e957a87b8bffa4) | [MIT](https://github.com/fastapi/fastapi/blob/7a0a3f0b286c6c865cf4398ea0e957a87b8bffa4/LICENSE) | [0.162.0](https://github.com/fastapi/fastapi/releases/tag/0.162.0) |
| [Farama-Foundation/Gymnasium](https://github.com/Farama-Foundation/Gymnasium) | main | 2026-10-23 | [5b6c5280](https://github.com/Farama-Foundation/Gymnasium/tree/5b6c5280e1e23a6f41b3cdfb297a26e349f6ef73) | [MIT](https://github.com/Farama-Foundation/Gymnasium/blob/5b6c5280e1e23a6f41b3cdfb297a26e349f6ef73/LICENSE) | [v1.4.0](https://github.com/Farama-Foundation/Gymnasium/releases/tag/v1.4.0) |
| [pixijs/pixijs](https://github.com/pixijs/pixijs) | dev | 2026-10-22 | [b78ff351](https://github.com/pixijs/pixijs/tree/b78ff35152f9b28fdf0289b54bc2deacd62956b6) | [MIT](https://github.com/pixijs/pixijs/blob/b78ff35152f9b28fdf0289b54bc2deacd62956b6/LICENSE) | [v8.22.0](https://github.com/pixijs/pixijs/releases/tag/v8.22.0) |
| [BaicaiBear/2DBedWars](https://github.com/BaicaiBear/2DBedWars) | main | 2026-01-02 | [b37f6f22](https://github.com/BaicaiBear/2DBedWars/tree/b37f6f2212db25fc409226a01417cdc6caf4326d) | [GPL-3.0](https://github.com/BaicaiBear/2DBedWars/blob/b37f6f2212db25fc409226a01417cdc6caf4326d/LICENSE) | 未列出 |
| [azuleamarelo91-cmyk/bedwars-2d](https://github.com/azuleamarelo91-cmyk/bedwars-2d) | main | 2026-08-14 | [e97e4c18](https://github.com/azuleamarelo91-cmyk/bedwars-2d/tree/e97e4c187e17ae23fc9841f4cb3b33bc99b1398c) | 未发现明确许可证 | 未列出 |
| [Farama-Foundation/MicroRTS](https://github.com/Farama-Foundation/MicroRTS) | master | 2025-08-11 | [72f2fd94](https://github.com/Farama-Foundation/MicroRTS/tree/72f2fd94039adf3323f4591947e98661a572f927) | [GPL-3.0](https://github.com/Farama-Foundation/MicroRTS/blob/72f2fd94039adf3323f4591947e98661a572f927/LICENSE) | 未列出 |

## 10. Hypixel 规则与数据来源

[Hypixel Bed Wars 版块](https://hypixel.net/bed-wars/)可用于追踪官方消息，但论坛帖子不能自动作为完整、固定版本的规则规范。

[Hypixel Public API v2 文档](https://api.hypixel.net/)中，recentgames 返回比赛时间、类型、模式、地图和结束时间等摘要；player 提供统计。所查公开接口没有逐 tick 位置、行动或完整对局回放端点。因此本项目的轨迹数据应由自己的引擎记录；真实游戏对照需要另外取得适当数据来源，不能把摘要 API 当成轨迹数据接口。

## 11. 调研结束时仍未知的内容

- 各候选在本机 macOS ARM64 上的实际安装和启动情况。
- 统一规则与配置下的吞吐量、内存、对局长度和训练效率。
- 已查项目的全部规则正确性与完整测试通过状态。
- 本项目的二维空间形式、首版规则范围和最终依赖选择。

本次已将原索引中会影响判断的遗漏和误导性优先级更正；项目尚未开始实现。
