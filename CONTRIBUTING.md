# 开发指南

需要 Python 3.11 或更高版本。当前核心没有运行时第三方依赖；开发 extra 只安装构建工具。

```bash
git clone https://github.com/setsuna-1106/bedwars-arena.git
cd bedwars-arena
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python scripts/check.py
```

## 常用命令

```bash
bedwars-arena --help
bedwars-arena --version
bedwars-arena info --json
bedwars-arena validate-l1 --json
python -m bedwars_arena info
python -m build
```

也可用 `make install`、`make check`、`make build`；先激活虚拟环境。

本机此前 `.venv` 的可编辑安装被 macOS 隐藏标记影响，已另建 `venv/` 并完成开发安装；可用 `source venv/bin/activate`。诊断与验证见 [P0 定义说明](docs/l1/p0-definitions.md)。

`scripts/check.py` 检查 Python 语法、TOML/JSON 格式、Markdown 本地链接，从仓库外运行模块/命令行入口、加载 L1 定义，并执行标准库 unittest。也可单独运行 `python -m unittest discover -s tests -v`。行为测试范围见 [tests/README.md](tests/README.md)。

GitHub Actions 使用 Linux/Python 3.11、Linux/Python 3.14 和 macOS/Python 3.14，检查开发安装、构建、从 sdist 构建 wheel 以及独立环境中的 wheel 安装。这些检查不发布 PyPI 包。

## 修改约定

- 源码放 `src/bedwars_arena/`，规则、接口、实验和回放分别维护。
- 新接口先说明输入、输出、时序、失败行为和信息边界。
- 新的规则或依赖选择在 `docs/decisions/` 记录上下文、选择及影响。
- L1 定义源随包发布；加载校验成功不代表世界处理器或完整对局已经实现。
- 行为测试和可分享的小型固定样例进入版本控制；批量生成数据放 `artifacts/`。
- 提交前运行相关检查；报告实际执行过的验证。

工程元数据采用 [PyPA 的 pyproject.toml 指南](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)所述的项目与命令行入口配置。

## 许可证

项目许可证待选择；初始化阶段没有引入第三方游戏源码。
