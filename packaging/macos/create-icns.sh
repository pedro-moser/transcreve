#!/usr/bin/env bash
set -euo pipefail

SOURCE_PNG="${1:-assets/transcreve-icon.png}"
OUTPUT_ICNS="${2:-packaging/generated/transcreve.icns}"
ICONSET="${RUNNER_TEMP:-/tmp}/Transcreve.iconset"

rm -rf "$ICONSET"
mkdir -p "$ICONSET" "$(dirname "$OUTPUT_ICNS")"

for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$SOURCE_PNG" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" "$SOURCE_PNG" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done

iconutil -c icns "$ICONSET" -o "$OUTPUT_ICNS"
file "$OUTPUT_ICNS"
