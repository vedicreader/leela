import AppKit
import LeelaCore

// `Leela --lock-test <lock folder> <work folder>`: build the env as the app does, with the bundled uv and childenv.json, and print it. No window.
let args = CommandLine.arguments
if let i = args.firstIndex(of: "--lock-test"), i + 2 < args.count {
    let res = Bundle.main.resourceURL!, uv = Bundle.main.bundleURL.appending(path: "Contents/Helpers/uv")
    let work = URL(fileURLWithPath: args[i + 2])
    let sem = DispatchSemaphore(value: 0)
    var code: Int32 = 1
    Task.detached {
        do {
            let spec = try ChildEnv.load(res.appending(path: "childenv.json"))
            let v = Run.output(uv, ["--version"])?.split(separator: " ").dropFirst().first.map(String.init) ?? ""
            let store = EnvStore(paths: Paths(support: work.appending(path: "support"), caches: work.appending(path: "caches")), spec: spec, uv: uv, uvVersion: v)
            let h = try await store.build(lock: URL(fileURLWithPath: args[i + 1]), n: 0, extras: [])
            print(store.paths.env(h).path); code = 0
        } catch { FileHandle.standardError.write(Data("lock test: \(error)\n".utf8)) }
        sem.signal()
    }
    sem.wait()
    exit(code)
}

MainActor.assumeIsolated {
    let app = NSApplication.shared
    let delegate = AppDelegate()
    app.delegate = delegate
    app.setActivationPolicy(.regular)
    app.run()
}
