import AppKit
import LeelaCore
import WebKit

/// The page's view: its native context menu is empty, as in the old app, unless the inspector is on.
/// A file or folder dragged in from another app opens as a Finder open does; a drag inside the page stays the page's.
final class LeelaWebView: WKWebView {
    var debug = false
    /// what a drop from outside opens; `Windows.make` sends it to the app's open events
    var onFiles: (([URL]) -> Void)?
    override func willOpenMenu(_ m: NSMenu, with e: NSEvent) { if !debug { m.removeAllItems() } }

    /// the file URLs on a pasteboard from another app, else none
    static func dropped(_ pb: NSPasteboard, outside: Bool) -> [URL] {
        guard outside else { return [] }
        return (pb.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL]) ?? []
    }
    func files(_ i: NSDraggingInfo) -> [URL] { Self.dropped(i.draggingPasteboard, outside: i.draggingSource == nil) }
    /// opens what a drop carries; false leaves the drop to WebKit
    func take(_ pb: NSPasteboard, outside: Bool) -> Bool {
        let urls = Self.dropped(pb, outside: outside)
        guard !urls.isEmpty, let onFiles else { return false }
        onFiles(urls); return true
    }
    override func draggingEntered(_ i: NSDraggingInfo) -> NSDragOperation { files(i).isEmpty ? super.draggingEntered(i) : .copy }
    override func draggingUpdated(_ i: NSDraggingInfo) -> NSDragOperation { files(i).isEmpty ? super.draggingUpdated(i) : .copy }
    override func draggingExited(_ i: NSDraggingInfo?) { if let i, !files(i).isEmpty { return }; super.draggingExited(i) }
    override func prepareForDragOperation(_ i: NSDraggingInfo) -> Bool { files(i).isEmpty ? super.prepareForDragOperation(i) : true }
    override func performDragOperation(_ i: NSDraggingInfo) -> Bool { take(i.draggingPasteboard, outside: i.draggingSource == nil) || super.performDragOperation(i) }
    override func concludeDragOperation(_ i: NSDraggingInfo?) { if let i, !files(i).isEmpty { return }; super.concludeDragOperation(i) }
}

/// What a navigation does.
enum Nav: Equatable { case allow, download, browser, cancel }

/// One WKWebView window per workspace, keyed by its slug; the bridge shim in each page.
@MainActor
final class Windows: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandlerWithReply, NSWindowDelegate, WKDownloadDelegate {
    static let homeKey = "leela:home"
    /// kavacha's DEFAULT_SIZE and MIN_SIZE
    static let size = NSSize(width: 1440, height: 900), minSize = NSSize(width: 900, height: 560)
    /// kavacha's NO_SUBSTITUTION: smart quotes and dashes would change code as it is typed
    static let noSubstitution = ["NSAutomaticQuoteSubstitutionEnabled", "NSAutomaticDashSubstitutionEnabled", "NSAutomaticTextReplacementEnabled",
                                 "NSAutomaticSpellingCorrectionEnabled", "NSAutomaticPeriodSubstitutionEnabled", "NSAutomaticCapitalizationEnabled",
                                 "NSAutomaticInlinePredictionEnabled"]
    /// the old app's `LEELA_WEBVIEW_DEBUG`: the inspector and the native context menu
    static let debug = !(ProcessInfo.processInfo.environment["LEELA_WEBVIEW_DEBUG"] ?? "").isEmpty
    var port = 0
    var background = NSColor.windowBackgroundColor
    var windows: [String: (NSWindow, WKWebView)] = [:]
    /// closed windows, kept for the Dock icon to bring back, most recent last
    var hidden: [String] = []
    /// the delegate does what the page asks: open a folder, pick one, the recent list
    weak var app: AppDelegate?

    static func quietTextSubstitution() { for k in noSubstitution { UserDefaults.standard.set(false, forKey: k) } }

    /// each workspace's own port and its slug, from `/hub/open` answers and `/app/sites`; the main port is the home window's
    var sites: [Int: String] = [:]
    /// each workspace's folder, so a restarted server can be asked for it again
    var roots: [String: String] = [:]

    /// the window a server URL belongs to: its workspace by port, a `<slug>.localhost` name, else home
    func key(_ url: URL) -> String {
        if let p = url.port, p != port, let s = sites[p] { return s }
        if let h = url.host, h.hasSuffix(".localhost") { return String(h.dropLast(".localhost".count)) }
        return Self.homeKey
    }

    /// what a `/hub/open` row or a `/app/sites` row says: the workspace's port and folder
    func learn(_ row: [String: Any]) {
        guard let id = row["id"] as? String, let s = row["url"] as? String, let u = URL(string: s), let p = u.port, !u.path.hasPrefix("/hub/go/") else { return }
        if p != port { sites = sites.filter { $0.value != id }; sites[p] = id }
        if let r = row["root"] as? String, !r.isEmpty { roots[id] = r }
    }

    static func loopback(_ h: String) -> Bool { h == "127.0.0.1" || h == "localhost" || h == "::1" || h.hasSuffix(".localhost") }
    func ours(_ p: Int?) -> Bool { p != nil && (p == port || sites[p!] != nil) }
    func isServer(_ u: URL) -> Bool {
        guard u.scheme == "http", ours(u.port), let h = u.host else { return false }
        return Self.loopback(h)
    }

    /// a window for `url`, not loaded and not on screen
    func make(_ url: URL, title: String) -> (NSWindow, WKWebView) {
        let c = WKWebViewConfiguration()
        c.websiteDataStore = .default()
        c.userContentController.addUserScript(WKUserScript(source: Bridge.shim, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        c.userContentController.addScriptMessageHandler(self, contentWorld: .page, name: Bridge.handler)
        let v = LeelaWebView(frame: .zero, configuration: c)
        v.debug = Self.debug; v.isInspectable = Self.debug
        v.onFiles = { [weak self] urls in self?.app?.application(NSApp, open: urls) }
        v.navigationDelegate = self; v.uiDelegate = self
        v.allowsBackForwardNavigationGestures = false
        v.underPageBackgroundColor = background
        let w = NSWindow(contentRect: NSRect(origin: .zero, size: Self.size), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        w.title = title; w.contentView = v; w.initialFirstResponder = v; w.makeFirstResponder(v)
        w.minSize = Self.minSize; w.collectionBehavior.insert(.fullScreenPrimary)
        w.backgroundColor = background
        w.isReleasedWhenClosed = false
        w.delegate = self
        return (w, v)
    }

    /// shows the window for `url`, opening it when there is none
    func show(_ url: URL, title: String = "Leela") {
        hidden.removeAll { $0 == key(url) }
        // a Finder open or a question while Leela is behind another app comes forward, as kavacha's bring_forward
        NSApp.activate()
        let w = reuse(url, title: title) ?? place(url, title: title)
        w.makeKeyAndOrderFront(nil)
    }

    /// the open window for `url` with `title`, its page loaded again when it has none; nil when there is no window
    func reuse(_ url: URL, title: String = "Leela") -> NSWindow? {
        guard let (w, v) = windows[key(url)] else { return nil }
        if title != "Leela" { w.title = title }
        if v.url == nil || failed.contains(ObjectIdentifier(v)) { point(v, url) }
        return w
    }

    /// a new window for `url`, not on screen yet, its page loading
    func place(_ url: URL, title: String) -> NSWindow {
        let k = key(url), (w, v) = make(url, title: title)
        w.setFrameAutosaveName("leela-\(k)")
        if windows.isEmpty { w.center() } else { w.cascadeTopLeft(from: NSPoint(x: 40, y: 40)) }
        windows[k] = (w, v)
        point(v, url)
        return w
    }

    /// pages that failed to load; `reuse` loads them again
    var failed = Set<ObjectIdentifier>()
    /// where each window's load is written down (`logs/windows.log`); nil writes nothing
    var log: URL?
    func note(_ v: WKWebView?, _ what: String) {
        guard let log else { return }
        let line = "\(ISO8601DateFormatter().string(from: Date())) \(v.flatMap { v in windows.first { $0.value.1 === v }?.key } ?? "-") \(what)\n"
        if let h = try? FileHandle(forWritingTo: log) { h.seekToEndOfFile(); h.write(Data(line.utf8)); try? h.close() }
        else { try? Data(line.utf8).write(to: log) }
    }
    /// seconds a new page waits for the server, as kavacha's `url_wait`
    var urlWait = 90.0

    /// loads `url` once the server answers it, as kavacha's `_point`; a server that never answers gets a page that says so
    func point(_ v: WKWebView, _ url: URL) {
        failed.remove(ObjectIdentifier(v))
        note(v, "point \(url.absoluteString)")
        Task { [urlWait] in
            let ok = await Self.answers(url, within: urlWait)
            self.note(v, "answers \(url.absoluteString) \(ok)")
            if ok { v.load(URLRequest(url: url)) } else { self.unreachable(v, url) }
        }
    }

    /// whether `url` gives any HTTP answer within `within` seconds
    static func answers(_ url: URL, within: Double) async -> Bool {
        let cfg = URLSessionConfiguration.ephemeral; cfg.connectionProxyDictionary = [:]; cfg.timeoutIntervalForRequest = 2
        let s = URLSession(configuration: cfg), end = Date().addingTimeInterval(within)
        repeat {
            if let (_, r) = try? await s.data(from: url), r is HTTPURLResponse { return true }
            try? await Task.sleep(for: .milliseconds(200))
        } while Date() < end
        return false
    }

    func unreachable(_ v: WKWebView, _ url: URL, why: String = "it did not answer") {
        failed.insert(ObjectIdentifier(v))
        let esc = { (s: String) in s.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;") }
        v.loadHTMLString("<body style='font:14px -apple-system;margin:3em'><p>Leela could not show \(esc(url.absoluteString)): \(esc(why)).</p><p>Open the file or folder again to try once more.</p></body>", baseURL: nil)
    }

    func webView(_ w: WKWebView, didFailProvisionalNavigation n: WKNavigation!, withError e: Error) { gone(w, e) }
    func webView(_ w: WKWebView, didFail n: WKNavigation!, withError e: Error) { gone(w, e) }
    func gone(_ w: WKWebView, _ e: Error) {
        let e = e as NSError
        note(w, "failed \(e.domain) \(e.code) \(e.localizedDescription) \((e.userInfo[NSURLErrorFailingURLErrorKey] as? URL)?.absoluteString ?? "")")
        // a download or a navigation the policy cancelled ends this way too, and the page stays
        guard !(e.domain == "WebKitErrorDomain" && [102, 101].contains(e.code)), e.code != NSURLErrorCancelled,
              let u = e.userInfo[NSURLErrorFailingURLErrorKey] as? URL ?? w.url, isServer(u) else { return }
        unreachable(w, u, why: e.localizedDescription)
    }
    /// the page's process ended (memory, a crash): load it again rather than leave the window blank
    func webView(_ w: WKWebView, didStartProvisionalNavigation n: WKNavigation!) { note(w, "start \(w.url?.absoluteString ?? "")") }
    func webView(_ w: WKWebView, didCommit n: WKNavigation!) { note(w, "commit") }
    func webView(_ w: WKWebView, didFinish n: WKNavigation!) { note(w, "finish") }
    func webViewWebContentProcessDidTerminate(_ w: WKWebView) { note(w, "page process ended"); if let u = w.url, isServer(u) { w.load(URLRequest(url: u)) } }

    /// after a restart: the home window to the new main port, each other window to the URL `urls` gives its slug
    func reload(port: Int, urls: [String: URL]) {
        self.port = port
        for (k, (_, v)) in windows {
            if k == Self.homeKey { point(v, URL(string: "http://127.0.0.1:\(port)/")!) }
            else if let u = urls[k] { point(v, u) }
        }
    }

    /// every window off screen and its page stopped, so its streams to the server close before the server is asked to stop
    func hideAll() { for (w, v) in windows.values { w.orderOut(nil); v.stopLoading(); v.loadHTMLString("", baseURL: nil) } }

    var front: WKWebView? { (NSApp.keyWindow?.contentView as? WKWebView) ?? windows.values.first { $0.0.isVisible }?.1 }

    /// a menu row: the page's own dispatcher in the front window
    func run(js: String) { front?.evaluateJavaScript(js) }

    /// closing hides the window, as the old app did; the Dock icon brings it back with its page as it was
    func windowShouldClose(_ w: NSWindow) -> Bool {
        guard let k = windows.first(where: { $0.value.0 === w })?.key else { return true }
        w.orderOut(nil)
        hidden.removeAll { $0 == k }; hidden.append(k)
        return false
    }

    /// the last closed window on screen again; false when there is none
    func reopen() -> Bool {
        guard let k = hidden.popLast(), let (w, _) = windows[k] else { return false }
        NSApp.activate(); w.makeKeyAndOrderFront(nil); return true
    }

    /// where a question goes: the key window, a visible one, else the last closed one brought back
    func forQuestion() -> NSWindow? {
        if let w = NSApp.keyWindow, windows.values.contains(where: { $0.0 === w }) { return w }
        if let w = windows.values.first(where: { $0.0.isVisible })?.0 { return w }
        return reopen() ? NSApp.keyWindow ?? windows.values.first(where: { $0.0.isVisible })?.0 : nil
    }

    // the bridge
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage, replyHandler: @escaping @MainActor @Sendable (Any?, String?) -> Void) {
        let o = m.frameInfo.securityOrigin
        guard m.frameInfo.isMainFrame, o.protocol == "http", ours(o.port), Self.loopback(o.host)
        else { return replyHandler(nil, "not a Leela page") }
        switch Bridge.route(m.body) {
        case .openFolder(let p): app?.openFolder(p, trusted: false); replyHandler(true, nil)
        case .pickFolder: app?.pickFolder { replyHandler($0, nil) }
        case .recent: replyHandler(app?.recent ?? [], nil)
        case .setBackground(let hexColour):
            paint(Self.colour(hexColour) ?? background)
            replyHandler(true, nil)
        case .setTitle(let t, let url):
            let w = url.flatMap(URL.init(string:)).flatMap { windows[self.key($0)]?.0 } ?? m.webView?.window
            w?.title = t
            replyHandler(w != nil, nil)
        case .unknown(let what): replyHandler(nil, "unknown call \(what)")
        }
    }

    /// every window and what WebKit draws past the page's edge, as kavacha's paint_background
    func paint(_ c: NSColor) {
        background = c
        for (w, v) in windows.values { w.backgroundColor = c; v.underPageBackgroundColor = c }
    }

    static func colour(_ s: String) -> NSColor? {
        guard Bridge.isColour(s), let v = UInt32(s.dropFirst(), radix: 16) else { return nil }
        return NSColor(srgbRed: CGFloat(v >> 16 & 0xff) / 255, green: CGFloat(v >> 8 & 0xff) / 255, blue: CGFloat(v & 0xff) / 255, alpha: 1)
    }

    /// the server's pages stay, a `download` link saves, a click to the web or mail goes to the browser; never file:, smb: or another app's scheme
    static func policy(_ u: URL?, server: Bool, link: Bool, download: Bool) -> Nav {
        guard let u, let s = u.scheme else { return .cancel }
        if server || ["blob", "data"].contains(s) { return download ? .download : .allow }
        if s == "about" { return .allow }
        return link && ["http", "https", "mailto"].contains(s) ? .browser : .cancel
    }

    /// a main-frame response WebKit cannot show, or one sent as an attachment, is saved
    static func saves(showable: Bool, mainFrame: Bool, disposition: String?) -> Bool {
        mainFrame && (!showable || (disposition ?? "").lowercased().hasPrefix("attachment"))
    }

    func webView(_ w: WKWebView, decidePolicyFor a: WKNavigationAction, decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void) {
        let u = a.request.url, p = Self.policy(u, server: u.map(isServer) ?? false, link: a.navigationType == .linkActivated, download: a.shouldPerformDownload)
        if a.targetFrame?.isMainFrame ?? true { note(w, "policy \(u?.absoluteString ?? "nil") type=\(a.navigationType.rawValue) port=\(port) -> \(p)") }
        switch p {
        case .allow: decisionHandler(.allow)
        case .download: decisionHandler(.download)
        case .browser: NSWorkspace.shared.open(u!); decisionHandler(.cancel)
        case .cancel: decisionHandler(.cancel)
        }
    }

    func webView(_ w: WKWebView, decidePolicyFor r: WKNavigationResponse, decisionHandler: @escaping @MainActor (WKNavigationResponsePolicy) -> Void) {
        let d = (r.response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Disposition")
        decisionHandler(Self.saves(showable: r.canShowMIMEType, mainFrame: r.isForMainFrame, disposition: d) ? .download : .allow)
    }

    func webView(_ w: WKWebView, navigationAction a: WKNavigationAction, didBecome d: WKDownload) { d.delegate = self }
    func webView(_ w: WKWebView, navigationResponse r: WKNavigationResponse, didBecome d: WKDownload) { d.delegate = self }

    func download(_ d: WKDownload, decideDestinationUsing r: URLResponse, suggestedFilename n: String, completionHandler: @escaping @MainActor @Sendable (URL?) -> Void) {
        let s = NSSavePanel()
        s.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
        s.nameFieldStringValue = n
        guard s.runModal() == .OK, let u = s.url else { return completionHandler(nil) }
        // the panel already asked to replace it; WebKit refuses a file that is there
        try? FileManager.default.removeItem(at: u)
        completionHandler(u)
    }

    func webView(_ w: WKWebView, createWebViewWith c: WKWebViewConfiguration, for a: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let u = a.request.url { if isServer(u) { show(u) } else if ["http", "https", "mailto"].contains(u.scheme ?? "") { NSWorkspace.shared.open(u) } }
        return nil
    }

    func webView(_ w: WKWebView, runJavaScriptAlertPanelWithMessage m: String, initiatedByFrame f: WKFrameInfo, completionHandler: @escaping @MainActor () -> Void) {
        NSApp.activate(); let a = NSAlert(); a.messageText = m; a.runModal(); completionHandler()
    }

    func webView(_ w: WKWebView, runJavaScriptConfirmPanelWithMessage m: String, initiatedByFrame f: WKFrameInfo, completionHandler: @escaping @MainActor (Bool) -> Void) {
        let a = NSAlert(); a.messageText = m; a.addButton(withTitle: "OK"); a.addButton(withTitle: "Cancel")
        completionHandler(a.runModal() == .alertFirstButtonReturn)
    }

    func webView(_ w: WKWebView, runJavaScriptTextInputPanelWithPrompt p: String, defaultText d: String?, initiatedByFrame f: WKFrameInfo, completionHandler: @escaping @MainActor (String?) -> Void) {
        let a = NSAlert(); a.messageText = p; a.addButton(withTitle: "OK"); a.addButton(withTitle: "Cancel")
        let t = NSTextField(string: d ?? ""); t.frame = NSRect(x: 0, y: 0, width: 320, height: 24)
        a.accessoryView = t; a.window.initialFirstResponder = t
        completionHandler(a.runModal() == .alertFirstButtonReturn ? t.stringValue : nil)
    }

    func webView(_ w: WKWebView, runOpenPanelWith p: WKOpenPanelParameters, initiatedByFrame f: WKFrameInfo, completionHandler: @escaping @MainActor ([URL]?) -> Void) {
        let o = NSOpenPanel(); o.allowsMultipleSelection = p.allowsMultipleSelection; o.canChooseDirectories = p.allowsDirectories
        completionHandler(o.runModal() == .OK ? o.urls : nil)
    }
}

/// The target of every row that runs in the page: `run` gets the row's JavaScript.
@MainActor
final class MenuRunner: NSObject {
    var run: (String) -> Void
    init(_ run: @escaping (String) -> Void) { self.run = run }
    @objc func menuRow(_ i: NSMenuItem) { if let js = i.representedObject as? String { run(js) } }
}

/// The menu bar from the server's `/app/menu.json`, and the Dock menu from `/app/recent`.
@MainActor
enum Menus {
    /// kavacha's DOCK_RECENT
    static let dockRecent = 8
    static let cmd = NSEvent.ModifierFlags.command

    /// the bar; `app` is the target of the launcher's own rows (Use Previous Version, Show Server Log)
    static func build(_ menus: [[String: Any]], runner: MenuRunner, app: AnyObject? = nil) -> NSMenu {
        let bar = NSMenu()
        let appItem = NSMenuItem(), appMenu = NSMenu(title: "Leela")
        appItem.submenu = appMenu
        bar.addItem(appItem)
        appMenu.addItem(withTitle: "About Leela", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        for m in menus where m["title"] as? String == "__app__" { for row in m["items"] as? [[String: Any]] ?? [] { appMenu.addItem(item(row, runner)) } }
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Use Previous Version", action: Selector(("usePrevious:")), keyEquivalent: "").target = app
        appMenu.addItem(withTitle: "Show Server Log", action: Selector(("showLog:")), keyEquivalent: "").target = app
        appMenu.addItem(.separator())
        let services = NSMenu(title: "Services")
        appMenu.addItem(withTitle: "Services", action: nil, keyEquivalent: "").submenu = services
        NSApplication.shared.servicesMenu = services
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide Leela", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "Hide Others", action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h").keyEquivalentModifierMask = [.command, .option]
        appMenu.addItem(withTitle: "Show All", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit Leela", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        for m in menus {
            guard let t = m["title"] as? String, t != "__app__" else { continue }
            let it = NSMenuItem(), sub = NSMenu(title: t)
            it.submenu = sub
            for row in m["items"] as? [[String: Any]] ?? [] { sub.addItem(item(row, runner)) }
            bar.addItem(it)
            if t == "Window" { NSApplication.shared.windowsMenu = sub }
            if t == "Help" { NSApplication.shared.helpMenu = sub }
        }
        closeWindow(bar); undo(bar)
        return bar
    }

    /// the bar before the server answers, or when it does not: the app menu and the editing rows
    static let fallback: [[String: Any]] = [["title": "Edit", "items": [["title": "Cut", "selector": "cut:", "key": "x", "mask": 1 << 20],
        ["title": "Copy", "selector": "copy:", "key": "c", "mask": 1 << 20], ["title": "Paste", "selector": "paste:", "key": "v", "mask": 1 << 20],
        ["title": "Select All", "selector": "selectAll:", "key": "a", "mask": 1 << 20]]]]

    /// ⌘Z and ⇧⌘Z for a plain field, as the old web view's keyDown gave; the page sees the key first, so the editor's own undo still wins
    static func undo(_ bar: NSMenu) {
        guard let m = bar.items.compactMap(\.submenu).first(where: { $0.title == "Edit" }), !m.items.contains(where: { $0.action == Selector(("undo:")) }) else { return }
        m.insertItem(.separator(), at: 0)
        m.insertItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z", at: 0)
        m.insertItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z", at: 0)
    }

    /// ⌘W closes the window, as the old app's web view did; the row goes in File, else Window, unless the server's bar has one
    static func closeWindow(_ bar: NSMenu) {
        let subs = bar.items.compactMap(\.submenu)
        if subs.contains(where: { $0.items.contains { $0.action == #selector(NSWindow.performClose(_:)) } }) { return }
        guard let m = subs.first(where: { $0.title == "File" }) ?? subs.first(where: { $0.title == "Window" }) else { return }
        m.addItem(.separator())
        m.addItem(withTitle: "Close Window", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
    }

    static func item(_ row: [String: Any], _ runner: MenuRunner) -> NSMenuItem {
        if row["sep"] as? Bool == true { return .separator() }
        let title = row["title"] as? String ?? ""
        let it: NSMenuItem
        if let sel = row["selector"] as? String { it = NSMenuItem(title: title, action: NSSelectorFromString(sel), keyEquivalent: "") }
        else {
            it = NSMenuItem(title: title, action: #selector(MenuRunner.menuRow(_:)), keyEquivalent: "")
            it.target = runner
            if let a = row["action"] as? String { it.representedObject = js(action: a) }
            else if let js = row["js"] as? String { it.representedObject = js }
        }
        if let k = row["key"] as? String, let mask = row["mask"] as? Int { (it.keyEquivalent, it.keyEquivalentModifierMask) = appKit(k, NSEvent.ModifierFlags(rawValue: UInt(mask))) }
        return it
    }

    /// what shift makes of a key on the US keyboard
    nonisolated static let usShift: [String: String] = ["1": "!", "2": "@", "3": "#", "4": "$", "5": "%", "6": "^", "7": "&", "8": "*", "9": "(", "0": ")", "-": "_",
        "=": "+", "[": "{", "]": "}", ";": ":", "'": "\"", ",": "<", ".": ">", "/": "?", "`": "~", "\\": "|"]

    /// AppKit matches shift by the character it makes, so ⇧ is the shifted character with no shift flag, as Help's ⌘?. A lower case
    /// key with the shift flag never fires, and takes the same chord without shift. kavacha's mac_key spells it that way: fix it there too.
    static func appKit(_ k: String, _ m: NSEvent.ModifierFlags) -> (String, NSEvent.ModifierFlags) {
        guard m.contains(.shift), k.count == 1 else { return (k, m) }
        if k.lowercased() != k.uppercased() { return (k.uppercased(), m.subtracting(.shift)) }
        return usShift[k].map { ($0, m.subtracting(.shift)) } ?? (k, m)
    }

    /// what an action row runs: the page's own dispatcher, as the old app's `leeAct("…")`
    static func js(action a: String) -> String { "leeAct(\(jsString(a)))" }

    static func jsString(_ s: String) -> String {
        let d = try? JSONSerialization.data(withJSONObject: [s])
        return d.map { String(decoding: $0, as: UTF8.self).dropFirst().dropLast() }.map(String.init) ?? "\"\""
    }

    /// the folders last open, newest first; a disabled row when there are none, as kavacha's dock_menu
    static func dock(_ recent: [String], target: AnyObject, action: Selector) -> NSMenu {
        let m = NSMenu()
        if recent.isEmpty { m.addItem(withTitle: "No recent folders", action: nil, keyEquivalent: ""); return m }
        for p in recent.prefix(dockRecent) {
            let name = (p as NSString).lastPathComponent
            let i = NSMenuItem(title: name.isEmpty ? p : name, action: action, keyEquivalent: "")
            i.target = target; i.representedObject = p; i.toolTip = p; m.addItem(i)
        }
        return m
    }
}
