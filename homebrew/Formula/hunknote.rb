# typed: false
# frozen_string_literal: true

# Homebrew formula for Hunknote
# Repository: https://github.com/nash911/homebrew-tap
#
# Install:  brew install nash911/tap/hunknote
# Upgrade:  brew upgrade hunknote
# Remove:   brew uninstall hunknote

class Hunknote < Formula
  desc "AI-powered CLI tool for generating git commit messages and composing atomic commit stacks"
  homepage "https://github.com/nash911/hunknote"
  version "1.6.9"
  license "MIT"

  on_macos do
    if Hardware::CPU.arm?
      url "https://github.com/nash911/hunknote/releases/download/v#{version}/hunknote_darwin_arm64.tar.gz"
      sha256 "18439154680b610317c9bbd4d1232c9b12234f34e46c790ab4a72ac0483259f3"
    end
  end

  on_linux do
    if Hardware::CPU.intel?
      url "https://github.com/nash911/hunknote/releases/download/v#{version}/hunknote_linux_amd64.tar.gz"
      sha256 "987b4304956e3b729234e9fc00c12b99a26ccfa67decca603bb570aa0cea96d3"
    end
  end

  def install
    bin.install "hunknote"
  end

  test do
    assert_match "hunknote #{version}", shell_output("#{bin}/hunknote --version")
  end
end

