import Foundation

public enum DeviceKind: String, Codable, Sendable {
    case macBook
    case iPad
    case android
    case unknown
}

public enum ConnectionMode: String, Codable, Sendable {
    case sidecar
    case wifi
    case usb
    case unknown
}

public struct DeviceCapabilities: Codable, Equatable, Sendable {
    public var supportsDisplay: Bool
    public var supportsKeyboardInput: Bool
    public var supportsPointerInput: Bool
    public var supportedConnectionModes: [ConnectionMode]

    public init(
        supportsDisplay: Bool,
        supportsKeyboardInput: Bool,
        supportsPointerInput: Bool,
        supportedConnectionModes: [ConnectionMode]
    ) {
        self.supportsDisplay = supportsDisplay
        self.supportsKeyboardInput = supportsKeyboardInput
        self.supportsPointerInput = supportsPointerInput
        self.supportedConnectionModes = supportedConnectionModes
    }
}

public struct RegisteredDevice: Identifiable, Codable, Equatable, Sendable {
    public var id: UUID
    public var alias: String
    public var kind: DeviceKind
    public var capabilities: DeviceCapabilities
    public var registeredAt: Date

    public init(
        id: UUID = UUID(),
        alias: String,
        kind: DeviceKind,
        capabilities: DeviceCapabilities,
        registeredAt: Date = Date()
    ) {
        self.id = id
        self.alias = alias
        self.kind = kind
        self.capabilities = capabilities
        self.registeredAt = registeredAt
    }
}

public struct DiscoveredDevice: Identifiable, Equatable, Sendable {
    public var id: UUID
    public var alias: String
    public var kind: DeviceKind
    public var connectionMode: ConnectionMode
    public var capabilities: DeviceCapabilities

    public init(
        id: UUID = UUID(),
        alias: String,
        kind: DeviceKind,
        connectionMode: ConnectionMode,
        capabilities: DeviceCapabilities
    ) {
        self.id = id
        self.alias = alias
        self.kind = kind
        self.connectionMode = connectionMode
        self.capabilities = capabilities
    }
}
