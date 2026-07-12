import SwiftUI
import OpenWorkspaceCore

@main
struct OpenWorkspaceApp: App {
    @NSApplicationDelegateAdaptor(OpenWorkspaceAppDelegate.self) private var appDelegate
    @StateObject private var viewModel = AppViewModel.bootstrap()

    var body: some Scene {
        MenuBarExtra {
            VStack(alignment: .leading, spacing: 8) {
                Text("OpenWorkspace")
                    .font(.headline)

                Text(viewModel.statusMessage)
                    .font(.subheadline)

                Text(viewModel.summary)
                    .font(.caption)

                Divider()

                Button("Status") {
                    Task { await viewModel.refreshStatus() }
                }

                Menu("Connected Devices") {
                    if viewModel.connectedDevices.isEmpty && viewModel.discoveredDevices.isEmpty {
                        Text("No devices detected")
                    }

                    ForEach(viewModel.connectedDevices) { device in
                        Text("\(device.alias) (\(device.kind.rawValue))")
                    }

                    ForEach(viewModel.discoveredDevices) { device in
                        Text("\(device.alias) (\(device.connectionMode.rawValue))")
                    }

                    Divider()

                    Button("Discover Devices") {
                        Task { await viewModel.discoverDevices() }
                    }

                    Button("Register Android Display") {
                        Task { await viewModel.registerAndroidDevice() }
                    }
                }

                Menu("Displays") {
                    Text("Detected: \(viewModel.displayCount)")
                    Text("Virtual Display: \(viewModel.isVirtualDisplayActive ? "Active" : "Inactive")")

                    Divider()

                    Button("Create Virtual Display") {
                        Task { await viewModel.createVirtualDisplay() }
                    }
                    .disabled(viewModel.isVirtualDisplayActive)

                    Button("Destroy Virtual Display") {
                        Task { await viewModel.destroyVirtualDisplay() }
                    }
                    .disabled(!viewModel.isVirtualDisplayActive)
                }

                Button("Launch Sunshine") {
                    Task { await viewModel.launchSunshine() }
                }
                .disabled(viewModel.isSunshineRunning)

                Button("Restart Sunshine") {
                    Task { await viewModel.restartSunshine() }
                }
                .disabled(!viewModel.isSunshineInstalled)

                Button("Stop Sunshine") {
                    Task { await viewModel.stopSunshine() }
                }
                .disabled(!viewModel.isSunshineRunning)

                Divider()

                Button("Save Workspace") {
                    Task { await viewModel.saveWorkspace() }
                }

                Button("Restore Workspace") {
                    Task { await viewModel.restoreWorkspace() }
                }

                Button("Settings") {
                    viewModel.openSettings()
                }

                Divider()

                Button("Quit") {
                    NSApplication.shared.terminate(nil)
                }
            }
            .padding(.vertical, 4)
            .task {
                await viewModel.refreshStatus()
            }
        } label: {
            Label("OpenWorkspace", systemImage: "display.2")
        }
        .menuBarExtraStyle(.menu)
    }
}
