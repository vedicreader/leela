import AppKit
import Foundation
import Testing
import WebKit
@testable import Leela

/// The server's menu bar as `make test` wrote it from the Python source, with the default keymap: `LEELA_MENU_JSON`.
func menuJSON() throws -> [[String: Any]] {
    let p = try #require(ProcessInfo.processInfo.environment["LEELA_MENU_JSON"], "run through make test, which writes the server's menu.json")
    let d = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: p))) as? [String: Any])
    return try #require(d["menus"] as? [[String: Any]])
}

/// The target a selector row is moved to in a test, so AppKit's dispatch can be seen without a window or the app acting.
final class Probe: NSObject {
    var got = [String]()
    @objc func cut(_ s: Any?) { got.append("cut:") }
    @objc func copy(_ s: Any?) { got.append("copy:") }
    @objc func paste(_ s: Any?) { got.append("paste:") }
    @objc func selectAll(_ s: Any?) { got.append("selectAll:") }
    @objc func undo(_ s: Any?) { got.append("undo:") }
    @objc func redo(_ s: Any?) { got.append("redo:") }
    @objc func toggleFullScreen(_ s: Any?) { got.append("toggleFullScreen:") }
    @objc func performMiniaturize(_ s: Any?) { got.append("performMiniaturize:") }
    @objc func performZoom(_ s: Any?) { got.append("performZoom:") }
    @objc func performClose(_ s: Any?) { got.append("performClose:") }
    @objc func arrangeInFront(_ s: Any?) { got.append("arrangeInFront:") }
    @objc func hide(_ s: Any?) { got.append("hide:") }
    @objc func hideOtherApplications(_ s: Any?) { got.append("hideOtherApplications:") }
    @objc func unhideAllApplications(_ s: Any?) { got.append("unhideAllApplications:") }
    @objc func terminate(_ s: Any?) { got.append("terminate:") }
    @objc func orderFrontStandardAboutPanel(_ s: Any?) { got.append("orderFrontStandardAboutPanel:") }
}

/// the US keyboard's key codes (Carbon kVK_*), so the event is the one the keyboard sends
let usKeys: [String: UInt16] = ["a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14,
    "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29, "]": 30,
    "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "\r": 36, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46,
    ".": 47, "\t": 48, " ": 49, "`": 50, "\u{1b}": 53, "\u{F702}": 123, "\u{F703}": 124, "\u{F701}": 125, "\u{F700}": 126]
/// A key-down as the US keyboard gives it: its key code, shift applied to the character, an arrow with the function flag.
func keyDown(_ key: String, _ mask: NSEvent.ModifierFlags) -> NSEvent {
    var flags = mask
    if let u = key.unicodeScalars.first?.value, (0xF700...0xF8FF).contains(u) { flags.formUnion([.function, .numericPad]) }
    let chars = mask.contains(.shift) ? Menus.usShift[key] ?? key.uppercased() : key
    return NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: flags, timestamp: 0, windowNumber: 0, context: nil,
                            characters: chars, charactersIgnoringModifiers: chars, isARepeat: false, keyCode: usKeys[key] ?? 0)!
}

/// every row with a key, in menu order, with the item AppKit built for it
@MainActor func keyed(_ bar: NSMenu) -> [NSMenuItem] {
    bar.items.compactMap(\.submenu).flatMap(\.items).filter { !$0.keyEquivalent.isEmpty }
}

func chord(_ i: NSMenuItem) -> String { "\(i.keyEquivalent)|\(i.keyEquivalentModifierMask.intersection(.deviceIndependentFlagsMask).rawValue)" }

@MainActor @Suite(.serialized) struct ShortcutTests {
    /// each row of menu.json with a chord: its menu, title, key and mask, in menu order
    func chords(_ menus: [[String: Any]]) -> [(menu: String, title: String, key: String, mask: NSEvent.ModifierFlags, what: String)] {
        menus.flatMap { m in (m["items"] as? [[String: Any]] ?? []).compactMap { r in
            guard let k = r["key"] as? String, let mask = r["mask"] as? Int else { return nil }
            let what = (r["action"] as? String).map(Menus.js(action:)) ?? r["selector"] as? String ?? r["js"] as? String ?? ""
            return (m["title"] as! String == "__app__" ? "Leela" : m["title"] as! String, r["title"] as! String, k, NSEvent.ModifierFlags(rawValue: UInt(mask)), what)
        } }
    }

    @Test func everyRowWithAKeyIsBuiltWithThatChord() throws {
        let menus = try menuJSON(), bar = Menus.build(menus, runner: MenuRunner { _ in })
        let built = Dictionary(bar.items.compactMap(\.submenu).flatMap { m in m.items.map { ("\(m.title)/\($0.title)", $0) } }, uniquingKeysWith: { a, _ in a })
        let rows = chords(menus)
        for r in rows {
            let it = try #require(built["\(r.menu)/\(r.title)"], "no item for \(r.menu)/\(r.title)")
            let (k, m) = Menus.appKit(r.key, r.mask)
            #expect(it.keyEquivalent == k && it.keyEquivalentModifierMask == m, "\(r.menu)/\(r.title)")
        }
        #expect(rows.count > 50)
    }

    @Test func eachChordFromTheKeyboardReachesItsRowAndRunsTheRowsJavaScript() throws {
        let menus = try menuJSON()
        var ran = [String]()
        let runner = MenuRunner { ran.append($0) }, bar = Menus.build(menus, runner: runner), probe = Probe()
        for i in keyed(bar) where i.target !== runner { i.target = probe }
        // the launcher's own rows, and every row of the server's bar; the first in menu order with a chord is the one AppKit picks
        let own: [(String, String, NSEvent.ModifierFlags, String)] = [("Undo", "z", .command, "undo:"), ("Redo", "z", [.command, .shift], "redo:"),
            ("Close Window", "w", .command, "performClose:"), ("Quit", "q", .command, "terminate:"), ("Hide", "h", .command, "hide:"),
            ("Hide Others", "h", [.command, .option], "hideOtherApplications:")]
        var seen = Set<String>()
        for (title, key, mask, what) in own + chords(menus).map({ ($0.title, $0.key, $0.mask, $0.what) }) where seen.insert("\(key)|\(mask.rawValue)").inserted {
            ran = []; probe.got = []
            #expect(bar.performKeyEquivalent(with: keyDown(key, mask)), "\(title) \(key) \(mask.rawValue) is not dispatched")
            #expect(ran + probe.got == [what], "\(title) \(key) \(mask.rawValue)")
        }
        #expect(seen.count > 50)
    }

    @Test func aChordWithoutShiftDoesNotFireItsShiftedRow() throws {
        // ⌥I is Live / isolated; with shift spelled as a flag on a lower case key it ran ⌥⇧I, Interrupt kernel
        var ran = [String]()
        let runner = MenuRunner { ran.append($0) }, bar = Menus.build(try menuJSON(), runner: runner)
        #expect(bar.performKeyEquivalent(with: keyDown("i", .option)))
        #expect(ran == [Menus.js(action: "toggle_scope")])
        #expect(Menus.appKit("o", [.command, .shift]) == ("O", .command) && Menus.appKit("/", [.command, .shift]) == ("?", .command))
        #expect(Menus.appKit("p", .command) == ("p", .command) && Menus.appKit("\u{F701}", [.command, .shift]) == ("\u{F701}", [.command, .shift]))
    }

    @Test func actionRowsRunLeeActWithTheActionName() throws {
        let menus = try menuJSON()
        var ran = [String]()
        let runner = MenuRunner { ran.append($0) }, bar = Menus.build(menus, runner: runner)
        #expect(bar.performKeyEquivalent(with: keyDown("p", .command)))
        #expect(ran == ["leeAct(\"quick_open\")"])
        #expect(Menus.js(action: "a\"b") == "leeAct(\"a\\\"b\")")
    }

    @Test func noTwoDifferentRowsShareAChord() throws {
        let bar = Menus.build(try menuJSON(), runner: MenuRunner { _ in })
        var seen = [String: String]()
        for i in keyed(bar) {
            let what = (i.representedObject as? String) ?? i.action.map(NSStringFromSelector) ?? i.title
            if let was = seen[chord(i)] { #expect(was == what, "\(chord(i)): \(was) and \(what)") } else { seen[chord(i)] = what }
        }
    }

    @Test func theLaunchersOwnRowsAreThere() throws {
        let bar = Menus.build(try menuJSON(), runner: MenuRunner { _ in })
        let all = bar.items.compactMap(\.submenu).flatMap(\.items)
        func has(_ sel: String, _ key: String, _ mask: NSEvent.ModifierFlags) -> Bool {
            all.contains { $0.action == Selector((sel)) && $0.keyEquivalent == key && $0.keyEquivalentModifierMask == mask && $0.target == nil }
        }
        #expect(has("terminate:", "q", .command) && has("hide:", "h", .command) && has("hideOtherApplications:", "h", [.command, .option]))
        #expect(has("performClose:", "w", .command) && has("undo:", "z", .command) && has("redo:", "Z", .command))
        #expect(all.contains { $0.action == #selector(NSApplication.unhideAllApplications(_:)) } && all.contains { $0.title == "Services" && $0.submenu != nil })
        #expect(has("performMiniaturize:", "m", .command) && has("toggleFullScreen:", "f", [.command, .control]))
    }

    @Test func undoIsAnEditingRowNeverAnAction() throws {
        // the page sees ⌘Z first (the notebook's own undo); a row that runs an action on it would run twice
        let bar = Menus.build(try menuJSON(), runner: MenuRunner { _ in })
        for i in keyed(bar) where i.keyEquivalent == "z" { #expect(i.target == nil, "\(i.title) takes ⌘Z") }
    }

    @Test func theFallbackBarHasTheEditingRowsBeforeTheServerAnswers() {
        let bar = Menus.build(Menus.fallback, runner: MenuRunner { _ in })
        let edit = bar.items.compactMap(\.submenu).first { $0.title == "Edit" }
        let sels = Set(edit?.items.compactMap { $0.action.map(NSStringFromSelector) } ?? [])
        #expect(sels.isSuperset(of: ["cut:", "copy:", "paste:", "selectAll:", "undo:", "redo:"]))
        #expect(bar.items[0].submenu?.items.contains { $0.action == #selector(NSApplication.terminate(_:)) } == true)
    }

    @Test func editingShortcutsGoToTheWebViewThroughTheResponderChain() throws {
        // a window never ordered on screen: the web view is its first responder; cut:, copy:, paste: sent to nil stop at it, and undo:
        // and redo: at the window, which uses the web view's undo manager. No row takes these keys for an action.
        let ws = Windows()
        let (w, v) = ws.make(URL(string: "http://127.0.0.1:1/")!, title: "t")
        #expect(!w.isVisible && w.firstResponder === v && w.initialFirstResponder === v)
        func first(_ s: Selector) -> NSResponder? { sequence(first: v as NSResponder, next: \.nextResponder).first { $0.responds(to: s) } }
        for s in ["cut:", "copy:", "paste:", "selectAll:"] { #expect(first(Selector((s))) === v, "\(s)") }
        for s in ["undo:", "redo:"] { #expect(first(Selector((s))) === w, "\(s)") }
        #expect(v.undoManager != nil)
        let bar = Menus.build(try menuJSON(), runner: MenuRunner { _ in })
        for i in keyed(bar) where ["x", "c", "v", "a", "z", "Z"].contains(i.keyEquivalent) && i.keyEquivalentModifierMask == .command {
            #expect(i.target == nil && first(i.action!) != nil, "\(i.title) does not reach the web view")
        }
        w.close()
    }
}
