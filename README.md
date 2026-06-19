# advai — 跨平台 AI Skill 管理器

一个用 Python 写的 CLI，让你可以像安装软件包一样安装/卸载 AI Skills。

- **平台**：macOS / Linux / Windows
- **安装方式**：`pip` / `npm` / `brew` / `curl | bash` 任选
- **核心命令**：`install` / `uninstall` / `list` / `update` / `info`

---

## 快速开始

```bash
# 方式一：pip
pip install advai

# 方式二：npm
npm install -g advai

# 方式三：brew
brew install https://raw.githubusercontent.com/Advai-X/advai-x-cli/main/Formula/advai.rb

# 方式四：一键脚本
curl -fsSL https://raw.githubusercontent.com/Advai-X/advai-x-cli/main/install.sh | bash
```

安装完成后：

```bash
advai --version
advai --help
advai install demo-skill
advai list
advai info demo-skill
advai uninstall demo-skill
```

---

## 项目结构

```
advai/              # 核心 CLI（Python）
  __init__.py
  cli.py            # 命令行入口（基于 click）
  skills.py         # Skill 安装 / 卸载 / 元数据逻辑
Formula/advai.rb    # Homebrew 配方
bin/advai.js        # npm 入口桥接脚本
install.sh          # curl | bash 一键安装脚本
pyproject.toml      # PyPI 打包配置
package.json        # npm 打包配置
```

---

## 本地开发

```bash
# 从源码运行
python3 -m advai.cli --help

# 构建发布包
python3 -m pip install --upgrade build twine
python3 -m build
python3 -m twine upload dist/*
```

---

## License

MIT
