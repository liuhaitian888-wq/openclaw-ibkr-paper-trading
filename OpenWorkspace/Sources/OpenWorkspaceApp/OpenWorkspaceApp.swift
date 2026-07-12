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

                    if viewModel.displays.isEmpty {
                        Text("No display snapshot")
                    } else {
                        ForEach(viewModel.displays) { display in
                            Text("\(display.name): \(display.resolution.width)x\(display.resolution.height)")
                        }
                    }

                    Divider()

                    Button("Create Virtual Display") {
                        Task { await viewModel.createVirtualDisplay() }
                    }
                    .disabled(viewModel.isVirtualDisplayActive)

                    Button("Destroy Virtual Display") {
                        Task { await viewModel.destroyVirtualDisplay() }
                    }
                    .disabled(!viewModel.isVirtualDisplayActive)

                    Button("Refresh Displays") {
                        Task { await viewModel.refreshDisplays() }
                    }

                    Button("List Displays") {
                        Task { await viewModel.listDisplays() }
                    }

                    Menu("Display Resolution") {
                        Button("1920x1080") {
                            Task { await viewModel.setResolution(Resolution(width: 1920, height: 1080)) }
                        }
                        Button("2560x1440") {
                            Task { await viewModel.setResolution(Resolution(width: 2560, height: 1440)) }
                        }
                    }
                    .disabled(!viewModel.isVirtualDisplayActive)

                    Menu("Display Scaling") {
                        ForEach(DisplayScalingMode.allCases, id: \.rawValue) { scalingMode in
                            Button(scalingMode.label) {
                                Task { await viewModel.setScaling(scalingMode) }
                            }
                        }
                    }
                    .disabled(!viewModel.isVirtualDisplayActive)

                    Menu("Display Rotation") {
                        ForEach(DisplayRotation.allCases, id: \.rawValue) { rotation in
                            Button(rotation.label) {
                                Task { await viewModel.setRotation(rotation) }
                            }
                        }
                    }
                    .disabled(!viewModel.isVirtualDisplayActive)

                    Menu("Diagnostics") {
                        Button("Run Diagnostics") {
                            Task { await viewModel.runDisplayDiagnostics() }
                        }

                        Divider()

                        if viewModel.diagnosticsLines.isEmpty {
                            Text("No diagnostics yet")
                        } else {
                            ForEach(viewModel.diagnosticsLines, id: \.self) { line in
                                Text(line)
                            }
                        }
                    }

                    Button("Settings") {
                        Task { await viewModel.openBetterDisplaySettings() }
                    }
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
