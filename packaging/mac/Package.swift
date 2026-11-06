// swift-tools-version: 6.0
import PackageDescription

let v5: [SwiftSetting] = [.swiftLanguageMode(.v5)]

let package = Package(
    name: "Leela",
    platforms: [.macOS(.v14)],
    targets: [
        // no AppKit: paths, child env, lock hash, SSHSIG, manifests, the env store, the channel, the supervisor, setup phases, the bridge
        // router and the control server. Written so abhyasa can share it later.
        .target(name: "LeelaCore", swiftSettings: v5),
        .executableTarget(name: "Leela", dependencies: ["LeelaCore"], swiftSettings: v5),
        .testTarget(name: "LeelaCoreTests", dependencies: ["LeelaCore"], exclude: ["Fixtures"], swiftSettings: v5),
    ]
)
