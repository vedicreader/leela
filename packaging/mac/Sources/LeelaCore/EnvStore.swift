import Darwin
import Foundation

/// state.json: which env runs, which ran before, which waits for a restart, the highest lock accepted, the hashes that failed.
public struct EnvState: Codable, Equatable, Sendable {
    public var current: String?
    public var previous: String?
    public var pending: String?
    public var highest_n: Int = -1
    public var bad: [String] = []
    /// lock number of each env hash
    public var locks: [String: Int] = [:]
    /// the extras the person installed; each new env gets them too
    public var extras: [String] = []
    /// crashes of `current` before it was ever ready
    public var early_crashes: Int = 0
    /// hashes that once reached ready; only an env never proven rolls back by itself
    public var proven: [String] = []
    /// hashes the person left with "Use Previous Version": offered again, never switched to by themselves
    public var held: [String] = []
    public var pruned: Double = 0
    public init() {}

    /// every key optional, so a state.json from an older launcher still loads
    public init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        current = try c.decodeIfPresent(String.self, forKey: .current)
        previous = try c.decodeIfPresent(String.self, forKey: .previous)
        pending = try c.decodeIfPresent(String.self, forKey: .pending)
        highest_n = try c.decodeIfPresent(Int.self, forKey: .highest_n) ?? -1
        bad = try c.decodeIfPresent([String].self, forKey: .bad) ?? []
        locks = try c.decodeIfPresent([String: Int].self, forKey: .locks) ?? [:]
        extras = try c.decodeIfPresent([String].self, forKey: .extras) ?? []
        early_crashes = try c.decodeIfPresent(Int.self, forKey: .early_crashes) ?? 0
        proven = try c.decodeIfPresent([String].self, forKey: .proven) ?? []
        held = try c.decodeIfPresent([String].self, forKey: .held) ?? []
        pruned = try c.decodeIfPresent(Double.self, forKey: .pruned) ?? 0
    }
}

/// .leela-env.json, written last: an env folder without it is a partial build.
public struct EnvMarker: Codable, Equatable, Sendable {
    public var hash: String
    public var n: Int
    public var uv: String
    public var extras: [String]
    public var built: Double
}

public enum BuildError: Error, Equatable {
    case failed(code: Int32, tail: String)
    case noCurrent
    case unknownExtra(String)
}

/// The envs on disk: build one per lock hash with the bundled uv, switch atomically through state.json, roll back, collect garbage.
public final class EnvStore: @unchecked Sendable {
    public let paths: Paths
    public let spec: ChildEnv
    public let uv: URL
    public let uvVersion: String
    let parent: [String: String]
    let home: String
    public static let extraNames = ["mlx", "llama", "langserver"]
    private let q = NSLock()

    public init(paths: Paths, spec: ChildEnv, uv: URL, uvVersion: String,
                parent: [String: String] = ProcessInfo.processInfo.environment, home: String = NSHomeDirectory()) {
        self.paths = paths; self.spec = spec; self.uv = uv; self.uvVersion = uvVersion; self.parent = parent; self.home = home
    }

    // state.json

    public func load() -> EnvState {
        guard let d = try? Data(contentsOf: paths.state), let s = try? JSONDecoder().decode(EnvState.self, from: d) else { return EnvState() }
        return s
    }

    /// state.json.tmp, then a rename, so a crash leaves the old state or the new one, never half of one
    public func save(_ s: EnvState) throws {
        try FileManager.default.createDirectory(at: paths.support, withIntermediateDirectories: true)
        let tmp = paths.support.appending(path: "state.json.tmp")
        let e = JSONEncoder(); e.outputFormatting = [.prettyPrinted, .sortedKeys]
        try e.encode(s).write(to: tmp)
        guard rename(tmp.path, paths.state.path) == 0 else { throw CocoaError(.fileWriteUnknown) }
    }

    public func update(_ f: (inout EnvState) -> Void) throws -> EnvState {
        q.lock(); defer { q.unlock() }
        var s = load(); f(&s); try save(s); return s
    }

    // envs

    /// the env hash of a lock folder: the lock hash with this app's uv, so a new uv builds a new env
    public func hash(lock: URL) throws -> String { try LockHash.hash(dir: lock, uv: uvVersion) }

    public func marker(_ hash: String) -> EnvMarker? {
        guard let d = try? Data(contentsOf: paths.marker(hash)) else { return nil }
        return try? JSONDecoder().decode(EnvMarker.self, from: d)
    }

    public func isBuilt(_ hash: String) -> Bool { marker(hash)?.hash == hash && FileManager.default.isExecutableFile(atPath: paths.server(hash).path) }

    public func vals(env: URL, python: String) -> [String: String] {
        ["cache": paths.uvCache.path, "python": paths.python.path, "python_version": python, "env": env.path]
    }

    static func python(_ lock: URL) -> String {
        ((try? String(contentsOf: lock.appending(path: ".python-version"), encoding: .utf8)) ?? "3.12").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    public func syncLaunch(lock: URL, hash: String, extras: [String], inexact: Bool = false) -> Launch {
        Launch(executable: uv, args: spec.syncArgs(lock: lock, extras: extras, inexact: inexact),
               env: spec.uvEnv(parent, home: home, vals: vals(env: paths.env(hash), python: Self.python(lock))), cwd: paths.support)
    }

    /// builds the env of lock `n` in `envs/<hash16>`, the marker last; a failed build leaves no folder. The hash.
    @discardableResult
    public func build(lock: URL, n: Int, extras: [String]? = nil, background: Bool = false,
                      line: (@Sendable (String) -> Void)? = nil, started: (@Sendable (Running) -> Void)? = nil) async throws -> String {
        let h = try hash(lock: lock)
        if isBuilt(h) { return h }
        let fm = FileManager.default, env = paths.env(h)
        if fm.fileExists(atPath: env.path) { try fm.removeItem(at: env) }
        try fm.createDirectory(at: paths.envs, withIntermediateDirectories: true)
        let xs = extras ?? load().extras
        let l = syncLaunch(lock: lock, hash: h, extras: xs)
        let code = try await Run.toEnd(background ? l.background : l, log: paths.syncLog(h), line: line, started: started)
        guard code == 0 else {
            try? fm.removeItem(at: env)
            throw BuildError.failed(code: code, tail: Run.tail(paths.syncLog(h)))
        }
        try writeMarker(EnvMarker(hash: h, n: n, uv: uvVersion, extras: xs, built: Date().timeIntervalSince1970))
        _ = try update { $0.locks[h] = n }
        return h
    }

    func writeMarker(_ m: EnvMarker) throws {
        let e = JSONEncoder(); e.outputFormatting = [.sortedKeys]
        try e.encode(m).write(to: paths.marker(m.hash), options: .atomic)
    }

    /// adds one pinned extra of the current lock to the running env (`uv sync --inexact --extra`), and records it
    public func installExtra(_ name: String, line: (@Sendable (String) -> Void)? = nil) async throws {
        guard Self.extraNames.contains(name) else { throw BuildError.unknownExtra(name) }
        let s = load()
        guard let h = s.current, var m = marker(h) else { throw BuildError.noCurrent }
        let xs = Array(Set(m.extras + [name])).sorted()
        let code = try await Run.toEnd(syncLaunch(lock: paths.lock(m.n), hash: h, extras: xs, inexact: true), log: paths.syncLog(h), line: line)
        guard code == 0 else { throw BuildError.failed(code: code, tail: Run.tail(paths.syncLog(h))) }
        m.extras = xs
        try writeMarker(m)
        _ = try update { $0.extras = Array(Set($0.extras + [name])).sorted() }
    }

    // switching

    /// a built env waits for the next launch or "Restart to update"
    public func stage(_ hash: String) throws { _ = try update { $0.pending = hash; $0.held.removeAll { $0 == hash } } }

    /// at launch: a built, good pending env becomes current, and current becomes previous. The hash to run.
    @discardableResult
    public func switchAtLaunch() throws -> String? {
        try update { s in
            if let p = s.pending, p != s.current, isBuilt(p), !s.bad.contains(p) {
                s.previous = s.current; s.current = p; s.early_crashes = 0
                if let n = s.locks[p] { s.highest_n = max(s.highest_n, n) }
            }
            s.pending = nil
        }.current
    }

    /// makes `hash` current with nothing before it: the first env
    public func adopt(_ hash: String) throws {
        _ = try update { s in
            if s.current != hash { s.previous = s.current }
            s.current = hash; s.pending = nil; s.early_crashes = 0
            if let n = s.locks[hash] { s.highest_n = max(s.highest_n, n) }
        }
    }

    /// back to the previous env; with `bad`, the current hash is never used again. False when there is no previous env.
    @discardableResult
    public func rollback(bad: Bool) throws -> Bool {
        var done = false
        _ = try update { s in
            guard let prev = s.previous, isBuilt(prev), let cur = s.current else { return }
            if bad && !s.bad.contains(cur) { s.bad.append(cur) }
            if !bad && !s.held.contains(cur) { s.held.append(cur) }
            s.current = prev; s.previous = bad ? nil : cur; s.pending = nil; s.early_crashes = 0
            done = true
        }
        return done
    }

    /// counts a crash before ready; the count, which resets on a switch
    public func earlyCrash() throws -> Int { try update { $0.early_crashes += 1 }.early_crashes }
    public func ready() throws { _ = try update { $0.early_crashes = 0 } }

    /// removes every env that is not current, previous, pending or in use, and every partial build not in `building`
    @discardableResult
    public func gc(inUse: Set<String> = [], building: Set<String> = []) throws -> [String] {
        let s = load(), fm = FileManager.default
        let keep = Set([s.current, s.previous, s.pending].compactMap { $0 } + Array(inUse)).map { String($0.prefix(16)) }
        let busy = Set(building.map { String($0.prefix(16)) })
        guard let names = try? fm.contentsOfDirectory(atPath: paths.envs.path) else { return [] }
        var gone = [String]()
        for n in names where !keep.contains(n) && !busy.contains(n) {
            try fm.removeItem(at: paths.envs.appending(path: n)); gone.append(n)
        }
        return gone.sorted()
    }

    /// whether the weekly `uv cache prune` is due
    public func pruneDue(now: Date = Date()) -> Bool { now.timeIntervalSince1970 - load().pruned > 7 * 86400 }

    public func pruneLaunch() -> Launch {
        Launch(executable: uv, args: ["cache", "prune"], env: spec.uvEnv(parent, home: home, vals: vals(env: paths.envs, python: "3.12")), cwd: paths.support)
    }

    /// copies a checked lock folder into locks/<n>, where uv reads it; the bundle stays untouched
    public func keep(lock dir: URL, n: Int) throws -> URL {
        let fm = FileManager.default, dst = paths.lock(n)
        if dir.standardizedFileURL == dst.standardizedFileURL { return dst }
        try fm.createDirectory(at: paths.locks, withIntermediateDirectories: true)
        let tmp = paths.locks.appending(path: ".tmp-\(n)-\(UUID().uuidString)")
        try fm.createDirectory(at: tmp, withIntermediateDirectories: true)
        for f in LockCheck.names { try fm.copyItem(at: dir.appending(path: f), to: tmp.appending(path: f)) }
        if fm.fileExists(atPath: dst.path) { try fm.removeItem(at: dst) }
        try fm.moveItem(at: tmp, to: dst)
        return dst
    }
}

/// run.lock: one launcher per user at a time.
public final class RunLock {
    let fd: Int32
    public init?(_ url: URL) {
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        fd = open(url.path, O_RDWR | O_CREAT, 0o644)
        guard fd >= 0, flock(fd, LOCK_EX | LOCK_NB) == 0 else { if fd >= 0 { close(fd) }; return nil }
    }
    deinit { flock(fd, LOCK_UN); close(fd) }
}
