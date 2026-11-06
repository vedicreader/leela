cask "leela" do
  version "1.0.0"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"

  url "https://github.com/vedicreader/leela/releases/download/app-v#{version}/Leela.zip"
  name "Leela"
  desc "Editor for notebooks and code files with a coding agent"
  homepage "https://github.com/vedicreader/leela"

  # app releases are not marked latest: the Python releases and the lock releases share the repository
  livecheck do
    url :url
    regex(/^app-v?(\d+(?:\.\d+)+)$/i)
    strategy :github_releases
  end

  depends_on arch: :arm64
  depends_on macos: :sonoma
  # lessons and new project environments install their packages with uv; the app itself ships its own pinned uv
  depends_on formula: "uv"

  app "Leela.app"

  uninstall quit: "org.vedicreader.leela"

  # the vault (~/.vishalakshi) belongs to all the vishalakshi tools, so zap keeps it
  zap trash: [
    "~/.config/leela",
    "~/.local/share/leela",
    "~/Library/Application Support/Leela",
    "~/Library/Caches/Leela",
    "~/Library/Caches/org.vedicreader.leela",
    "~/Library/HTTPStorages/org.vedicreader.leela",
    "~/Library/Preferences/org.vedicreader.leela.plist",
    "~/Library/Saved Application State/org.vedicreader.leela.savedState",
    "~/Library/WebKit/org.vedicreader.leela",
  ]
end
