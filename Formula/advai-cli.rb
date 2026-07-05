class AdvaiCli < Formula
  include Language::Python::Virtualenv

  desc "CLI for browser automation, skills, and external CLIs"
  homepage "https://github.com/Advai-X/advai-cli"
  url "https://files.pythonhosted.org/packages/89/94/d8326155c88e6995f722158407574fccc77a813fb41768d3e69ca09858e2/advai_cli-1.0.9.tar.gz"
  sha256 "471a30bcfc9f3f1693eea612101b66e740282d3706f9ccafca9fe3af88543468"
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
