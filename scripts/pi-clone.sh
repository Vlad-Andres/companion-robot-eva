#!/usr/bin/env bash
# Lightweight clone for the Raspberry Pi: checks out the robot client only.
# Excludes backend/ from the working tree and, thanks to the blob filter,
# never downloads backend blobs (including the ~63 MB Piper voice model).
#
# Usage: ./pi-clone.sh [repo-url] [target-dir]
set -euo pipefail

REPO_URL="${1:-git@github.com:Vlad-Andres/companion-robot-eva.git}"
TARGET_DIR="${2:-companion-robot-eva}"

git clone --filter=blob:none --no-checkout "$REPO_URL" "$TARGET_DIR"
cd "$TARGET_DIR"
git sparse-checkout set --no-cone '/*' '!/backend/'
git checkout main

echo
echo "Done. Working tree excludes backend/ and its blobs were never fetched."
