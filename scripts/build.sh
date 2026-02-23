#!/usr/bin/env bash
#
# Build hunknote standalone binary using PyInstaller
#
# Usage:
#   ./scripts/build.sh
#
# Output:
#   dist/hunknote - standalone executable
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "==> Building hunknote standalone binary..."
echo ""

# Check for pyinstaller
if ! command -v pyinstaller &> /dev/null; then
    echo "Error: pyinstaller not found. Install with: poetry install --with build"
    exit 1
fi

# Clean previous builds
echo "==> Cleaning previous builds..."
rm -rf build/ dist/

# Build using spec file
echo "==> Running PyInstaller..."
pyinstaller hunknote.spec --noconfirm

# Check result
if [[ -f "dist/hunknote" ]]; then
    echo ""
    echo "==> Build successful!"
    echo ""
    echo "Binary location: dist/hunknote"
    echo "Size: $(du -h dist/hunknote | cut -f1)"
    echo ""
    echo "Test with: ./dist/hunknote --version"
else
    echo ""
    echo "Error: Build failed. Check the output above for errors."
    exit 1
fi

