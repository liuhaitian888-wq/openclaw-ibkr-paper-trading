import Foundation
import CoreGraphics

public protocol DisplayManaging: Sendable {
    func createVirtualDisplay() async throws -> VirtualDisplayHandle
    func destroyVirtualDisplay() async throws
    func refreshDisplays() async throws -> [ManagedDisplay]
    func listDisplays() async throws -> [ManagedDisplay]
    func isVirtualDisplayActive() async throws -> Bool
    func setVirtualDisplayResolution(_ resolution: Resolution) async throws
    func setVirtualDisplayScaling(_ scalingMode: DisplayScalingMode) async throws
    func setVirtualDisplayRotation(_ rotation: DisplayRotation) async throws
    func betterDisplayDiagnostics() async throws -> BetterDisplayDiagnostics
    func openBetterDisplaySettings() async throws
    func currentLayout() async throws -> [MonitorPlacement]
    func applyLayout(_ placements: [MonitorPlacement]) async throws
}

public protocol DisplayProviding: Sendable {
    func isAvailable() async -> Bool
    func createVirtualDisplay(named name: String, preferences: DisplayPreferences) async throws -> VirtualDisplayHandle
    func destroyVirtualDisplay(named name: String) async throws
    func isVirtualDisplayActive(named name: String) async throws -> Bool
    func setResolution(_ resolution: Resolution, forDisplayNamed name: String) async throws
    func setScaling(_ scalingMode: DisplayScalingMode, forDisplayNamed name: String) async throws
    func setRotation(_ rotation: DisplayRotation, forDisplayNamed name: String) async throws
    func diagnostics(forDisplayNamed name: String, currentDisplayCount: Int) async throws -> BetterDisplayDiagnostics
    func openSettings() async throws
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

    public func setVirtualDisplayResolution(_ resolution: Resolution) async throws {
        try await provider.setResolution(resolution, forDisplayNamed: virtualDisplayName)
        _ = try await refreshDisplays()
    }

    public func setVirtualDisplayScaling(_ scalingMode: DisplayScalingMode) async throws {
        try await provider.setScaling(scalingMode, forDisplayNamed: virtualDisplayName)
        _ = try await refreshDisplays()
    }

    public func setVirtualDisplayRotation(_ rotation: DisplayRotation) async throws {
        try await provider.setRotation(rotation, forDisplayNamed: virtualDisplayName)
        _ = try await refreshDisplays()
    }

    public func betterDisplayDiagnostics() async throws -> BetterDisplayDiagnostics {
        let displays = try await refreshDisplays()
        return try await provider.diagnostics(
            forDisplayNamed: virtualDisplayName,
            currentDisplayCount: displays.count
        )
    }

    public func openBetterDisplaySettings() async throws {
        try await provider.openSettings()
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

    public func setResolution(_ resolution: Resolution, forDisplayNamed name: String) async throws {
        guard let cliURL = betterDisplayCLIURL() else {
            throw DisplayManagerError.providerUnavailable("BetterDisplay CLI")
        }
        try await processRunner.run(
            cliURL,
            arguments: BetterDisplayCommandBuilder.setResolutionArguments(name: name, resolution: resolution)
        )
        logger.info("Set virtual display resolution name=\(name)")
    }

    public func setScaling(_ scalingMode: DisplayScalingMode, forDisplayNamed name: String) async throws {
        guard let cliURL = betterDisplayCLIURL() else {
            throw DisplayManagerError.providerUnavailable("BetterDisplay CLI")
        }
        try await processRunner.run(
            cliURL,
            arguments: BetterDisplayCommandBuilder.setScalingArguments(name: name, scalingMode: scalingMode)
        )
        logger.info("Set virtual display scaling name=\(name) mode=\(scalingMode.rawValue)")
    }

    public func setRotation(_ rotation: DisplayRotation, forDisplayNamed name: String) async throws {
        guard let cliURL = betterDisplayCLIURL() else {
            throw DisplayManagerError.providerUnavailable("BetterDisplay CLI")
        }
        try await processRunner.run(
            cliURL,
            arguments: BetterDisplayCommandBuilder.setRotationArguments(name: name, rotation: rotation)
        )
        logger.info("Set virtual display rotation name=\(name) rotation=\(rotation.rawValue)")
    }

    public func diagnostics(forDisplayNamed name: String, currentDisplayCount: Int) async throws -> BetterDisplayDiagnostics {
        let cliURL = betterDisplayCLIURL()
        let appURL = betterDisplayAppURL()
        let environment = BetterDisplayEnvironment(
            isInstalled: appURL != nil || cliURL != nil,
            isCLIAvailable: cliURL != nil,
            appURL: appURL,
            cliURL: cliURL,
            pathEntries: locator.pathEntries(),
            hasExecutablePermission: cliURL.map { FileManager.default.isExecutableFile(atPath: $0.path) } ?? false,
            isRequiredConfigurationLikelyEnabled: await canReachBetterDisplayCLI(cliURL),
            guidance: guidance(appURL: appURL, cliURL: cliURL)
        )
        let version = await detectVersion(cliURL: cliURL, appURL: appURL)
        let capabilities = await detectCapabilities(cliURL: cliURL)
        let connected = (try? await isVirtualDisplayActive(named: name)) ?? false
        let supportedResolutions = await supportedResolutions(cliURL: cliURL, name: name)

        return BetterDisplayDiagnostics(
            environment: environment,
            version: version,
            capabilities: capabilities,
            virtualDisplayConnected: connected,
            currentDisplayCount: currentDisplayCount,
            supportedResolutions: supportedResolutions
        )
    }

    public func openSettings() async throws {
        if let cliURL = betterDisplayCLIURL() {
            try await processRunner.run(cliURL, arguments: BetterDisplayCommandBuilder.openSettingsArguments())
            return
        }
        if let appURL = betterDisplayAppURL() {
            try await processRunner.run(URL(fileURLWithPath: "/usr/bin/open"), arguments: [appURL.path])
            return
        }
        throw DisplayManagerError.providerUnavailable("BetterDisplay")
    }

    private func betterDisplayCLIURL() -> URL? {
        locator.firstExecutable(
            named: ["betterdisplaycli", "BetterDisplayCLI", "BetterDisplay"],
            additionalDirectories: [
                "/Applications/BetterDisplay.app/Contents/MacOS"
            ]
        )
    }

    private func betterDisplayAppURL() -> URL? {
        locator.firstExistingApplication(named: ["BetterDisplay.app"])
    }

    private func canReachBetterDisplayCLI(_ cliURL: URL?) async -> Bool {
        guard let cliURL else { return false }
        let result = try? await processRunner.capture(cliURL, arguments: ["help"])
        return result?.exitCode == 0
    }

    private func detectVersion(cliURL: URL?, appURL: URL?) async -> String? {
        if let appURL {
            let plistURL = appURL.appendingPathComponent("Contents/Info.plist")
            if
                let data = try? Data(contentsOf: plistURL),
                let plist = try? PropertyListSerialization.propertyList(
                    from: data,
                    options: [],
                    format: nil
                ) as? [String: Any],
                let version = plist["CFBundleShortVersionString"] as? String
            {
                return version
            }
        }

        guard let cliURL else { return nil }
        for arguments in [["version"], ["--version"], ["help"]] {
            let result = try? await processRunner.capture(cliURL, arguments: arguments)
            guard result?.exitCode == 0 else { continue }
            let output = [result?.standardOutput, result?.standardError]
                .compactMap { $0 }
                .joined(separator: "\n")
                .split(separator: "\n")
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .first { !$0.isEmpty }
            if let output {
                return output
            }
        }
        return nil
    }

    private func detectCapabilities(cliURL: URL?) async -> [BetterDisplayCapability] {
        guard let cliURL else { return [] }
        let help = (try? await processRunner.capture(cliURL, arguments: ["help"]))?.standardOutput ?? ""
        let known: [BetterDisplayCapability] = [
            .createVirtualDisplay,
            .destroyVirtualDisplay,
            .connectVirtualDisplay,
            .displayResolution,
            .displayScaling,
            .displayRotation,
            .displayDiagnostics,
            .settingsWindow
        ]
        guard !help.isEmpty else { return known }

        var capabilities: [BetterDisplayCapability] = []
        if help.localizedCaseInsensitiveContains("create") { capabilities.append(.createVirtualDisplay) }
        if help.localizedCaseInsensitiveContains("discard") { capabilities.append(.destroyVirtualDisplay) }
        if help.localizedCaseInsensitiveContains("connected") { capabilities.append(.connectVirtualDisplay) }
        if help.localizedCaseInsensitiveContains("resolution") { capabilities.append(.displayResolution) }
        if help.localizedCaseInsensitiveContains("hidpi") { capabilities.append(.displayScaling) }
        if help.localizedCaseInsensitiveContains("rotation") { capabilities.append(.displayRotation) }
        if help.localizedCaseInsensitiveContains("displayModeList") || help.localizedCaseInsensitiveContains("displayInformation") {
            capabilities.append(.displayDiagnostics)
        }
        if help.localizedCaseInsensitiveContains("settingsWindow") { capabilities.append(.settingsWindow) }
        return capabilities.isEmpty ? known : capabilities
    }

    private func supportedResolutions(cliURL: URL?, name: String) async -> [Resolution] {
        guard let cliURL else { return [] }
        let result = try? await processRunner.capture(
            cliURL,
            arguments: BetterDisplayCommandBuilder.displayModeListArguments(name: name)
        )
        guard result?.exitCode == 0 else { return [] }
        return BetterDisplayCommandBuilder.parseResolutions(result?.standardOutput ?? "")
    }

    private func guidance(appURL: URL?, cliURL: URL?) -> [String] {
        var guidance: [String] = []
        if appURL == nil {
            guidance.append("Install BetterDisplay from https://betterdisplay.pro or Homebrew cask betterdisplay.")
        }
        if cliURL == nil {
            guidance.append("Install betterdisplaycli with: brew install waydabber/betterdisplay/betterdisplaycli")
            guidance.append("Enable BetterDisplay Settings > Application > Integration if CLI requests are disabled.")
        }
        return guidance
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

    public static func setResolutionArguments(name: String, resolution: Resolution) -> [String] {
        [
            "set",
            "-namelike=\(name)",
            "-resolution=\(resolution.width)x\(resolution.height)"
        ]
    }

    public static func setScalingArguments(name: String, scalingMode: DisplayScalingMode) -> [String] {
        [
            "set",
            "-namelike=\(name)",
            "-hiDPI=\(scalingMode == .hiDPI ? "on" : "off")"
        ]
    }

    public static func setRotationArguments(name: String, rotation: DisplayRotation) -> [String] {
        [
            "set",
            "-namelike=\(name)",
            "-rotation=\(rotation.rawValue)"
        ]
    }

    public static func displayModeListArguments(name: String) -> [String] {
        [
            "get",
            "-namelike=\(name)",
            "-displayModeList"
        ]
    }

    public static func openSettingsArguments() -> [String] {
        [
            "set",
            "-settingsWindow=on"
        ]
    }

    public static func parseResolutions(_ output: String) -> [Resolution] {
        let pattern = #"(?<!\d)(\d{3,5})\s*x\s*(\d{3,5})(?!\d)"#
        guard let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else {
            return []
        }

        let range = NSRange(output.startIndex..<output.endIndex, in: output)
        var seen = Set<String>()
        return regex.matches(in: output, range: range).compactMap { match in
            guard
                let widthRange = Range(match.range(at: 1), in: output),
                let heightRange = Range(match.range(at: 2), in: output),
                let width = Int(output[widthRange]),
                let height = Int(output[heightRange])
            else {
                return nil
            }
            let key = "\(width)x\(height)"
            guard seen.insert(key).inserted else { return nil }
            return Resolution(width: width, height: height)
        }
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

    public func setResolution(_ resolution: Resolution, forDisplayNamed name: String) async throws {
        throw DisplayManagerError.providerUnavailable("Virtual display provider")
    }

    public func setScaling(_ scalingMode: DisplayScalingMode, forDisplayNamed name: String) async throws {
        throw DisplayManagerError.providerUnavailable("Virtual display provider")
    }

    public func setRotation(_ rotation: DisplayRotation, forDisplayNamed name: String) async throws {
        throw DisplayManagerError.providerUnavailable("Virtual display provider")
    }

    public func diagnostics(forDisplayNamed name: String, currentDisplayCount: Int) async throws -> BetterDisplayDiagnostics {
        BetterDisplayDiagnostics(
            environment: BetterDisplayEnvironment(
                isInstalled: false,
                isCLIAvailable: false,
                appURL: nil,
                cliURL: nil,
                pathEntries: [],
                hasExecutablePermission: false,
                isRequiredConfigurationLikelyEnabled: false,
                guidance: ["Install and configure a virtual display provider."]
            ),
            version: nil,
            capabilities: [],
            virtualDisplayConnected: false,
            currentDisplayCount: currentDisplayCount,
            supportedResolutions: []
        )
    }

    public func openSettings() async throws {
        throw DisplayManagerError.providerUnavailable("Virtual display provider")
    }
}
