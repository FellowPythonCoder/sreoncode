# Sreon Browser

A native desktop browser: PySide6 (Qt WebEngine / Chromium) for the window, tabs and
downloads, a small Rust sidecar for search, an encrypted local vault. No accounts, no
telemetry, no Electron.

`Search privately. Browse freely.`

```
Browser/app/          the browser itself (Qt)
Browser/search/       Rust search engine (sreon-api), a stdin/stdout JSON sidecar
Browser/installer/    NSIS script for Windows, entitlements for macOS
Browser/assets/       icons + the disk-image artwork
Browser/tools/        build.py, make_dmg.py, make_dmg_background.py, check_dmg.py
Browser/VERSION       the one version string: bundles, installers, artwork, deb, Cargo
If-it-says-unverified.txt   the guide that ships inside every build
```

## Build the double-click files

Everything goes through one script, on the machine whose files you want:

```sh
python3 -m venv .venv && .venv/bin/pip install -r Browser/requirements.txt -r Browser/tools/requirements-design.txt
.venv/bin/python Browser/tools/build.py            # needs Rust + Python 3.12
```

| OS | Produces | Notes |
| --- | --- | --- |
| macOS | `Browser/dist/Sreon.dmg`, `Sreon.pkg` | DMG opens as a styled drag-to-Applications window with the Gatekeeper card printed on it (`dmgbuild` writes the Finder layout; `hdiutil` fallback if dmgbuild is missing) |
| Windows | `Browser/dist/SreonSetup.exe` | NSIS/MUI2 installer, branded header + sidebar, Start Menu entry, browser-list registration, clean uninstall |
| Linux | `Browser/dist/Sreon.AppImage`, `sreon_<version>_amd64.deb` | AppImage is the double-click file; the deb installs to `/opt/sreon` |

Flags: `--skip-engine` (use a prebuilt `sreon-api`), `--only dmg`, `--installer-app`,
`--zip`. Useful environment variables: `SREON_CODESIGN_IDENTITY`,
`SREON_PRODUCTSIGN_IDENTITY`, `SREON_PLATFORMS` (the label printed on the DMG artwork).

CI does all three platforms at once in
[`.github/workflows/browser.yml`](.github/workflows/browser.yml) and uploads a
`Sreon-<version>-double-click.zip` containing exactly the three double-click files.

To turn a finished build into a downloadable release, use
[`.github/workflows/publish-release.yml`](.github/workflows/publish-release.yml). It
re-downloads the artifacts of a build run and attaches them to a GitHub release, so nothing
is refrozen (the installers are ~600 MB and a rebuild takes fifteen minutes):

```sh
git commit --allow-empty -m "[release] publish the newest green build"
git commit --allow-empty -m "[release 35808314540] publish that run"   # or name one
git push
```

The release carries the zip plus each installer on its own (`Sreon.dmg`, `Sreon.pkg`,
`SreonSetup.exe`, `Sreon.AppImage`, the `.deb`), `SHA256SUMS.txt`, and the guide, and it is
marked pre-release while the builds are unsigned. The **Run workflow** button on
`Sreon Release` does the same thing and takes an optional run number.

Everything in the zip is checked before it is uploaded, per platform, in CI: the DMG is mounted
and inspected (payload, exec bit, `QtWebEngineCore.framework`, the `/Applications` drop link,
the background and the Finder icon records), then the frozen binary is launched from the read-only
image; the Windows installer is run silently, its installed tree, Start Menu entry and
Add/Remove Programs record are checked, then it is uninstalled; the AppImage is unpacked with
`--appimage-extract` and the deb is installed with `dpkg -i`.


## Artwork

The DMG background is code, not a binary blob someone hand-edited:

```sh
python3 Browser/tools/make_dmg_background.py            # assets/dmg-background{,@2x}.png
python3 Browser/tools/make_dmg_background.py --preview   # assets/dmg-preview.png, with fake Finder icons
python3 Browser/tools/make_dmg_background.py --nsis-assets   # installer/nsis/{header,welcome}.bmp
```

`layout()` in that file is the single source of truth for the Finder icon coordinates, and
`tools/build.py` feeds those same numbers to dmgbuild, so the artwork and the icon positions
cannot drift apart. Text that would overflow the window raises instead of being clipped, and
CI fails if the committed PNGs differ from what the script produces.

## "App is not verified"

Expected for an unsigned, unpaid build, and it is one approval per machine, ever:
open Sreon once, click **Done**, then **Apple menu → System Settings → Privacy & Security →
Security → Open Anyway → Open** (or right-click Sreon in Applications → Open). Windows
SmartScreen is the same story: **More info → Run anyway**. Full text in
[`If-it-says-unverified.txt`](If-it-says-unverified.txt), mirrored in the app under
Help → If Sreon Won't Open. We deliberately do **not** tell users to disable Gatekeeper or
strip quarantine flags.

To make the warning disappear for good, add signing and the next build is notarised:

| Secret | Effect |
| --- | --- |
| `SREON_APPLE_CERT_P12` + `SREON_APPLE_CERT_PASSWORD` | `Developer ID Application` signing of the .app and .pkg |
| `SREON_APPLE_ID`, `SREON_APPLE_TEAM_ID`, `SREON_APPLE_APP_PASSWORD` | notarisation + staple, so Gatekeeper never complains |
| `SREON_WINDOWS_CERT_P12` + password | Authenticode on `SreonSetup.exe` |

Set them and export `SREON_CODESIGN_IDENTITY` in the macOS job (see the workflow);
until then the build is ad-hoc signed, which is enough to run on Apple silicon.

## Tests

```sh
PYTHONPATH=Browser python3 -m pytest Browser/tests -q
```

`test_release.py` is the packaging guard: version agreement, artwork geometry and fit,
the NSIS script's parameters, and that the guide still only documents Apple's and
Microsoft's own approval routes.
