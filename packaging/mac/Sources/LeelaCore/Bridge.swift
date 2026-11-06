import Foundation
import Network

/// One call the page makes on `window.pywebview.api`.
public enum BridgeAction: Equatable, Sendable {
    case openFolder(String)
    case pickFolder
    case recent
    case setBackground(String)
    case setTitle(String, url: String?)
    case unknown(String)
}

/// The page's native bridge: the same `window.pywebview.api` the pywebview app gave it, so the page JavaScript does not change.
public enum Bridge {
    public static let handler = "leela"
    public static let methods = ["open_folder", "pick_folder", "recent", "set_background", "set_title"]

    /// the message `{method, args}` the shim posts, as an action
    public static func route(_ body: Any) -> BridgeAction {
        guard let d = body as? [String: Any], let m = d["method"] as? String else { return .unknown("\(body)") }
        let a = d["args"] as? [Any] ?? []
        let s = { (i: Int) in i < a.count ? a[i] as? String : nil }
        switch m {
        case "open_folder": return s(0).map { $0.isEmpty ? .unknown(m) : .openFolder($0) } ?? .unknown(m)
        case "pick_folder": return .pickFolder
        case "recent": return .recent
        case "set_background": return s(0).flatMap { isColour($0) ? .setBackground($0) : nil } ?? .unknown(m)
        case "set_title": return s(0).map { .setTitle($0, url: s(1)) } ?? .unknown(m)
        default: return .unknown(m)
        }
    }

    public static func isColour(_ s: String) -> Bool { s.range(of: "^#[0-9a-fA-F]{6}$", options: .regularExpression) != nil }

    /// injected at document start in every page of the server
    public static let shim = """
    (() => {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.__leela) return;
      const call = (method, args) => window.webkit.messageHandlers.\(handler).postMessage({method, args});
      const api = {__leela: true};
      for (const m of \(methods.description)) api[m] = (...args) => call(m, args);
      window.pywebview = {api};
      const ready = () => window.dispatchEvent(new Event('pywebviewready'));
      if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready); else ready();
    })();
    """
}

/// What the launcher does for a control route; the app delegate implements it.
@MainActor public protocol ControlHost: AnyObject {
    /// nil when no window can ask
    func confirm(_ question: String) async -> Bool?
    func installExtra(_ name: String) async -> Bool
    func startUpdate(kind: String) async -> UpdateState
    func updateState() -> UpdateState
    func restartServer() async -> Bool
    func status() -> [String: Any]
}

public struct ControlRequest: Sendable {
    public var method: String
    public var path: String
    public var headers: [String: String]
    public var body: Data
    public init(method: String, path: String, headers: [String: String], body: Data) {
        self.method = method; self.path = path; self.headers = headers; self.body = body
    }
}

/// The routes of the launcher's control server, without the socket. See docs/thin-app.md.
public enum ControlRouter {
    public static func tokenOK(_ headers: [String: String], token: String) -> Bool {
        guard !token.isEmpty, let a = headers["authorization"], a.hasPrefix("Bearer ") else { return false }
        let given = Array(a.dropFirst(7).utf8), want = Array(token.utf8)
        guard given.count == want.count else { return false }
        return zip(given, want).reduce(0) { $0 | ($1.0 ^ $1.1) } == 0
    }

    @MainActor public static func handle(_ r: ControlRequest, token: String, host: ControlHost) async -> (Int, [String: Any]) {
        guard tokenOK(r.headers, token: token) else { return (401, ["ok": false, "error": "bad token"]) }
        let body = (try? JSONSerialization.jsonObject(with: r.body)) as? [String: Any] ?? [:]
        switch (r.method, r.path) {
        case ("POST", "/confirm"):
            guard let q = body["question"] as? String else { return (400, ["ok": false, "error": "no question"]) }
            guard let yes = await host.confirm(q) else { return (200, ["ok": false, "no_window": true]) }
            return (200, ["answer": yes])
        case ("POST", "/extras"):
            guard let n = body["name"] as? String, EnvStore.extraNames.contains(n) else { return (400, ["ok": false, "error": "unknown extra"]) }
            return (200, ["ok": await host.installExtra(n)])
        case ("POST", "/update"):
            guard let k = body["kind"] as? String, ["app", "lock"].contains(k) else { return (400, ["ok": false, "error": "kind is app or lock"]) }
            let u = await host.startUpdate(kind: k)
            return (200, ["state": u.state, "line": u.line])
        case ("GET", "/update"):
            let u = host.updateState()
            return (200, ["state": u.state, "line": u.line])
        case ("POST", "/restart"): return (200, ["ok": await host.restartServer()])
        case ("GET", "/status"): return (200, host.status())
        default: return (404, ["ok": false, "error": "no route \(r.method) \(r.path)"])
        }
    }
}

/// A small HTTP/1.1 server on 127.0.0.1 for the control routes: one request per connection.
public final class ControlServer: @unchecked Sendable {
    public let token: String
    public private(set) var port = 0
    private var listener: NWListener?
    private let q = DispatchQueue(label: "leela-control")
    private let handle: @Sendable (ControlRequest) async -> (Int, [String: Any])

    public init(token: String = ControlServer.newToken(), handle: @escaping @Sendable (ControlRequest) async -> (Int, [String: Any])) {
        self.token = token; self.handle = handle
    }

    public static func newToken() -> String {
        var b = [UInt8](repeating: 0, count: 32)
        _ = SecRandomCopyBytes(kSecRandomDefault, b.count, &b)
        return hex(b)
    }

    public var url: String { "http://127.0.0.1:\(port)" }

    public func start() throws {
        let params = NWParameters.tcp
        params.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)
        let l = try NWListener(using: params)
        let ready = DispatchSemaphore(value: 0)
        l.stateUpdateHandler = { s in if case .ready = s { ready.signal() } }
        l.newConnectionHandler = { [weak self] c in self?.serve(c) }
        l.start(queue: q)
        listener = l
        _ = ready.wait(timeout: .now() + 5)
        port = Int(l.port?.rawValue ?? 0)
    }

    public func stop() { listener?.cancel() }

    private func serve(_ c: NWConnection) {
        c.start(queue: q)
        read(c, Data())
    }

    private func read(_ c: NWConnection, _ have: Data) {
        c.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] d, _, done, err in
            guard let self else { return c.cancel() }
            let buf = have + (d ?? Data())
            if let req = Self.parse(buf) { return self.answer(c, req) }
            if done || err != nil || buf.count > 1 << 20 { return c.cancel() }
            self.read(c, buf)
        }
    }

    /// a whole request, or nil while bytes are still to come
    static func parse(_ d: Data) -> ControlRequest? {
        guard let end = d.firstRange(of: Data("\r\n\r\n".utf8)) else { return nil }
        let head = String(decoding: d[..<end.lowerBound], as: UTF8.self).components(separatedBy: "\r\n")
        let first = head.first?.split(separator: " ") ?? []
        guard first.count >= 2 else { return nil }
        var h = [String: String]()
        for l in head.dropFirst() { if let i = l.firstIndex(of: ":") { h[l[..<i].lowercased()] = l[l.index(after: i)...].trimmingCharacters(in: .whitespaces) } }
        let n = max(0, Int(h["content-length"] ?? "0") ?? 0), body = d[end.upperBound...]
        guard body.count >= n else { return nil }
        return ControlRequest(method: String(first[0]), path: String(first[1]).components(separatedBy: "?")[0], headers: h, body: Data(body.prefix(n)))
    }

    private func answer(_ c: NWConnection, _ req: ControlRequest) {
        let handle = self.handle
        Task {
            let (code, obj) = await handle(req)
            let body = (try? JSONSerialization.data(withJSONObject: obj)) ?? Data("{}".utf8)
            let head = "HTTP/1.1 \(code) \(code == 200 ? "OK" : "Error")\r\nContent-Type: application/json\r\nContent-Length: \(body.count)\r\nConnection: close\r\n\r\n"
            c.send(content: Data(head.utf8) + body, completion: .contentProcessed { _ in c.cancel() })
        }
    }
}
