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
}
