import Foundation

/// packaging/childenv.json: the child environment that the launcher and tools/lock.py both build from one file.
public struct ChildEnv: Codable, Sendable, Equatable {
    public var api: Int
    public var drop: [String]
    public var drop_prefixes: [String]
    public var set: [String: String]
    public var uv: [String: String]
    public var server: [String: String]
    public var path_first: [String]
    public var tool_dirs: [String]
    public var sync: [String]
    public var extra: [String]
    public var inexact: [String]
    public var server_args: [String]

    public static func load(_ url: URL) throws -> ChildEnv { try JSONDecoder().decode(ChildEnv.self, from: Data(contentsOf: url)) }

    /// `{key}` replaced by `vals[key]`
    public static func fill(_ s: String, _ vals: [String: String]) -> String {
        vals.reduce(s) { $0.replacingOccurrences(of: "{\($1.key)}", with: $1.value) }
    }

    public static func expand(_ p: String, home: String) -> String { p == "~" ? home : p.hasPrefix("~/") ? home + p.dropFirst(1) : p }

    /// the parent environment without the dropped names, with `set`, HOME, and a PATH of `first`, the tool folders, then the parent's
    func base(_ parent: [String: String], home: String, first: [String]) -> [String: String] {
        var e = parent.filter { k, _ in !drop.contains(k) && !drop_prefixes.contains { k.hasPrefix($0) } }
        for (k, v) in set where e[k] == nil { e[k] = v }
        e["HOME"] = home
        var seen = Set<String>(), out = [String]()
        for d in first + tool_dirs.map({ Self.expand($0, home: home) }) + (parent["PATH"] ?? "").split(separator: ":").map(String.init)
        where !d.isEmpty && seen.insert(d).inserted { out.append(d) }
        e["PATH"] = out.joined(separator: ":")
        return e
    }

    /// what uv gets: `vals` holds cache, python, python_version and env
    public func uvEnv(_ parent: [String: String], home: String, vals: [String: String]) -> [String: String] {
        var e = base(parent, home: home, first: [])
        for (k, v) in uv { e[k] = Self.fill(v, vals) }
        return e
    }

    /// what the server gets: the uv environment, the server keys, the env's bin first on PATH, and the launcher's own `extra`
    public func serverEnv(_ parent: [String: String], home: String, vals: [String: String], extra: [String: String] = [:]) -> [String: String] {
        var e = base(parent, home: home, first: path_first.map { Self.fill($0, vals) })
        for (k, v) in uv { e[k] = Self.fill(v, vals) }
        for (k, v) in server { e[k] = Self.fill(v, vals) }
        for (k, v) in extra { e[k] = v }
        return e
    }

    public func syncArgs(lock: URL, extras: [String] = [], inexact: Bool = false) -> [String] {
        sync.map { Self.fill($0, ["lock": lock.path]) } + (inexact ? self.inexact : []) + extras.flatMap { x in extra.map { Self.fill($0, ["name": x]) } }
    }

    public func serverArgs(port: Int) -> [String] { server_args.map { Self.fill($0, ["port": String(port)]) } }
}
