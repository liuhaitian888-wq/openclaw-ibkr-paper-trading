import Foundation
import AppKit
import OpenWorkspaceCore

@MainActor
final class AppViewModel: ObservableObject {
    @Published var statusMessage = "OpenWorkspace is idle"
    @Published var connectedDevices: [RegisteredDevice] = []
    @Published var discoveredDevices: [DiscoveredDevice] = []
    @Published var displays: [ManagedDisplay] = []
    @Published var displayCount = 0
    @Published var isVirtualDisplayActive = false
    @Published var isSunshineInstalled = false
    @Published var isSunshineRunning = false

    private let workspaceService: WorkspaceServicing
    private let logger: AppLogging

    init(workspaceService: WorkspaceServicing, logger: AppLogging) {
        self.workspaceService = workspaceService
        self.logger = logger
    }

    static func bootstrap() -> AppViewModel {
        DiagnosticsCommand.runAndExitIfNeeded()

        let logger = ConsoleLogger(minimumLevel: .info)
        let processRunner = ShellProcessRunner(logger: logger)
        let configurationStore = JSONConfigurationStore.defaultStore(logger: logger)
        let displayProvider = BetterDisplayProvider(processRunner: processRunner, logger: logger)

        let workspaceService = WorkspaceService(
            discoveryService: CompositeDeviceDiscovery(
                backends: [
                    ADBDeviceDiscoveryBackend(processRunner: processRunner, logger: logger),
                    PlaceholderDiscoveryBackend(name: "Bonjour", logger: logger),
                    PlaceholderDiscoveryBackend(name: "mDNS", logger: logger),
                    PlaceholderDiscoveryBackend(name: "USB", logger: logger),
                    PlaceholderDiscoveryBackend(name: "Bluetooth", logger: logger),
                    PlaceholderDiscoveryBackend(name: "Wi-Fi", logger: logger)
                ],
                logger: logger
            ),
            deviceRegistry: InMemoryDeviceRegistry(logger: logger),
            displayManager: MacDisplayManager(provider: displayProvider, logger: logger),
            sunshineManager: SunshineManager(processRunner: processRunner, logger: logger),
            clientManager: ExternalClientManager(logger: logger),
            configurationStore: configurationStore,
            logger: logger
        )

        return AppViewModel(workspaceService: workspaceService, logger: logger)
    }

    var summary: String {
        if isVirtualDisplayActive && isSunshineRunning {
            return "Ready for third display"
        }
        if isVirtualDisplayActive {
            return "Virtual display active"
        }
        if isSunshineRunning {
            return "Sunshine running"
        }
        return statusMessage
    }

    func refreshStatus() async {
        do {
            let status = try await workspaceService.status()
            connectedDevices = status.connectedDevices
            discoveredDevices = status.discoveredDevices
            displays = status.displays
            displayCount = status.displays.count
            isVirtualDisplayActive = status.isVirtualDisplayActive
            isSunshineInstalled = status.isSunshineInstalled
            isSunshineRunning = status.isSunshineRunning
            statusMessage = "Displays: \(displayCount) | Sunshine: \(isSunshineRunning ? "Running" : "Stopped")"
        } catch {
            logger.error("Status refresh failed: \(error.localizedDescription)")
            statusMessage = "Status unavailable"
        }
    }

    func discoverDevices() async {
        await run("Discovering devices") {
            let devices = try await self.workspaceService.discoverDevices()
            self.discoveredDevices = devices
            return "Found \(devices.count) discoverable device(s)"
        }
    }

    func registerAndroidDevice() async {
        await run("Registering Android display") {
            _ = try await self.workspaceService.registerAndroidDevice(alias: "Android Display")
            await self.refreshStatus()
            return "Android display registered"
        }
    }

    func createVirtualDisplay() async {
        await run("Creating virtual display") {
            _ = try await self.workspaceService.createVirtualDisplay()
            await self.refreshStatus()
            return "Virtual display created"
        }
    }

    func destroyVirtualDisplay() async {
        await run("Destroying virtual display") {
            try await self.workspaceService.destroyVirtualDisplay()
            await self.refreshStatus()
            return "Virtual display destroyed"
        }
    }

    func refreshDisplays() async {
        await run("Refreshing displays") {
            let refreshedDisplays = try await self.workspaceService.refreshDisplays()
            let status = try await self.workspaceService.status()
            self.displays = refreshedDisplays
            self.displayCount = refreshedDisplays.count
            self.isVirtualDisplayActive = status.isVirtualDisplayActive
            return "Displays refreshed: \(refreshedDisplays.count)"
        }
    }

    func listDisplays() async {
        await run("Listing displays") {
            let listedDisplays = try await self.workspaceService.listDisplays()
            self.displays = listedDisplays
            self.displayCount = listedDisplays.count
            return "Displays listed: \(listedDisplays.count)"
        }
    }

    func launchSunshine() async {
        await run("Launching Sunshine") {
            try await self.workspaceService.launchSunshine()
            await self.refreshStatus()
            return "Sunshine launch requested"
        }
    }

    func stopSunshine() async {
        await run("Stopping Sunshine") {
            try await self.workspaceService.stopSunshine()
            await self.refreshStatus()
            return "Sunshine stop requested"
        }
    }

    func restartSunshine() async {
        await run("Restarting Sunshine") {
            try await self.workspaceService.restartSunshine()
            await self.refreshStatus()
            return "Sunshine restart requested"
        }
    }

    func saveWorkspace() async {
        await run("Saving workspace") {
            try await self.workspaceService.saveWorkspace()
            return "Workspace saved"
        }
    }

    func restoreWorkspace() async {
        await run("Restoring workspace") {
            try await self.workspaceService.restoreWorkspace()
            await self.refreshStatus()
            return "Workspace restored"
        }
    }

    func openSettings() {
        let url = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        )[0].appendingPathComponent("OpenWorkspace", isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        NSWorkspace.shared.open(url)
    }

    private func run(_ pendingMessage: String, operation: @escaping () async throws -> String) async {
        statusMessage = pendingMessage
        do {
            statusMessage = try await operation()
        } catch {
            logger.error("Operation failed: \(error.localizedDescription)")
            statusMessage = "Error: \(error.localizedDescription)"
        }
    }
}
