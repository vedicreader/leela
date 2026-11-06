import Foundation
import Testing
@testable import LeelaCore

@Suite struct BridgeTests {
    @Test func eachPageCallMapsToOneAction() {
        #expect(Bridge.route(["method": "open_folder", "args": ["/a"]]) == .openFolder("/a"))
        #expect(Bridge.route(["method": "pick_folder", "args": []]) == .pickFolder)
        #expect(Bridge.route(["method": "recent"]) == .recent)
        #expect(Bridge.route(["method": "set_background", "args": ["#112233"]]) == .setBackground("#112233"))
        #expect(Bridge.route(["method": "set_title", "args": ["leela — x", "http://x.localhost:5010/"]]) == .setTitle("leela — x", url: "http://x.localhost:5010/"))
    }

    @Test func badCallsAreUnknown() {
        #expect(Bridge.route(["method": "set_background", "args": ["red"]]) == .unknown("set_background"))
        #expect(Bridge.route(["method": "open_folder", "args": [""]]) == .unknown("open_folder"))
        #expect(Bridge.route(["method": "eval"]) == .unknown("eval"))
        #expect(Bridge.route("junk") == .unknown("junk"))
    }

    @Test func theShimGivesThePageTheSameApiAndTheReadyEvent() {
        for m in Bridge.methods { #expect(Bridge.shim.contains("\"\(m)\"")) }
        #expect(Bridge.shim.contains("window.pywebview = {api}") && Bridge.shim.contains("pywebviewready") && Bridge.shim.contains("messageHandlers.leela"))
    }
}

@MainActor final class FakeHost: ControlHost {
    var asked = [String](), answer: Bool? = true, extras = [String](), kinds = [String](), restarts = 0
    func confirm(_ q: String) async -> Bool? { asked.append(q); return answer }
    func installExtra(_ name: String) async -> Bool { extras.append(name); return true }
    func startUpdate(kind: String) async -> UpdateState { kinds.append(kind); return UpdateState(state: "running", line: "x") }
    func updateState() -> UpdateState { UpdateState(state: "ready") }
    func restartServer() async -> Bool { restarts += 1; return true }
    func status() -> [String: Any] { ["app_version": "1.0.0", "brew": true] }
    let grants = GrantBook()
    func checkGrant(_ nonce: String, path: String) -> Bool { grants.check(nonce, path: path) }
}

func req(_ method: String, _ path: String, _ body: [String: Any]? = nil, token: String? = "tok") -> ControlRequest {
    ControlRequest(method: method, path: path, headers: token.map { ["authorization": "Bearer \($0)"] } ?? [:],
                   body: body.map { try! JSONSerialization.data(withJSONObject: $0) } ?? Data())
}

@MainActor @Suite struct ControlTests {
    @Test func everyRouteNeedsTheToken() async {
        let h = FakeHost()
        for r in [req("GET", "/status", token: nil), req("GET", "/status", token: "wrong"), req("GET", "/status", token: ""), req("POST", "/confirm", ["question": "q"], token: "to")] {
            #expect(await ControlRouter.handle(r, token: "tok", host: h).0 == 401)
        }
        #expect(await ControlRouter.handle(req("GET", "/status", token: ""), token: "", host: h).0 == 401, "an empty token matches nothing")
        #expect(h.asked.isEmpty)
    }

    @Test func theRoutesReachTheHost() async {
        let h = FakeHost()
        var (c, d) = await ControlRouter.handle(req("POST", "/confirm", ["question": "Add x?"]), token: "tok", host: h)
        #expect(c == 200 && d["answer"] as? Bool == true && h.asked == ["Add x?"])
        h.answer = nil
        (c, d) = await ControlRouter.handle(req("POST", "/confirm", ["question": "Add y?"]), token: "tok", host: h)
        #expect(c == 200 && d["answer"] == nil && d["no_window"] as? Bool == true, "no window is not a No")
        #expect(await ControlRouter.handle(req("POST", "/extras", ["name": "mlx"]), token: "tok", host: h).0 == 200 && h.extras == ["mlx"])
        #expect(await ControlRouter.handle(req("POST", "/extras", ["name": "torch"]), token: "tok", host: h).0 == 400)
        (c, d) = await ControlRouter.handle(req("POST", "/update", ["kind": "lock"]), token: "tok", host: h)
        #expect(d["state"] as? String == "running" && h.kinds == ["lock"])
        #expect(await ControlRouter.handle(req("POST", "/update", ["kind": "rm"]), token: "tok", host: h).0 == 400)
        #expect(await ControlRouter.handle(req("GET", "/update"), token: "tok", host: h).1["state"] as? String == "ready")
        #expect(await ControlRouter.handle(req("POST", "/restart", [:]), token: "tok", host: h).1["ok"] as? Bool == true && h.restarts == 1)
        #expect(await ControlRouter.handle(req("GET", "/status"), token: "tok", host: h).1["brew"] as? Bool == true)
        #expect(await ControlRouter.handle(req("GET", "/nope"), token: "tok", host: h).0 == 404)
        let n = h.grants.issue("/a")
        #expect(await ControlRouter.handle(req("POST", "/grant", ["nonce": n, "path": "/b"]), token: "tok", host: h).1["ok"] as? Bool == false, "another path")
        let m = h.grants.issue("/a")
        #expect(await ControlRouter.handle(req("POST", "/grant", ["nonce": m, "path": "/a"]), token: "tok", host: h).1["ok"] as? Bool == true)
        #expect(await ControlRouter.handle(req("POST", "/grant", ["nonce": m, "path": "/a"]), token: "tok", host: h).1["ok"] as? Bool == false, "once")
    }

    @Test func theServerAnswersOverHTTPOnLoopbackWithTheToken() async throws {
        let h = FakeHost()
        let srv = ControlServer(token: "tok") { r in await ControlRouter.handle(r, token: "tok", host: h) }
        try srv.start(); defer { srv.stop() }
        #expect(srv.url.hasPrefix("http://127.0.0.1:") && srv.port > 0)
        func call(_ token: String?) async throws -> (Int, [String: Any]) {
            var r = URLRequest(url: URL(string: "\(srv.url)/confirm")!)
            r.httpMethod = "POST"; r.httpBody = try JSONSerialization.data(withJSONObject: ["question": "Add z?"])
            if let token { r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
            let (d, resp) = try await URLSession(configuration: .ephemeral).data(for: r)
            return ((resp as! HTTPURLResponse).statusCode, try JSONSerialization.jsonObject(with: d) as! [String: Any])
        }
        #expect(try await call(nil).0 == 401)
        let (c, d) = try await call("tok")
        #expect(c == 200 && d["answer"] as? Bool == true && h.asked == ["Add z?"])
    }

    @Test func aRequestInPiecesIsReadWhole() {
        let raw = Data("POST /extras?x=1 HTTP/1.1\r\nAuthorization: Bearer t\r\nContent-Length: 15\r\n\r\n{\"name\":\"mlx\"}".utf8)
        #expect(ControlServer.parse(raw) == nil, "the body is one byte short")
        let r = ControlServer.parse(raw + Data(" ".utf8))
        #expect(r?.path == "/extras" && r?.headers["authorization"] == "Bearer t" && r?.body.count == 15)
        #expect(ControlServer.parse(Data("GET / HTTP/1.1\r\nContent-Length: -1\r\n\r\n".utf8))?.body.isEmpty == true, "a negative length does not crash")
    }

    @Test func tokensCompareWhole() {
        #expect(ControlRouter.tokenOK(["authorization": "Bearer abc"], token: "abc"))
        #expect(!ControlRouter.tokenOK(["authorization": "Bearer abcd"], token: "abc") && !ControlRouter.tokenOK(["authorization": "abc"], token: "abc"))
        #expect(ControlServer.newToken().count == 64 && ControlServer.newToken() != ControlServer.newToken())
    }
}

@Suite struct BrewTests {
    @Test func onlyTheCasksLeelaAppUpgradesThroughBrew() throws {
        let d = tempDir(), brew = d.appending(path: "bin/brew")
        try FileManager.default.createDirectory(at: brew.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("#!/bin/sh\necho upgraded\n".utf8).write(to: brew)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: brew.path)
        #expect(BrewUpgrade.find(app: URL(fileURLWithPath: "/Applications/Leela.app"), places: [brew.path]) == nil, "no Caskroom/leela")
        try FileManager.default.createDirectory(at: d.appending(path: "Caskroom/leela"), withIntermediateDirectories: true)
        #expect(BrewUpgrade.find(app: URL(fileURLWithPath: "/Applications/Leela.app"), places: [brew.path]) == brew)
        #expect(BrewUpgrade.find(app: URL(fileURLWithPath: "/tmp/Other.app"), places: [brew.path]) == nil)
        #expect(BrewUpgrade(app: URL(fileURLWithPath: "/tmp/Other.app"), places: [brew.path]).start(log: d.appending(path: "log")).state == "unavailable")
    }

    @Test func anUpgradeThatChangesNothingIsSame() async throws {
        let d = tempDir(), brew = d.appending(path: "brew"), app = d.appending(path: "Leela.app")
        try FileManager.default.createDirectory(at: app.appending(path: "Contents"), withIntermediateDirectories: true)
        try Data("<?xml version=\"1.0\"?><plist version=\"1.0\"><dict><key>CFBundleShortVersionString</key><string>1.0.0</string></dict></plist>".utf8).write(to: app.appending(path: "Contents/Info.plist"))
        try Data("#!/bin/sh\necho \"Warning: leela is up to date\"\n".utf8).write(to: brew)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: brew.path)
        let b = BrewUpgrade(app: app, brew: brew)
        #expect(b.start(log: d.appending(path: "log")).state == "running")
        let end = Date().addingTimeInterval(10)
        while b.state.state == "running" && Date() < end { try await Task.sleep(for: .milliseconds(50)) }
        #expect(b.state.state == "same")
    }
}
