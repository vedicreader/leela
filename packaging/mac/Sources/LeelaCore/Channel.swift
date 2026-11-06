import Foundation

/// The lock channel on GitHub releases: `lock-channel/<name>.json` points at `lock-<n>/`. See docs/thin-app.md.
public struct Channel: Sendable {
    public static let github = URL(string: "https://github.com/vedicreader/leela/releases/download")!
    public var base: URL
    /// `channel` or `channel-test`
    public var name: String
    public var keys: [SSHKey]
    public var app: AppFacts
    public var session: URLSession

    public init(base: URL = Channel.github, test: Bool = false, keys: [SSHKey], app: AppFacts, session: URLSession = Channel.defaultSession) {
        self.base = base; self.name = test ? "channel-test" : "channel"; self.keys = keys; self.app = app; self.session = session
    }

    /// `LEELA_LOCK_CHANNEL=test` points an app at the test channel
    public static func isTest(_ env: [String: String]) -> Bool { env["LEELA_LOCK_CHANNEL"] == "test" }

    public static let defaultSession: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 15
        c.timeoutIntervalForResource = 120
        return URLSession(configuration: c)
    }()

    /// GitHub drops a leading dot from an asset name
    public static func asset(_ f: String) -> String { f == ".python-version" ? "python-version" : f }

    public enum FetchError: Error, Equatable { case offline(String), status(Int, String), mismatch }

    func get(_ url: URL) async throws -> Data? {
        let d: Data, r: URLResponse
        do { (d, r) = try await session.data(from: url) } catch { throw FetchError.offline("\(error.localizedDescription)") }
        let code = (r as? HTTPURLResponse)?.statusCode ?? 0
        if code == 404 { return nil }
        guard code == 200 else { throw FetchError.status(code, url.lastPathComponent) }
        return d
    }

    /// the signed pointer, or nil when none is published
    public func pointer() async throws -> ChannelPointer? {
        let dir = base.appending(path: "lock-channel")
        guard let d = try await get(dir.appending(path: "\(name).json")), let s = try await get(dir.appending(path: "\(name).sig")) else { return nil }
        return try LockCheck.pointer(d, signature: s, keys: keys, name: name)
    }

    /// downloads lock `n` into `into` and checks it as the app does
    public func download(_ p: ChannelPointer, into: URL, highest: Int, bad: [String] = []) async throws -> LockVerdict {
        try FileManager.default.createDirectory(at: into, withIntermediateDirectories: true)
        for f in LockCheck.names {
            guard let d = try await get(base.appending(path: "lock-\(p.n)").appending(path: Self.asset(f))) else { throw LockRefusal.missing(f) }
            try d.write(to: into.appending(path: f))
        }
        guard sha256(try Data(contentsOf: into.appending(path: "manifest.json"))) == p.manifest_sha256 else { throw FetchError.mismatch }
        return try LockCheck.check(dir: into, keys: keys, app: app, highest: highest, bad: bad)
    }
}

/// Which lock to run: the newest valid one the channel offers, else the bundled one.
public struct LockPlan: Equatable, Sendable {
    public var dir: URL
    public var verdict: LockVerdict
    /// whether the channel answered; offline means the bundled lock or the env on disk
    public var online: Bool
    public var n: Int { switch verdict { case .ok(let m), .needsApp(let m): m.n } }
    public var manifest: Manifest { switch verdict { case .ok(let m), .needsApp(let m): m } }
}

public enum LockChoice {
    /// the channel lock when it is valid and newer than the bundled one, else the bundled lock; both are copied into locks/<n>
    public static func choose(bundled: URL, channel: Channel?, keys: [SSHKey], app: AppFacts, store: EnvStore) async -> (plan: LockPlan?, error: String?) {
        let s = store.load()
        var best: LockPlan?, why: String?, online = false
        if let ch = channel {
            do {
                if let p = try await ch.pointer() {
                    online = true
                    if p.n > s.highest_n {
                        let tmp = store.paths.locks.appending(path: ".dl-\(p.n)-\(UUID().uuidString)")
                        defer { try? FileManager.default.removeItem(at: tmp) }
                        let v = try await ch.download(p, into: tmp, highest: s.highest_n, bad: s.bad)
                        let plan = LockPlan(dir: tmp, verdict: v, online: true)
                        best = LockPlan(dir: try store.keep(lock: tmp, n: plan.n), verdict: v, online: true)
                    } else if let n = s.current.flatMap({ s.locks[$0] }) {
                        best = (try? LockCheck.check(dir: store.paths.lock(n), keys: keys, app: app)).map { LockPlan(dir: store.paths.lock(n), verdict: $0, online: true) }
                    }
                } else { online = true }
            } catch Channel.FetchError.offline(let e) { why = e }
            catch let r as LockRefusal { why = r.text; online = true }
            catch { why = "\(error)" }
        }
        if let v = try? LockCheck.check(dir: bundled, keys: keys, app: app, bad: s.bad) {
            let m = { switch v { case .ok(let m), .needsApp(let m): m } }()
            if best == nil || m.n > best!.n, let kept = try? store.keep(lock: bundled, n: m.n) { best = LockPlan(dir: kept, verdict: v, online: online) }
        }
        if var b = best { b.online = online; return (b, why) }
        return (nil, why)
    }
}
