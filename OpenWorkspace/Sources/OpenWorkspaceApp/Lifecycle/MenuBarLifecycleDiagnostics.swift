import AppKit
import Foundation
import OpenWorkspaceCore

struct MenuBarLifecycleDiagnostics {
    private let logger: AppLogging

    init(logger: AppLogging) {
        self.logger = logger
    }

    func record(event: String) {
        logger.info("App lifecycle event=\(event)")
    }

    @MainActor
    func verifyStartupState() {
        let bundle = Bundle.main
        let executable = bundle.executableURL?.path ?? "unknown"
        let bundlePath = bundle.bundleURL.path
        let activationPolicy = NSApplication.shared.activationPolicy().diagnosticName
        let isPackagedApp = bundle.bundleURL.pathExtension == "app"
        let lsuiElement = bundle.object(forInfoDictionaryKey: "LSUIElement") as? String

        logger.info("Startup executable=\(executable)")
        logger.info("Startup bundle=\(bundlePath)")
        logger.info("Startup packagedApp=\(isPackagedApp)")
        logger.info("Startup activationPolicy=\(activationPolicy)")

        if isPackagedApp {
            logger.info("Startup LSUIElement=\(lsuiElement ?? "unset")")
        } else {
            logger.warning("Startup is not packaged as .app; Info.plist scene keys are unavailable under swift run.")
        }

        guard #available(macOS 13.0, *) else {
            logger.error("MenuBarExtra requires macOS 13 or later.")
            return
        }

        logger.info("MenuBarExtra registration requested")
    }

    @MainActor
    static func commandLineReport() -> String {
        let bundle = Bundle.main
        let activationPolicy: String
        if Thread.isMainThread {
            activationPolicy = NSApplication.shared.activationPolicy().diagnosticName
        } else {
            activationPolicy = "unknown"
        }

        return [
            "OpenWorkspace lifecycle diagnostics",
            "bundlePath=\(bundle.bundleURL.path)",
            "executablePath=\(bundle.executableURL?.path ?? "unknown")",
            "isPackagedApp=\(bundle.bundleURL.pathExtension == "app")",
            "minimumMenuBarExtraOS=macOS 13",
            "activationPolicy=\(activationPolicy)",
            "debugExpectedActivationPolicy=regular",
            "releaseExpectedActivationPolicy=accessory",
            "lsuiElement=\((bundle.object(forInfoDictionaryKey: "LSUIElement") as? String) ?? "unset")"
        ].joined(separator: "\n")
    }
}

private extension NSApplication.ActivationPolicy {
    var diagnosticName: String {
        switch self {
        case .regular:
            "regular"
        case .accessory:
            "accessory"
        case .prohibited:
            "prohibited"
        @unknown default:
            "unknown"
        }
    }
}
