import Foundation

public protocol DeviceDiscovering: Sendable {
    func discoverDevices() async throws -> [DiscoveredDevice]
}

public protocol DeviceDiscoveryBackend: Sendable {
    var name: String { get }
    func discoverDevices() async throws -> [DiscoveredDevice]
}

public struct CompositeDeviceDiscovery: DeviceDiscovering {
    private let backends: [DeviceDiscoveryBackend]
    private let logger: AppLogging

    public init(backends: [DeviceDiscoveryBackend], logger: AppLogging) {
        self.backends = backends
        self.logger = logger
    }

    public func discoverDevices() async throws -> [DiscoveredDevice] {
        var devices: [DiscoveredDevice] = []
        for backend in backends {
            do {
                devices.append(contentsOf: try await backend.discoverDevices())
            } catch {
                logger.warning("Discovery backend failed name=\(backend.name) error=\(error.localizedDescription)")
            }
        }
        return devices
    }
}

public struct ADBDeviceDiscoveryBackend: DeviceDiscoveryBackend {
    public let name = "ADB"

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

    public func discoverDevices() async throws -> [DiscoveredDevice] {
        guard let adbURL = locator.firstExecutable(
            named: ["adb"],
            additionalDirectories: [
                "\(NSHomeDirectory())/Library/Android/sdk/platform-tools"
            ]
        ) else {
            logger.info("ADB executable was not found")
            return []
        }

        let result = try await processRunner.capture(adbURL, arguments: ["devices", "-l"])
        guard result.exitCode == 0 else {
            logger.warning("ADB device discovery failed")
            return []
        }

        return parseADBDevices(result.standardOutput)
    }

    public func parseADBDevices(_ output: String) -> [DiscoveredDevice] {
        var index = 0
        return output
            .split(separator: "\n")
            .compactMap { rawLine -> DiscoveredDevice? in
                let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !line.isEmpty, !line.hasPrefix("List of devices") else { return nil }

                let columns = line.split(whereSeparator: { $0 == " " || $0 == "\t" }).map(String.init)
                guard columns.count >= 2, columns[1] == "device" else { return nil }

                index += 1
                let connectionMode: ConnectionMode = columns[0].contains(":") ? .wifi : .usb
                return DiscoveredDevice(
                    alias: "Android Device \(index)",
                    kind: .android,
                    connectionMode: connectionMode,
                    capabilities: DeviceCapabilities(
                        supportsDisplay: true,
                        supportsKeyboardInput: true,
                        supportsPointerInput: true,
                        supportedConnectionModes: [connectionMode]
                    )
                )
            }
    }
}

public struct PlaceholderDiscoveryBackend: DeviceDiscoveryBackend {
    public let name: String
    private let logger: AppLogging

    public init(name: String, logger: AppLogging) {
        self.name = name
        self.logger = logger
    }

    public func discoverDevices() async throws -> [DiscoveredDevice] {
        logger.debug("Discovery backend placeholder name=\(name)")
        return []
    }
}

public protocol DeviceRegistering: Sendable {
    func register(_ device: RegisteredDevice) async throws
    func allDevices() async -> [RegisteredDevice]
}

public actor InMemoryDeviceRegistry: DeviceRegistering {
    private var devices: [RegisteredDevice] = []
    private let logger: AppLogging

    public init(logger: AppLogging) {
        self.logger = logger
    }

    public func register(_ device: RegisteredDevice) async throws {
        devices.append(device)
        logger.info("Registered device alias=\(device.alias)")
    }

    public func allDevices() async -> [RegisteredDevice] {
        devices
    }
}
