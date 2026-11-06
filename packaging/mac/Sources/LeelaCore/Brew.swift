import Foundation

/// `brew upgrade --cask leela`, run by the launcher as its own child, so the cask's `uninstall quit` does not stop it.
public final class BrewUpgrade: @unchecked Sendable {
    public static let cask = "leela"
    public static let places = ["/opt/homebrew/bin/brew", "/usr/local/bin/brew"]
    public let brew: URL?
    public let app: URL
    private let q = NSLock()
    private var _state = UpdateState()
    private var was: String?

    /// the version this launcher runs; a newer one already on disk is installed and waits for a restart
    public let running: String?
    /// the environment brew starts from: this process's, or a test's with only its fake brew on PATH
    let base: [String: String]?

    public init(app: URL, brew: URL? = nil, places: [String] = BrewUpgrade.places, running: String? = nil, base: [String: String]? = nil) {
        self.app = app; self.running = running; self.base = base
        self.brew = brew ?? Self.find(app: app, places: places)
    }

    /// the brew whose Caskroom holds the leela cask, when this app is the cask's Leela.app
    public static func find(app: URL, places: [String]) -> URL? {
        guard app.lastPathComponent == "Leela.app" else { return nil }
        return places.map { URL(fileURLWithPath: $0) }.first { b in
            FileManager.default.isExecutableFile(atPath: b.path)
                && FileManager.default.fileExists(atPath: b.deletingLastPathComponent().deletingLastPathComponent().appending(path: "Caskroom/\(cask)").path)
        }
    }

    public var available: Bool { brew != nil }
    public var state: UpdateState { q.lock(); defer { q.unlock() }; return _state }
    func set(_ s: UpdateState) { q.lock(); _state = s; q.unlock() }

    public static func version(_ app: URL) -> String? {
        (NSDictionary(contentsOf: app.appending(path: "Contents/Info.plist")) as? [String: Any])?["CFBundleShortVersionString"] as? String
    }

    /// Homebrew's own markers that an auto-update already ran, and the opt-out; any of them skips the tap fetch, so a cask pushed today is not seen
    public static let noFetch = ["HOMEBREW_NO_AUTO_UPDATE", "HOMEBREW_AUTO_UPDATING", "HOMEBREW_UPDATE_AUTO", "HOMEBREW_AUTO_UPDATE_CHECKED"]
    /// `brew update-report` lines about other formulae, which mean nothing in Leela's bar
    static let noise = ["You have ", "Run `brew", "==> Outdated", "==> New "]

    /// brew's environment with the tap fetch forced, as leela.core.update.Upgrade.env
    public func env() -> [String: String] {
        var e = (base ?? ProcessInfo.processInfo.environment).filter { !Self.noFetch.contains($0.key) }
        for k in ["HOMEBREW_NO_ENV_HINTS", "HOMEBREW_NO_COLOR", "HOMEBREW_NO_EMOJI", "NONINTERACTIVE"] { e[k] = "1" }
        e["HOMEBREW_AUTO_UPDATE_SECS"] = "0"
        return e
    }

    /// whether version `a` is later than `b`, number by number
    public static func newer(_ a: String?, _ b: String?) -> Bool {
        guard let a, let b else { return false }
        let x = a.split(separator: ".").map { Int($0) ?? 0 }, y = b.split(separator: ".").map { Int($0) ?? 0 }
        for i in 0..<max(x.count, y.count) { let p = i < x.count ? x[i] : 0, q = i < y.count ? y[i] : 0; if p != q { return p > q } }
        return false
    }

    /// starts the upgrade to `latest`; the state goes running, then done (a new version is in place), same (Homebrew does not list it yet), or error
    @discardableResult
    public func start(log: URL, latest: String? = nil) -> UpdateState {
        guard let brew else { set(UpdateState(state: "unavailable")); return state }
        if state.state == "running" { return state }
        if let v = Self.version(app), Self.newer(v, running) { set(UpdateState(state: "done", line: "Leela \(v) is installed.")); return state }
        was = Self.version(app)
        set(UpdateState(state: "running", line: "Homebrew is getting the newest list of apps…"))
        Task.detached { [self] in
            var code = await run(brew, ["upgrade", "--cask", Self.cask], log: log)
            // a brew.env setting can still skip the fetch; `brew update` ignores it, so one more try after it
            if code == 0, Self.version(app) == was, Self.newer(latest, was), await run(brew, ["update"], log: log) == 0 { code = await run(brew, ["upgrade", "--cask", Self.cask], log: log) }
            let v = Self.version(app)
            if code != 0 { set(UpdateState(state: "error", line: Run.tail(log, lines: 1))) }
            else if v != was { set(UpdateState(state: "done", line: "Leela \(v ?? "") is installed.")) }
            else { set(UpdateState(state: "same", line: "Homebrew does not list Leela \(latest ?? "the new version") yet. Try again in a few minutes.")) }
        }
        return state
    }

    func run(_ brew: URL, _ args: [String], log: URL) async -> Int32 {
        let l = Launch(executable: brew, args: args, env: env())
        return (try? await Run.toEnd(l, log: log, line: { [weak self] line in
            let t = line.trimmingCharacters(in: .whitespaces)
            if !t.isEmpty, !Self.noise.contains(where: { t.hasPrefix($0) }) { self?.set(UpdateState(state: "running", line: t)) }
        })) ?? -1
    }
}
