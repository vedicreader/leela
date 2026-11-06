import Foundation
import Network
@testable import LeelaCore

let here = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
let fixtures = here.appending(path: "Fixtures")
let repo = here.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
let childenvURL = repo.appending(path: "packaging/childenv.json")
let fixtureKeys = try! SSHKey.load(fixtures.appending(path: "keys.pub"))
let facts = AppFacts(uv: "0.13.6", api: 1, macOS: OperatingSystemVersion(majorVersion: 15, minorVersion: 0, patchVersion: 0))

func tempDir() -> URL {
    let u = FileManager.default.temporaryDirectory.appending(path: "leela-tests-\(UUID().uuidString)").resolvingSymlinksInPath()
    try! FileManager.default.createDirectory(at: u, withIntermediateDirectories: true)
    return u
}

func tempPaths() -> Paths { let d = tempDir(); return Paths(support: d.appending(path: "support"), caches: d.appending(path: "caches")) }

@discardableResult
func sh(_ exe: String, _ args: [String], env: [String: String] = ["PATH": "/usr/bin:/bin"]) -> Int32 {
    let p = Process(); p.executableURL = URL(fileURLWithPath: exe); p.arguments = args; p.environment = env
    p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice
    try! p.run(); p.waitUntilExit(); return p.terminationStatus
}

/// signs `file` with the throwaway fixture key through the real ssh-keygen, with a temporary HOME and no agent
func sign(_ file: URL, namespace: String = "leela-lock") -> URL {
    let d = tempDir(), key = d.appending(path: "k")
    try! FileManager.default.copyItem(at: fixtures.appending(path: "main.key"), to: key)
    try! FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: key.path)
    let sig = URL(fileURLWithPath: file.path + ".sig")
    try? FileManager.default.removeItem(at: sig)
    precondition(sh("/usr/bin/ssh-keygen", ["-Y", "sign", "-n", namespace, "-f", key.path, file.path], env: ["PATH": "/usr/bin:/bin", "HOME": d.path]) == 0)
    return sig
}

/// a signed lock folder: the three lock files, manifest.json, manifest.sig
@discardableResult
func makeLock(_ dir: URL, n: Int, uv: String = "0.13.6", body: String = "lock", api: Int = 1, platform: String = "darwin-arm64",
              macos: String = "14.0", tamper: ((inout Manifest) -> Void)? = nil) -> Manifest {
    let fm = FileManager.default
    try! fm.createDirectory(at: dir, withIntermediateDirectories: true)
    try! Data("[project]\nname = \"leela-lock\"\n".utf8).write(to: dir.appending(path: "pyproject.toml"))
    try! Data("version = 1\n# \(body) \(n)\n".utf8).write(to: dir.appending(path: "uv.lock"))
    try! Data("3.12.16\n".utf8).write(to: dir.appending(path: ".python-version"))
    var m = Manifest(n: n, hash: try! LockHash.hash(dir: dir, uv: uv), files: Dictionary(uniqueKeysWithValues: LockHash.files.map { ($0, sha256(try! Data(contentsOf: dir.appending(path: $0)))) }),
                     leela: "0.1.23", python: "3.12.16", uv_min: uv, launcher_api_min: api, platform: platform, macos_min: macos, download_bytes: 1000)
    tamper?(&m)
    let e = JSONEncoder(); e.outputFormatting = [.sortedKeys]
    try! e.encode(m).write(to: dir.appending(path: "manifest.json"))
    let sig = sign(dir.appending(path: "manifest.json"))
    try? fm.removeItem(at: dir.appending(path: "manifest.sig"))
    try! fm.moveItem(at: sig, to: dir.appending(path: "manifest.sig"))
    return m
}

/// a fake uv: `--version`, and `sync` that makes `$UV_PROJECT_ENVIRONMENT/bin/leela`; a FAIL file beside it makes sync fail half way
func fakeUV(_ dir: URL = tempDir()) -> URL {
    let u = dir.appending(path: "uv")
    let script = """
    #!/bin/sh
    d=$(dirname "$0")
    if [ "$1" = "--version" ]; then echo "uv 0.13.6"; exit 0; fi
    echo "$@" >> "$d/calls.txt"
    env | grep '^UV_' | sort > "$d/env.txt"
    mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
    echo "Downloading cpython-3.12.16-macos-aarch64-none (23.9MiB)"
    echo "Prepared 3 packages in 10ms"
    if [ -f "$d/FAIL" ]; then echo "error: Failed to fetch: no network" >&2; exit 2; fi
    printf '#!/bin/sh\\nexit 0\\n' > "$UV_PROJECT_ENVIRONMENT/bin/leela"; chmod +x "$UV_PROJECT_ENVIRONMENT/bin/leela"
    echo "Installed 3 packages in 5ms"
    """
    try! Data(script.utf8).write(to: u)
    try! FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: u.path)
    return u
}

func store(_ paths: Paths = tempPaths(), uv: URL = fakeUV()) -> EnvStore {
    EnvStore(paths: paths, spec: try! ChildEnv.load(childenvURL), uv: uv, uvVersion: "0.13.6",
             parent: ["PATH": "/usr/bin:/bin", "UV_INDEX_URL": "https://evil.example", "VIRTUAL_ENV": "/elsewhere"], home: NSTemporaryDirectory())
}

/// A small HTTP server on 127.0.0.1 for the tests: each path gives a status and bytes.
final class FakeHTTP: @unchecked Sendable {
    var routes: [String: (Int, Data)]
    private var listener: NWListener?
    private let q = DispatchQueue(label: "fake-http")
    private(set) var port = 0
    private(set) var hits: [String] = []

    init(_ routes: [String: (Int, Data)] = [:]) { self.routes = routes }

    func start() throws {
        let params = NWParameters.tcp
        params.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)
        let l = try NWListener(using: params)
        let ready = DispatchSemaphore(value: 0)
        l.stateUpdateHandler = { s in if case .ready = s { ready.signal() } }
        l.newConnectionHandler = { [weak self] c in self?.serve(c) }
        l.start(queue: q)
        listener = l
        _ = ready.wait(timeout: .now() + 5)
        port = Int(l.port!.rawValue)
    }

    var base: URL { URL(string: "http://127.0.0.1:\(port)")! }
    func stop() { listener?.cancel() }

    private func serve(_ c: NWConnection) {
        c.start(queue: q)
        c.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] d, _, _, _ in
            guard let self else { return c.cancel() }
            let head = d.map { String(decoding: $0, as: UTF8.self) } ?? ""
            let path = head.split(separator: " ").dropFirst().first.map(String.init) ?? "/"
            self.hits.append(path)
            let (code, body) = self.routes[path] ?? (404, Data("not found".utf8))
            let h = "HTTP/1.1 \(code) X\r\nContent-Length: \(body.count)\r\nConnection: close\r\n\r\n"
            c.send(content: Data(h.utf8) + body, completion: .contentProcessed { _ in c.cancel() })
        }
    }
}

/// publishes a lock folder at `lock-<n>/` and a pointer at `lock-channel/<name>.json`
func publish(_ http: FakeHTTP, lock dir: URL, n: Int, name: String = "channel", pointerName: String? = nil, extra: String = "") {
    for f in LockCheck.names { http.routes["/lock-\(n)/\(Channel.asset(f))"] = (200, try! Data(contentsOf: dir.appending(path: f))) }
    let p = ChannelPointer(n: n, manifest_sha256: sha256(try! Data(contentsOf: dir.appending(path: "manifest.json"))), published: "2026-11-06T00:00:00Z", channel: pointerName ?? name)
    let d = tempDir(), f = d.appending(path: "\(name).json")
    var raw = String(decoding: try! JSONEncoder().encode(p), as: UTF8.self)
    if !extra.isEmpty { raw = String(raw.dropLast()) + "," + extra + "}" }
    try! Data(raw.utf8).write(to: f)
    http.routes["/lock-channel/\(name).json"] = (200, try! Data(contentsOf: f))
    http.routes["/lock-channel/\(name).sig"] = (200, try! Data(contentsOf: sign(f)))
}
