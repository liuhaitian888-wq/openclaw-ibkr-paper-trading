import Foundation

public protocol ConfigurationStoring: Sendable {
    func loadWorkspace() async throws -> WorkspaceConfiguration
    func saveWorkspace(_ configuration: WorkspaceConfiguration) async throws
}

public enum ConfigurationError: Error, LocalizedError {
    case missingConfiguration

    public var errorDescription: String? {
        switch self {
        case .missingConfiguration:
            "No saved workspace configuration exists yet."
        }
    }
}

public actor JSONConfigurationStore: ConfigurationStoring {
    private let workspaceURL: URL
    private let logger: AppLogging
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    public init(workspaceURL: URL, logger: AppLogging) {
        self.workspaceURL = workspaceURL
        self.logger = logger

        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        self.encoder = encoder

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        self.decoder = decoder
    }

    public static func defaultStore(logger: AppLogging) -> JSONConfigurationStore {
        let baseURL = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        )[0]
        let directoryURL = baseURL.appendingPathComponent("OpenWorkspace", isDirectory: true)
        return JSONConfigurationStore(
            workspaceURL: directoryURL.appendingPathComponent("workspace.json"),
            logger: logger
        )
    }

    public func loadWorkspace() async throws -> WorkspaceConfiguration {
        guard FileManager.default.fileExists(atPath: workspaceURL.path) else {
            throw ConfigurationError.missingConfiguration
        }
        let data = try Data(contentsOf: workspaceURL)
        return try decoder.decode(WorkspaceConfiguration.self, from: data)
    }

    public func saveWorkspace(_ configuration: WorkspaceConfiguration) async throws {
        let directoryURL = workspaceURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directoryURL, withIntermediateDirectories: true)
        let data = try encoder.encode(configuration)
        try data.write(to: workspaceURL, options: [.atomic])
        logger.info("Saved workspace configuration to \(workspaceURL.path)")
    }
}
