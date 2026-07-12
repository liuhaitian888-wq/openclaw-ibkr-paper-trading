import Foundation

public protocol ClientManaging: Sendable {
    func prepareClient(for device: RegisteredDevice) async throws
}

public struct ExternalClientManager: ClientManaging {
    private let logger: AppLogging

    public init(logger: AppLogging) {
        self.logger = logger
    }

    public func prepareClient(for device: RegisteredDevice) async throws {
        logger.info("Preparing external client alias=\(device.alias)")
    }
}
