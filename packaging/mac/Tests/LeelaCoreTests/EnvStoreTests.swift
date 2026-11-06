import Foundation
import Testing
@testable import LeelaCore

@Suite struct EnvStoreTests {
    @Test func aBuildWritesTheMarkerLastWithTheCleanEnv() async throws {
        let uv = fakeUV(), s = store(uv: uv), lock = tempDir()
        makeLock(lock, n: 1)
        let h = try await s.build(lock: lock, n: 1)
        #expect(h == (try LockHash.hash(dir: lock, uv: "0.13.6")))
        #expect(s.isBuilt(h) && s.marker(h)?.n == 1 && s.load().locks[h] == 1)
        let env = try String(contentsOf: uv.deletingLastPathComponent().appending(path: "env.txt"), encoding: .utf8)
        #expect(env.contains("UV_PROJECT_ENVIRONMENT=\(s.paths.env(h).path)") && env.contains("UV_FROZEN=1") && !env.contains("evil.example"))
        let calls = try String(contentsOf: uv.deletingLastPathComponent().appending(path: "calls.txt"), encoding: .utf8)
        #expect(calls.hasPrefix("sync --frozen --no-install-project --project \(lock.path)"))
        #expect(try String(contentsOf: s.paths.syncLog(h), encoding: .utf8).contains("Installed 3 packages"))
    }

    @Test func aFailedBuildLeavesNoFolderAndTheTail() async throws {
        let uv = fakeUV(), s = store(uv: uv), lock = tempDir()
        makeLock(lock, n: 1)
        try Data().write(to: uv.deletingLastPathComponent().appending(path: "FAIL"))
        await #expect { try await s.build(lock: lock, n: 1) } throws: { e in
            if case BuildError.failed(2, let tail) = e { tail.contains("no network") } else { false }
        }
        #expect(!FileManager.default.fileExists(atPath: s.paths.env(try s.hash(lock: lock)).path))
        #expect(s.load().current == nil)
    }

    @Test func aPartialFolderIsRebuiltAndGCRemovesUnmarkedOnes() async throws {
        let s = store(), lock = tempDir()
        makeLock(lock, n: 1)
        let h = try s.hash(lock: lock)
        try FileManager.default.createDirectory(at: s.paths.env(h).appending(path: "lib"), withIntermediateDirectories: true)
        #expect(!s.isBuilt(h))
        try await s.build(lock: lock, n: 1)
        #expect(s.isBuilt(h))
        try s.adopt(h)
        let junk = s.paths.envs.appending(path: "0123456789abcdef")
        try FileManager.default.createDirectory(at: junk, withIntermediateDirectories: true)
        #expect(try s.gc() == ["0123456789abcdef"])
        #expect(s.isBuilt(h))
    }

    @Test func theStateSwitchesAtomicallyAndOnlyAtLaunch() async throws {
        let s = store(), a = tempDir(), b = tempDir()
        makeLock(a, n: 1); makeLock(b, n: 2)
        let ha = try await s.build(lock: a, n: 1)
        try s.adopt(ha)
        let hb = try await s.build(lock: b, n: 2)
        try s.stage(hb)
        #expect(s.load().current == ha && s.load().pending == hb, "a staged env waits for a launch")
        #expect(try s.switchAtLaunch() == hb)
        let st = s.load()
        #expect(st.current == hb && st.previous == ha && st.pending == nil && st.highest_n == 2)
        #expect(!FileManager.default.fileExists(atPath: s.paths.support.appending(path: "state.json.tmp").path))
    }

    @Test func rollbackMarksTheEnvBadAndUsePreviousDoesNot() async throws {
        let s = store(), a = tempDir(), b = tempDir()
        makeLock(a, n: 1); makeLock(b, n: 2)
        let ha = try await s.build(lock: a, n: 1); try s.adopt(ha)
        let hb = try await s.build(lock: b, n: 2); try s.stage(hb); try s.switchAtLaunch()
        #expect(try s.rollback(bad: false))
        #expect(s.load().current == ha && s.load().previous == hb && s.load().bad.isEmpty)
        try s.stage(hb); try s.switchAtLaunch()
        #expect(try s.rollback(bad: true))
        #expect(s.load().current == ha && s.load().bad == [hb] && s.load().previous == nil)
        try s.stage(hb)
        #expect(try s.switchAtLaunch() == ha, "a bad env never comes back")
        #expect(try !s.rollback(bad: true), "no previous env: nothing to roll back to")
    }

    @Test func extrasAreInstalledInPlaceRecordedAndCarriedToTheNextEnv() async throws {
        let uv = fakeUV(), s = store(uv: uv), a = tempDir(), b = tempDir()
        makeLock(a, n: 1); makeLock(b, n: 2)
        let ha = try await s.build(lock: a, n: 1); try s.adopt(ha)
        _ = try s.keep(lock: a, n: 1)
        try await s.installExtra("mlx")
        #expect(s.marker(ha)?.extras == ["mlx"] && s.load().extras == ["mlx"])
        let calls = try String(contentsOf: uv.deletingLastPathComponent().appending(path: "calls.txt"), encoding: .utf8)
        #expect(calls.contains("--inexact --extra mlx"))
        let hb = try await s.build(lock: b, n: 2)
        #expect(s.marker(hb)?.extras == ["mlx"])
        #expect(try String(contentsOf: uv.deletingLastPathComponent().appending(path: "calls.txt"), encoding: .utf8).split(separator: "\n").last!.hasSuffix("--extra mlx"))
        await #expect(throws: BuildError.unknownExtra("torch")) { try await s.installExtra("torch") }
    }

    @Test func anOldStateFileStillLoads() throws {
        let s = store()
        try FileManager.default.createDirectory(at: s.paths.support, withIntermediateDirectories: true)
        try Data(#"{"current":"abc","highest_n":3}"#.utf8).write(to: s.paths.state)
        #expect(s.load().current == "abc" && s.load().highest_n == 3 && s.load().proven.isEmpty)
    }

    @Test func oneLauncherAtATime() {
        let p = tempPaths()
        let a = RunLock(p.runLock)
        #expect(a != nil && RunLock(p.runLock) == nil)
    }
}
