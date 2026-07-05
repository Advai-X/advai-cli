class AdvaiCli < Formula
  include Language::Python::Virtualenv

  desc "CLI for browser automation, skills, and external CLIs"
  homepage "https://github.com/Advai-X/advai-cli"
  url "https://files.pythonhosted.org/packages/59/19/6b5c69e2c9df361012459be7fde9fcf52de94caef75c85ad27287634e06a/advai_cli-1.0.7.tar.gz"
  sha256 "b4a3a0242118ca1403157b581b88391ce021610a2990f5ae8a603ab1e8f0488d"
  license "MIT"

  depends_on "python@3.14"

  resource "click" do
    url "https://files.pythonhosted.org/packages/9b/98/518d8e5081007684232226f475082b30087d0f585e8457db087298259f49/click-8.4.1.tar.gz"
    sha256 "918b5633eddf6b41c32d4f454bf0de810065c74e3f7dbf8ee5452f8be88d3e96"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    (testpath/"home").mkpath
    ENV["HOME"] = testpath/"home"

    assert_match version.to_s, shell_output("#{bin}/advai --version")
    assert_match "(no Skills installed)", shell_output("#{bin}/advai skill list")
    assert_match "Skill platforms:", shell_output("#{bin}/advai skill platform list")
    assert_match "Cursor", shell_output("#{bin}/advai skill platform list")
  end
end
