class AdvaiCli < Formula
  include Language::Python::Virtualenv

  desc "CLI for browser automation, skills, and external CLIs"
  homepage "https://github.com/Advai-X/advai-cli"
  url "https://files.pythonhosted.org/packages/75/46/7b61263427afd35f7fc1d779bc3edd5cd99eb917eb65fd5fdcbf86d1d08d/advai_cli-1.0.8.tar.gz"
  sha256 "33b704a1b77c2d4a2de779757472cca27832c1d1a8ae9e3831cc793e1f57fa79"
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
