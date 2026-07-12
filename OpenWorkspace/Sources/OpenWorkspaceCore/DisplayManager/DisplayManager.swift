import Foundation
import CoreGraphics

public protocol DisplayManaging: Sendable {
    func createVirtualDisplay() async throws -> VirtualDisplayHandle
    func destroyVirtualDisplay() async throws
    func listDisplays() async throws -> [ManagedDisplay]
    func isVirtualDisplayActive() async throws -> Bool
    func currentLayout() async throws -> [MonitorPlacement]
    func applyLayout(_ placements: [MonitorPlacement]) async throws
}

public protocol DisplayProviding: Sendable {
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

public struct MacDisplayManager: DisplayManaging {
    public static let defaultVirtualDisplayName = "OpenWorkspace Virtual Display"

    private let provider: DisplayProviding
    private let logger: AppLogging
    private let virtualDisplayName: String

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
        try await provider.createVirtualDisplay(
            named: virtualDisplayName,
            preferences: DisplayPreferences()
        )
    }

    public func destroyVirtualDisplay() async throws {
        try await provider.destroyVirtualDisplay(named: virtualDisplayName)
    }

    public func listDisplays() async throws -> [ManagedDisplay] {
        var displayCount: UInt32 = 0
        CGGetActiveDisplayList(0, nil, &displayCount)

        var displayIDs = [CGDirectDisplayID](repeating: 0, count: Int(displayCount))
        CGGetActiveDisplayList(displayCount, &displayIDs, &displayCount)

        return displayIDs.map { displayID in
            let width = Int(CGDisplayPixelsWide(displayID))
            let height = Int(CGDisplayPixelsHigh(displayID))
            let name = "Display \(displayID)"
            return ManagedDisplay(
                id: String(displayID),
                name: name,
                resolution: Resolution(width: width, height: height),
                isVirtual: false,
                isActive: true,
                source: .system
            )
        }
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

    public func createVirtualDisplay(named name: String, preferences: DisplayPreferences) async throws -> VirtualDisplayHandle {
        guard let cliURL = betterDisplayCLIURL() else {
            throw DisplayManagerError.providerUnavailable("BetterDisplay CLI")
        }

        try await processRunner.run(cliURL, arguments: [
            "create",
            "-devicetype=virtualscreen",
            "-virtualscreenname=\(name)",
            "-aspectWidth=\(preferences.resolution.width)",
            "-aspectHeight=\(preferences.resolution.height)"
        ])
        try await processRunner.run(cliURL, arguments: [
            "set",
            "-namelike=\(name)",
            "-connected=on"
        ])

        logger.info("Created virtual display name=\(name)")
        return VirtualDisplayHandle(name: name, preferences: preferences)
    }

    public func destroyVirtualDisplay(named name: String) async throws {
        guard let cliURL = betterDisplayCLIURL() else {
            throw DisplayManagerError.providerUnavailable("BetterDisplay CLI")
        }

        try await processRunner.run(cliURL, arguments: [
            "discard",
            "-namelike=\(name)"
        ])
        logger.info("Destroyed virtual display name=\(name)")
    }

    public func isVirtualDisplayActive(named name: String) async throws -> Bool {
        guard let cliURL = betterDisplayCLIURL() else {
            return false
        }

        let result = try await processRunner.capture(cliURL, arguments: [
            "get",
            "-namelike=\(name)",
            "-connected"
        ])
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

public struct UnavailableDisplayProvider: DisplayProviding {
    public init() {}

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
