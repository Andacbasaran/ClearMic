# Homebrew Cask for ClearMic (macOS Apple Silicon)
#
# After publishing a GitHub Release, replace `sha256` with the checksum for
# `ClearMic-v1.0.0-macOS-arm64.dmg` from the release's `SHA256SUMS.txt`.
#
# Local install:
#   brew install --cask ./packaging/homebrew/clearmic.rb
#
# Tap install:
#   brew tap Andacbasaran/tap
#   brew install --cask clearmic

cask "clearmic" do
  arch arm: "arm64"

  version "1.0.0"
  sha256 "REPLACE_WITH_SHA256_FROM_RELEASE_SHA256SUMS_TXT"

  url "https://github.com/Andacbasaran/ClearMic/releases/download/v#{version}/ClearMic-v#{version}-macOS-#{arch}.dmg",
      verified: "github.com/Andacbasaran/ClearMic/"
  name "ClearMic"
  desc "100% offline, 0 MB VRAM AI microphone noise suppressor & broadcast voice studio"
  homepage "https://clearmic.andacbasaran.com"

  livecheck do
    url :url
    strategy :github_latest
  end

  depends_on arch: :arm64
  depends_on macos: ">= :monterey"

  app "ClearMic.app"

  caveats <<~EOS
    To route ClearMic's cleaned voice to Discord, Zoom, or OBS on macOS,
    install BlackHole 2ch:
      brew install blackhole-2ch
  EOS

  zap trash: [
    "~/Library/Application Support/ClearMic",
    "~/Library/LaunchAgents/com.andacbasaran.clearmic.plist",
    "~/Library/Preferences/com.andacbasaran.clearmic.plist",
  ]
end
