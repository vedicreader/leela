import Foundation
import Testing
@testable import LeelaCore

@Suite struct ServerCommandTests {
    let info = HostInfo(url: "http://127.0.0.1:4567", token: "secret-token-123", appVersion: "1.0.0", bundle: "/Applications/Leela.app", uv: URL(fileURLWithPath: "/x/uv"))

    @Test func theTokenGoesOnStdinAndNowhereElse() async throws {
        let s = store(), lock = tempDir(); makeLock(lock, n: 3)
        let h = try await s.build(lock: lock, n: 3); _ = try s.keep(lock: lock, n: 3)
        let l = ServerCommand.launch(store: s, port: 5123, hash: h, host: info)
        #expect(l.stdinLine == "secret-token-123")
        #expect(!l.env.values.contains { $0.contains("secret-token-123") } && !l.args.contains { $0.contains("secret-token-123") })
        #expect(l.env["LEELA_HOST_TOKEN"] == nil && l.env["LEELA_HOST_URL"] == "http://127.0.0.1:4567" && l.env["LEELA_LOCK_N"] == "3" && l.env["LEELA_ENV_HASH"] == h)
        #expect(l.env["UV_PYTHON"] == "3.12.16" && l.env["VIRTUAL_ENV"] == s.paths.env(h).path && l.args == ["--app", "--shell", "none", "--port", "5123", "--gateway-port", "0"])
    }

    @Test func aStartedChildReadsTheLineThenEndOfFile() async throws {
        let log = tempDir().appending(path: "log")
        let l = Launch(executable: URL(fileURLWithPath: "/bin/sh"), args: ["-c", "read t; echo \"first:$t\"; if read u; then echo more; else echo eof; fi"],
                       env: ["PATH": "/usr/bin:/bin"], stdinLine: "tok")
        let done = DispatchSemaphore(value: 0)
        _ = try Run.start(l, log: log) { _ in done.signal() }
        #expect(done.wait(timeout: .now() + 10) == .success)
        let out = try String(contentsOf: log, encoding: .utf8)
        #expect(out.contains("first:tok") && out.contains("eof") && !out.contains("more"))
    }

    @Test func aGrantIsGoodOnceForOnePathAndExpires() {
        let g = GrantBook()
        let n = g.issue("/a")
        #expect(!g.check(n, path: "/b") && !g.check(n, path: "/a"), "a wrong path spends it")
        let m = g.issue("/a")
        #expect(g.check(m, path: "/a") && !g.check(m, path: "/a") && !g.check("made-up", path: "/a"))
        g.ttl = -1
        let o = g.issue("/a")
        #expect(!g.check(o, path: "/a"))
    }
}
