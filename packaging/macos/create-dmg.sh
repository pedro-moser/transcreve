#!/usr/bin/env bash
set -euo pipefail

APP_PATH="${1:?Usage: create-dmg.sh APP_PATH OUTPUT_DMG}"
OUTPUT_DMG="${2:?Usage: create-dmg.sh APP_PATH OUTPUT_DMG}"
STAGING="${RUNNER_TEMP:-/tmp}/transcreve-dmg"

rm -rf "$STAGING"
mkdir -p "$STAGING" "$(dirname "$OUTPUT_DMG")"
cp -R "$APP_PATH" "$STAGING/Transcreve.app"
ln -s /Applications "$STAGING/Applications"
hdiutil create -volname "Transcreve" -srcfolder "$STAGING" -ov -format UDZO "$OUTPUT_DMG"
hdiutil verify "$OUTPUT_DMG"
