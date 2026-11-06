import AppKit
import Foundation
import Testing
import WebKit
@testable import Leela

@MainActor @Suite(.serialized) struct WindowTests {
    let u = { (s: String) in URL(string: s)! }

    @Test func navigationPolicyKeepsTheServerSavesDownloadsAndSendsClicksOut() {
        let p = Windows.policy
        #expect(p(u("http://x.localhost:5/"), true, false, false) == .allow)
        #expect(p(u("http://x.localhost:5/raw?p=a&download=true"), true, true, true) == .download)
        #expect(p(u("blob:http://x.localhost:5/1"), false, true, true) == .download)
        #expect(p(u("blob:http://x.localhost:5/1"), false, false, false) == .allow)
        #expect(p(u("about:blank"), false, false, false) == .allow)
        #expect(p(u("https://example.com/"), false, true, false) == .browser)
        #expect(p(u("https://example.com/f.zip"), false, true, true) == .browser)
        #expect(p(u("mailto:a@b.c"), false, true, false) == .browser)
        #expect(p(u("https://example.com/"), false, false, false) == .cancel)
        #expect(p(u("file:///etc/passwd"), false, true, false) == .cancel)
        #expect(p(u("smb://host/share"), false, true, false) == .cancel)
        #expect(p(nil, false, true, false) == .cancel)
    }

    @Test func aResponseIsSavedWhenWebKitCannotShowItOrItIsAnAttachment() {
        #expect(Windows.saves(showable: false, mainFrame: true, disposition: nil))
        #expect(Windows.saves(showable: true, mainFrame: true, disposition: "attachment; filename=a.py"))
        #expect(!Windows.saves(showable: true, mainFrame: true, disposition: "inline"))
        #expect(!Windows.saves(showable: false, mainFrame: false, disposition: "attachment"))
    }

    @Test func serverURLsAndKeys() {
        let ws = Windows(); ws.port = 5
        #expect(ws.isServer(u("http://x.localhost:5/")) && ws.isServer(u("http://127.0.0.1:5/")) && !ws.isServer(u("http://x.localhost:6/")))
        #expect(!ws.isServer(u("https://127.0.0.1:5/")) && !ws.isServer(u("http://evil.com:5/")))
        #expect(Windows.key(u("http://my-proj.localhost:5/")) == "my-proj" && Windows.key(u("http://127.0.0.1:5/")) == Windows.homeKey)
    }

    @Test func aWindowOpensAsTheOldAppsDidWithoutGoingOnScreen() {
        let ws = Windows()
        let (w, v) = ws.make(u("http://127.0.0.1:1/"), title: "leela — x")
        #expect(!w.isVisible && w.title == "leela — x" && w.minSize == Windows.minSize && w.frame.size.width >= Windows.size.width - 1)
        #expect(w.collectionBehavior.contains(.fullScreenPrimary) && !v.allowsBackForwardNavigationGestures && v.uiDelegate === ws)
        w.close()
    }

    @Test func theBackgroundPaintsEveryWindowAndWhatIsPastThePage() {
        let ws = Windows()
        let (w, v) = ws.make(u("http://127.0.0.1:1/"), title: "t")
        ws.windows["k"] = (w, v)
        let c = Windows.colour("#102030")!
        ws.paint(c)
        #expect(w.backgroundColor == c && v.underPageBackgroundColor == c && ws.background == c)
        #expect(Windows.colour("red") == nil)
        w.close()
    }

    @Test func closingHidesTheWindowAndKeepsItForTheDock() {
        let ws = Windows()
        let (a, av) = ws.make(u("http://a.localhost:1/"), title: "a"), (b, bv) = ws.make(u("http://b.localhost:1/"), title: "b")
        ws.windows = ["a": (a, av), "b": (b, bv)]
        #expect(!ws.windowShouldClose(a) && !ws.windowShouldClose(b) && !ws.windowShouldClose(a))
        #expect(ws.hidden == ["b", "a"] && ws.windows.count == 2 && !a.isVisible)
        let other = NSWindow(contentRect: .zero, styleMask: [.titled, .closable], backing: .buffered, defer: true); other.isReleasedWhenClosed = false
        #expect(ws.windowShouldClose(other))
        for w in [a, b, other] { w.delegate = nil; w.close() }
    }

    @Test func theNativeContextMenuIsEmptyUnlessTheInspectorIsOn() {
        let v = LeelaWebView(frame: .zero, configuration: WKWebViewConfiguration())
        let m = NSMenu(); m.addItem(withTitle: "Reload", action: nil, keyEquivalent: "")
        let e = NSEvent.mouseEvent(with: .rightMouseDown, location: .zero, modifierFlags: [], timestamp: 0, windowNumber: 0, context: nil, eventNumber: 0, clickCount: 1, pressure: 1)!
        v.willOpenMenu(m, with: e)
        #expect(m.items.isEmpty)
        m.addItem(withTitle: "Inspect Element", action: nil, keyEquivalent: ""); v.debug = true
        v.willOpenMenu(m, with: e)
        #expect(m.items.count == 1)
    }

    @Test func theDockMenuListsEightRecentFoldersOrSaysThereAreNone() {
        let t = Probe(), s = #selector(Probe.hide(_:))
        let none = Menus.dock([], target: t, action: s)
        #expect(none.items.map(\.title) == ["No recent folders"] && none.items[0].action == nil)
        let m = Menus.dock((1...12).map { "/p/f\($0)/" }, target: t, action: s)
        #expect(m.items.count == Menus.dockRecent && m.items[0].title == "f1" && m.items[0].toolTip == "/p/f1/" && m.items[0].representedObject as? String == "/p/f1/")
    }

    @Test func aFileDroppedFromFinderGoesWhereAFinderOpenGoes() throws {
        let app = AppDelegate(); app.windows.app = app
        let (w, v) = app.windows.make(u("http://127.0.0.1:1/"), title: "t")
        defer { w.close() }
        let web = try #require(v as? LeelaWebView)
        let dir = FileManager.default.temporaryDirectory.appending(path: "leela-drop-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let f = dir.appending(path: "a.ipynb"); try Data("{}".utf8).write(to: f)
        let pb = NSPasteboard(name: .init("leela-drop-\(UUID().uuidString)")); defer { pb.releaseGlobally() }
        pb.clearContents(); pb.writeObjects([f as NSURL, dir as NSURL])
        #expect(!web.take(pb, outside: false), "a drag inside the page is the page's")
        #expect(app.queued.isEmpty)
        // no server yet: queued as `application(_:open:)` queues a Finder open, and `open` sends a folder to its window, a file to its folder's
        #expect(web.take(pb, outside: true))
        #expect(app.queued.map(\.standardizedFileURL) == [f, dir].map(\.standardizedFileURL))
        let text = NSPasteboard(name: .init("leela-drop-\(UUID().uuidString)")); defer { text.releaseGlobally() }
        text.clearContents(); text.setString("print(1)", forType: .string)
        #expect(!web.take(text, outside: true), "text dropped from another app goes to the page")
    }

    @Test func aWindowWhoseServerDoesNotAnswerSaysSoAndASecondOpenLoadsItAgain() async throws {
        // a new window loaded at once and kept nothing on failure, so a dropped file gave a blank window that a second drop only raised
        let ws = Windows(); ws.port = 1; ws.urlWait = 0.5
        let url = u("http://loose.localhost:1/")
        let w = ws.place(url, title: "leela — a.png")
        defer { w.close() }
        let v = try #require(ws.windows["loose"]?.1)
        var text = ""
        for _ in 0..<40 where !text.contains("could not show") {
            try await Task.sleep(for: .milliseconds(250))
            text = (try? await v.evaluateJavaScript("document.body ? document.body.innerText : ''") as? String) ?? ""
        }
        #expect(text.contains("Leela could not show http://loose.localhost:1/") && ws.failed.contains(ObjectIdentifier(v)))
        #expect(ws.reuse(url, title: "leela — b.docx") === w && w.title == "leela — b.docx")
        #expect(!ws.failed.contains(ObjectIdentifier(v)), "the second open loads the page again")
        #expect(ws.reuse(u("http://other.localhost:1/")) == nil)
    }

    @Test func aCancelledOrDownloadedNavigationKeepsThePage() {
        let ws = Windows(); ws.port = 5
        let (w, v) = ws.make(u("http://a.localhost:5/"), title: "t")
        defer { w.close() }
        let at = [NSURLErrorFailingURLErrorKey: u("http://a.localhost:5/")]
        ws.gone(v, NSError(domain: NSURLErrorDomain, code: NSURLErrorCancelled, userInfo: at))
        ws.gone(v, NSError(domain: "WebKitErrorDomain", code: 102, userInfo: at))
        ws.gone(v, NSError(domain: NSURLErrorDomain, code: NSURLErrorCannotConnectToHost, userInfo: [NSURLErrorFailingURLErrorKey: u("https://example.com/")]))
        #expect(ws.failed.isEmpty)
        ws.gone(v, NSError(domain: NSURLErrorDomain, code: NSURLErrorCannotConnectToHost, userInfo: at))
        #expect(ws.failed.contains(ObjectIdentifier(v)))
    }

    @Test func textSubstitutionKeysAreTheOldAppsList() {
        #expect(Windows.noSubstitution.count == 7 && Windows.noSubstitution.contains("NSAutomaticQuoteSubstitutionEnabled"))
    }
}
