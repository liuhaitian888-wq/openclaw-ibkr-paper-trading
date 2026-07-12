import Foundation

public struct WorkspaceConfiguration: Codable, Equatable, Sendable {
    public var schemaVersion: Int
    public var activeProfileName: String
    public var registeredDevices: [RegisteredDevice]
    public var virtualDisplays: [VirtualDisplayHandle]
    public var monitorPlacements: [MonitorPlacement]

    public init(
        schemaVersion: Int = 1,
        activeProfileName: String = "Default",
        registeredDevices: [RegisteredDevice] = [],
        virtualDisplays: [VirtualDisplayHandle] = [],
        monitorPlacements: [MonitorPlacement] = []
    ) {
        self.schemaVersion = schemaVersion
        self.activeProfileName = activeProfileName
        self.registeredDevices = registeredDevices
        self.virtualDisplays = virtualDisplays
        self.monitorPlacements = monitorPlacements
    }
}
