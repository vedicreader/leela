import AppKit
import LeelaCore
import WebKit

/// One WKWebView window per workspace, keyed by its slug; the bridge shim in each page.
@MainActor
final class Windows: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandlerWithReply, NSWindowDelegate {
    static let homeKey = "leela:home"
    var port = 0
    var background = NSColor.windowBackgroundColor
    var windows: [String: (NSWindow, WKWebView)] = [:]
    /// the delegate does what the page asks: open a folder, pick one, the recent list
    weak var app: AppDelegate?

    /// the slug of a server URL (`<slug>.localhost`), else the home key
    static func key(_ url: URL) -> String {
        guard let h = url.host, h.hasSuffix(".localhost") else { return homeKey }
        return String(h.dropLast(".localhost".count))
    }

    func isServer(_ u: URL) -> Bool {
        guard u.scheme == "http", u.port == port, let h = u.host else { return false }
        return h == "127.0.0.1" || h == "localhost" || h.hasSuffix(".localhost")
    }

    /// shows the window for `url`, opening it when there is none
    func show(_ url: URL, title: String = "Leela") {
        let k = Self.key(url)
        if let (w, _) = windows[k] { w.makeKeyAndOrderFront(nil); return }
        let c = WKWebViewConfiguration()
        c.websiteDataStore = .default()
        c.userContentController.addUserScript(WKUserScript(source: Bridge.shim, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        c.userContentController.addScriptMessageHandler(self, contentWorld: .page, name: Bridge.handler)
        let v = WKWebView(frame: .zero, configuration: c)
        v.navigationDelegate = self
        v.uiDelegate = self
        v.allowsBackForwardNavigationGestures = false
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1400, height: 900), styleMask: [.titled, .closable, .miniaturizable, .resizable],
                         backing: .buffered, defer: false)
        w.title = title
        w.contentView = v
        w.backgroundColor = background
        w.setFrameAutosaveName("leela-\(k)")
        w.isReleasedWhenClosed = false
        w.delegate = self
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

    var front: WKWebView? { (NSApp.keyWindow?.contentView as? WKWebView) ?? windows.values.first?.1 }

    /// a menu row: the page's own dispatcher in the front window
    func run(js: String) { front?.evaluateJavaScript(js) }

    func windowWillClose(_ n: Notification) {
        guard let w = n.object as? NSWindow, let k = windows.first(where: { $0.value.0 === w })?.key else { return }
        windows[k] = nil
    }

    // the bridge
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage, replyHandler: @escaping @MainActor @Sendable (Any?, String?) -> Void) {
        guard let o = m.frameInfo.request.url, isServer(o) else { return replyHandler(nil, "not a Leela page") }
        switch Bridge.route(m.body) {
        case .openFolder(let p): app?.openFolder(p, trusted: false); replyHandler(true, nil)
        case .pickFolder: app?.pickFolder { replyHandler($0, nil) }
        case .recent: replyHandler(app?.recent ?? [], nil)
        case .setBackground(let hexColour):
            background = Self.colour(hexColour) ?? background
            for (w, _) in windows.values { w.backgroundColor = background }
            replyHandler(true, nil)
        case .setTitle(let t, let url):
            let w = url.flatMap(URL.init(string:)).flatMap { windows[Self.key($0)]?.0 } ?? m.webView?.window
            w?.title = t
            replyHandler(w != nil, nil)
        case .unknown(let what): replyHandler(nil, "unknown call \(what)")
        }
    }

    static func colour(_ s: String) -> NSColor? {
        guard Bridge.isColour(s), let v = UInt32(s.dropFirst(), radix: 16) else { return nil }
        return NSColor(srgbRed: CGFloat(v >> 16 & 0xff) / 255, green: CGFloat(v >> 8 & 0xff) / 255, blue: CGFloat(v & 0xff) / 255, alpha: 1)
    }

    // links: the server's pages stay, everything else goes to the browser
    func webView(_ w: WKWebView, decidePolicyFor a: WKNavigationAction, decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void) {
        guard let u = a.request.url else { return decisionHandler(.cancel) }
        if isServer(u) || ["about", "blob", "data"].contains(u.scheme ?? "") { return decisionHandler(.allow) }
        NSWorkspace.shared.open(u)
        decisionHandler(.cancel)
    }

    func webView(_ w: WKWebView, createWebViewWith c: WKWebViewConfiguration, for a: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let u = a.request.url { if isServer(u) { show(u) } else { NSWorkspace.shared.open(u) } }
        return nil
    }

    func webView(_ w: WKWebView, runJavaScriptAlertPanelWithMessage m: String, initiatedByFrame f: WKFrameInfo, completionHandler: @escaping @MainActor () -> Void) {
        let a = NSAlert(); a.messageText = m; a.runModal(); completionHandler()
    }

    func webView(_ w: WKWebView, runJavaScriptConfirmPanelWithMessage m: String, initiatedByFrame f: WKFrameInfo, completionHandler: @escaping @MainActor (Bool) -> Void) {
        let a = NSAlert(); a.messageText = m; a.addButton(withTitle: "OK"); a.addButton(withTitle: "Cancel")
        completionHandler(a.runModal() == .alertFirstButtonReturn)
    }

    func webView(_ w: WKWebView, runOpenPanelWith p: WKOpenPanelParameters, initiatedByFrame f: WKFrameInfo, completionHandler: @escaping @MainActor ([URL]?) -> Void) {
        let o = NSOpenPanel(); o.allowsMultipleSelection = p.allowsMultipleSelection; o.canChooseDirectories = p.allowsDirectories
        completionHandler(o.runModal() == .OK ? o.urls : nil)
    }
}

/// The menu bar from the server's `/app/menu.json`, and the Dock menu from `/app/recent`.
@MainActor
enum Menus {
    static func build(_ menus: [[String: Any]], target: AppDelegate) -> NSMenu {
        let bar = NSMenu()
        let appItem = NSMenuItem(), appMenu = NSMenu(title: "Leela")
        appItem.submenu = appMenu
        bar.addItem(appItem)
        appMenu.addItem(withTitle: "About Leela", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        for m in menus where m["title"] as? String == "__app__" { for row in m["items"] as? [[String: Any]] ?? [] { appMenu.addItem(item(row, target)) } }
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Use Previous Version", action: #selector(AppDelegate.usePrevious(_:)), keyEquivalent: "").target = target
        appMenu.addItem(withTitle: "Show Server Log", action: #selector(AppDelegate.showLog(_:)), keyEquivalent: "").target = target
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide Leela", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "Quit Leela", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        for m in menus {
            guard let t = m["title"] as? String, t != "__app__" else { continue }
            let it = NSMenuItem(), sub = NSMenu(title: t)
            it.submenu = sub
            for row in m["items"] as? [[String: Any]] ?? [] { sub.addItem(item(row, target)) }
            bar.addItem(it)
            if t == "Window" { NSApp.windowsMenu = sub }
            if t == "Help" { NSApp.helpMenu = sub }
        }
        return bar
    }

    static func item(_ row: [String: Any], _ target: AppDelegate) -> NSMenuItem {
        if row["sep"] as? Bool == true { return .separator() }
        let title = row["title"] as? String ?? ""
        let it: NSMenuItem
        if let sel = row["selector"] as? String { it = NSMenuItem(title: title, action: NSSelectorFromString(sel), keyEquivalent: "") }
        else {
            it = NSMenuItem(title: title, action: #selector(AppDelegate.menuRow(_:)), keyEquivalent: "")
            it.target = target
            if let a = row["action"] as? String { it.representedObject = "leeAct(\(jsString(a)))" }
            else if let js = row["js"] as? String { it.representedObject = js }
        }
        if let k = row["key"] as? String, let mask = row["mask"] as? Int {
            it.keyEquivalent = k
            it.keyEquivalentModifierMask = NSEvent.ModifierFlags(rawValue: UInt(mask))
        }
        return it
    }

    static func jsString(_ s: String) -> String {
        let d = try? JSONSerialization.data(withJSONObject: [s])
        return d.map { String(decoding: $0, as: UTF8.self).dropFirst().dropLast() }.map(String.init) ?? "\"\""
    }
}
