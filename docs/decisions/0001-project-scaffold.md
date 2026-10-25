# 0001：Python 工程骨架与模块预留

日期：2026-10-25  
状态：本次初始化采用的工程选择；游戏规则与仿真底座待选择。

## 背景

项目已有目标和候选调研，当前请求是初始化项目结构并创建 GitHub 公开仓库。二维模型、机制范围、接口和底层框架尚未确定。

## 选择

- 先用 Python 3.11+ 建立可安装的 `src/bedwars_arena` 包。
- 用 setuptools 构建，提供 `bedwars-arena` 与 `python -m bedwars_arena` 两个入口。
- 入口当前只显示工程信息；不提供伪对局或尚未定义的规则参数。
- 分开预留 core、interfaces、agents、runner、replay 与 web。
- 当前不依赖 PettingZoo、Lab2D、MAgent2、FastAPI、OpenEnv 或 PixiJS。
- 生成数据统一写入默认忽略的 `artifacts/`。

## 影响

可以先验证安装、构建与 CI，并为后续规则讨论提供稳定目录。Python 骨架不排除将来以适配器连接其他底座或将性能热点迁移到其他语言。

## 未解决

仿真框架、空间表示、首版规则、观测动作协议、回放格式、性能阈值及项目许可证。
