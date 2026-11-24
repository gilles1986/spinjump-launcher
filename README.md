# SMW Play Launcher

A small desktop program (Python, standard library plus `websockets` for FXPak) for Windows, Linux and macOS. Set it up once, then **Play** on a website starts the hack directly in your emulator. The link format is not tied to Spinjump: it is meant to work with other sites too, for example an SMW Central extension or the SMWC Downloader & Patcher.

Requires your own unmodified Super Mario World ROM. No ROMs are hosted or downloaded.

## Download

Builds for all three systems come from GitHub Actions (`.github/workflows/build.yml`):

- **Release:** pushing a tag like `v0.1.0` builds everything and publishes a GitHub release with `SMWPlayLauncher.exe` (Windows), `SMWPlayLauncher-linux.tar.gz`, `SMWPlayLauncher-macos-arm64.zip` (Apple Silicon) and `SMWPlayLauncher-macos-intel.zip` (Intel).
- **Every push:** the same files are attached to the workflow run as artifacts.

## Link format

```
smwplay://play?url=<https address of a .bps or .zip>[&id=<id>][&title=<title>][&sha256=<checksum>]
```

- `url`: required, `https` only, no username. Either a `.bps` directly or a `.zip` containing `.bps` files (the launcher asks if there are several).
- `id`: `source:name` used as the library key (not for file names), e.g. `spinjump:my-hack@1.0`. Without an `id`: host plus a hash of the address.
- `title`: display only. `sha256`: checksum of the download (before unzipping); the launcher aborts if it does not match.

The **link generator** (small link at the bottom of the setup window) builds a link from an address.

## How it works

The system starts the launcher with the link. It downloads the file, takes the `.bps` out of a ZIP, applies it to your ROM (checksums of source, result and patch are verified) and writes `<hacks folder>/<name>/<name>.sfc`, where `<name>` is the name of the BPS file (e.g. `Mario's Inferno/Mario's Inferno.sfc`; for a direct link without a file name, the title). If the ROM already exists nothing is downloaded: the launcher keeps a small library in the hacks folder (`.smwplay-library.json`, id → finished ROM) and checks it before downloading. If a ZIP contains **several** BPS patches, all are patched into one folder (`<hack>/<patch>.sfc`, folder named after the title); only which one starts is asked (the one started last is preselected). A patch that does not fit the ROM does not stop the others. Deleted ROMs are downloaded again. Then the emulator starts.

**FXPak Pro:** In the setup the target can be set to "FXPak Pro". The launcher patches as usual, copies the ROM through **QUsb2Snes** (`ws://localhost:23074`, must be running) to `<folder>/<name>/<name>.sfc` on the SD card (default `/ROMS/Spinjump`) and starts it there. If it is already there, it is only started. The flow follows the SMWC Downloader & Patcher (`fxpak.py`). Tested against a fake server, not with real hardware. If QUsb2Snes is not found, the launcher does **not** silently fall back to the emulator: it shows a message with "Try again", "Switch to emulator" (remembered permanently, can be undone in the setup) and "Cancel". "No device found" (QUsb2Snes runs but the FXPak is missing) asks the same way.

**Emulator:** The launcher recognizes it by file name (Mesen, Snes9x, bsnes, higan, ares, ZSNES, RetroArch) and uses matching arguments as long as the field is empty (usually just the ROM). For RetroArch it looks in `cores/` for an SNES core (snes9x, bsnes, Mesen-S) and starts with `-L <core> <rom>`. RetroArch is only tested against file names and the core search, not with a real start.

Settings are stored in `%APPDATA%\Spinjump\launcher.json` (Windows), `~/.config/Spinjump/launcher.json` (Linux) or `~/Library/Application Support/Spinjump/launcher.json` (macOS): ROM, hacks folder, emulator, arguments.

## Platforms

- **Windows:** `SMWPlayLauncher.exe`. Saving the setup registers `smwplay://` under `HKCU\Software\Classes\smwplay`.
- **Linux:** one file, `SMWPlayLauncher` (unpack the `.tar.gz`). Saving the setup writes `~/.local/share/applications/smwplay.desktop` and sets the handler for `smwplay://` with `xdg-mime`. Without an emulator configured, `xdg-open` opens the ROM.
- **macOS:** `SMWPlayLauncher.app` (in the ZIP; pick `arm64` for Apple Silicon, `intel` for Intel Macs). The app declares `smwplay://` in its Info.plist; the link arrives as an event (`::tk::mac::LaunchURL`), not as an argument. Emulators that are `.app` bundles are started with `open -a`. The app is not signed: on first start use right click → Open.
- **Not verified on real machines:** the tests pass on all three systems in CI, but registering the link handler, the macOS link event and the built programs have not yet been tried on real Linux and macOS machines.
- **Android:** not supported. It would need its own app (link handler, BPS patching, starting the emulator by intent).

## Security

- Files are only downloaded from **trusted domains** (a domain includes its subdomains). Only the operator maintains the list (`BUILTIN_TRUSTED` in `core.py`: `spinjump.club`, `smwcentral.net`); players cannot add anything. Other domains are rejected, and so are redirects to them or to `http`.
- From a ZIP only `.bps` files are read, in memory. Nothing is extracted or executed. Limits: 32 MB, 500 entries.
- File names are sanitized and outputs only go inside the hacks folder. BPS only. No ROMs are downloaded or hosted.

## Browser extension for SMW Central

`extension/` is a small Chrome extension (Manifest V3, should also work in Firefox). On detail pages of smwcentral.net it adds a **Play** button next to "Download" that opens the launcher with the file SMWC itself links (`smwplay://play?url=https://dl.smwcentral.net/<id>/<file>&id=smwcentral:<name>-<id>&title=…`). It downloads nothing and only needs access to the page. The folder is named like the BPS file inside the ZIP.

- Build a ZIP with `python build-extension.py`.
- To try it: `chrome://extensions` → developer mode → "Load unpacked" → folder `extension`.
- On the first click Chrome asks whether smwcentral.net may open the launcher; choose "Always allow".
- Test: `node --test extension/content.test.js` (against a saved excerpt of `?p=section&a=details&id=39701`). It has not been checked against the live site; if SMWC changes the page structure (`#file-download-button`, `#submission-header .title`), `content.js` has to follow.
- Many older SMWC hacks only ship IPS patches; the launcher only supports BPS.

## Next steps

- Load the list of trusted sites from spinjump.club (signed, with an application process for site owners), so new sites need no launcher update.
- FXPak Pro: one target per Play button instead of a global one; selectable device.
- Verify the emulator defaults with real starts (RetroArch, Snes9x, bsnes); a selection list instead of detection by file name.
- Shared module with the SMWC Downloader & Patcher.
- Sign the Windows and macOS builds (SmartScreen, Gatekeeper).
- Android.

## Development

```
python -m pytest tests               # tests
python app.py                        # setup window
python app.py "smwplay://play?url=https%3A%2F%2Fspinjump.club%2Fapi%2Fv1%2Fhacks%2Fmy-hack%2Fdownload%2F1.0"
python -m PyInstaller smwplay.spec   # build the program for the current system
```

On Linux the tests need Tk and a display (`python3-tk`, `xvfb-run`).
