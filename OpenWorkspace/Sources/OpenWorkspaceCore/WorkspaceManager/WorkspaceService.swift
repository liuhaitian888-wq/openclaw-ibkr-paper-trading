import Foundation

public protocol WorkspaceServicing: Sendable {
    func status() async throws -> WorkspaceStatus
    func discoverDevices() async throws -> [DiscoveredDevice]
    func registerAndroidDevice(alias: String) async throws -> RegisteredDevice
    func createVirtualDisplay() async throws -> VirtualDisplayHandle
    func destroyVirtualDisplay() async throws
    func refreshDisplays() async throws -> [ManagedDisplay]
    func listDisplays() async throws -> [ManagedDisplay]
    func betterDisplayDiagnostics() async throws -> BetterDisplayDiagnostics
    func setVirtualDisplayResolution(_ resolution: Resolution) async throws
    func setVirtualDisplayScaling(_ scalingMode: DisplayScalingMode) async throws
    func setVirtualDisplayRotation(_ rotation: DisplayRotation) async throws
    func openBetterDisplaySettings() async throws
    func streamingState() async -> StreamingState
    func streamingInstallation() async -> StreamingInstallation
    func launchStreaming() async throws
    func stopStreaming() async throws
    func restartStreaming() async throws
    func reloadStreamingConfiguration() async throws
    func streamingConfiguration() async throws -> StreamingConfiguration
    func streamingLogs() async throws -> [String]
    func streamingStatistics() async throws -> StreamingStatistics
    func streamingDiagnostics() async throws -> StreamingDiagnostics
    func openStreamingSettings() async throws
    func saveWorkspace() async throws
    func restoreWorkspace() async throws
}

public struct WorkspaceStatus: Equatable, Sendable {
    public var connectedDevices: [RegisteredDevice]
    public var discoveredDevices: [DiscoveredDevice]
    public var displays: [ManagedDisplay]
    public var isVirtualDisplayActive: Bool
    public var streamingState: StreamingState
    public var streamingInstallation: StreamingInstallation

    public init(
        connectedDevices: [RegisteredDevice],
        discoveredDevices: [DiscoveredDevice],
        displays: [ManagedDisplay],
        isVirtualDisplayActive: Bool,
        streamingState: StreamingState,
        streamingInstallation: StreamingInstallation
    ) {
        self.connectedDevices = connectedDevices
        self.discoveredDevices = discoveredDevices
        self.displays = displays
        self.isVirtualDisplayActive = isVirtualDisplayActive
        self.streamingState = streamingState
        self.streamingInstallation = streamingInstallation
    }
}

public actor WorkspaceService: WorkspaceServicing {
    private let discoveryService: DeviceDiscovering
    private let deviceRegistry: DeviceRegistering
    private let displayManager: DisplayManaging
    private let streamingManager: StreamingManager
    private let clientManager: ClientManaging
    private let configurationStore: ConfigurationStoring
    private let logger: AppLogging

    private var virtualDisplays: [VirtualDisplayHandle] = []

    public init(
        discoveryService: DeviceDiscovering,
        deviceRegistry: DeviceRegistering,
        displayManager: DisplayManaging,
        streamingManager: StreamingManager,
        clientManager: ClientManaging,
        configurationStore: ConfigurationStoring,
        logger: AppLogging
    ) {
        self.discoveryService = discoveryService
        self.deviceRegistry = deviceRegistry
        self.displayManager = displayManager
        self.streamingManager = streamingManager
        self.clientManager = clientManager
        self.configurationStore = configurationStore
        self.logger = logger
    }

    public func status() async throws -> WorkspaceStatus {
        let discoveredDevices = try await discoveryService.discoverDevices()
        let displays = try await displayManager.refreshDisplays()
        let virtualDisplayActive = try await displayManager.isVirtualDisplayActive()
        let streamingInstallation = await streamingManager.installation()
        let streamingState = await streamingManager.state()

        return WorkspaceStatus(
            connectedDevices: await deviceRegistry.allDevices(),
            discoveredDevices: discoveredDevices,
            displays: displays,
            isVirtualDisplayActive: virtualDisplayActive,
            streamingState: streamingState,
            streamingInstallation: streamingInstallation
        )
    }

    public func discoverDevices() async throws -> [DiscoveredDevice] {
        try await discoveryService.discoverDevices()
    }

    public func registerAndroidDevice(alias: String) async throws -> RegisteredDevice {
        let device = RegisteredDevice(
            alias: alias,
            kind: .android,
            capabilities: DeviceCapabilities(
                supportsDisplay: true,
                supportsKeyboardInput: true,
                supportsPointerInput: true,
                supportedConnectionModes: [.wifi]
            )
        )
        try await deviceRegistry.register(device)
        try await clientManager.prepareClient(for: device)
        return device
    }

    public func createVirtualDisplay() async throws -> VirtualDisplayHandle {
        let display = try await displayManager.createVirtualDisplay()
        virtualDisplays.append(display)
        return display
    }

    public func destroyVirtualDisplay() async throws {
        try await displayManager.destroyVirtualDisplay()
        virtualDisplays.removeAll()
    }

    public func refreshDisplays() async throws -> [ManagedDisplay] {
        try await displayManager.refreshDisplays()
    }

    public func listDisplays() async throws -> [ManagedDisplay] {
        try await displayManager.listDisplays()
    }

    public func betterDisplayDiagnostics() async throws -> BetterDisplayDiagnostics {
        try await displayManager.betterDisplayDiagnostics()
    }

    public func setVirtualDisplayResolution(_ resolution: Resolution) async throws {
        try await displayManager.setVirtualDisplayResolution(resolution)
    }

    public func setVirtualDisplayScaling(_ scalingMode: DisplayScalingMode) async throws {
        try await displayManager.setVirtualDisplayScaling(scalingMode)
    }

    public func setVirtualDisplayRotation(_ rotation: DisplayRotation) async throws {
        try await displayManager.setVirtualDisplayRotation(rotation)
    }

    public func openBetterDisplaySettings() async throws {
        try await displayManager.openBetterDisplaySettings()
    }

    public func streamingState() async -> StreamingState {
        await streamingManager.state()
    }

    public func streamingInstallation() async -> StreamingInstallation {
        await streamingManager.installation()
    }

    public func launchStreaming() async throws {
        try await streamingManager.launch()
    }

    public func stopStreaming() async throws {
        try await streamingManager.stop()
    }

    public func restartStreaming() async throws {
        try await streamingManager.restart()
    }

    public func reloadStreamingConfiguration() async throws {
        try await streamingManager.reloadConfiguration()
    }

    public func streamingConfiguration() async throws -> StreamingConfiguration {
        try await streamingManager.readConfiguration()
    }

    public func streamingLogs() async throws -> [String] {
        try await streamingManager.readLogs()
    }

    public func streamingStatistics() async throws -> StreamingStatistics {
        try await streamingManager.statistics()
    }

    public func streamingDiagnostics() async throws -> StreamingDiagnostics {
        try await streamingManager.diagnostics()
    }

    public func openStreamingSettings() async throws {
        try await streamingManager.openSettings()
    }

    public func saveWorkspace() async throws {
        let configuration = WorkspaceConfiguration(
            registeredDevices: await deviceRegistry.allDevices(),
            virtualDisplays: virtualDisplays,
            monitorPlacements: try await displayManager.currentLayout()
        )
        try await configurationStore.saveWorkspace(configuration)
    }

    public func restoreWorkspace() async throws {
        let configuration = try await configurationStore.loadWorkspace()
        virtualDisplays = configuration.virtualDisplays
        try await displayManager.applyLayout(configuration.monitorPlacements)
        logger.info("Restored workspace profile=\(configuration.activeProfileName)")
    }
}
