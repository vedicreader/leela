import Darwin
import Foundation

/// One command to run.
public struct Launch: Sendable {
    public var executable: URL
    public var args: [String]
    public var env: [String: String]
    public var cwd: URL?

    public init(executable: URL, args: [String], env: [String: String], cwd: URL? = nil) {
        self.executable = executable; self.args = args; self.env = env; self.cwd = cwd
    }

    /// the same command at background priority (`taskpolicy -b`), for an update that builds while Leela runs
    public var background: Launch {
        Launch(executable: URL(fileURLWithPath: "/usr/sbin/taskpolicy"), args: ["-b", executable.path] + args, env: env, cwd: cwd)
    }
}

/// `Process` is not Sendable; the health wait reads only `isRunning`, which is safe from any thread.
public final class Running: @unchecked Sendable {
    public let p: Process
    init(_ p: Process) { self.p = p }
    public var isRunning: Bool { p.isRunning }
    public var pid: Int32 { p.processIdentifier }

    /// SIGTERM, then SIGKILL after `grace` seconds
    public func stop(grace: Double = 3) {
        if p.isRunning { p.terminate() }
        let end = Date().addingTimeInterval(grace)
        while p.isRunning && Date() < end { usleep(20_000) }
        if p.isRunning { kill(p.processIdentifier, SIGKILL) }
    }
}

public enum Run {
    public static func openLog(_ url: URL, append: Bool = false) throws -> FileHandle {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !append || !FileManager.default.fileExists(atPath: url.path) { FileManager.default.createFile(atPath: url.path, contents: nil) }
        let h = try FileHandle(forWritingTo: url)
        if append { h.seekToEndOfFile() }
        return h
    }

    static func process(_ l: Launch) -> Process {
        let p = Process()
        p.executableURL = l.executable
        p.arguments = l.args
        p.environment = l.env
        // a writable working folder: a GUI app starts in /, which is read only
        p.currentDirectoryURL = l.cwd ?? FileManager.default.temporaryDirectory
        p.standardInput = FileHandle.nullDevice
        return p
    }

    /// runs `l` to the end, its output into `log`; `line` gets each last line as it comes, and `started` the running process
    public static func toEnd(_ l: Launch, log: URL, line: (@Sendable (String) -> Void)? = nil,
                             started: (@Sendable (Running) -> Void)? = nil) async throws -> Int32 {
        let h = try openLog(log)
        let pipe = Pipe(), p = process(l)
        p.standardOutput = pipe
        p.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { f in
            let d = f.availableData
            guard !d.isEmpty else { return }
            h.write(d)
            if let last = String(decoding: d, as: UTF8.self).split(whereSeparator: \.isNewline).last { line?(String(last)) }
        }
        return try await withCheckedThrowingContinuation { c in
            p.terminationHandler = { p in
                pipe.fileHandleForReading.readabilityHandler = nil
                if let rest = try? pipe.fileHandleForReading.readToEnd(), !rest.isEmpty { h.write(rest) }
                try? h.close()
                c.resume(returning: p.terminationStatus)
            }
            do { try p.run(); started?(Running(p)) } catch { c.resume(throwing: error) }
        }
    }

    /// starts `l` with its output appended to `log`; `exited` gets the exit code
    public static func start(_ l: Launch, log: URL, exited: @escaping @Sendable (Int32) -> Void) throws -> Running {
        let h = try openLog(log, append: true)
        let p = process(l)
        p.standardOutput = h
        p.standardError = h
        p.terminationHandler = { p in try? h.close(); exited(p.terminationStatus) }
        try p.run()
        return Running(p)
    }

    /// the last lines of a log, for a failure message
    public static func tail(_ url: URL, lines: Int = 6) -> String {
        guard let d = try? Data(contentsOf: url) else { return "" }
        return String(decoding: d.suffix(8192), as: UTF8.self).split(whereSeparator: \.isNewline).suffix(lines).joined(separator: "\n")
    }

    /// the first line a command prints, or nil
    public static func output(_ exe: URL, _ args: [String]) -> String? {
        let p = Process(), pipe = Pipe()
        p.executableURL = exe; p.arguments = args; p.standardOutput = pipe; p.standardError = FileHandle.nullDevice
        guard (try? p.run()) != nil else { return nil }
        let d = pipe.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        return String(decoding: d, as: UTF8.self).split(whereSeparator: \.isNewline).first.map(String.init)
    }
}

public enum PortError: Error { case socket, bind, name }

/// A free TCP port on the loopback address.
public enum Port {
    public static let host = "127.0.0.1"

    public static func free() throws -> Int {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        guard fd >= 0 else { throw PortError.socket }
        defer { close(fd) }
        var addr = sockaddr_in()
        addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = 0
        addr.sin_addr.s_addr = inet_addr(host)
        let size = socklen_t(MemoryLayout<sockaddr_in>.size)
        let ok = withUnsafeMutablePointer(to: &addr) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(fd, $0, size) } }
        guard ok == 0 else { throw PortError.bind }
        var len = size
        let got = withUnsafeMutablePointer(to: &addr) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(fd, $0, &len) } }
        guard got == 0 else { throw PortError.name }
        return Int(UInt16(bigEndian: addr.sin_port))
    }

    public static func base(_ port: Int) -> URL { URL(string: "http://\(host):\(port)/")! }
}

public enum HealthError: Error, Equatable { case timedOut, exited }

/// Calls to the server on loopback, never through a proxy.
public enum Health {
    public static let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.connectionProxyDictionary = [:]
        c.timeoutIntervalForRequest = 2
        return URLSession(configuration: c)
    }()

    public static func json(_ url: URL) async -> [String: Any]? {
        guard let (d, r) = try? await session.data(from: url), (r as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return try? JSONSerialization.jsonObject(with: d) as? [String: Any]
    }

    public static func check(_ base: URL) async -> Bool { await json(base.appending(path: "health"))?["status"] as? String == "ok" }

    /// waits until `/health` is ok; stops early when `alive` gives false, because the server stopped
    public static func wait(_ base: URL, timeout: Duration, every: Duration = .milliseconds(200),
                            alive: @escaping @Sendable () -> Bool = { true }) async throws {
        let clock = ContinuousClock(), end = clock.now + timeout
        while clock.now < end {
            if await check(base) { return }
            guard alive() else { throw HealthError.exited }
            try await Task.sleep(for: every)
        }
        throw HealthError.timedOut
    }
}
