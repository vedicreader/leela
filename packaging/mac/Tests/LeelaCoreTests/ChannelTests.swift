import Foundation
import Testing
@testable import LeelaCore

@Suite(.serialized) struct ChannelTests {
    func setup() throws -> (FakeHTTP, EnvStore, URL) {
        let http = FakeHTTP(); try http.start()
        let bundled = tempDir(); makeLock(bundled, n: 1, body: "bundled")
        return (http, store(), bundled)
    }

    func choose(_ http: FakeHTTP?, _ s: EnvStore, _ bundled: URL, test: Bool = false) async -> (plan: LockPlan?, error: String?) {
        let ch = http.map { Channel(base: $0.base, test: test, keys: fixtureKeys, app: facts) }
        return await LockChoice.choose(bundled: bundled, channel: ch, keys: fixtureKeys, app: facts, store: s)
    }

    @Test func aNewerChannelLockWinsAndIsKeptInLocks() async throws {
        let (http, s, bundled) = try setup(); defer { http.stop() }
        let d = tempDir(); makeLock(d, n: 2, body: "channel")
        publish(http, lock: d, n: 2)
        let (p, why) = await choose(http, s, bundled)
        #expect(why == nil && p?.n == 2 && p?.online == true)
        #expect(p?.dir == s.paths.lock(2) && FileManager.default.fileExists(atPath: s.paths.lock(2).appending(path: "uv.lock").path))
        #expect(http.hits.contains("/lock-2/python-version"))
    }

    @Test func offlineTakesTheBundledLock() async throws {
        let (http, s, bundled) = try setup()
        http.stop()
        let (p, why) = await choose(http, s, bundled)
        #expect(p?.n == 1 && p?.online == false && why != nil)
    }

    @Test func noPointerPublishedTakesTheBundledLockOnline() async throws {
        let (http, s, bundled) = try setup(); defer { http.stop() }
        let (p, _) = await choose(http, s, bundled)
        #expect(p?.n == 1 && p?.online == true)
    }

    @Test func theBundledLockWinsWhenItIsNewer() async throws {
        let (http, s, _) = try setup(); defer { http.stop() }
        let bundled = tempDir(); makeLock(bundled, n: 5, body: "bundled")
        let d = tempDir(); makeLock(d, n: 2, body: "channel")
        publish(http, lock: d, n: 2)
        #expect(await choose(http, s, bundled).plan?.n == 5)
    }

    @Test func theTestChannelIsAnotherPointer() async throws {
        let (http, s, bundled) = try setup(); defer { http.stop() }
        let d = tempDir(); makeLock(d, n: 3, body: "test")
        publish(http, lock: d, n: 3, name: "channel-test")
        #expect(await choose(http, s, bundled).plan?.n == 1, "the stable channel has no pointer")
        #expect(await choose(http, s, bundled, test: true).plan?.n == 3)
        #expect(Channel.isTest(["LEELA_LOCK_CHANNEL": "test"]) && !Channel.isTest([:]))
    }

    @Test func aPointerWithABadSignatureOrAMismatchedManifestFallsBack() async throws {
        let (http, s, bundled) = try setup(); defer { http.stop() }
        let d = tempDir(); makeLock(d, n: 2, body: "channel")
        publish(http, lock: d, n: 2)
        http.routes["/lock-channel/channel.sig"] = (200, try Data(contentsOf: fixtures.appending(path: "stranger.sig")))
        var (p, why) = await choose(http, s, bundled)
        #expect(p?.n == 1 && why?.contains("signature") == true)
        publish(http, lock: d, n: 2)
        http.routes["/lock-2/manifest.json"] = (200, Data("{}".utf8))
        (p, why) = await choose(http, s, bundled)
        #expect(p?.n == 1 && why != nil)
    }

    @Test func aTestPointerServedAsStableIsRefusedAndAnOldExpiresFieldIsIgnored() async throws {
        let (http, s, bundled) = try setup(); defer { http.stop() }
        let d = tempDir(); makeLock(d, n: 2, body: "channel")
        publish(http, lock: d, n: 2, name: "channel", pointerName: "channel-test")
        var (p, why) = await choose(http, s, bundled)
        #expect(p?.n == 1 && why?.contains("channel-test") == true)
        publish(http, lock: d, n: 2, extra: "\"expires\":\"2020-01-01T00:00:00Z\"")
        (p, why) = await choose(http, s, bundled)
        #expect(p?.n == 2 && why == nil, "a lock with no change for months is still good")
    }

    @Test func aLockBelowTheHighestIsRefusedEvenWithNoEnv() async throws {
        let (http, s, bundled) = try setup(); defer { http.stop() }
        let d = tempDir(); makeLock(d, n: 2, body: "channel")
        publish(http, lock: d, n: 2)
        _ = try s.update { $0.highest_n = 5 }
        #expect(await choose(http, s, bundled).plan?.n != 2, "a lost env does not reopen replays")
    }

    @Test func aLockAtOrBelowTheHighestIsNotFetchedAgain() async throws {
        let (http, s, bundled) = try setup(); defer { http.stop() }
        let d = tempDir(); makeLock(d, n: 2, body: "channel")
        publish(http, lock: d, n: 2)
        _ = try s.update { $0.highest_n = 2; $0.current = "x" }
        _ = await choose(http, s, bundled)
        #expect(!http.hits.contains("/lock-2/manifest.json"))
    }
}
