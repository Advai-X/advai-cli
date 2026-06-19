# Homebrew 配方 — 使用方式：
#
#   # 方式一（推荐，标准 tap 流程）：
#   brew tap Advai-X/advai https://github.com/Advai-X/advai-x-cli
#   brew install advai
#
#   # 方式二（手动创建本地 tap）：
#   curl -fsSL https://cdn.jsdelivr.net/gh/Advai-X/advai-x-cli@main/Formula/advai.rb \
#     > "$(brew --repository)/Library/Taps/advai-x/homebrew-advai/Formula/advai.rb"
#   brew trust advai-x/advai
#   brew install advai
#
# 新版本发布时，只需更新 url 与 sha256 两项即可。

class Advai < Formula
  desc "跨平台 AI Skill 管理器 — 一键 install / uninstall / list / update"
  homepage "https://github.com/Advai-X/advai-x-cli"
  url "https://github.com/Advai-X/advai-x-cli/archive/refs/tags/v1.0.0.tar.gz"
  sha256 "26499419c131f88f7ec56fdec9f507b1586bffa76dd57e9b778063da8cfc3dd3"
  license "MIT"

  depends_on "python@3.11"

  def install
    # 手动创建 venv 并 pip install（比 virtualenv_install_with_resources 更可控）
    venv = libexec/"venv"
    system Formula["python@3.11"].opt_bin/"python3", "-m", "venv", venv
    system venv/"bin/pip", "install", "--upgrade", "pip"
    system venv/"bin/pip", "install", "-e", "."

    # 创建 bin/advai 包装脚本，指向 venv 内的 entry point
    (bin/"advai").write_env_script venv/"bin/advai",
      PATH: "#{venv/"bin"}:$PATH"
  end

  test do
    system "#{bin}/advai", "--version"
    system "#{bin}/advai", "--help"
  end
end
