# Packaging Transcreve

The public beta installers are built natively by `.github/workflows/package-beta.yml`.

## Targets

- Windows x64: PyInstaller onedir bundle wrapped by Inno Setup
- macOS Apple Silicon: PyInstaller `.app` wrapped in a DMG
- macOS Intel: PyInstaller `.app` using the last compatible Intel PyTorch line (`2.2.2`), wrapped in a DMG

All builds include the base application, chord detection, Demucs stem separation, and the official Rubber Band command-line binary. Demucs model weights and FFmpeg are downloaded automatically on first use and stored in the platform-native user data directory.

## Local build inputs

```text
requirements-build.txt
requirements-full.txt
requirements-full-macos-intel.txt
packaging/transcreve.spec
packaging/fetch-rubberband.ps1
packaging/fetch-rubberband-macos.sh
```

Downloaded binaries and generated icon files are written under ignored `packaging/vendor/` and `packaging/generated/` directories.

## Unsigned beta warning

The beta workflow applies an ad-hoc signature to macOS bundles but does not notarize them. Windows and macOS will therefore show security warnings until Developer ID and Authenticode certificates are configured.

## GPL compliance

The application is GPL-3.0-or-later. The workflow bundles the Rubber Band GPL notice and its complete corresponding source archive inside the installer. GitHub Releases also exposes the exact Transcreve source tag beside each binary release.
