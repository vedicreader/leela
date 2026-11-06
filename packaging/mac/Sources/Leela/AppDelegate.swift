import AppKit
import LeelaCore
import Network

/// The launcher: one supervisor, the control server, the windows, the menus, open events, updates.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, ControlHost {
    let bundle = Bundle.main
    let paths = Paths.user
    var store: EnvStore!
    var sup: Supervisor!
    var control: ControlServer!
    var brew: BrewUpgrade!
    let windows = Windows()
    let setup = SetupWindow()
    var runLock: RunLock?
    var queued: [URL] = []
    var recent: [String] = []
    var appVersion: String { bundle.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0" }
    let net = NWPathMonitor()
    var timer: Timer?

    var res: URL { bundle.resourceURL! }

    func applicationDidFinishLaunching(_ n: Notification) {
        guard let lock = RunLock(paths.runLock) else {
            let a = NSAlert(); a.messageText = "Leela is already open."; a.runModal()
            return NSApp.terminate(nil)
        }
        runLock = lock
        let uv = bundle.bundleURL.appending(path: "Contents/Helpers/uv")
        guard let spec = try? ChildEnv.load(res.appending(path: "childenv.json")), let keys = try? SSHKey.load(res.appending(path: "lock-keys.pub")),
              let uvLine = Run.output(uv, ["--version"]), let uvVersion = uvLine.split(separator: " ").dropFirst().first.map(String.init) else {
            return setup.show(.failed("This copy of Leela is damaged. Install it again.\n\nThe bundled uv, childenv.json or lock-keys.pub is missing."))
        }
        let parent = ProcessInfo.processInfo.environment, home = NSHomeDirectory()
        store = EnvStore(paths: paths, spec: spec, uv: uv, uvVersion: uvVersion, parent: parent, home: home)
        brew = BrewUpgrade(app: bundle.bundleURL)
        windows.app = self
        let app = AppFacts(uv: uvVersion)
        let channel = Channel(test: Channel.isTest(parent), keys: keys, app: app)
        let bundled = res.appending(path: "Lock"), store = store!
        control = ControlServer { [weak self] r in
            guard let self else { return (503, [:]) }
            return await ControlRouter.handle(r, token: self.control.token, host: self)
        }
        try? control.start()
        let token = control.token, url = control.url, bundlePath = bundle.bundleURL.path, version = appVersion
        sup = Supervisor(store: store, plan: { await LockChoice.choose(bundled: bundled, channel: channel, keys: keys, app: app, store: store) },
                         serverLaunch: { port, h in
            let s = store.load(), env = store.paths.env(h)
            let vals = store.vals(env: env, python: (try? String(contentsOf: store.paths.lock(s.locks[h] ?? 0).appending(path: ".python-version"), encoding: .utf8))?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? "3.12")
            let extra = ["LEELA_HOST_URL": url, "LEELA_HOST_TOKEN": token, "LEELA_APP_VERSION": version, "LEELA_APP_BUNDLE": bundlePath,
                         "LEELA_LOCK_N": String(s.locks[h] ?? 0), "LEELA_ENV_HASH": h, "LEELA_UV": uv.path]
            return Launch(executable: store.paths.server(h), args: spec.serverArgs(port: port),
                          env: spec.serverEnv(parent, home: home, vals: vals, extra: extra), cwd: store.paths.support)
        })
        setup.logURL = paths.serverLog
        setup.onRetry = { [weak self] in self?.begin() }
        sup.onPhase = { [weak self] p in self?.phase(p) }
        sup.onReady = { [weak self] base in self?.ready(base) }
        net.pathUpdateHandler = { [weak self] p in
            guard p.status == .satisfied else { return }
            Task { @MainActor in if self?.sup.phase == .offline { self?.begin() } }
        }
        net.start(queue: .main)
        timer = Timer.scheduledTimer(withTimeInterval: 6 * 3600, repeats: true) { [weak self] _ in Task { @MainActor in await self?.sup.checkForUpdates() } }
        begin()
    }

    func begin() { Task { await sup.start() } }

    func phase(_ p: Phase) {
        if case .ready = p { setup.window.orderOut(nil); return }
        if case .setup(.starting) = p, !windows.windows.isEmpty { return }
        setup.show(p)
    }

    func ready(_ base: URL) {
        windows.port = sup.port
        Task {
            if let m = await get("/app/menu.json")?["menus"] as? [[String: Any]] { NSApp.mainMenu = Menus.build(m, target: self) }
            recent = await get("/app/recent")?["recent"] as? [String] ?? []
        }
        if windows.windows.isEmpty {
            let q = queued; queued = []
            if q.isEmpty { windows.show(base) } else { open(q) }
        } else { windows.reloadAll(port: sup.port) }
        if store.pruneDue() { Task.detached { [store] in _ = try? await Run.toEnd(store!.pruneLaunch(), log: store!.paths.logs.appending(path: "prune.log")); _ = try? store!.update { $0.pruned = Date().timeIntervalSince1970 } } }
        _ = try? store.gc(inUse: Set([sup.hash].compactMap { $0 }))
    }

    // calls to the server with the token
    func request(_ path: String, method: String = "GET", query: [String: String] = [:], timeout: Double = 600) async -> (Int, [String: Any]) {
        var c = URLComponents(string: "http://127.0.0.1:\(sup.port)\(path)")!
        if !query.isEmpty { c.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) } }
        var r = URLRequest(url: c.url!, timeoutInterval: timeout)
        r.httpMethod = method
        r.setValue(control.token, forHTTPHeaderField: "X-Leela-Host-Token")
        if method == "POST" { r.httpBody = Data() }
        let cfg = URLSessionConfiguration.ephemeral
        cfg.connectionProxyDictionary = [:]
        guard let (d, resp) = try? await URLSession(configuration: cfg).data(for: r) else { return (0, [:]) }
        return ((resp as? HTTPURLResponse)?.statusCode ?? 0, (try? JSONSerialization.jsonObject(with: d)) as? [String: Any] ?? [:])
    }

    func get(_ path: String) async -> [String: Any]? { let (c, d) = await request(path, timeout: 10); return c == 200 ? d : nil }

    // open events: Finder, the Dock, `open -a Leela`
    func application(_ a: NSApplication, open urls: [URL]) {
        guard case .ready = sup?.phase else { queued += urls; return }
        open(urls)
    }

    func open(_ urls: [URL]) {
        for u in urls {
            var dir: ObjCBool = false
            guard FileManager.default.fileExists(atPath: u.path, isDirectory: &dir) else { continue }
            if dir.boolValue { openFolder(u.path, trusted: true) }
            else { openFile(u.path) }
        }
    }

    func openFolder(_ path: String, trusted: Bool) {
        Task {
            let (code, d) = trusted ? await request("/hub/open", method: "POST", query: ["path": path]) : await untrusted(["path": path])
            guard code == 200, d["ok"] as? Bool == true, let s = d["url"] as? String, let u = URL(string: s) else {
                return tell("Leela could not open \(path): \(d["error"] as? String ?? "no answer")")
            }
            windows.show(u, title: "leela — \(d["name"] as? String ?? "")")
        }
    }

    /// a folder the page asked for: no token, so the server asks the person through /confirm
    func untrusted(_ q: [String: String]) async -> (Int, [String: Any]) {
        var c = URLComponents(string: "http://127.0.0.1:\(sup.port)/hub/open")!
        c.queryItems = q.map { URLQueryItem(name: $0.key, value: $0.value) }
        var r = URLRequest(url: c.url!, timeoutInterval: 600)
        r.httpMethod = "POST"; r.httpBody = Data()
        guard let (d, resp) = try? await URLSession(configuration: .ephemeral).data(for: r) else { return (0, [:]) }
        return ((resp as? HTTPURLResponse)?.statusCode ?? 0, (try? JSONSerialization.jsonObject(with: d)) as? [String: Any] ?? [:])
    }

    func openFile(_ path: String) {
        Task {
            let (code, d) = await request("/hub/open", method: "POST", query: ["path": (path as NSString).deletingLastPathComponent, "file": path])
            guard code == 200, let s = d["url"] as? String, let u = URL(string: s) else { return tell("Leela could not open \(path): \(d["error"] as? String ?? "no answer")") }
            windows.show(u, title: "leela — \((path as NSString).lastPathComponent)")
        }
    }

    func pickFolder(_ done: @escaping (String?) -> Void) {
        let o = NSOpenPanel()
        o.canChooseDirectories = true; o.canChooseFiles = false; o.allowsMultipleSelection = false
        guard o.runModal() == .OK, let u = o.url else { return done(nil) }
        Task { _ = await request("/hub/grant", method: "POST", query: ["path": u.path], timeout: 10); done(u.path) }
    }

    func tell(_ msg: String) { let a = NSAlert(); a.messageText = msg; a.runModal() }

    // menus
    @objc func menuRow(_ i: NSMenuItem) { if let js = i.representedObject as? String { windows.run(js: js) } }
    @objc func usePrevious(_ i: Any?) { Task { if !(await sup.usePrevious()) { tell("There is no previous version to go back to.") } } }
    @objc func showLog(_ i: Any?) { NSWorkspace.shared.open(paths.serverLog) }
    @objc func openRecent(_ i: NSMenuItem) { if let p = i.representedObject as? String { openFolder(p, trusted: true) } }

    func applicationDockMenu(_ s: NSApplication) -> NSMenu? {
        Task { recent = await get("/app/recent")?["recent"] as? [String] ?? recent }
        let m = NSMenu()
        for p in recent.prefix(10) {
            let i = NSMenuItem(title: (p as NSString).lastPathComponent, action: #selector(openRecent(_:)), keyEquivalent: "")
            i.target = self; i.representedObject = p; m.addItem(i)
        }
        return m
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ s: NSApplication, hasVisibleWindows v: Bool) -> Bool {
        if !v, case .ready(let base) = sup.phase { windows.show(base) }
        return true
    }

    func applicationWillTerminate(_ n: Notification) { sup?.stop(); control?.stop() }

    // ControlHost
    func confirm(_ question: String) async -> Bool? {
        NSApp.activate(ignoringOtherApps: true)
        let a = NSAlert()
        a.messageText = "Leela"; a.informativeText = question
        a.addButton(withTitle: "Add"); a.addButton(withTitle: "Cancel")
        if let w = NSApp.keyWindow ?? windows.windows.values.first?.0 {
            return await withCheckedContinuation { c in a.beginSheetModal(for: w) { c.resume(returning: $0 == .alertFirstButtonReturn) } }
        }
        return a.runModal() == .alertFirstButtonReturn
    }

    func installExtra(_ name: String) async -> Bool { Task { await sup.installExtra(name) }; return true }

    func startUpdate(kind: String) async -> UpdateState {
        if kind == "app" { return brew.start(log: paths.logs.appending(path: "brew.log")) }
        Task { await sup.buildUpdate() }
        return UpdateState(state: "running", line: "getting the new packages")
    }

    func updateState() -> UpdateState { brew.state.state != "idle" ? brew.state : sup.update }

    func restartServer() async -> Bool {
        if brew.state.state == "done" {
            // the new app is in place: open it once this one has quit
            let sh = "while kill -0 \"$0\" 2>/dev/null; do sleep .2; done; exec open \"$1\""
            let p = Process(); p.executableURL = URL(fileURLWithPath: "/bin/sh")
            p.arguments = ["-c", sh, String(ProcessInfo.processInfo.processIdentifier), bundle.bundleURL.path]
            try? p.run()
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { NSApp.terminate(nil) }
            return true
        }
        DispatchQueue.main.async { Task { await self.sup.restart() } }
        return true
    }

    func status() -> [String: Any] { sup.status(appVersion: appVersion, brew: brew.available) }
}
