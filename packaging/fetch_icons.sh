#!/bin/bash
# Build-time script (not shipped): fetches curated Fluent UI System Icons
# (MIT license, https://github.com/microsoft/fluentui-system-icons) as the
# light-theme variant, then generates a dark-theme variant by recoloring the
# single fill color these monochrome SVGs use. Run once; re-run only if the
# icon set changes.
set -e

ICONS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/memoryos/ui/icons"
LIGHT_DIR="$ICONS_DIR/light"
DARK_DIR="$ICONS_DIR/dark"
mkdir -p "$LIGHT_DIR" "$DARK_DIR"

# local_name:FluentAssetFolder(url-encoded):icon_slug
ICONS=(
  "folder:Folder:folder"
  "search:Search:search"
  "play:Play:play"
  "pause:Pause:pause"
  "stop:Stop:stop"
  "delete:Delete:delete"
  "edit:Edit:edit"
  "copy:Copy:copy"
  "open:Open:open"
  "folder_open:Folder%20Open:folder_open"
  "history:History:history"
  "settings:Settings:settings"
  "weather_moon:Weather%20Moon:weather_moon"
  "weather_sunny:Weather%20Sunny:weather_sunny"
  "desktop:Desktop:desktop"
  "dismiss:Dismiss:dismiss"
  "mail:Mail:mail"
  "attach:Attach:attach"
  "eye:Eye:eye"
  "sparkle:Sparkle:sparkle"
)

for entry in "${ICONS[@]}"; do
  IFS=":" read -r local_name asset_folder slug <<< "$entry"
  url="https://raw.githubusercontent.com/microsoft/fluentui-system-icons/main/assets/${asset_folder}/SVG/ic_fluent_${slug}_24_regular.svg"
  light_path="$LIGHT_DIR/${local_name}.svg"
  curl -sL -o "$light_path" "$url"
  if ! grep -q "<svg" "$light_path"; then
    echo "FAILED to fetch $local_name from $url"
    exit 1
  fi
  # Dark variant: recolor the single fill (#212121, dark gray meant for light
  # backgrounds) to a warm ivory matching the Zynora AI dark theme's text
  # tone (#F2EFE9), suited to dark backgrounds.
  sed 's/#212121/#F2EFE9/g' "$light_path" > "$DARK_DIR/${local_name}.svg"
  echo "fetched: $local_name"
done

echo "Done. $(ls "$LIGHT_DIR" | wc -l) light icons, $(ls "$DARK_DIR" | wc -l) dark icons."
