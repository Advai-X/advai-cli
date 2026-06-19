# Homebrew 配方 — 使用方式：
#   brew tap Advai-X/advai
#   brew install advai
#
# 新版本发布时，只需更新 url 与 sha256 两项即可。

class Advai < Formula
  include Language::Python::Virtualenv

  desc "跨平台 AI Skill 管理器 — 一键 install / uninstall / list / update"
  homepage "https://github.com/Advai-X/advai-x-cli"
  url "https://github.com/Advai-X/advai-x-cli/archive/refs/tags/v1.0.0.tar.gz"
  sha256 "26499419c131f88f7ec56fdec9f507b1586bffa76dd57e9b778063da8cfc3dd3"
  license "MIT"

  depends_on "python@3.11"

  resource "click" do
    url "https://files.pythonhosted.org/packages/59/87/84326af34517fca8c58418d148f2403df25303e02736832403587318e9e8/click-8.1.3.tar.gz"
    sha256 "7682dc8afb30297001674575ea00d1814d808d6a36af415a82bd481d37ba7b8e"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/advai", "--version"
    system "#{bin}/advai", "--help"
  end
end
