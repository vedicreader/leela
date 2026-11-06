import Foundation
import Observation

/// What the app shows: setup, start, the windows, offline, or a failure with Try Again.
public enum Phase: Equatable, Sendable {
    case idle
    case setup(SetupPhase)
    case starting
    case ready(URL)
    /// no env and no network: the app retries when the network comes back
    case offline
    case failed(String)
}

/// An update's state as `/update` reports it; `ready` means built and waiting for "Restart to update".
public struct UpdateState: Equatable, Sendable {
    public var state = "idle"
    public var line = ""
    public init(state: String = "idle", line: String = "") { self.state = state; self.line = line }
}

/// Builds the env, starts the server, waits for `/health`, and rolls back an env that cannot start. Adapted from abhyasa's Supervisor.
@MainActor @Observable
public final class Supervisor {
    public private(set) var phase: Phase = .idle
    public private(set) var port = 0
    public private(set) var hash: String?
    /// a newer lock the channel offers, not built yet; Update builds it
    public private(set) var offered: LockPlan?
    public private(set) var needsApp: Manifest?
    public private(set) var update = UpdateState()
    public private(set) var extras: [String: UpdateState] = [:]
    public var healthTimeout: Duration = .seconds(120)
    public var tries = 2
    public let store: EnvStore
    /// which lock to run; tests replace it
    @ObservationIgnored public var plan: () async -> (plan: LockPlan?, error: String?)
    /// the server command for a port and an env hash; tests replace it
    @ObservationIgnored public var serverLaunch: (Int, String) -> Launch
    @ObservationIgnored public var onReady: ((URL) -> Void)?
    @ObservationIgnored public var onPhase: ((Phase) -> Void)?
    @ObservationIgnored private var server: Running?
    @ObservationIgnored private var building: Running?
    @ObservationIgnored private var stopping = false
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var rolledBack = false

    public init(store: EnvStore, plan: @escaping () async -> (plan: LockPlan?, error: String?),
                serverLaunch: @escaping (Int, String) -> Launch) {
        self.store = store; self.plan = plan; self.serverLaunch = serverLaunch
    }

    public var isRunning: Bool { server?.isRunning ?? false }
    /// the env an update build writes, which gc must leave alone
    public private(set) var buildingHash: String?

    func set(_ p: Phase) { phase = p; onPhase?(p) }

    /// one line in logs/setup.log: which lock was chosen and why
    func note(_ what: String) {
        let log = store.paths.logs.appending(path: "setup.log"), line = "\(ISO8601DateFormatter().string(from: Date())) \(what)\n"
        try? FileManager.default.createDirectory(at: store.paths.logs, withIntermediateDirectories: true)
        if let h = try? FileHandle(forWritingTo: log) { h.seekToEndOfFile(); h.write(Data(line.utf8)); try? h.close() } else { try? Data(line.utf8).write(to: log) }
    }

    /// stops a running server, then: choose the lock, build the first env if there is none, switch to a pending env, start, wait
    public func start() async {
        stop()
        stopping = false
        rolledBack = false
        generation += 1
        let gen = generation
        set(.setup(.checking))
        let (p, why) = await plan()
        guard gen == generation, !stopping else { return }
        var run: String?
        do { run = try store.switchAtLaunch() } catch { run = store.load().current }
        if let r = run, !store.isBuilt(r) { run = nil }
        let s = store.load()
        offered = nil; needsApp = nil
        if let p {
            switch p.verdict {
            case .needsApp(let m): needsApp = m
            case .ok(let m):
                let h = (try? store.hash(lock: p.dir)) ?? ""
                if run == nil {
                    do { run = try await firstBuild(p, gen: gen) } catch {
                        guard gen == generation, !stopping else { return }
                        return set(.failed(Setup.failure(Setup.buildFailed, log: store.paths.syncLog(h))))
                    }
                } else if h != run, (s.locks[run!] ?? -1) < m.n, !s.bad.contains(h) {
                    if store.isBuilt(h) && !s.held.contains(h) { try? store.stage(h); update = UpdateState(state: "ready") }
                    else if p.bundled && !s.held.contains(h) {
                        // a new app brings its own lock: built and run now, with the env in use kept as previous; a failed build leaves that env running
                        note("lock \(m.n) \(h.prefix(16)) came with the app: building it over lock \(s.locks[run!] ?? -1) \(run!.prefix(16))")
                        do { run = try await firstBuild(p, gen: gen); note("lock \(m.n) built and current") }
                        catch { guard gen == generation, !stopping else { return }; note("lock \(m.n) did not build: \(error); lock \(s.locks[run!] ?? -1) runs"); offered = p }
                    } else { offered = p; note("lock \(m.n) \(h.prefix(16)) is offered: \(p.bundled ? "held after Use Previous Version" : "from the channel")") }
                } else if h != run { note("lock \(m.n) \(h.prefix(16)) not taken: lock \(s.locks[run ?? ""] ?? -1) runs\(s.bad.contains(h) ? ", and this one failed before" : "")") }
            }
        }
        guard gen == generation, !stopping else { return }
        guard let h = run else {
            if needsApp != nil { return set(.failed("This Leela app is too old for the newest packages. Update the Leela app.")) }
            return set(p == nil && why != nil ? .offline : .failed("Leela has no packages to run. " + (why ?? "")))
        }
        await launch(h, gen: gen)
    }

    func firstBuild(_ p: LockPlan, gen: Int) async throws -> String {
        set(.setup(.packages(done: 0, total: p.manifest.download_bytes, line: "")))
        let cache = store.paths.uvCache, start = Setup.bytes(cache), total = p.manifest.download_bytes
        let h = try await store.build(lock: p.dir, n: p.n, line: { [weak self] l in
            Task { @MainActor in
                guard let self, gen == self.generation, case .setup(let cur) = self.phase else { return }
                if let next = Setup.phase(after: l, current: cur, done: Setup.bytes(cache) - start, total: total) { self.set(.setup(next)) }
            }
        }, started: { [weak self] r in Task { @MainActor in self?.building = r } })
        guard gen == generation, !stopping else { throw CancellationError() }
        building = nil
        try store.adopt(h)
        return h
    }

    func launch(_ h: String, gen: Int) async {
        hash = h
        for attempt in 1...max(tries, 1) {
            set(.setup(.starting))
            do {
                let p = try Port.free()
                let proc = try Run.start(serverLaunch(p, h), log: store.paths.serverLog) { [weak self] code in
                    Task { @MainActor in self?.exited(code: code, gen: gen) }
                }
                server = proc; port = p
                try await Health.wait(Port.base(p), timeout: healthTimeout) { proc.isRunning }
                guard gen == generation, !stopping else { return }
                try? store.ready()
                _ = try? store.update { if !$0.proven.contains(h) { $0.proven.append(h) } }
                set(.ready(Port.base(p)))
                onReady?(Port.base(p))
                return
            } catch {
                guard gen == generation, !stopping else { return }
                server?.stop(); server = nil
                let s = store.load(), fresh = !s.proven.contains(h) && s.previous != nil
                let crashes = (try? store.earlyCrash()) ?? 0
                if fresh && (error as? HealthError == .timedOut || crashes >= 2), !rolledBack, (try? store.rollback(bad: true)) == true {
                    rolledBack = true
                    let prev = store.load().current!
                    return await launch(prev, gen: gen)
                }
                if attempt < tries, error as? HealthError == .exited { continue }
                return set(.failed("The Leela server did not start.\n\n" + Run.tail(store.paths.serverLog)))
            }
        }
    }

    private func exited(code: Int32, gen: Int) {
        guard gen == generation, !stopping, case .ready = phase else { return }
        server = nil
        set(.failed("The Leela server stopped (exit code \(code)).\n\n" + Run.tail(store.paths.serverLog)))
    }

    /// stops the server and a build that runs: SIGTERM, then SIGKILL after `grace` seconds
    public func stop(grace: Double = 3) {
        stopping = true
        building?.stop(); building = nil
        server?.stop(grace: grace); server = nil
        if case .ready = phase { set(.idle) }
        if case .setup = phase { set(.idle) }
    }

    /// Update for a lock: build the offered env at low priority while Leela runs, then wait for "Restart to update"
    public func buildUpdate() async {
        guard let p = offered, update.state != "running" else { return }
        update = UpdateState(state: "running", line: "getting the new packages")
        buildingHash = try? store.hash(lock: p.dir)
        defer { buildingHash = nil }
        do {
            let h = try await store.build(lock: p.dir, n: p.n, background: true, line: { [weak self] l in Task { @MainActor in self?.update.line = l } })
            try store.stage(h)
            offered = nil
            update = UpdateState(state: "ready")
        } catch { update = UpdateState(state: "error", line: Setup.updateFailed) }
    }

    /// the 6-hourly channel check while Leela runs: a newer good lock is offered, never built without a click
    public func checkForUpdates() async {
        guard case .ready = phase, let cur = hash else { return }
        let (p, _) = await plan()
        guard let p else { return }
        let s = store.load()
        switch p.verdict {
        case .needsApp(let m): if m.n > (s.locks[cur] ?? -1) { needsApp = m }
        case .ok(let m):
            let h = (try? store.hash(lock: p.dir)) ?? ""
            guard h != cur, m.n > (s.locks[cur] ?? -1), !s.bad.contains(h), s.pending != h else { return }
            if store.isBuilt(h) && !s.held.contains(h) { try? store.stage(h); update = UpdateState(state: "ready") } else { offered = p }
        }
    }

    /// "Restart to update" and "Start again": the pending env, if any, becomes current at this start
    public func restart() async { await start() }

    /// Leela > Use Previous Version
    public func usePrevious() async -> Bool {
        guard (try? store.rollback(bad: false)) == true else { return false }
        await restart()
        return true
    }

    public func setUpdate(_ u: UpdateState) { update = u }

    /// installs one pinned extra into the running env; `/status` reports it
    public func installExtra(_ name: String) async {
        guard extras[name]?.state != "running" else { return }
        extras[name] = UpdateState(state: "running")
        do {
            try await store.installExtra(name)
            extras[name] = UpdateState(state: "ok", line: "")
        } catch BuildError.failed(_, let tail) { extras[name] = UpdateState(state: "error", line: tail) }
        catch { extras[name] = UpdateState(state: "error", line: "\(error)") }
    }

    /// `/status` for the server
    public func status(appVersion: String, brew: Bool) -> [String: Any] {
        let s = store.load(), cur = s.current.flatMap { s.locks[$0] }
        let newest = offered?.n ?? needsApp?.n ?? (s.pending.flatMap { s.locks[$0] }) ?? cur
        var lock: [String: Any] = ["newer": (newest ?? -1) > (cur ?? -1), "needs_app": needsApp != nil]
        if let cur { lock["current_n"] = cur }
        if let newest { lock["newest_n"] = newest }
        return ["app_version": appVersion, "api": LauncherAPI.version, "brew": brew, "lock": lock, "env": hash ?? "",
                "extras": extras.mapValues { ["state": $0.state, "log": $0.line] }]
    }
}
