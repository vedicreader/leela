import Foundation

/// The folders and files the app keeps outside its bundle. See docs/thin-app.md.
public struct Paths: Sendable, Equatable {
    /// ~/Library/Application Support/Leela
    public let support: URL
    /// ~/Library/Caches/Leela
    public let caches: URL

    public init(support: URL, caches: URL) {
        self.support = support
        self.caches = caches
    }

    public static var user: Paths {
        let fm = FileManager.default
        return Paths(support: fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appending(path: "Leela"),
                     caches: fm.urls(for: .cachesDirectory, in: .userDomainMask)[0].appending(path: "Leela"))
    }

    public var locks: URL { support.appending(path: "locks") }
    public func lock(_ n: Int) -> URL { locks.appending(path: String(n)) }
    public var envs: URL { support.appending(path: "envs") }
    /// one env per lock hash; the folder name is the first 16 hex characters
    public func env(_ hash: String) -> URL { envs.appending(path: String(hash.prefix(16))) }
    public func marker(_ hash: String) -> URL { env(hash).appending(path: ".leela-env.json") }
    public var python: URL { support.appending(path: "python") }
    public var state: URL { support.appending(path: "state.json") }
    public var logs: URL { support.appending(path: "logs") }
    public func syncLog(_ hash: String) -> URL { logs.appending(path: "sync-\(hash.prefix(16)).log") }
    public var serverLog: URL { logs.appending(path: "server.log") }
    public var runLock: URL { support.appending(path: "run.lock") }
    public var uvCache: URL { caches.appending(path: "uv") }
    public func server(_ hash: String) -> URL { env(hash).appending(path: "bin/leela") }
}
