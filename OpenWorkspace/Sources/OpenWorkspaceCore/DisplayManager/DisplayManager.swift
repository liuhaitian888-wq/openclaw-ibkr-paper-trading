import Foundation
import CoreGraphics

public protocol DisplayManaging: Sendable {
    func createVirtualDisplay() async throws -> VirtualDisplayHandle
    func destroyVirtualDisplay() async throws
    func refreshDisplays() async throws -> [ManagedDisplay]
    func listDisplays() async throws -> [ManagedDisplay]
    func isVirtualDisplayActive() async throws -> Bool
    func currentLayout() async throws -> [MonitorPlacement]
    func applyLayout(_ placements: [MonitorPlacement]) async throws
}

public protocol DisplayProviding: Sendable {
    func isAvailable() async -> Bool
    func createVirtualDisplay(named name: String, preferences: DisplayPreferences) async throws -> VirtualDisplayHandle
    func destroyVirtualDisplay(named name: String) async throws
    func isVirtualDisplayActive(named name: String) async throws -> Bool
}

public enum DisplayManagerError: Error, LocalizedError {
    case providerUnavailable(String)

    public var errorDescription: String? {
        switch self {
        case .providerUnavailable(let provider):
            "\(provider) is not available. Install and configure the provider, then retry."
        }
    }
}

public actor MacDisplayManager: DisplayManaging {
    public static let defaultVirtualDisplayName = "OpenWorkspace Virtual Display"

    private let provider: DisplayProviding
    private let logger: AppLogging
    private let virtualDisplayName: String
    private var cachedDisplays: [ManagedDisplay] = []

    public init(
        provider: DisplayProviding,
        logger: AppLogging,
        virtualDisplayName: String = MacDisplayManager.defaultVirtualDisplayName
    ) {
        self.provider = provider
        self.logger = logger
        self.virtualDisplayName = virtualDisplayName
    }

    public func createVirtualDisplay() async throws -> VirtualDisplayHandle {
        let handle = try await provider.createVirtualDisplay(
            named: virtualDisplayName,
            preferences: DisplayPreferences()
        )
        _ = try await refreshDisplays()
        return handle
    }

    public func destroyVirtualDisplay() async throws {
        try await provider.destroyVirtualDisplay(named: virtualDisplayName)
        _ = try await refreshDisplays()
    }

    public func refreshDisplays() async throws -> [ManagedDisplay] {
        let displays = try await readSystemDisplays()
        cachedDisplays = displays
        logger.info("Refreshed displays count=\(displays.count)")
        return displays
    }

    public func listDisplays() async throws -> [ManagedDisplay] {
        if !cachedDisplays.isEmpty {
            return cachedDisplays
        }
        return try await refreshDisplays()
    }

    public func isVirtualDisplayActive() async throws -> Bool {
        try await provider.isVirtualDisplayActive(named: virtualDisplayName)
    }

    public func currentLayout() async throws -> [MonitorPlacement] {
        logger.info("Reading current display layout")
        return []
    }

    public func applyLayout(_ placements: [MonitorPlacement]) async throws {
        logger.info("Applying display layout count=\(placements.count)")
    }

    private func readSystemDisplays() async throws -> [ManagedDisplay] {
        var displayCount: UInt32 = 0
        CGGetActiveDisplayList(0, nil, &displayCount)

        var displayIDs = [CGDirectDisplayID](repeating: 0, count: Int(displayCount))
        CGGetActiveDisplayList(displayCount, &displayIDs, &displayCount)

        let virtualDisplayActive = try await provider.isVirtualDisplayActive(named: virtualDisplayName)

        return displayIDs.enumerated().map { index, displayID in
            let width = Int(CGDisplayPixelsWide(displayID))
            let height = Int(CGDisplayPixelsHigh(displayID))
            let displayNumber = index + 1
            return ManagedDisplay(
                id: "display-\(displayNumber)",
                name: "Display \(displayNumber)",
                resolution: Resolution(width: width, height: height),
                isVirtual: virtualDisplayActive && displayNumber == displayIDs.count,
                isActive: true,
                source: .system
            )
        }
    }
}

public struct BetterDisplayProvider: DisplayProviding {
    private let processRunner: ProcessRunning
    private let locator: ExecutableLocator
    private let logger: AppLogging

    public init(
        processRunner: ProcessRunning,
        locator: ExecutableLocator = ExecutableLocator(),
        logger: AppLogging
    ) {
        self.processRunner = processRunner
        self.locator = locator
        self.logger = logger
    }

    public func isAvailable() async -> Bool {
        betterDisplayCLIURL() != nil
    }

    public func createVirtualDisplay(named name: String, preferences: DisplayPreferences) async throws -> VirtualDisplayHandle {
        guard let cliURL = betterDisplayCLIURL() else {
            throw DisplayManagerError.providerUnavailable("BetterDisplay CLI")
        }

        try await processRunner.run(
            cliURL,
            arguments: BetterDisplayCommandBuilder.createVirtualScreenArguments(
                name: name,
                preferences: preferences
            )
        )
        try await processRunner.run(
            cliURL,
            arguments: BetterDisplayCommandBuilder.connectVirtualScreenArguments(name: name)
        )

        logger.info("Created virtual display name=\(name)")
        return VirtualDisplayHandle(name: name, preferences: preferences)
    }

    public func destroyVirtualDisplay(named name: String) async throws {
        guard let cliURL = betterDisplayCLIURL() else {
            throw DisplayManagerError.providerUnavailable("BetterDisplay CLI")
        }

        try await processRunner.run(
            cliURL,
            arguments: BetterDisplayCommandBuilder.discardVirtualScreenArguments(name: name)
        )
        logger.info("Destroyed virtual display name=\(name)")
    }

    public func isVirtualDisplayActive(named name: String) async throws -> Bool {
        guard let cliURL = betterDisplayCLIURL() else {
            return false
        }

        let result = try await processRunner.capture(
            cliURL,
            arguments: BetterDisplayCommandBuilder.getVirtualScreenConnectedArguments(name: name)
        )
        return result.exitCode == 0 && result.standardOutput.localizedCaseInsensitiveContains("on")
    }

    private func betterDisplayCLIURL() -> URL? {
        locator.firstExecutable(
            named: ["betterdisplaycli", "BetterDisplayCLI"],
            additionalDirectories: [
                "/Applications/BetterDisplay.app/Contents/MacOS"
            ]
        )
    }
}

public enum BetterDisplayCommandBuilder {
    public static func createVirtualScreenArguments(
        name: String,
        preferences: DisplayPreferences
    ) -> [String] {
        let aspectRatio = reducedAspectRatio(preferences.resolution)
        return [
            "create",
            "-devicetype=virtualscreen",
            "-virtualscreenname=\(name)",
            "-aspectWidth=\(aspectRatio.width)",
            "-aspectHeight=\(aspectRatio.height)",
            "-useResolutionList=on",
            "-resolutionList=\(preferences.resolution.width)x\(preferences.resolution.height)"
        ]
    }

    public static func connectVirtualScreenArguments(name: String) -> [String] {
        [
            "set",
            "-namelike=\(name)",
            "-connected=on"
        ]
    }

    public static func discardVirtualScreenArguments(name: String) -> [String] {
        [
            "discard",
            "-namelike=\(name)"
        ]
    }

    public static func getVirtualScreenConnectedArguments(name: String) -> [String] {
        [
            "get",
            "-namelike=\(name)",
            "-connected"
        ]
    }

    private static func reducedAspectRatio(_ resolution: Resolution) -> Resolution {
        let divisor = greatestCommonDivisor(resolution.width, resolution.height)
        return Resolution(
            width: resolution.width / divisor,
            height: resolution.height / divisor
        )
    }

    private static func greatestCommonDivisor(_ lhs: Int, _ rhs: Int) -> Int {
        var a = abs(lhs)
        var b = abs(rhs)
        while b != 0 {
            let remainder = a % b
            a = b
            b = remainder
        }
        return max(a, 1)
    }
}

public struct UnavailableDisplayProvider: DisplayProviding {
    public init() {}

    public func isAvailable() async -> Bool {
        false
    }

    public func createVirtualDisplay(named name: String, preferences: DisplayPreferences) async throws -> VirtualDisplayHandle {
        throw DisplayManagerError.providerUnavailable("Virtual display provider")
    }

    public func destroyVirtualDisplay(named name: String) async throws {
        throw DisplayManagerError.providerUnavailable("Virtual display provider")
    }

    public func isVirtualDisplayActive(named name: String) async throws -> Bool {
        false
    }
}
