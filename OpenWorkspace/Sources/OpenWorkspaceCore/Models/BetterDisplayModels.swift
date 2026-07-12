import Foundation

public enum DisplayRotation: Int, Codable, CaseIterable, Sendable {
    case degrees0 = 0
    case degrees90 = 90
    case degrees180 = 180
    case degrees270 = 270

    public var label: String {
        "\(rawValue) degrees"
    }
}

public enum DisplayScalingMode: String, Codable, CaseIterable, Sendable {
    case standard
    case hiDPI

    public var label: String {
        switch self {
        case .standard:
            "Standard"
        case .hiDPI:
            "HiDPI"
        }
    }
}

public enum BetterDisplayCapability: String, Codable, CaseIterable, Sendable {
    case createVirtualDisplay
    case destroyVirtualDisplay
    case connectVirtualDisplay
    case displayResolution
    case displayScaling
    case displayRotation
    case displayDiagnostics
    case settingsWindow
}

public struct BetterDisplayEnvironment: Equatable, Sendable {
    public var isInstalled: Bool
    public var isCLIAvailable: Bool
    public var appURL: URL?
    public var cliURL: URL?
    public var pathEntries: [String]
    public var hasExecutablePermission: Bool
    public var isRequiredConfigurationLikelyEnabled: Bool
    public var guidance: [String]

    public init(
        isInstalled: Bool,
        isCLIAvailable: Bool,
        appURL: URL?,
        cliURL: URL?,
        pathEntries: [String],
        hasExecutablePermission: Bool,
        isRequiredConfigurationLikelyEnabled: Bool,
        guidance: [String]
    ) {
        self.isInstalled = isInstalled
        self.isCLIAvailable = isCLIAvailable
        self.appURL = appURL
        self.cliURL = cliURL
        self.pathEntries = pathEntries
        self.hasExecutablePermission = hasExecutablePermission
        self.isRequiredConfigurationLikelyEnabled = isRequiredConfigurationLikelyEnabled
        self.guidance = guidance
    }
}

public struct BetterDisplayDiagnostics: Equatable, Sendable {
    public var environment: BetterDisplayEnvironment
    public var version: String?
    public var capabilities: [BetterDisplayCapability]
    public var virtualDisplayConnected: Bool
    public var currentDisplayCount: Int
    public var supportedResolutions: [Resolution]

    public init(
        environment: BetterDisplayEnvironment,
        version: String?,
        capabilities: [BetterDisplayCapability],
        virtualDisplayConnected: Bool,
        currentDisplayCount: Int,
        supportedResolutions: [Resolution]
    ) {
        self.environment = environment
        self.version = version
        self.capabilities = capabilities
        self.virtualDisplayConnected = virtualDisplayConnected
        self.currentDisplayCount = currentDisplayCount
        self.supportedResolutions = supportedResolutions
    }
}
