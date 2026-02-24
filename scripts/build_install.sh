#!/usr/bin/env bash
#
# Build and install hunknote locally for testing
#
# This script builds a standalone binary using PyInstaller and installs it
# to ~/.local/bin, allowing you to test the complete build and installation
# process before pushing to GitHub.
#
# Usage:
#   ./scripts/build_install.sh           # Build and install
#   ./scripts/build_install.sh --clean   # Clean build artifacts only
#   ./scripts/build_install.sh --uninstall  # Remove local installation
#
# Requirements:
#   - Python 3.12+
#   - Poetry
#   - PyInstaller (poetry install --with build)
#

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
INSTALL_DIR="$HOME/.local/bin"
BINARY_NAME="hunknote"

info() {
    printf '%b==>%b %b%s%b\n' "${BLUE}" "${NC}" "${BOLD}" "$1" "${NC}"
}

success() {
    printf '%b==>%b %b%s%b\n' "${GREEN}" "${NC}" "${BOLD}" "$1" "${NC}"
}

warn() {
    printf '%b==>%b %b%s%b\n' "${YELLOW}" "${NC}" "${BOLD}" "$1" "${NC}"
}

error() {
    printf '%bError:%b %s\n' "${RED}" "${NC}" "$1" >&2
    exit 1
}

# -----------------------------------------------------------------------------
# Clean
# -----------------------------------------------------------------------------

clean_build() {
    info "Cleaning build artifacts..."
    cd "$PROJECT_ROOT"
    rm -rf build/ dist/ *.spec.tmp
    success "Build artifacts cleaned"
}

# -----------------------------------------------------------------------------
# Uninstall
# -----------------------------------------------------------------------------

uninstall_local() {
    info "Uninstalling local hunknote binary..."

    local binary_path="${INSTALL_DIR}/${BINARY_NAME}"

    if [[ -f "$binary_path" ]]; then
        rm -f "$binary_path"
        success "Removed: $binary_path"
    else
        warn "No local binary found at $binary_path"
    fi

    # Also check if there's a pipx/pip installation
    if command -v pipx &> /dev/null && pipx list 2>/dev/null | grep -q "hunknote"; then
        warn "Note: hunknote is also installed via pipx. Run 'pipx uninstall hunknote' to remove it."
    fi

    if command -v pip &> /dev/null && pip show hunknote &>/dev/null; then
        warn "Note: hunknote is also installed via pip. Run 'pip uninstall hunknote' to remove it."
    fi
}

# -----------------------------------------------------------------------------
# Build
# -----------------------------------------------------------------------------

check_requirements() {
    info "Checking requirements..."

    # Check Python
    if ! command -v python &> /dev/null; then
        error "Python not found. Please install Python 3.12+"
    fi

    local py_version
    py_version=$(python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    info "Python version: $py_version"

    # Check Poetry
    if ! command -v poetry &> /dev/null; then
        error "Poetry not found. Please install Poetry: https://python-poetry.org/docs/#installation"
    fi

    # Check PyInstaller
    if ! poetry run python -c "import PyInstaller" &> /dev/null; then
        warn "PyInstaller not found. Installing build dependencies..."
        poetry install --with build
    fi

    success "All requirements satisfied"
}

build_binary() {
    info "Building hunknote binary..."
    cd "$PROJECT_ROOT"

    # Clean previous builds
    rm -rf build/ dist/

    # Check if spec file exists
    if [[ -f "hunknote.spec" ]]; then
        info "Using hunknote.spec file..."
        poetry run pyinstaller hunknote.spec --noconfirm
    else
        info "Building with PyInstaller defaults..."
        poetry run pyinstaller \
            --onefile \
            --name hunknote \
            --hidden-import=hunknote.cli \
            --hidden-import=hunknote.llm \
            --hidden-import=hunknote.compose \
            --hidden-import=hunknote.cache \
            --hidden-import=hunknote.git \
            --hidden-import=hunknote.styles \
            --collect-all anthropic \
            --collect-all openai \
            --collect-all google.genai \
            --collect-all mistralai \
            --collect-all cohere \
            --collect-all groq \
            --collect-all pydantic \
            --collect-all typer \
            hunknote/__main__.py
    fi

    # Check if build succeeded
    if [[ ! -f "dist/hunknote" ]]; then
        error "Build failed. Check the output above for errors."
    fi

    local size
    size=$(du -h "dist/hunknote" | cut -f1)
    success "Build successful! Binary size: $size"
}

# -----------------------------------------------------------------------------
# Install
# -----------------------------------------------------------------------------

install_binary() {
    info "Installing binary to ${INSTALL_DIR}..."

    # Create install directory if needed
    mkdir -p "$INSTALL_DIR"

    # Remove existing binary
    local install_path="${INSTALL_DIR}/${BINARY_NAME}"
    if [[ -f "$install_path" ]]; then
        rm -f "$install_path"
    fi

    # Copy new binary
    cp "dist/hunknote" "$install_path"
    chmod +x "$install_path"

    success "Installed to: $install_path"
}

# -----------------------------------------------------------------------------
# Verify
# -----------------------------------------------------------------------------

verify_installation() {
    info "Verifying installation..."

    local install_path="${INSTALL_DIR}/${BINARY_NAME}"

    # Check binary exists
    if [[ ! -f "$install_path" ]]; then
        error "Binary not found at $install_path"
    fi

    # Check binary is executable
    if [[ ! -x "$install_path" ]]; then
        error "Binary is not executable"
    fi

    # Try to run --version
    local version_output
    if version_output=$("$install_path" --version 2>&1); then
        success "Binary works! Version: $version_output"
    else
        echo ""
        warn "Binary execution failed. Output:"
        echo "$version_output"
        echo ""
        error "Binary verification failed. This may be due to missing system libraries."
    fi

    # Check if in PATH
    if command -v hunknote &> /dev/null; then
        local which_path
        which_path=$(command -v hunknote)
        if [[ "$which_path" == "$install_path" ]]; then
            success "hunknote is in PATH and points to the new binary"
        else
            warn "hunknote in PATH points to: $which_path"
            warn "New binary installed at: $install_path"
            echo ""
            echo "To use the new binary, either:"
            echo "  1. Remove the old binary: rm $which_path"
            echo "  2. Add $INSTALL_DIR to the front of your PATH"
        fi
    else
        warn "hunknote is not in PATH"
        echo ""
        echo "Add this to your shell config (~/.bashrc or ~/.zshrc):"
        echo "  export PATH=\"$INSTALL_DIR:\$PATH\""
    fi
}

# -----------------------------------------------------------------------------
# Test
# -----------------------------------------------------------------------------

run_quick_test() {
    info "Running quick functionality test..."

    local install_path="${INSTALL_DIR}/${BINARY_NAME}"

    echo ""
    echo "Testing --help..."
    if "$install_path" --help > /dev/null 2>&1; then
        success "--help works"
    else
        warn "--help failed"
    fi

    echo "Testing config show..."
    if "$install_path" config show > /dev/null 2>&1; then
        success "config show works"
    else
        warn "config show failed (may be expected if no config exists)"
    fi

    echo ""
    success "Quick test completed!"
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

show_help() {
    echo "Build and install hunknote locally for testing"
    echo ""
    echo "Usage:"
    echo "  $0              Build and install"
    echo "  $0 --clean      Clean build artifacts only"
    echo "  $0 --uninstall  Remove local installation"
    echo "  $0 --help       Show this help"
    echo ""
    echo "The binary will be installed to: $INSTALL_DIR"
}

main() {
    # Parse arguments
    case "${1:-}" in
        --clean)
            clean_build
            exit 0
            ;;
        --uninstall)
            uninstall_local
            exit 0
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        "")
            # No arguments - build and install
            ;;
        *)
            error "Unknown option: $1. Use --help for usage."
            ;;
    esac

    echo ""
    echo -e "${BLUE}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║${NC}     ${BOLD}Hunknote Local Build & Install${NC}                        ${BLUE}║${NC}"
    echo -e "${BLUE}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""

    check_requirements
    echo ""

    build_binary
    echo ""

    install_binary
    echo ""

    verify_installation
    echo ""

    run_quick_test
    echo ""

    echo -e "${GREEN}${BOLD}════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}${BOLD}  ✓ Build and installation complete!${NC}"
    echo -e "${GREEN}${BOLD}════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo "You can now test hunknote:"
    echo "  hunknote --version"
    echo "  hunknote --help"
    echo "  hunknote config show"
    echo ""
    echo "To test with staged changes:"
    echo "  git add ."
    echo "  hunknote"
    echo ""
}

main "$@"

