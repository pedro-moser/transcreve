#!/usr/bin/env bash
set -euo pipefail

DESTINATION="${1:-packaging/vendor}"
VERSION="4.0.0"
ARCHIVE_URL="https://breakfastquay.com/files/releases/rubberband-${VERSION}-gpl-executable-macos.tar.bz2"
SOURCE_URL="https://breakfastquay.com/files/releases/rubberband-${VERSION}.tar.bz2"
ARCHIVE_SHA256="0dc91509a31a94c1144436cc20e6f1d165bdab39fe125f9be7d46139921b733f"
SOURCE_SHA256="af050313ee63bc18b35b2e064e5dce05b276aaf6d1aa2b8a82ced1fe2f8028e9"
TEMP_ROOT="${RUNNER_TEMP:-/tmp}/rubberband-macos"
ARCHIVE="${TEMP_ROOT}.tar.bz2"
PAYLOAD="${TEMP_ROOT}/rubberband-${VERSION}-gpl-executable-macos"

rm -rf "$TEMP_ROOT"
mkdir -p "$TEMP_ROOT" "$DESTINATION/bin" "$DESTINATION/licenses"
curl -fsSL "$ARCHIVE_URL" -o "$ARCHIVE"
echo "$ARCHIVE_SHA256  $ARCHIVE" | shasum -a 256 -c -
tar -xjf "$ARCHIVE" -C "$TEMP_ROOT"
cp "$PAYLOAD/rubberband" "$DESTINATION/bin/rubberband"
cp "$PAYLOAD/rubberband-r3" "$DESTINATION/bin/rubberband-r3"
cp "$PAYLOAD/COPYING" "$DESTINATION/licenses/RUBBERBAND-COPYING"
chmod +x "$DESTINATION/bin/rubberband" "$DESTINATION/bin/rubberband-r3"
SOURCE_ARCHIVE="$DESTINATION/licenses/rubberband-${VERSION}.tar.bz2"
curl -fsSL "$SOURCE_URL" -o "$SOURCE_ARCHIVE"
echo "$SOURCE_SHA256  $SOURCE_ARCHIVE" | shasum -a 256 -c -

"$DESTINATION/bin/rubberband" --version
