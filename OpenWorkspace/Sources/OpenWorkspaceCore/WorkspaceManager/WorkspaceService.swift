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
    func launchSunshine() async throws
    func stopSunshine() async throws
    func restartSunshine() async throws
    func saveWorkspace() async throws
    func restoreWorkspace() async throws
}

public struct WorkspaceStatus: Equatable, Sendable {
    public var connectedDevices: [RegisteredDevice]
    public var discoveredDevices: [DiscoveredDevice]
    public var displays: [ManagedDisplay]
    public var isVirtualDisplayActive: Bool
    public var isSunshineInstalled: Bool
    public var isSunshineRunning: Bool

    public init(
        connectedDevices: [RegisteredDevice],
        discoveredDevices: [DiscoveredDevice],
        displays: [ManagedDisplay],
        isVirtualDisplayActive: Bool,
        isSunshineInstalled: Bool,
        isSunshineRunning: Bool
    ) {
        self.connectedDevices = connectedDevices
        self.discoveredDevices = discoveredDevices
        self.displays = displays
        self.isVirtualDisplayActive = isVirtualDisplayActive
        self.isSunshineInstalled = isSunshineInstalled
        self.isSunshineRunning = isSunshineRunning
    }
}

public actor WorkspaceService: WorkspaceServicing {
    private let discoveryService: DeviceDiscovering
    private let deviceRegistry: DeviceRegistering
    private let displayManager: DisplayManaging
    private let sunshineManager: SunshineManaging
    private let clientManager: ClientManaging
    private let configurationStore: ConfigurationStoring
    private let logger: AppLogging

    private var virtualDisplays: [VirtualDisplayHandle] = []

    public init(
        discoveryService: DeviceDiscovering,
        deviceRegistry: DeviceRegistering,
        displayManager: DisplayManaging,
        sunshineManager: SunshineManaging,
        clientManager: ClientManaging,
        configurationStore: ConfigurationStoring,
        logger: AppLogging
    ) {
        self.discoveryService = discoveryService
        self.deviceRegistry = deviceRegistry
        self.displayManager = displayManager
        self.sunshineManager = sunshineManager
        self.clientManager = clientManager
        self.configurationStore = configurationStore
        self.logger = logger
    }

    public func status() async throws -> WorkspaceStatus {
        let discoveredDevices = try await discoveryService.discoverDevices()
        let displays = try await displayManager.refreshDisplays()
        let virtualDisplayActive = try await displayManager.isVirtualDisplayActive()
        let sunshineInstalled = await sunshineManager.installation() != nil
        let sunshineRunning = await sunshineManager.isRunning()

        return WorkspaceStatus(
            connectedDevices: await deviceRegistry.allDevices(),
            discoveredDevices: discoveredDevices,
            displays: displays,
            isVirtualDisplayActive: virtualDisplayActive,
            isSunshineInstalled: sunshineInstalled,
            isSunshineRunning: sunshineRunning
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

    public func launchSunshine() async throws {
        try await sunshineManager.start()
    }

    public func stopSunshine() async throws {
        try await sunshineManager.stop()
    }

    public func restartSunshine() async throws {
        try await sunshineManager.restart()
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
