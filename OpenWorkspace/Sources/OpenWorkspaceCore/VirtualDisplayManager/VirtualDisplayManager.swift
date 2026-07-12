import Foundation

public protocol VirtualDisplayManaging: Sendable {
    func createDisplay(preferences: DisplayPreferences) async throws -> VirtualDisplayHandle
    func removeDisplay(_ display: VirtualDisplayHandle) async throws
}

public struct ExternalVirtualDisplayManager: VirtualDisplayManaging {
    private let logger: AppLogging

    public init(logger: AppLogging) {
        self.logger = logger
    }

    public func createDisplay(preferences: DisplayPreferences) async throws -> VirtualDisplayHandle {
        logger.info("Virtual display creation requested")
        return VirtualDisplayHandle(name: "Android Extended Display", preferences: preferences)
    }

    public func removeDisplay(_ display: VirtualDisplayHandle) async throws {
        logger.info("Virtual display removal requested name=\(display.name)")
    }
}
