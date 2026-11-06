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

    /// the slug of a server URL (`<slug>.localhost`), else the home key
    static func key(_ url: URL) -> String {
        guard let h = url.host, h.hasSuffix(".localhost") else { return homeKey }
        return String(h.dropLast(".localhost".count))
    }

    func isServer(_ u: URL) -> Bool {
        guard u.scheme == "http", u.port == port, let h = u.host else { return false }
        return h == "127.0.0.1" || h == "localhost" || h.hasSuffix(".localhost")
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
        let k = Self.key(url)
        hidden.removeAll { $0 == k }
        // a Finder open or a question while Leela is behind another app comes forward, as kavacha's bring_forward
        NSApp.activate()
        if let (w, _) = windows[k] { w.makeKeyAndOrderFront(nil); return }
        let (w, v) = make(url, title: title)
        w.setFrameAutosaveName("leela-\(k)")
        if windows.isEmpty { w.center() } else { w.cascadeTopLeft(from: NSPoint(x: 40, y: 40)) }
        windows[k] = (w, v)
        v.load(URLRequest(url: url))
        w.makeKeyAndOrderFront(nil)
    }

    func reloadAll(port: Int) {
        self.port = port
        for (k, (_, v)) in windows {
            let host = k == Self.homeKey ? "127.0.0.1" : "\(k).localhost"
            v.load(URLRequest(url: URL(string: "http://\(host):\(port)/")!))
        }
    }

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
        guard m.frameInfo.isMainFrame, o.protocol == "http", o.port == port, o.host == "127.0.0.1" || o.host == "localhost" || o.host.hasSuffix(".localhost")
        else { return replyHandler(nil, "not a Leela page") }
        switch Bridge.route(m.body) {
        case .openFolder(let p): app?.openFolder(p, trusted: false); replyHandler(true, nil)
        case .pickFolder: app?.pickFolder { replyHandler($0, nil) }
        case .recent: replyHandler(app?.recent ?? [], nil)
        case .setBackground(let hexColour):
            paint(Self.colour(hexColour) ?? background)
            replyHandler(true, nil)
        case .setTitle(let t, let url):
            let w = url.flatMap(URL.init(string:)).flatMap { windows[Self.key($0)]?.0 } ?? m.webView?.window
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
        let u = a.request.url
        switch Self.policy(u, server: u.map(isServer) ?? false, link: a.navigationType == .linkActivated, download: a.shouldPerformDownload) {
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
