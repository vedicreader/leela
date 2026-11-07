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

    @Test func aNewLocksEnvStartsFromACopyOfTheOneInUseAndKeepsNoReferenceToIt() async throws {
        let uv = fakeUV(), s = store(uv: uv), a = tempDir(), b = tempDir()
        makeLock(a, n: 1); makeLock(b, n: 2)
        let ha = try await s.build(lock: a, n: 1); try s.adopt(ha)
        let A = s.paths.env(ha), before = try Data(contentsOf: s.paths.marker(ha)) + Data(contentsOf: A.appending(path: "bin/tool"))
        let hb = try await s.build(lock: b, n: 2)
        let B = s.paths.env(hb), calls = try String(contentsOf: uv.deletingLastPathComponent().appending(path: "seeded.txt"), encoding: .utf8)
        #expect(calls.components(separatedBy: "\n").filter { $0 == "SEEDED" }.count == 1, "the second build started from a copy")
        #expect(try String(contentsOf: B.appending(path: "bin/tool"), encoding: .utf8) == "#!\(B.path)/bin/python\n")
        var left = [String]()
        for case let f as URL in FileManager.default.enumerator(at: B, includingPropertiesForKeys: nil)! {
            if let d = try? Data(contentsOf: f), d.range(of: Data(A.path.utf8)) != nil { left.append(f.path) }
        }
        #expect(left.isEmpty, "B still names A: \(left)")
        #expect(s.isBuilt(hb) && s.marker(hb)?.n == 2)
        #expect(try Data(contentsOf: s.paths.marker(ha)) + Data(contentsOf: A.appending(path: "bin/tool")) == before, "A is not touched")
    }

    @Test func aCopyThatFailsToSyncIsBuiltFresh() async throws {
        let uv = fakeUV(), s = store(uv: uv), a = tempDir(), b = tempDir()
        makeLock(a, n: 1); makeLock(b, n: 2)
        let ha = try await s.build(lock: a, n: 1); try s.adopt(ha)
        try Data().write(to: uv.deletingLastPathComponent().appending(path: "SEEDFAIL"))
        let hb = try await s.build(lock: b, n: 2)
        #expect(s.isBuilt(hb) && s.isBuilt(ha))
    }

    @Test func anEnvWithAnotherPythonOrNoCloneIsNotACopy() async throws {
        let uv = fakeUV(), s = store(uv: uv), a = tempDir(), b = tempDir()
        makeLock(a, n: 1); makeLock(b, n: 2)
        let ha = try await s.build(lock: a, n: 1); try s.adopt(ha)
        #expect(!s.seed(tempDir().appending(path: "x"), from: s.paths.env(ha), python: "3.12.16"), "another Python is a fresh build")
        #expect(!s.seed(tempDir().appending(path: "x"), from: tempDir().appending(path: "missing"), python: "3.13.18"))
        let hb = try await s.build(lock: b, n: 2)
        #expect(s.isBuilt(hb))
    }

    @Test func theChangesBetweenTwoLocksAreSaidInAFewWords() throws {
        let a = tempDir(), b = tempDir()
        try Data("version = 1\n\n[[package]]\nname = \"leela-lock\"\nversion = \"0\"\n\n[[package]]\nname = \"ramabana\"\nversion = \"0.2.109\"\n\n[[package]]\nname = \"x\"\nversion = \"1\"\n".utf8).write(to: a.appending(path: "uv.lock"))
        try Data("version = 1\n\n[[package]]\nname = \"ramabana\"\nversion = \"0.2.110\"\n\n[[package]]\nname = \"x\"\nversion = \"1\"\n".utf8).write(to: b.appending(path: "uv.lock"))
        #expect(LockDiff.summary(LockDiff.changes(from: a, to: b)) == "Updating 1 package: ramabana 0.2.109 → 0.2.110")
        #expect(LockDiff.summary((1...5).map { "p\($0)" }) == "Updating 5 packages: p1, p2, p3 and 2 more" && LockDiff.summary([]) == "")
    }
}
