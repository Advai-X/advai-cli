class Advai < Formula
  desc "A cross-platform CLI tool."
  homepage "https://pypi.org/project/advai-cli/"
  url "https://files.pythonhosted.org/packages/8c/f1/d365949065369246da5fa2f70aed3dd67f3b609506ffd58ac38a66453939/advai_cli-1.0.3.tar.gz"
  sha256 "4195790ade2b8406d305e3e53717fcf1a9c40424a932d2002cb436943671f72f"
  license "MIT"

  depends_on "python@3.11"

  resource "click" do
    url "https://files.pythonhosted.org/packages/c7/0d/67e5b4109ea4a837e80daa87c2c696711955e40449a97e8926672534def2/click-8.4.1-py3-none-any.whl"
    sha256 "482be17c6991b8c19c5429a1e995d9b0efdbb63172824c41f99965dc0ade8ec2"
  end

  def install
    # Create an isolated virtualenv under libexec so the advai entry-point
    # resolves against a private, self-contained Python interpreter.
    venv = libexec/"venv"
    system Formula["python@3.11"].opt_bin/"python3", "-m", "venv", venv
    system venv/"bin/pip", "install", "--upgrade", "pip"

    # Install vendored dependencies (no network access during brew build)
    resource("click").stage do
      system venv/"bin/pip", "install", "--no-deps", "."
    end

    # Install the main package
    system venv/"bin/pip", "install", "--no-deps", "."

    # Expose the "advai" binary on PATH
    (bin/"advai").write_env_script venv/"bin/advai",
      PATH: "#{venv/"bin"}:$PATH"
  end

  test do
    system "#{bin}/advai", "--version"
    system "#{bin}/advai", "--help"
  end
end
