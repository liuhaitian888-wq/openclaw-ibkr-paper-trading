import Foundation

public struct Resolution: Codable, Equatable, Sendable {
    public var width: Int
    public var height: Int

    public init(width: Int, height: Int) {
        self.width = width
        self.height = height
    }
}

public struct DisplayPreferences: Codable, Equatable, Sendable {
    public var resolution: Resolution
    public var framesPerSecond: Int
    public var scaleFactor: Double

    public init(
        resolution: Resolution = Resolution(width: 1920, height: 1080),
        framesPerSecond: Int = 60,
        scaleFactor: Double = 1.0
    ) {
        self.resolution = resolution
        self.framesPerSecond = framesPerSecond
        self.scaleFactor = scaleFactor
    }
}

public enum DisplaySource: String, Codable, Sendable {
    case system
    case betterDisplay
    case unknown
}

public struct ManagedDisplay: Identifiable, Codable, Equatable, Sendable {
    public var id: String
    public var name: String
    public var resolution: Resolution
    public var isVirtual: Bool
    public var isActive: Bool
    public var source: DisplaySource

    public init(
        id: String,
        name: String,
        resolution: Resolution,
        isVirtual: Bool,
        isActive: Bool,
        source: DisplaySource
    ) {
        self.id = id
        self.name = name
        self.resolution = resolution
        self.isVirtual = isVirtual
        self.isActive = isActive
        self.source = source
    }
}

public struct VirtualDisplayHandle: Codable, Equatable, Sendable {
    public var id: UUID
    public var name: String
    public var preferences: DisplayPreferences

    public init(
        id: UUID = UUID(),
        name: String,
        preferences: DisplayPreferences = DisplayPreferences()
    ) {
        self.id = id
        self.name = name
        self.preferences = preferences
    }
}

public struct MonitorPlacement: Codable, Equatable, Sendable {
    public var displayName: String
    public var x: Int
    public var y: Int

    public init(displayName: String, x: Int, y: Int) {
        self.displayName = displayName
        self.x = x
        self.y = y
    }
}
