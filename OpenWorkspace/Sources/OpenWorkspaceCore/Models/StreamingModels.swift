import Foundation

public enum StreamingProviderKind: String, Codable, CaseIterable, Sendable {
    case sunshine
    case rustDesk
    case parsec
    case steamLink
}

public enum StreamingState: String, Codable, Sendable {
    case unavailable
    case stopped
    case starting
    case running
    case stopping
    case error
}

public enum StreamingDeviceConnectionState: String, Codable, Sendable {
    case offline
    case connecting
    case connected
}

public struct StreamingInstallation: Equatable, Sendable {
    public var isInstalled: Bool
    public var executableURL: URL?
    public var applicationURL: URL?
    public var version: String?
    public var guidance: [String]

    public init(
        isInstalled: Bool,
        executableURL: URL?,
        applicationURL: URL?,
        version: String?,
        guidance: [String]
    ) {
        self.isInstalled = isInstalled
        self.executableURL = executableURL
        self.applicationURL = applicationURL
        self.version = version
        self.guidance = guidance
    }
}

public struct StreamingConfiguration: Equatable, Sendable {
    public var url: URL?
    public var redactedValues: [String: String]
    public var validationWarnings: [String]

    public init(url: URL?, redactedValues: [String: String], validationWarnings: [String]) {
        self.url = url
        self.redactedValues = redactedValues
        self.validationWarnings = validationWarnings
    }
}

public struct StreamingStatistics: Equatable, Sendable {
    public var processIdentifier: Int32?
    public var uptimeSeconds: TimeInterval?
    public var webPortAvailable: Bool
    public var streamPortsAvailable: Bool
    public var videoToolboxAvailable: Bool
    public var hardwareEncoderAvailable: Bool

    public init(
        processIdentifier: Int32?,
        uptimeSeconds: TimeInterval?,
        webPortAvailable: Bool,
        streamPortsAvailable: Bool,
        videoToolboxAvailable: Bool,
        hardwareEncoderAvailable: Bool
    ) {
        self.processIdentifier = processIdentifier
        self.uptimeSeconds = uptimeSeconds
        self.webPortAvailable = webPortAvailable
        self.streamPortsAvailable = streamPortsAvailable
        self.videoToolboxAvailable = videoToolboxAvailable
        self.hardwareEncoderAvailable = hardwareEncoderAvailable
    }
}

public struct StreamingDiagnostics: Equatable, Sendable {
    public var provider: StreamingProviderKind
    public var installation: StreamingInstallation
    public var state: StreamingState
    public var configuration: StreamingConfiguration
    public var statistics: StreamingStatistics
    public var logPreview: [String]
    public var issues: [String]

    public init(
        provider: StreamingProviderKind,
        installation: StreamingInstallation,
        state: StreamingState,
        configuration: StreamingConfiguration,
        statistics: StreamingStatistics,
        logPreview: [String],
        issues: [String]
    ) {
        self.provider = provider
        self.installation = installation
        self.state = state
        self.configuration = configuration
        self.statistics = statistics
        self.logPreview = logPreview
        self.issues = issues
    }
}
