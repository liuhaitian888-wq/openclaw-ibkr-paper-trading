import AppKit
import OpenWorkspaceCore

@MainActor
final class OpenWorkspaceAppDelegate: NSObject, NSApplicationDelegate {
    private let diagnostics = MenuBarLifecycleDiagnostics(logger: ConsoleLogger(minimumLevel: .debug))

    func applicationWillFinishLaunching(_ notification: Notification) {
        configureActivationPolicy()
        diagnostics.record(event: "applicationWillFinishLaunching")
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        diagnostics.record(event: "applicationDidFinishLaunching")
        diagnostics.verifyStartupState()
    }

    func applicationWillTerminate(_ notification: Notification) {
        diagnostics.record(event: "applicationWillTerminate")
    }

    private func configureActivationPolicy() {
        #if DEBUG
        NSApplication.shared.setActivationPolicy(.regular)
        diagnostics.record(event: "activationPolicy=regular")
        #else
        NSApplication.shared.setActivationPolicy(.accessory)
        diagnostics.record(event: "activationPolicy=accessory")
        #endif
    }
}
