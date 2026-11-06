import Foundation
import Testing
@testable import LeelaCore

@Suite struct ChildEnvTests {
    let spec = try! ChildEnv.load(childenvURL)

    @Test func dropsThePythonAndUVSettingsOfTheParent() {
        let parent = ["PATH": "/usr/bin", "VIRTUAL_ENV": "/v", "PYTHONPATH": "p", "UV_INDEX_URL": "x", "CONDA_PREFIX": "c", "LEELA_HOST_TOKEN": "t", "OPENAI_API_KEY": "k"]
        let e = spec.uvEnv(parent, home: "/h", vals: ["cache": "/c", "python": "/py", "python_version": "3.13.18", "env": "/e"])
        for k in ["VIRTUAL_ENV", "PYTHONPATH", "UV_INDEX_URL", "CONDA_PREFIX", "LEELA_HOST_TOKEN"] { #expect(e[k] == nil, "\(k)") }
        #expect(e["OPENAI_API_KEY"] == "k" && e["HOME"] == "/h" && e["LANG"] == "en_US.UTF-8")
        #expect(e["UV_PROJECT_ENVIRONMENT"] == "/e" && e["UV_PYTHON"] == "3.13.18" && e["UV_NO_CONFIG"] == "1" && e["UV_FROZEN"] == "1")
        #expect(e["UV_PYTHON_PREFERENCE"] == "only-managed" && e["UV_LINK_MODE"] == "clone" && e["UV_CACHE_DIR"] == "/c")
    }

    @Test func theServerGetsThePersonsEnvAndNoBuildSettings() {
        let e = spec.serverEnv(["PATH": "/usr/bin:/x", "UV_INDEX_URL": "x", "VIRTUAL_ENV": "/v", "OPENAI_API_KEY": "k"], home: "/h", extra: ["LEELA_APP_VERSION": "1.0.0"])
        #expect(e["PATH"]!.hasPrefix("/h/.local/bin:/opt/homebrew/bin") && e["PATH"]!.hasSuffix(":/x"))
        #expect(!e.keys.contains { $0.hasPrefix("UV_") } && e["VIRTUAL_ENV"] == nil && e["PYTHONNOUSERSITE"] == nil && e["NO_COLOR"] == nil)
        #expect(e["PYTHONUNBUFFERED"] == "1" && e["LEELA_APP_VERSION"] == "1.0.0" && e["OPENAI_API_KEY"] == "k" && e["HOME"] == "/h")
    }

    @Test func theCommandsComeFromTheSameFileAsToolsLockPy() {
        #expect(spec.syncArgs(lock: URL(fileURLWithPath: "/l"), extras: ["mlx", "llama"]) == ["sync", "--frozen", "--no-install-project", "--project", "/l", "--extra", "mlx", "--extra", "llama"])
        #expect(spec.syncArgs(lock: URL(fileURLWithPath: "/l"), extras: ["mlx"], inexact: true).suffix(3) == ["--inexact", "--extra", "mlx"])
        #expect(spec.serverArgs(port: 5123) == ["--app", "--shell", "none", "--port", "5123", "--gateway-port", "0"])
        #expect(spec.api == LauncherAPI.version)
    }
}

@Suite struct SSHSigTests {
    let msg = try! Data(contentsOf: fixtures.appending(path: "message.json"))
    func sig(_ n: String) -> String { String(decoding: try! Data(contentsOf: fixtures.appending(path: "\(n).sig")), as: UTF8.self) }

    @Test func aSignatureFromEitherEmbeddedKeyIsGood() throws {
        #expect(try SSHSig.verify(message: msg, signature: sig("main"), keys: fixtureKeys).comment == "fixture-main")
        #expect(try SSHSig.verify(message: msg, signature: sig("emergency"), keys: fixtureKeys).comment == "fixture-emergency")
    }

    @Test func aChangedMessageAnotherKeyOrNamespaceOrBrokenArmorIsRefused() {
        var bad = msg; bad[bad.startIndex] ^= 1
        #expect(throws: SSHSigError.badSignature) { try SSHSig.verify(message: bad, signature: sig("main"), keys: fixtureKeys) }
        #expect(throws: SSHSigError.unknownKey) { try SSHSig.verify(message: msg, signature: sig("stranger"), keys: fixtureKeys) }
        #expect(throws: SSHSigError.namespace) { try SSHSig.verify(message: msg, signature: sig("wrongns"), keys: fixtureKeys) }
        #expect(throws: SSHSigError.armor) { try SSHSig.verify(message: msg, signature: "not a signature", keys: fixtureKeys) }
        #expect(throws: SSHSigError.unknownKey) { try SSHSig.verify(message: msg, signature: sig("main"), keys: [fixtureKeys[1]]) }
    }

    @Test func keysPubParsesOnlyEd25519Lines() {
        #expect(fixtureKeys.count == 2 && fixtureKeys.allSatisfy { $0.raw.count == 32 })
        #expect(SSHKey.parse(line: "ssh-rsa AAAAB3NzaC1yc2E x") == nil)
    }
}

@Suite struct LockCheckTests {
    @Test func theLockHashIsTheOneToolsLockPyComputes() throws {
        let d = tempDir()
        try Data("p".utf8).write(to: d.appending(path: "pyproject.toml"))
        try Data("l".utf8).write(to: d.appending(path: "uv.lock"))
        try Data("3.12.16\n".utf8).write(to: d.appending(path: ".python-version"))
        // tests/test_lock.py pins the same value
        #expect(try LockHash.hash(dir: d, uv: "0.13.6") == "2b6ad4d75869cd770d5cf35be37c47dc40fe7cfce61490729959b38333e9472a")
        #expect(try LockHash.hash(dir: d, uv: "0.13.7") != LockHash.hash(dir: d, uv: "0.13.6"))
    }

    @Test func aGoodLockIsOK() throws {
        let d = tempDir(), m = makeLock(d, n: 3)
        #expect(try LockCheck.check(dir: d, keys: fixtureKeys, app: facts) == .ok(m))
    }

    @Test func aBadSignatureIsRefused() throws {
        let d = tempDir(); makeLock(d, n: 3)
        try Data((String(decoding: try Data(contentsOf: d.appending(path: "manifest.json")), as: UTF8.self) + " ").utf8).write(to: d.appending(path: "manifest.json"))
        #expect { try LockCheck.check(dir: d, keys: fixtureKeys, app: facts) } throws: { if case LockRefusal.signature = $0 { true } else { false } }
        #expect { try LockCheck.check(dir: d, keys: [], app: facts) } throws: { if case LockRefusal.signature = $0 { true } else { false } }
    }

    @Test func aChangedFileIsRefused() throws {
        let d = tempDir(); makeLock(d, n: 3)
        // one hash in uv.lock changed: the manifest no longer matches
        try Data("version = 1\n# lock 3 sha256:00\n".utf8).write(to: d.appending(path: "uv.lock"))
        #expect(throws: LockRefusal.fileHash("uv.lock")) { try LockCheck.check(dir: d, keys: fixtureKeys, app: facts) }
    }

    @Test func aWrongLockHashIsRefused() throws {
        let d = tempDir(); makeLock(d, n: 3) { $0.hash = String(repeating: "0", count: 64) }
        #expect(throws: LockRefusal.lockHash) { try LockCheck.check(dir: d, keys: fixtureKeys, app: facts) }
    }

    @Test func anOlderOrSameLockIsAReplay() throws {
        let d = tempDir(); makeLock(d, n: 3)
        #expect(throws: LockRefusal.replay(n: 3, highest: 3)) { try LockCheck.check(dir: d, keys: fixtureKeys, app: facts, highest: 3) }
        #expect(throws: LockRefusal.replay(n: 3, highest: 5)) { try LockCheck.check(dir: d, keys: fixtureKeys, app: facts, highest: 5) }
    }

    @Test func aLockForANewerAppNeedsTheApp() throws {
        let a = tempDir(), m = makeLock(a, n: 4, uv: "0.14.0")
        #expect(try LockCheck.check(dir: a, keys: fixtureKeys, app: facts) == .needsApp(m))
        let b = tempDir(), m2 = makeLock(b, n: 4, api: 2)
        #expect(try LockCheck.check(dir: b, keys: fixtureKeys, app: facts) == .needsApp(m2))
    }

    @Test func aWrongPlatformOrMacOSOrABadHashIsRefused() throws {
        let a = tempDir(); makeLock(a, n: 4, platform: "darwin-x86_64")
        #expect(throws: LockRefusal.platform("darwin-x86_64")) { try LockCheck.check(dir: a, keys: fixtureKeys, app: facts) }
        let b = tempDir(); makeLock(b, n: 4, macos: "27.0")
        #expect(throws: LockRefusal.macOS("27.0")) { try LockCheck.check(dir: b, keys: fixtureKeys, app: facts) }
        let c = tempDir(), m = makeLock(c, n: 4)
        #expect(throws: LockRefusal.bad(m.hash)) { try LockCheck.check(dir: c, keys: fixtureKeys, app: facts, bad: [m.hash]) }
    }

    @Test func aMissingFileIsRefused() throws {
        let d = tempDir(); makeLock(d, n: 3)
        try FileManager.default.removeItem(at: d.appending(path: ".python-version"))
        #expect(throws: LockRefusal.missing(".python-version")) { try LockCheck.check(dir: d, keys: fixtureKeys, app: facts) }
    }

    @Test func versionsCompareByNumber() {
        #expect(versionLess("0.13.6", "0.13.10") && !versionLess("0.13.10", "0.13.6") && !versionLess("14.0", "14.0.0"))
    }
}
