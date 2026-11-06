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

    public init(app: URL, brew: URL? = nil, places: [String] = BrewUpgrade.places) {
        self.app = app
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

    /// starts the upgrade; the state goes running, then done (a new version is in place), same, or error
    @discardableResult
    public func start(log: URL) -> UpdateState {
        guard let brew else { set(UpdateState(state: "unavailable")); return state }
        if state.state == "running" { return state }
        was = Self.version(app)
        set(UpdateState(state: "running", line: "asking Homebrew"))
        var env = ProcessInfo.processInfo.environment
        for k in ["HOMEBREW_NO_ENV_HINTS", "HOMEBREW_NO_COLOR", "HOMEBREW_NO_EMOJI", "NONINTERACTIVE"] { env[k] = "1" }
        let l = Launch(executable: brew, args: ["upgrade", "--cask", Self.cask], env: env)
        Task.detached { [self] in
            let code = (try? await Run.toEnd(l, log: log, line: { [weak self] line in self?.set(UpdateState(state: "running", line: line)) })) ?? -1
            set(UpdateState(state: code != 0 ? "error" : Self.version(app) == was ? "same" : "done", line: code != 0 ? Run.tail(log, lines: 1) : ""))
        }
        return state
    }
}
