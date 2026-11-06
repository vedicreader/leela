import Foundation
import Testing
@testable import LeelaCore

/// The system Python runs a small HTTP server in place of Leela. Arguments: the port, then the seconds before it stops with exit code 3
/// (0: never; less than 0: stop at once with exit code 2; 999: never answer /health).
let fakeLeela = """
import sys, os, threading, http.server, time
port, die = int(sys.argv[1]), float(sys.argv[2])
if die < 0: sys.exit(2)
if die == 999: time.sleep(60); sys.exit(0)
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        b = b'{"status":"ok"}' if self.path == '/health' else b'{}'
        self.send_response(200); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
if die > 0: threading.Timer(die, lambda: os._exit(3)).start()
print('fake leela on', port, flush=True)
http.server.HTTPServer(('127.0.0.1', port), H).serve_forever()
"""

func py(_ port: Int, _ die: Double) -> Launch {
    Launch(executable: URL(fileURLWithPath: "/usr/bin/python3"), args: ["-c", fakeLeela, String(port), String(die)], env: ["PATH": "/usr/bin:/bin"])
}

@MainActor func until(_ seconds: Double = 15, _ cond: () -> Bool) async -> Bool {
    let end = Date().addingTimeInterval(seconds)
    while Date() < end { if cond() { return true }; try? await Task.sleep(for: .milliseconds(50)) }
    return cond()
}

@MainActor func supervisor(_ s: EnvStore, lock: URL?, n: Int = 1, die: @escaping (String) -> Double = { _ in 0 }) -> Supervisor {
    let m = lock.map { try! JSONDecoder().decode(Manifest.self, from: Data(contentsOf: $0.appending(path: "manifest.json"))) }
    let sup = Supervisor(store: s, plan: { (lock.map { LockPlan(dir: $0, verdict: .ok(m!), online: true) }, nil) },
                         serverLaunch: { port, h in py(port, die(h)) })
    sup.healthTimeout = .seconds(10)
    return sup
}

@MainActor @Suite(.serialized) struct SupervisorTests {
    @Test func theFirstRunBuildsShowsThePhasesAndStarts() async throws {
        let s = store(), lock = tempDir(); makeLock(lock, n: 1)
        let sup = supervisor(s, lock: lock)
        var seen = [Phase]()
        sup.onPhase = { seen.append($0) }
        await sup.start()
        guard case .ready(let base) = sup.phase else { Issue.record("phase \(sup.phase)"); return }
        #expect(await Health.check(base))
        #expect(seen.first == .setup(.checking) && seen.contains(.setup(.starting)))
        #expect(seen.contains { if case .setup(.packages) = $0 { true } else { false } })
        #expect(s.load().current == sup.hash && s.load().proven == [sup.hash!])
        sup.stop()
        #expect(!sup.isRunning && sup.phase == .idle)
    }

    @Test func aFailedFirstBuildShowsTheReasonAndTheLog() async throws {
        let uv = fakeUV(), s = store(uv: uv), lock = tempDir(); makeLock(lock, n: 1)
        try Data().write(to: uv.deletingLastPathComponent().appending(path: "FAIL"))
        let sup = supervisor(s, lock: lock)
        await sup.start()
        guard case .failed(let msg) = sup.phase else { Issue.record("phase \(sup.phase)"); return }
        #expect(msg.hasPrefix(Setup.buildFailed) && msg.contains("no network"))
    }

    @Test func noEnvAndNoNetworkIsOffline() async throws {
        let s = store()
        let sup = Supervisor(store: s, plan: { (nil, "The Internet connection appears to be offline.") }, serverLaunch: { p, _ in py(p, 0) })
        await sup.start()
        #expect(sup.phase == .offline)
    }

    @Test func aServerThatNeverAnswersTimesOut() async throws {
        let s = store(), lock = tempDir(); makeLock(lock, n: 1)
        let sup = supervisor(s, lock: lock, die: { _ in 999 })
        sup.healthTimeout = .seconds(2)
        await sup.start()
        guard case .failed(let msg) = sup.phase else { Issue.record("phase \(sup.phase)"); return }
        #expect(msg.hasPrefix("The Leela server did not start."))
    }

    @Test func aCrashGivesStartAgainAndStartAgainWorks() async throws {
        let s = store(), lock = tempDir(); makeLock(lock, n: 1)
        var die = 1.0
        let sup = supervisor(s, lock: lock, die: { _ in die })
        await sup.start()
        guard case .ready = sup.phase else { Issue.record("phase \(sup.phase)"); return }
        #expect(await until { if case .failed = sup.phase { true } else { false } })
        guard case .failed(let msg) = sup.phase else { return }
        #expect(msg.contains("exit code 3") && msg.contains("fake leela on"))
        die = 0
        await sup.restart()
        guard case .ready = sup.phase else { Issue.record("phase \(sup.phase)"); return }
        sup.stop()
    }

    @Test func aNewEnvThatCrashesTwiceRollsBackAndIsMarkedBad() async throws {
        let s = store(), a = tempDir(), b = tempDir()
        makeLock(a, n: 1); makeLock(b, n: 2)
        let ha = try await s.build(lock: a, n: 1); try s.adopt(ha)
        _ = try s.update { $0.proven = [ha] }
        let hb = try await s.build(lock: b, n: 2); try s.stage(hb)
        var started = [String]()
        let sup = supervisor(s, lock: b, n: 2, die: { h in started.append(h); return h == hb ? -1 : 0 })
        await sup.start()
        guard case .ready = sup.phase else { Issue.record("phase \(sup.phase)"); return }
        #expect(sup.hash == ha && s.load().current == ha && s.load().bad == [hb])
        #expect(started.filter { $0 == hb }.count == 2 && started.last == ha)
        sup.stop()
        await sup.start()
        #expect(sup.hash == ha, "the bad env is not staged again")
        sup.stop()
    }

    @Test func aNewerLockIsOfferedNotBuiltThenUpdateBuildsAndRestartSwitches() async throws {
        let s = store(), a = tempDir(), b = tempDir()
        makeLock(a, n: 1); makeLock(b, n: 2)
        let ha = try await s.build(lock: a, n: 1); try s.adopt(ha)
        let sup = supervisor(s, lock: b, n: 2)
        await sup.start()
        #expect(sup.hash == ha && sup.offered?.n == 2)
        #expect((sup.status(appVersion: "1.0.0", brew: false)["lock"] as? [String: Any])?["newer"] as? Bool == true)
        await sup.buildUpdate()
        #expect(sup.update.state == "ready" && s.load().pending != nil)
        await sup.restart()
        #expect(sup.hash != ha && s.load().previous == ha)
        #expect(await sup.usePrevious())
        #expect(sup.hash == ha)
        sup.stop()
    }

    @Test func aFailedUpdateLeavesTheCurrentEnvRunning() async throws {
        let uv = fakeUV(), s = store(uv: uv), a = tempDir(), b = tempDir()
        makeLock(a, n: 1); makeLock(b, n: 2)
        let ha = try await s.build(lock: a, n: 1); try s.adopt(ha)
        let sup = supervisor(s, lock: b, n: 2)
        await sup.start()
        try Data().write(to: uv.deletingLastPathComponent().appending(path: "FAIL"))
        await sup.buildUpdate()
        #expect(sup.update == UpdateState(state: "error", line: Setup.updateFailed))
        #expect(s.load().current == ha && s.load().pending == nil && sup.isRunning)
        sup.stop()
    }
}

@Suite struct SetupTests {
    @Test func uvLinesMoveThePhasesInOrder() {
        var p = SetupPhase.checking
        for (line, want) in [("Using CPython 3.12.16", "packages"), ("Downloading cpython-3.12.16-macos-aarch64-none (23.9MiB)", "python"),
                             ("Downloading numpy (5.1MiB)", "packages"), ("Prepared 272 packages in 30s", "packages"), ("Installed 272 packages in 2s", "verifying")] {
            p = Setup.phase(after: line, current: p, done: 10_000_000, total: 400_000_000) ?? p
            #expect("\(p)".hasPrefix(want), "\(line)")
        }
    }

    @Test func thePackagesPhaseIsDeterminateWithATotal() {
        let p = SetupPhase.packages(done: 100_000_000, total: 400_000_000, line: "x")
        #expect(p.fraction == 0.25 && p.title == "Getting packages (100 MB of about 400 MB)")
        #expect(SetupPhase.packages(done: 1, total: 0, line: "").fraction == nil && SetupPhase.python.fraction == nil)
    }

    @Test func aFailureShowsTheReasonAndTheLastSixLines() throws {
        let f = tempDir().appending(path: "log")
        try Data((1...10).map { "line \($0)" }.joined(separator: "\n").utf8).write(to: f)
        let msg = Setup.failure(Setup.buildFailed, log: f)
        #expect(msg.hasPrefix(Setup.buildFailed) && msg.contains("line 5") && !msg.contains("line 4\n") && msg.hasSuffix("line 10"))
    }
}
