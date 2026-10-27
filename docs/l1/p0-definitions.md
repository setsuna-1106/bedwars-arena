# L1 P0 定义、安装与版本边界

2026-10-27。P0 将[已采用实验参数](../rules/l1-experiment-parameters-v0.1.md)和[固定地图](../decisions/0016-four-level-platform-and-l1.md)落实为可加载、可检查的数据；数值是平台实验，并非 Hypixel 现服实测。相关参考仍按 [BW-WORLD-01–03、BW-LIFE-01–06、BW-COMBAT-01、BW-ECON-01–05、BW-SHOP-01、BW-ITEM-01、BW-END-01–02](../rules/hypixel-bedwars.md)区分证据。地图文件不含随机生成器；改变 seed 不能改变地图。

## 使用与资产位置

```bash
bedwars-arena validate-l1 --json
# 可逐项指定外部文件；未指定项使用内置版本
bedwars-arena validate-l1 --profile /path/profile.json --map /path/map.json --scenario /path/scenario.json
```

这只验证静态定义，**不创建可推进的世界**。CLI 在字段、版本、引用、几何或参数无效时以退出码 2 报错。Python 接口允许从文件或数据加载，并检查预期哈希：

```python
from bedwars_arena.core.definitions import load_l1_definitions

bundle = load_l1_definitions()  # 也可用 profile_path/map_path/scenario_path
print(bundle.hashes)
profile_copy = bundle.profile.data  # 独立副本；修改它不会改变 bundle
same = load_l1_definitions(expected_hashes=bundle.hashes)
```

唯一维护源位于 Python 包内，wheel 和 sdist 均包含这三份文件及其格式 Schema；不存在需手工同步的第二套 `configs/`/`maps/` 数值：

| 数据 | ID、内容版本 | 仓库内文件 | canonical SHA-256 |
| --- | --- | --- | --- |
| 规则 | `l1-2v2-experiment-v0.1`，`0.1` | [profile-v0.1.json](../../src/bedwars_arena/data/l1/profile-v0.1.json) | `3e74d9648c77af874f36789e6b090b0935bd7154ad280eb01e546352c78b5fc5` |
| 地图 | `l1-three-islands-v1`，`1` | [three-islands-v1.json](../../src/bedwars_arena/data/l1/three-islands-v1.json) | `0ea23c72a673b530a0d1ff9d3e68d1654c38f6bd48891a4583befa6314b47f6f` |
| 场景 | `l1-standard-2v2-v1`，`1` | [standard-2v2-v1.json](../../src/bedwars_arena/data/l1/standard-2v2-v1.json) | `2af3373da36d1f0918d2d2e85429a6e7971e288c61a61b185973c2dc390e9dd8` |

场景的玩家数组顺序就是固定 `player_order`；四人均初始存活、`life_index=1`、tick 0、双通道为空，出生/背包/保护由关联地图和规则定义。它不是 P1 的 WorldState，不能据此声称已有构造或推进功能。规则中 `effects=false` 指关闭 L1 的药水/区域等一般效果，生命表明确的出生保护仍然存在于设计中。

## 验证边界

三份文档采用各自的 `schema_version=1`，对应[profile](../../src/bedwars_arena/data/l1/schemas/profile-v1.schema.json)、[map](../../src/bedwars_arena/data/l1/schemas/map-v1.schema.json)和[scenario](../../src/bedwars_arena/data/l1/schemas/scenario-v1.schema.json) JSON Schema。加载器先按封闭字段格式逐层检查，再检查参数关系和跨文档约束；Schema 本身不代替后者。检查包括：

- 缺失/未知字段、重复 JSON 键、非有限值、非安全整数、错误类型/版本、无效开关、成本/产量/时长/预算、速度单位与倍数、装备/容量和地图图层。
- 地图范围、岛屿正面积且不重叠、床完整承载、出生体完整承载且不与床相交、出生/商店/生成器各自禁建区、朝向和地面物高度、生成器及队伍引用。
- 场景版本与 profile/map 引用、两队各两人、ID 不重复；可选的 profile/map/scenario 三项预期哈希必须全部匹配。

规则数值允许在同一格式的实验档案中显式调整，但新实验应使用新内容版本并记录新哈希；加载器不在内部补值，也不会实现启用的其他层级机制。加载成功只是静态一致性，不证明玩法、平衡或性能。地图矩形为半开区间，禁建区覆盖出生身体或各参考点 ±1；碰撞、支撑变化及玩法处理将在后续阶段实现。

哈希对 **解析后的 JSON 内容**计算：Python `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)` 的 UTF-8 字节经 SHA-256；空格和键顺序不影响结果，数字类型/值改变会影响结果。要求有限数值，数值绝对值不超过 JSON 安全整数上限 `2^53−1`；这是本项目明确的 Python 编码约定，不宣称 RFC 8785 或跨语言逐字节标准。读取时拒绝重复键、NaN 与无穷。恢复时仍须保存/核对定义自身 ID、内容版本和哈希，不能只用 ID。

## 彼此独立的版本

| 类别 | P0 状态 |
| --- | --- |
| profile、map、scenario | 各有格式 `schema_version=1` 和独立的内容 ID/版本/哈希；它们互不替代 |
| 外部 action、feedback、observation | 三个协议版本各为 1；[字段和原因码](protocol-v1.md)是 P0 规格，接收器/生产器未实现 |
| WorldSnapshot | 为完整世界格式预留版本 1，字段、编码和恢复在 P1/P7；此预留不是可用快照 |
| TeamState、旧事件队列 | 各自既有版本 1，与上述版本无兼容推论；旧队列不能自动当作世界快照 |

## 本机开发环境修复

原 `.venv` 中可编辑安装的 `.pth` 被 macOS 标记为隐藏，Python 3.14 的 `site.py` 会跳过它；仓库外的模块导入因此失败。仅在当前 shell 临时清除标记无法保证子进程也正常。本次保留旧 `.venv`，用本机捆绑的 Python 3.12.14 和 `--system-site-packages` 创建忽略于 Git 的 `venv/`，使用本机已有 setuptools 84.1.0，并从旧环境的纯 Python 安装包离线恢复构建工具，真实安装 `-e '.[dev]'`；不靠 `PYTHONPATH` 伪装安装。可用 `source venv/bin/activate`、`python scripts/check.py` 和 `python -m build --no-isolation`；其他机器可按 README 正常新建环境安装。

## P0 验证记录

- Python 3.12.14 开发安装执行 `python scripts/check.py`：29 项测试通过，包含仓库外 CLI/定义加载及既有 17 项回归。
- `python -m build --no-isolation` 成功构建 sdist，并从 sdist 构建 wheel；wheel 内含三份定义与三个定义 Schema。
- 从仓库外将 wheel 安装至独立的 Python 3.11.15 和 3.14.7 环境，在隔离模式下分别执行全部 29 项测试并通过；3.14 的已安装 CLI 也成功加载定义并返回三项哈希。
- 这些结果验证 P0 的数据、工程和安装边界；对局、物理、训练与回放仍未运行。
