class Unienv < Formula
  desc "One always-ready environment shared by every AI tool"
  homepage "https://github.com/rupeshbharambe24/unienv-ai"
  url "https://github.com/rupeshbharambe24/unienv-ai/archive/refs/tags/v0.2.2.tar.gz"
  sha256 "REPLACE_WITH_RELEASE_SHA256"
  license "MIT"

  depends_on "uv"

  def install
    libexec.install "src", "recipes", "templates", "shims"
    (bin/"unienv").write <<~EOS
      #!/bin/sh
      set -e
      UV="#{Formula["uv"].opt_bin}/uv"
      PY="$("$UV" python find 3.12 --managed-python 2>/dev/null || true)"
      if [ -z "$PY" ]; then
        "$UV" python install 3.12 --quiet
        PY="$("$UV" python find 3.12 --managed-python)"
      fi
      exec "$PY" "#{opt_libexec}/src/unienv.py" "$@"
    EOS
    chmod 0755, bin/"unienv"
    bin.install_symlink "unienv" => "ue"
  end

  def caveats
    <<~EOS
      Finish setting up UniEnv AI's shared environment and AI tool wiring:
        unienv install
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/unienv --version")
  end
end
