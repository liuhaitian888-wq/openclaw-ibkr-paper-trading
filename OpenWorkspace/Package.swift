// swift-tools-version: 6.1

import PackageDescription

let package = Package(
    name: "OpenWorkspace",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "OpenWorkspace", targets: ["OpenWorkspaceApp"]),
        .library(name: "OpenWorkspaceCore", targets: ["OpenWorkspaceCore"])
    ],
    targets: [
        .executableTarget(
            name: "OpenWorkspaceApp",
            dependencies: ["OpenWorkspaceCore"]
        ),
        .target(
            name: "OpenWorkspaceCore"
        ),
        .testTarget(
            name: "OpenWorkspaceCoreTests",
            dependencies: ["OpenWorkspaceCore"]
        )
    ]
)
