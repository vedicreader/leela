import CryptoKit
import Foundation

public func hex(_ d: some Sequence<UInt8>) -> String { d.map { String(format: "%02x", $0) }.joined() }
public func sha256(_ d: Data) -> String { hex(SHA256.hash(data: d)) }

/// The lock hash: sha256 over the name and bytes of each lock file, then "uv" and the uv version. tools/lock.py computes the same.
public enum LockHash {
    public static let files = ["pyproject.toml", "uv.lock", ".python-version"]

    public static func hash(dir: URL, uv: String) throws -> String {
        var h = SHA256()
        for name in files {
            h.update(data: Data(name.utf8))
            h.update(data: try Data(contentsOf: dir.appending(path: name)))
        }
        h.update(data: Data("uv".utf8))
        h.update(data: Data(uv.utf8))
        return hex(h.finalize())
    }
}

public enum SSHSigError: Error, Equatable { case armor, format, unknownKey, namespace, hashAlgorithm, badSignature }

/// One public key from an OpenSSH `ssh-ed25519 AAAA... comment` line.
public struct SSHKey: Equatable, Sendable {
    public let raw: Data
    public let comment: String

    public static func parse(line: String) -> SSHKey? {
        let parts = line.split(separator: " ", omittingEmptySubsequences: true)
        guard parts.count >= 2, parts[0] == "ssh-ed25519", let blob = Data(base64Encoded: String(parts[1])) else { return nil }
        var r = Reader(blob)
        guard let kind = r.string(), String(decoding: kind, as: UTF8.self) == "ssh-ed25519", let key = r.string(), key.count == 32 else { return nil }
        return SSHKey(raw: key, comment: parts.dropFirst(2).joined(separator: " "))
    }

    /// every ssh-ed25519 key in a keys.pub file
    public static func load(_ url: URL) throws -> [SSHKey] {
        try String(contentsOf: url, encoding: .utf8).split(whereSeparator: \.isNewline).compactMap { parse(line: String($0)) }
    }
}

/// SSH wire format: big-endian u32 lengths before each string.
struct Reader {
    var d: Data
    init(_ d: Data) { self.d = Data(d) }
    mutating func bytes(_ n: Int) -> Data? {
        guard d.count >= n else { return nil }
        let out = d.prefix(n)
        d = d.dropFirst(n)
        return Data(out)
    }
    mutating func u32() -> UInt32? { bytes(4).map { $0.reduce(0) { $0 << 8 | UInt32($1) } } }
    mutating func string() -> Data? { u32().flatMap { bytes(Int($0)) } }
}

func sshString(_ d: Data) -> Data {
    var n = UInt32(d.count).bigEndian
    return Data(bytes: &n, count: 4) + d
}

/// SSHSIG (`ssh-keygen -Y sign`) checked with CryptoKit: the key must be one of `keys`, the namespace `namespace`, the hash sha512
/// or sha256, and the Ed25519 signature must hold over the signed-data blob.
public enum SSHSig {
    public static let namespace = "leela-lock"

    public static func blob(armored: String) throws -> Data {
        let lines = armored.split(whereSeparator: \.isNewline).map { $0.trimmingCharacters(in: .whitespaces) }
        guard let a = lines.firstIndex(of: "-----BEGIN SSH SIGNATURE-----"), let b = lines.firstIndex(of: "-----END SSH SIGNATURE-----"), a < b,
              let d = Data(base64Encoded: lines[(a + 1)..<b].joined()) else { throw SSHSigError.armor }
        return d
    }

    /// the key that signed, when the signature is good
    @discardableResult
    public static func verify(message: Data, signature armored: String, keys: [SSHKey], namespace: String = namespace) throws -> SSHKey {
        var r = Reader(try blob(armored: armored))
        guard r.bytes(6) == Data("SSHSIG".utf8), r.u32() == 1, let pub = r.string(), let ns = r.string(), let reserved = r.string(),
              let algo = r.string(), let sig = r.string(), r.d.isEmpty else { throw SSHSigError.format }
        var pk = Reader(pub)
        guard pk.string() == Data("ssh-ed25519".utf8), let raw = pk.string(), raw.count == 32, pk.d.isEmpty else { throw SSHSigError.format }
        guard let key = keys.first(where: { $0.raw == raw }) else { throw SSHSigError.unknownKey }
        guard String(decoding: ns, as: UTF8.self) == namespace else { throw SSHSigError.namespace }
        let digest: Data
        switch String(decoding: algo, as: UTF8.self) {
        case "sha512": digest = Data(SHA512.hash(data: message))
        case "sha256": digest = Data(SHA256.hash(data: message))
        default: throw SSHSigError.hashAlgorithm
        }
        var s = Reader(sig)
        guard s.string() == Data("ssh-ed25519".utf8), let raw64 = s.string(), raw64.count == 64, s.d.isEmpty else { throw SSHSigError.format }
        let signed = Data("SSHSIG".utf8) + sshString(ns) + sshString(reserved) + sshString(algo) + sshString(digest)
        guard let k = try? Curve25519.Signing.PublicKey(rawRepresentation: raw), k.isValidSignature(raw64, for: signed) else { throw SSHSigError.badSignature }
        return key
    }
}

/// What a new lock changes against the one in use, from the two `uv.lock` files: what the setup window and the update notice say.
public enum LockDiff {
    /// `name -> version` of each `[[package]]` in a uv.lock
    public static func versions(_ lock: URL) -> [String: String] {
        guard let t = try? String(contentsOf: lock.appending(path: "uv.lock"), encoding: .utf8) else { return [:] }
        var out = [String: String](), name: String?
        for l in t.split(separator: "\n", omittingEmptySubsequences: false) {
            if l == "[[package]]" { name = nil; continue }
            if l.hasPrefix("name = "), name == nil { name = String(l.dropFirst(7)).trimmingCharacters(in: CharacterSet(charactersIn: "\"")) }
            else if l.hasPrefix("version = "), let n = name, out[n] == nil { out[n] = String(l.dropFirst(10)).trimmingCharacters(in: CharacterSet(charactersIn: "\"")) }
        }
        return out.filter { $0.key != "leela-lock" }
    }

    /// each changed package as `name old → new`, `name new` (added) or `name old, removed`, sorted by name
    public static func changes(from a: URL, to b: URL) -> [String] {
        let x = versions(a), y = versions(b)
        return Set(x.keys).union(y.keys).sorted().compactMap { n in
            switch (x[n], y[n]) {
            case let (o?, v?) where o != v: "\(n) \(o) → \(v)"
            case (nil, let v?): "\(n) \(v) (new)"
            case (let o?, nil): "\(n) \(o) (removed)"
            default: nil
            }
        }
    }

    /// "Updating 1 package: ramabana 0.2.109 → 0.2.110", a few by name, then "and N more"; "" for none
    public static func summary(_ c: [String], shown: Int = 3) -> String {
        guard !c.isEmpty else { return "" }
        let head = c.prefix(shown).joined(separator: ", "), more = c.count > shown ? " and \(c.count - shown) more" : ""
        return "Updating \(c.count) package\(c.count == 1 ? "" : "s"): \(head)\(more)"
    }
}
