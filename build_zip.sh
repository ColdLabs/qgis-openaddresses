#!/usr/bin/env bash
# Build the plugins.qgis.org upload: dist/<plugin>-<version>.zip, plugin folder at the root.
set -euo pipefail
cd "$(dirname "$0")"
plugin=openaddresses_downloader
version=$(sed -n 's/^version=//p' "$plugin/metadata.txt")
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
rsync -a --exclude '__pycache__' --exclude '*.pyc' --exclude '.*' "$plugin/" "$stage/$plugin/"
cp LICENSE "$stage/$plugin/LICENSE"
mkdir -p dist
out="$PWD/dist/$plugin-$version.zip"
rm -f "$out"
(cd "$stage" && zip -qrX "$out" "$plugin")
echo "dist/$plugin-$version.zip"
