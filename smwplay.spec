# PyInstaller spec for the SMW Play Launcher (all platforms).
# Run from the repository root: python -m PyInstaller smwplay.spec
import sys

a = Analysis(["app.py"], pathex=["."], hiddenimports=["fxpak", "websockets"])
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SMWPlayLauncher", console=False,
               target_arch="universal2")  # Intel + Apple Silicon
    coll = COLLECT(exe, a.binaries, a.datas, name="SMWPlayLauncher")
    app = BUNDLE(
        coll,
        name="SMWPlayLauncher.app",
        bundle_identifier="club.spinjump.smwplay",
        info_plist={
            "CFBundleURLTypes": [
                {"CFBundleURLName": "SMW Play", "CFBundleURLSchemes": ["smwplay"]}
            ],
            "NSHighResolutionCapable": True,
        },
    )
else:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="SMWPlayLauncher", console=False,
    )
