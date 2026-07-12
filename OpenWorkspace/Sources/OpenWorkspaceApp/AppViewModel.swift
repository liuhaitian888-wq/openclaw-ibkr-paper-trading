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
    @Published var betterDisplayDiagnostics: BetterDisplayDiagnostics?
    @Published var diagnosticsLines: [String] = []
    @Published var streamingState: StreamingState = .unavailable
    @Published var streamingInstalled = false
    @Published var streamingDiagnosticsLines: [String] = []
    @Published var streamingLogLines: [String] = []
    @Published var streamingStatisticsLines: [String] = []
    @Published var connectedDeviceState: StreamingDeviceConnectionState = .offline

    private let workspaceService: WorkspaceServicing
    private let logger: AppLogging

    init(workspaceService: WorkspaceServicing, logger: AppLogging) {
        self.workspaceService = workspaceService
        self.logger = logger
    }

    static func bootstrap() -> AppViewModel {
        DiagnosticsCommand.runAndExitIfNeeded()
        BetterDisplayCommandLine.runAndExitIfNeeded()
        StreamingCommandLine.runAndExitIfNeeded()

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
            streamingManager: StreamingManager(
                provider: SunshineProvider(processRunner: processRunner, logger: logger)
            ),
            clientManager: ExternalClientManager(logger: logger),
            configurationStore: configurationStore,
            logger: logger
        )

        return AppViewModel(workspaceService: workspaceService, logger: logger)
    }

    var summary: String {
        if isVirtualDisplayActive && streamingState == .running {
            return "Ready for third display"
        }
        if isVirtualDisplayActive {
            return "Virtual display active"
        }
        if streamingState == .running {
            return "Streaming running"
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
            streamingState = status.streamingState
            streamingInstalled = status.streamingInstallation.isInstalled
            statusMessage = "Displays: \(displayCount) | Streaming: \(streamingState.rawValue)"
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

    func runDisplayDiagnostics() async {
        await run("Running display diagnostics") {
            let diagnostics = try await self.workspaceService.betterDisplayDiagnostics()
            self.betterDisplayDiagnostics = diagnostics
            self.diagnosticsLines = Self.formatDiagnostics(diagnostics)
            self.displayCount = diagnostics.currentDisplayCount
            self.isVirtualDisplayActive = diagnostics.virtualDisplayConnected
            return "Diagnostics complete"
        }
    }

    func setResolution(_ resolution: Resolution) async {
        await run("Setting resolution") {
            try await self.workspaceService.setVirtualDisplayResolution(resolution)
            await self.refreshDisplays()
            return "Resolution set to \(resolution.width)x\(resolution.height)"
        }
    }

    func setScaling(_ scalingMode: DisplayScalingMode) async {
        await run("Setting scaling") {
            try await self.workspaceService.setVirtualDisplayScaling(scalingMode)
            await self.refreshDisplays()
            return "Scaling set to \(scalingMode.label)"
        }
    }

    func setRotation(_ rotation: DisplayRotation) async {
        await run("Setting rotation") {
            try await self.workspaceService.setVirtualDisplayRotation(rotation)
            await self.refreshDisplays()
            return "Rotation set to \(rotation.label)"
        }
    }

    func openBetterDisplaySettings() async {
        await run("Opening BetterDisplay settings") {
            try await self.workspaceService.openBetterDisplaySettings()
            return "BetterDisplay settings requested"
        }
    }

    func launchStreaming() async {
        await run("Launching streaming provider") {
            try await self.workspaceService.launchStreaming()
            await self.refreshStatus()
            return "Streaming launch requested"
        }
    }

    func stopStreaming() async {
        await run("Stopping streaming provider") {
            try await self.workspaceService.stopStreaming()
            await self.refreshStatus()
            return "Streaming stop requested"
        }
    }

    func restartStreaming() async {
        await run("Restarting streaming provider") {
            try await self.workspaceService.restartStreaming()
            await self.refreshStatus()
            return "Streaming restart requested"
        }
    }

    func reloadStreamingConfiguration() async {
        await run("Reloading streaming configuration") {
            try await self.workspaceService.reloadStreamingConfiguration()
            await self.refreshStatus()
            return "Streaming configuration reloaded"
        }
    }

    func readStreamingLogs() async {
        await run("Reading streaming logs") {
            let logs = try await self.workspaceService.streamingLogs()
            self.streamingLogLines = logs
            return "Streaming logs loaded"
        }
    }

    func readStreamingStatistics() async {
        await run("Reading streaming statistics") {
            let statistics = try await self.workspaceService.streamingStatistics()
            self.streamingStatisticsLines = Self.formatStatistics(statistics)
            return "Streaming statistics loaded"
        }
    }

    func runStreamingDiagnostics() async {
        await run("Running streaming diagnostics") {
            let diagnostics = try await self.workspaceService.streamingDiagnostics()
            self.streamingDiagnosticsLines = Self.formatStreamingDiagnostics(diagnostics)
            self.streamingLogLines = diagnostics.logPreview
            self.streamingStatisticsLines = Self.formatStatistics(diagnostics.statistics)
            self.streamingState = diagnostics.state
            self.streamingInstalled = diagnostics.installation.isInstalled
            return "Streaming diagnostics complete"
        }
    }

    func openStreamingSettings() async {
        await run("Opening streaming settings") {
            try await self.workspaceService.openStreamingSettings()
            return "Streaming settings requested"
        }
    }

    func pairDevicePlaceholder() {
        statusMessage = "Pair Device is reserved for a future Moonlight workflow"
        connectedDeviceState = .offline
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

    private static func formatDiagnostics(_ diagnostics: BetterDisplayDiagnostics) -> [String] {
        let environment = diagnostics.environment
        let version = diagnostics.version ?? "Unavailable"
        let capabilities = diagnostics.capabilities.map(\.rawValue).joined(separator: ", ")
        let supportedResolutions = diagnostics.supportedResolutions
            .map { "\($0.width)x\($0.height)" }
            .joined(separator: ", ")

        var lines = [
            "Installed: \(environment.isInstalled ? "Yes" : "No")",
            "CLI Available: \(environment.isCLIAvailable ? "Yes" : "No")",
            "Version: \(version)",
            "Capabilities: \(capabilities.isEmpty ? "Unavailable" : capabilities)",
            "Executable Permission: \(environment.hasExecutablePermission ? "Yes" : "No")",
            "PATH Entries: \(environment.pathEntries.count)",
            "Virtual Display: \(diagnostics.virtualDisplayConnected ? "Connected" : "Disconnected")",
            "Current Display Count: \(diagnostics.currentDisplayCount)",
            "Supported Resolutions: \(supportedResolutions.isEmpty ? "Unavailable" : supportedResolutions)",
            "Required Configuration: \(environment.isRequiredConfigurationLikelyEnabled ? "Likely enabled" : "Unavailable")"
        ]

        if !environment.guidance.isEmpty {
            lines.append(contentsOf: environment.guidance.map { "Guidance: \($0)" })
        }
        return lines
    }

    private static func formatStreamingDiagnostics(_ diagnostics: StreamingDiagnostics) -> [String] {
        var lines = [
            "Provider: \(diagnostics.provider.rawValue)",
            "Installed: \(diagnostics.installation.isInstalled ? "Yes" : "No")",
            "Executable: \(diagnostics.installation.executableURL == nil ? "Unavailable" : "Available")",
            "Version: \(diagnostics.installation.version ?? "Unavailable")",
            "State: \(diagnostics.state.rawValue)",
            "Configuration: \(diagnostics.configuration.url?.lastPathComponent ?? "Unavailable")",
            "VideoToolbox: \(diagnostics.statistics.videoToolboxAvailable ? "Available" : "Unavailable")",
            "Hardware Encoder: \(diagnostics.statistics.hardwareEncoderAvailable ? "Available" : "Unavailable")",
            "Web Port Available: \(diagnostics.statistics.webPortAvailable ? "Yes" : "No")",
            "Stream Ports Available: \(diagnostics.statistics.streamPortsAvailable ? "Yes" : "No")"
        ]
        lines.append(contentsOf: diagnostics.issues.map { "Issue: \($0)" })
        lines.append(contentsOf: diagnostics.installation.guidance.map { "Guidance: \($0)" })
        return lines
    }

    private static func formatStatistics(_ statistics: StreamingStatistics) -> [String] {
        [
            "PID: \(statistics.processIdentifier.map(String.init) ?? "Unavailable")",
            "Web Port Available: \(statistics.webPortAvailable ? "Yes" : "No")",
            "Stream Ports Available: \(statistics.streamPortsAvailable ? "Yes" : "No")",
            "VideoToolbox: \(statistics.videoToolboxAvailable ? "Available" : "Unavailable")",
            "Hardware Encoder: \(statistics.hardwareEncoderAvailable ? "Available" : "Unavailable")"
        ]
    }
}
