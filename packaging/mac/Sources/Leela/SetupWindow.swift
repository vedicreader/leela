import AppKit
import LeelaCore

/// The first-run and failure window: the phase, a progress bar, uv's last line; on failure the reason, Try Again, Show Log, Copy Details.
@MainActor
final class SetupWindow {
    let window: NSWindow
    let title = NSTextField(labelWithString: "Starting Leela")
    let detail = NSTextField(wrappingLabelWithString: "")
    let bar = NSProgressIndicator()
    let retry = NSButton(title: "Try Again", target: nil, action: nil)
    let log = NSButton(title: "Show Log", target: nil, action: nil)
    let copy = NSButton(title: "Copy Details", target: nil, action: nil)
    var onRetry: (() -> Void)?
    var logURL: URL?

    init() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 520, height: 220), styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "Leela"
        window.isReleasedWhenClosed = false
        title.font = .systemFont(ofSize: 17, weight: .semibold)
        detail.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        detail.textColor = .secondaryLabelColor
        detail.maximumNumberOfLines = 8
        bar.isIndeterminate = true
        bar.style = .bar
        for (b, s) in [(retry, #selector(tapRetry)), (log, #selector(tapLog)), (copy, #selector(tapCopy))] { b.target = self; b.action = s; b.bezelStyle = .rounded }
        let buttons = NSStackView(views: [retry, log, copy])
        let stack = NSStackView(views: [title, bar, detail, buttons])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12
        stack.edgeInsets = NSEdgeInsets(top: 24, left: 24, bottom: 24, right: 24)
        bar.widthAnchor.constraint(equalToConstant: 472).isActive = true
        detail.widthAnchor.constraint(equalToConstant: 472).isActive = true
        window.contentView = stack
        window.center()
    }

    func show(_ p: Phase) {
        let failed: Bool
        switch p {
        case .setup(let s):
            title.stringValue = s.title
            if let f = s.fraction { bar.isIndeterminate = false; bar.doubleValue = f * 100 } else { bar.isIndeterminate = true; bar.startAnimation(nil) }
            switch s { case .packages(_, _, let line), .installing(_, let line): detail.stringValue = line; default: detail.stringValue = "" }
            failed = false
        case .starting, .idle: title.stringValue = "Starting Leela"; detail.stringValue = ""; bar.isIndeterminate = true; bar.startAnimation(nil); failed = false
        case .offline: title.stringValue = "Leela needs the internet"; detail.stringValue = Setup.offline; failed = true
        case .failed(let why):
            let parts = why.components(separatedBy: "\n\n")
            title.stringValue = parts.first ?? "Leela did not start"
            detail.stringValue = parts.dropFirst().joined(separator: "\n\n")
            failed = true
        case .ready: window.orderOut(nil); return
        }
        bar.isHidden = failed
        for b in [retry, log, copy] { b.isHidden = !failed }
        if !window.isVisible { window.makeKeyAndOrderFront(nil) }
    }

    @objc func tapRetry() { onRetry?() }
    @objc func tapLog() { if let u = logURL { NSWorkspace.shared.open(u) } }
    @objc func tapCopy() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(title.stringValue + "\n\n" + detail.stringValue, forType: .string)
    }
}
