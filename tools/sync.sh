#!/bin/sh
# Refresh the engine (skill + library) and the website from the JWT workspace.
set -e
SRC=${1:-/home/claude/jwt}
cd "$(dirname "$0")/.."
rm -rf engine site
cp -r "$SRC/skill/just-wear-this" engine
rm -rf engine/assets/models engine/examples
find engine -name __pycache__ -prune -exec rm -rf {} +
cp -r "$SRC/site" site
echo "synced from $SRC"
