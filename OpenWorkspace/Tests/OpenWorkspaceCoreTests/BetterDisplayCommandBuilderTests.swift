import Testing
@testable import OpenWorkspaceCore

struct BetterDisplayCommandBuilderTests {
    @Test func createVirtualScreenUsesDocumentedBetterDisplayArguments() {
        let arguments = BetterDisplayCommandBuilder.createVirtualScreenArguments(
            name: "OpenWorkspace Virtual Display",
            preferences: DisplayPreferences(
                resolution: Resolution(width: 1920, height: 1080),
                framesPerSecond: 60,
                scaleFactor: 1.0
            )
        )

        #expect(arguments.contains("create"))
        #expect(arguments.contains("-devicetype=virtualscreen"))
        #expect(arguments.contains("-virtualscreenname=OpenWorkspace Virtual Display"))
        #expect(arguments.contains("-aspectWidth=16"))
        #expect(arguments.contains("-aspectHeight=9"))
        #expect(arguments.contains("-useResolutionList=on"))
        #expect(arguments.contains("-resolutionList=1920x1080"))
    }

    @Test func lifecycleCommandsTargetOnlyTheOpenWorkspaceVirtualDisplay() {
        #expect(
            BetterDisplayCommandBuilder.connectVirtualScreenArguments(name: "OpenWorkspace Virtual Display") == [
                "set",
                "-namelike=OpenWorkspace Virtual Display",
                "-connected=on"
            ]
        )
        #expect(
            BetterDisplayCommandBuilder.discardVirtualScreenArguments(name: "OpenWorkspace Virtual Display") == [
                "discard",
                "-namelike=OpenWorkspace Virtual Display"
            ]
        )
    }

    @Test func controlCommandsUseDocumentedBetterDisplayParameters() {
        let name = "OpenWorkspace Virtual Display"

        #expect(
            BetterDisplayCommandBuilder.setResolutionArguments(
                name: name,
                resolution: Resolution(width: 2560, height: 1440)
            ) == [
                "set",
                "-namelike=OpenWorkspace Virtual Display",
                "-resolution=2560x1440"
            ]
        )
        #expect(
            BetterDisplayCommandBuilder.setScalingArguments(name: name, scalingMode: .hiDPI) == [
                "set",
                "-namelike=OpenWorkspace Virtual Display",
                "-hiDPI=on"
            ]
        )
        #expect(
            BetterDisplayCommandBuilder.setRotationArguments(name: name, rotation: .degrees90) == [
                "set",
                "-namelike=OpenWorkspace Virtual Display",
                "-rotation=90"
            ]
        )
        #expect(BetterDisplayCommandBuilder.openSettingsArguments() == [
            "set",
            "-settingsWindow=on"
        ])
    }

    @Test func parsesSupportedResolutionsFromDisplayModeOutput() {
        let output = """
        Available display modes:
        1920x1080 @ 60Hz HiDPI
        2560 x 1440 @ 60Hz
        1920x1080 duplicate
        """

        let resolutions = BetterDisplayCommandBuilder.parseResolutions(output)

        #expect(resolutions == [
            Resolution(width: 1920, height: 1080),
            Resolution(width: 2560, height: 1440)
        ])
    }
}
