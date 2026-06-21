class AdvaiCli < Formula
  desc "Cross-platform CLI tool for skill management"
  homepage "https://pypi.org/project/advai-cli/"
  url "https://files.pythonhosted.org/packages/8c/f1/d365949065369246da5fa2f70aed3dd67f3b609506ffd58ac38a66453939/advai_cli-1.0.3.tar.gz"
  sha256 "4195790ade2b8406d305e3e53717fcf1a9c40424a932d2002cb436943671f72f"
  license "MIT"

  depends_on "python@3.11"

  resource "click" do
    url "https://files.pythonhosted.org/packages/9b/98/518d8e5081007684232226f475082b30087d0f585e8457db087298259f49/click-8.4.1.tar.gz"
    sha256 "918b5633eddf6b41c32d4f454bf0de810065c74e3f7dbf8ee5452f8be88d3e96"
  end

  def install
    python = Formula["python@3.11"].opt_bin/"python3.11"

    resource("click").stage do
      system python, "-c", <<~PYTHON
        import shutil, os
        src = "src/click" if os.path.isdir("src/click") else "click"
        target = "#{libexec}/click"
        os.makedirs("#{libexec}", exist_ok=True)
        shutil.copytree(src, target, dirs_exist_ok=True)
      PYTHON
    end

    system python, "-c", <<~PYTHON
      import shutil, os
      src = "advai" if os.path.isdir("advai") else "advai"
      target = "#{libexec}/advai"
      shutil.copytree(src, target, dirs_exist_ok=True)
    PYTHON

    (bin/"advai").write <<~EOS
      #!/bin/bash
      PYTHONPATH="#{libexec}" exec "#{python}" -c "from advai.cli import cli; cli()" "$@"
    EOS
  end

  test do
    assert_match "advai", shell_output("#{bin}/advai --version")
    system "#{bin}/advai", "--help"
  end
end
