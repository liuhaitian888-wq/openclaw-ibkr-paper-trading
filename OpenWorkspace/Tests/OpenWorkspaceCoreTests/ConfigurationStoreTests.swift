import Foundation
import Testing
@testable import OpenWorkspaceCore

struct ConfigurationStoreTests {
    @Test func savesAndLoadsWorkspaceConfiguration() async throws {
        let directoryURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let configurationURL = directoryURL.appendingPathComponent("workspace.json")
        let store = JSONConfigurationStore(workspaceURL: configurationURL, logger: ConsoleLogger(minimumLevel: .error))
        let registeredAt = Date(timeIntervalSince1970: 1_785_000_000)

        let expected = WorkspaceConfiguration(
            activeProfileName: "Coding",
            registeredDevices: [
                RegisteredDevice(
                    id: UUID(uuidString: "11111111-1111-1111-1111-111111111111")!,
                    alias: "Android Display",
                    kind: .android,
                    capabilities: DeviceCapabilities(
                        supportsDisplay: true,
                        supportsKeyboardInput: true,
                        supportsPointerInput: true,
                        supportedConnectionModes: [.wifi]
                    ),
                    registeredAt: registeredAt
                )
            ],
            virtualDisplays: [
                VirtualDisplayHandle(
                    id: UUID(uuidString: "22222222-2222-2222-2222-222222222222")!,
                    name: "Android Extended Display"
                )
            ],
            monitorPlacements: [
                MonitorPlacement(displayName: "Built-in Display", x: 0, y: 0)
            ]
        )

        try await store.saveWorkspace(expected)
        let actual = try await store.loadWorkspace()

        #expect(actual == expected)
    }
}
