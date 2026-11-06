import Foundation

/// The setup window's phases, in order.
public enum SetupPhase: Equatable, Sendable {
    case checking
    case python
    /// bytes so far of about `total`, and the last line uv wrote
    case packages(done: Int64, total: Int64, line: String)
    case verifying
    case starting

    public var title: String {
        switch self {
        case .checking: "Checking for the newest version"
        case .python: "Getting Python 3.12"
        case .packages(let d, let t, _): t > 0 ? "Getting packages (\(Setup.mb(d)) of about \(Setup.mb(t)))" : "Getting packages"
        case .verifying: "Checking the packages"
        case .starting: "Starting Leela"
        }
    }

    /// 0...1 for a determinate bar, nil for an indeterminate one
    public var fraction: Double? {
        if case .packages(let d, let t, _) = self, t > 0 { return min(1, Double(d) / Double(t)) }
        return nil
    }
}

public enum Setup {
    public static func mb(_ b: Int64) -> String { "\(max(0, b) / 1_000_000) MB" }

    /// the phase a uv output line moves to, or nil to stay
    public static func phase(after line: String, current: SetupPhase, done: Int64, total: Int64) -> SetupPhase? {
        let l = line.lowercased()
        if l.contains("cpython") && (l.contains("download") || l.contains("install")) { return .python }
        if l.hasPrefix("installed ") || l.contains("audited") { return .verifying }
        if l.contains("download") || l.contains("prepared") || l.contains("resolved") || l.contains("building") || l.contains("using cpython") {
            return .packages(done: done, total: total, line: line)
        }
        if case .packages = current { return .packages(done: done, total: total, line: line) }
        return nil
    }

    /// the bytes in a folder: the uv cache grows as packages download
    public static func bytes(_ url: URL) -> Int64 {
        guard let e = FileManager.default.enumerator(at: url, includingPropertiesForKeys: [.totalFileAllocatedSizeKey, .isRegularFileKey]) else { return 0 }
        var n: Int64 = 0
        for case let u as URL in e {
            let v = try? u.resourceValues(forKeys: [.totalFileAllocatedSizeKey, .isRegularFileKey])
            if v?.isRegularFile == true { n += Int64(v?.totalFileAllocatedSize ?? 0) }
        }
        return n
    }

    /// the short reason a failed setup shows, then the last log lines
    public static func failure(_ reason: String, log: URL) -> String { reason + "\n\n" + Run.tail(log) }

    public static let offline = "Leela needs the internet the first time, to get Python and its packages. It tries again when this Mac is online."
    public static let buildFailed = "Setup did not complete. Leela did not change anything that already works."
    public static let updateFailed = "The update did not install. Leela still runs the current version."
}
