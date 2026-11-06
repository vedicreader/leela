import Foundation

/// manifest.json of one lock. See docs/thin-app.md.
public struct Manifest: Codable, Equatable, Sendable {
    public var n: Int
    public var hash: String
    public var files: [String: String]
    public var leela: String?
    public var python: String
    public var uv_min: String
    public var launcher_api_min: Int
    public var platform: String
    public var macos_min: String
    public var download_bytes: Int64
}

/// channel.json and channel-test.json: which lock is current.
public struct ChannelPointer: Codable, Equatable, Sendable {
    public var n: Int
    public var manifest_sha256: String
    public var published: String
    public var expires: String?
    /// `channel` or `channel-test`: a pointer served under the other name is refused
    public var channel: String?
}

public enum LockRefusal: Error, Equatable, Sendable {
    case missing(String)
    case signature(String)
    case fileHash(String)
    case lockHash
    case replay(n: Int, highest: Int)
    case platform(String)
    case macOS(String)
    case bad(String)
    case pointer(String)

    public var text: String {
        switch self {
        case .missing(let f): "The lock has no \(f)."
        case .signature(let why): "The lock signature is not good (\(why))."
        case .fileHash(let f): "\(f) does not match the signed manifest."
        case .lockHash: "The lock hash does not match the signed manifest."
        case .replay(let n, let h): "Lock \(n) is not newer than lock \(h)."
        case .platform(let p): "The lock is for \(p), not this Mac."
        case .macOS(let v): "The lock needs macOS \(v) or later."
        case .bad(let h): "Lock \(h.prefix(16)) failed on this Mac before."
        case .pointer(let why): "The channel pointer is refused (\(why))."
        }
    }
}

/// What the app may do with a checked lock.
public enum LockVerdict: Equatable, Sendable {
    case ok(Manifest)
    /// good, but this app is too old for it: its uv or launcher API is lower than the lock asks
    case needsApp(Manifest)
}

/// The launcher's own facts that a lock is checked against.
public struct AppFacts: Sendable {
    public var uv: String
    public var api: Int
    public var macOS: OperatingSystemVersion
    public var platform: String

    public init(uv: String, api: Int = LauncherAPI.version, macOS: OperatingSystemVersion = ProcessInfo.processInfo.operatingSystemVersion,
                platform: String = "darwin-arm64") {
        self.uv = uv; self.api = api; self.macOS = macOS; self.platform = platform
    }
}

public enum LauncherAPI { public static let version = 1 }

func versionParts(_ s: String) -> [Int] { s.split(separator: ".").map { Int($0) ?? 0 } }
/// `a < b` by numeric parts
public func versionLess(_ a: String, _ b: String) -> Bool {
    let x = versionParts(a), y = versionParts(b)
    for i in 0..<max(x.count, y.count) {
        let p = i < x.count ? x[i] : 0, q = i < y.count ? y[i] : 0
        if p != q { return p < q }
    }
    return false
}

/// Checks a lock folder as the app must before it builds from it.
public enum LockCheck {
    public static let names = ["manifest.json", "manifest.sig"] + LockHash.files

    public static func check(dir: URL, keys: [SSHKey], app: AppFacts, highest: Int = -1, bad: [String] = []) throws -> LockVerdict {
        let fm = FileManager.default
        for f in names where !fm.fileExists(atPath: dir.appending(path: f).path) { throw LockRefusal.missing(f) }
        let raw = try Data(contentsOf: dir.appending(path: "manifest.json"))
        do { try SSHSig.verify(message: raw, signature: String(decoding: try Data(contentsOf: dir.appending(path: "manifest.sig")), as: UTF8.self), keys: keys) }
        catch { throw LockRefusal.signature("\(error)") }
        let m = try JSONDecoder().decode(Manifest.self, from: raw)
        for f in LockHash.files where m.files[f] != sha256(try Data(contentsOf: dir.appending(path: f))) { throw LockRefusal.fileHash(f) }
        guard try LockHash.hash(dir: dir, uv: m.uv_min) == m.hash else { throw LockRefusal.lockHash }
        guard m.n > highest else { throw LockRefusal.replay(n: m.n, highest: highest) }
        guard m.platform == app.platform else { throw LockRefusal.platform(m.platform) }
        let os = "\(app.macOS.majorVersion).\(app.macOS.minorVersion).\(app.macOS.patchVersion)"
        guard !versionLess(os, m.macos_min) else { throw LockRefusal.macOS(m.macos_min) }
        guard !bad.contains(m.hash) else { throw LockRefusal.bad(m.hash) }
        return versionLess(app.uv, m.uv_min) || app.api < m.launcher_api_min ? .needsApp(m) : .ok(m)
    }

    /// a channel pointer, checked against its signature, its channel name and its expiry
    public static func pointer(_ data: Data, signature: Data, keys: [SSHKey], name: String, now: Date = Date()) throws -> ChannelPointer {
        do { try SSHSig.verify(message: data, signature: String(decoding: signature, as: UTF8.self), keys: keys) }
        catch { throw LockRefusal.signature("\(error)") }
        let p = try JSONDecoder().decode(ChannelPointer.self, from: data)
        guard p.channel == name else { throw LockRefusal.pointer("it is for \(p.channel ?? "no channel"), not \(name)") }
        if let e = p.expires.flatMap({ ISO8601DateFormatter().date(from: $0) }), e < now { throw LockRefusal.pointer("it expired at \(p.expires!)") }
        return p
    }
}
