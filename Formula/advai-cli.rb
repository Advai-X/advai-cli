class AdvaiCli < Formula
  include Language::Python::Virtualenv

  desc "CLI for browser automation, skills, and external CLIs"
  homepage "https://github.com/Advai-X/advai-cli"
  url "https://files.pythonhosted.org/packages/32/24/f06412429212844c19320cc689e8859d744075a28db2732bf244d5e1a0d5/advai_cli-1.0.10.tar.gz"
  sha256 "e91db8eba55f8e796c14f11a0482f6d073087ecf4bb332bccd5dd44727acc2ce"
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
