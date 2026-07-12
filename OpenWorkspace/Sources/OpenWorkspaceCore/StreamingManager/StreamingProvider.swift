import Foundation

public protocol StreamingProvider: Sendable {
    var kind: StreamingProviderKind { get }
    var displayName: String { get }

    func installation() async -> StreamingInstallation
    func state() async -> StreamingState
    func launch() async throws
    func stop() async throws
    func restart() async throws
    func reloadConfiguration() async throws
    func readConfiguration() async throws -> StreamingConfiguration
    func validateConfiguration() async throws -> StreamingConfiguration
    func readLogs(limit: Int) async throws -> [String]
    func statistics() async throws -> StreamingStatistics
    func diagnostics() async throws -> StreamingDiagnostics
    func openSettings() async throws
}

public actor StreamingManager {
    private let provider: StreamingProvider

    public init(provider: StreamingProvider) {
        self.provider = provider
    }

    public func installation() async -> StreamingInstallation {
        await provider.installation()
    }

    public func state() async -> StreamingState {
        await provider.state()
    }

    public func launch() async throws {
        try await provider.launch()
    }

    public func stop() async throws {
        try await provider.stop()
    }

    public func restart() async throws {
        try await provider.restart()
    }

    public func reloadConfiguration() async throws {
        try await provider.reloadConfiguration()
    }

    public func readConfiguration() async throws -> StreamingConfiguration {
        try await provider.readConfiguration()
    }

    public func validateConfiguration() async throws -> StreamingConfiguration {
        try await provider.validateConfiguration()
    }

    public func readLogs(limit: Int = 80) async throws -> [String] {
        try await provider.readLogs(limit: limit)
    }

    public func statistics() async throws -> StreamingStatistics {
        try await provider.statistics()
    }

    public func diagnostics() async throws -> StreamingDiagnostics {
        try await provider.diagnostics()
    }

    public func openSettings() async throws {
        try await provider.openSettings()
    }
}
