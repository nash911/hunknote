#!/usr/bin/env bash
#
# Hunknote Installer Script
# https://hunknote.com
#
# Usage:
#   Install:    curl -fsSL https://hunknote.com/install.sh | bash
#   Uninstall:  curl -fsSL https://hunknote.com/install.sh | bash -s -- --uninstall
#
# Options:
#   --uninstall    Remove hunknote from the system
#   --help         Show this help message
#
# This script downloads and installs a pre-built hunknote binary.
# No Python installation required.
#

set -euo pipefail

GITHUB_REPO="nash911/hunknote"
DEFAULT_INSTALL_DIR="$HOME/.local/bin"
HUNKNOTE_CONFIG_DIR="$HOME/.config/hunknote"

# Colors (disabled in non-interactive mode)
if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    NC='\033[0m' # No Color
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    CYAN=''
    BOLD=''
    NC=''
fi

# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------

print_banner() {
    echo -e "${BLUE}"
    echo "  _   _             _                _       "
    echo " | | | |_   _ _ __ | | ___ __   ___ | |_ ___ "
    echo " | |_| | | | | '_ \| |/ / '_ \ / _ \| __/ _ \\"
    echo " |  _  | |_| | | | |   <| | | | (_) | ||  __/"
    echo " |_| |_|\__,_|_| |_|_|\_\_| |_|\___/ \__\___|"
    echo -e "${NC}"
    echo -e "${BOLD}AI-powered git commit messages${NC}"
    echo ""
}

info() {
    printf '%b%s%b\n' "${BLUE}==>${NC} ${BOLD}" "$1" "${NC}"
}

success() {
    printf '%b%s%b\n' "${GREEN}==>${NC} ${BOLD}" "$1" "${NC}"
}

warn() {
    printf '%b %s\n' "${YELLOW}Warning:${NC}" "$1"
}

error() {
    printf '%b %s\n' "${RED}Error:${NC}" "$1" >&2
    exit 1
}

# -----------------------------------------------------------------------------
# System detection
# -----------------------------------------------------------------------------

detect_os() {
    local os
    os="$(uname -s | tr '[:upper:]' '[:lower:]')"
    case "$os" in
        darwin)
            echo "darwin"
            ;;
        linux)
            echo "linux"
            ;;
        mingw*|msys*|cygwin*)
            error "Windows is not yet supported. Please use WSL or install via pip: pip install hunknote"
            ;;
        *)
            error "Unsupported operating system: $os"
            ;;
    esac
}

detect_arch() {
    local arch
    arch="$(uname -m)"
    case "$arch" in
        x86_64|amd64)
            echo "amd64"
            ;;
        arm64|aarch64)
            echo "arm64"
            ;;
        *)
            error "Unsupported architecture: $arch. Please install via pip: pip install hunknote"
            ;;
    esac
}

# -----------------------------------------------------------------------------
# Version and download
# -----------------------------------------------------------------------------

get_latest_version() {
    local url="https://api.github.com/repos/${GITHUB_REPO}/releases/latest"
    local version
    local curl_opts=(-fsSL)

    # Use GitHub token if available (for rate limiting)
    if [[ -n "${GITHUB_TOKEN:-}" ]]; then
        curl_opts+=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
    fi

    # Fetch latest release info and extract tag_name
    version=$(curl "${curl_opts[@]}" "$url" 2>/dev/null | grep '"tag_name"' | sed -E 's/.*"tag_name": *"v?([^"]+)".*/\1/')

    if [[ -z "$version" ]]; then
        error "Failed to fetch latest version from GitHub. Please check your internet connection or try again later."
    fi

    echo "$version"
}

download_file() {
    local url="$1"
    local output="$2"

    if ! curl -fsSL "$url" -o "$output"; then
        error "Failed to download: $url"
    fi
}

verify_checksum() {
    local file="$1"
    local expected_checksum="$2"
    local actual_checksum

    if command -v sha256sum &> /dev/null; then
        actual_checksum=$(sha256sum "$file" | awk '{print $1}')
    elif command -v shasum &> /dev/null; then
        actual_checksum=$(shasum -a 256 "$file" | awk '{print $1}')
    else
        warn "No checksum tool found (sha256sum or shasum). Skipping verification."
        return 0
    fi

    if [[ "$actual_checksum" != "$expected_checksum" ]]; then
        error "Checksum verification failed!\n  Expected: $expected_checksum\n  Actual:   $actual_checksum"
    fi
}

# -----------------------------------------------------------------------------
# Installation
# -----------------------------------------------------------------------------

# Global variable for cleanup
CLEANUP_DIR=""

cleanup() {
    if [[ -n "$CLEANUP_DIR" && -d "$CLEANUP_DIR" ]]; then
        rm -rf "$CLEANUP_DIR"
    fi
}

install_binary() {
    local os="$1"
    local arch="$2"
    local version="$3"
    local install_dir="$4"

    local archive_name="hunknote_${os}_${arch}.tar.gz"
    local download_url="https://github.com/${GITHUB_REPO}/releases/download/v${version}/${archive_name}"
    local checksums_url="https://github.com/${GITHUB_REPO}/releases/download/v${version}/checksums.txt"

    # Create temp directory
    CLEANUP_DIR=$(mktemp -d)
    trap cleanup EXIT

    # Download archive
    local archive_path="${CLEANUP_DIR}/${archive_name}"
    info "Downloading ${archive_name}..."
    download_file "$download_url" "$archive_path"

    # Download and verify checksums
    info "Downloading checksums..."
    local checksums_path="${CLEANUP_DIR}/checksums.txt"
    download_file "$checksums_url" "$checksums_path"

    info "Verifying checksum..."
    local expected_checksum
    expected_checksum=$(grep -E "${archive_name}\$" "$checksums_path" | awk '{print $1}' || true)
    if [[ -z "$expected_checksum" ]]; then
        warn "Checksum for ${archive_name} not found. Skipping verification."
    else
        verify_checksum "$archive_path" "$expected_checksum"
        success "Checksum verified"
    fi

    # Extract
    info "Extracting..."
    tar -xzf "$archive_path" -C "$CLEANUP_DIR"

    local binary_path="${CLEANUP_DIR}/hunknote"
    chmod +x "$binary_path"

    # Install
    info "Installing to ${install_dir}..."
    mkdir -p "${install_dir}"

    if [[ ! -w "$install_dir" ]]; then
        error "Cannot write to ${install_dir}. Try running with sudo or choose a different directory."
    fi

    local install_path="${install_dir}/hunknote"
    mv "$binary_path" "$install_path"

    # Verify installation with better error reporting
    local version_output
    if version_output=$("$install_path" --version 2>&1); then
        success "Hunknote installed to ${install_path}"
    else
        echo ""
        warn "Binary verification failed. Output:"
        echo "$version_output"
        echo ""
        warn "This may be due to missing system libraries. Falling back to pip installation..."
        rm -f "$install_path"
        # Return non-zero to trigger fallback
        return 1
    fi

    echo "$install_path"
}

# -----------------------------------------------------------------------------
# Post-installation
# -----------------------------------------------------------------------------

print_path_instructions() {
    local install_dir="$1"

    # Check if install_dir is already in PATH
    local path_binary
    path_binary=$(command -v "hunknote" 2>/dev/null || true)

    if [[ -n "$path_binary" && "$path_binary" != "${install_dir}/hunknote" ]]; then
        # Another hunknote found in PATH
        echo ""
        echo -e "${YELLOW}!${NC} ${BOLD}WARNING: Another hunknote found in PATH${NC}"
        echo -e "${YELLOW}!${NC}"
        echo -e "${YELLOW}!${NC} Installed to: ${install_dir}/hunknote"
        echo -e "${YELLOW}!${NC} But 'hunknote' resolves to: ${path_binary}"
        echo -e "${YELLOW}!${NC}"
        echo -e "${YELLOW}!${NC} To fix, either:"
        echo -e "${YELLOW}!${NC}   1. Remove the old binary: rm ${path_binary}"
        echo -e "${YELLOW}!${NC}   2. Adjust your PATH to prioritize ${install_dir}"
        echo ""
        return 1
    elif [[ -z "$path_binary" ]]; then
        # hunknote not in PATH - show instructions
        local shell_name shell_config
        shell_name="$(basename "${SHELL:-bash}")"

        case "$shell_name" in
            zsh)
                shell_config="~/.zshrc"
                ;;
            bash)
                if [[ -f "$HOME/.bash_profile" ]]; then
                    shell_config="~/.bash_profile"
                else
                    shell_config="~/.bashrc"
                fi
                ;;
            fish)
                shell_config="~/.config/fish/config.fish"
                ;;
            *)
                shell_config=""
                ;;
        esac

        echo ""
        echo -e "  ${YELLOW}Almost there!${NC} Add hunknote to your PATH:"
        echo ""

        if [[ "$shell_name" == "fish" ]]; then
            echo -e "  Run this, then restart your terminal:"
            echo ""
            echo -e "    ${BOLD}echo 'fish_add_path ${install_dir}' >> ~/.config/fish/config.fish${NC}"
        elif [[ -n "$shell_config" ]]; then
            echo -e "  Run this, then restart your terminal:"
            echo ""
            echo -e "    ${BOLD}echo 'export PATH=\"${install_dir}:\$PATH\"' >> ${shell_config}${NC}"
        else
            echo -e "  Add this to your shell config, then restart your terminal:"
            echo ""
            echo -e "    ${BOLD}export PATH=\"${install_dir}:\$PATH\"${NC}"
        fi
        echo ""
    fi

    return 0
}

print_next_steps() {
    echo ""
    echo -e "${GREEN}${BOLD}✓ Installation complete!${NC}"
    echo ""
    echo -e "${BOLD}Next steps:${NC}"
    echo ""
    echo "  1. Set up your API key (choose one):"
    echo ""
    echo -e "     ${BLUE}# For Anthropic Claude (recommended)${NC}"
    echo "     export ANTHROPIC_API_KEY='your-api-key'"
    echo ""
    echo -e "     ${BLUE}# For OpenAI${NC}"
    echo "     export OPENAI_API_KEY='your-api-key'"
    echo ""
    echo -e "     ${BLUE}# For Google Gemini${NC}"
    echo "     export GEMINI_API_KEY='your-api-key'"
    echo ""
    echo "  2. Add the export to your shell profile (~/.bashrc or ~/.zshrc)"
    echo ""
    echo "  3. Try it out:"
    echo ""
    echo -e "     ${BLUE}# Stage some changes${NC}"
    echo "     git add ."
    echo ""
    echo -e "     ${BLUE}# Generate a commit message${NC}"
    echo "     hunknote"
    echo ""
    echo -e "     ${BLUE}# Or commit directly${NC}"
    echo "     hunknote --commit"
    echo ""
    echo -e "${BOLD}Documentation:${NC} https://docs.hunknote.com"
    echo -e "${BOLD}GitHub:${NC}        https://github.com/${GITHUB_REPO}"
    echo ""
}

# -----------------------------------------------------------------------------
# Fallback to pip installation
# -----------------------------------------------------------------------------

fallback_to_pip() {
    local os="$1"
    local arch="$2"

    warn "Pre-built binary not available for ${os}/${arch}."
    echo ""
    info "Falling back to pip installation..."
    echo ""

    # Check for Python
    local python_cmd=""
    for cmd in python3 python; do
        if command -v "$cmd" &> /dev/null; then
            python_cmd="$cmd"
            break
        fi
    done

    if [[ -z "$python_cmd" ]]; then
        error "Python not found. Please install Python 3.10+ and try again, or install manually: pip install hunknote"
    fi

    # Check Python version
    local py_version
    py_version=$($python_cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")

    if [[ "$(printf '%s\n' "3.10" "$py_version" | sort -V | head -n1)" != "3.10" ]]; then
        error "Python 3.10+ required (found $py_version). Please upgrade Python or install manually: pip install hunknote"
    fi

    # Try pipx first, then pip
    if command -v pipx &> /dev/null; then
        info "Installing with pipx..."
        pipx install hunknote --force
    else
        info "Installing with pip..."
        $python_cmd -m pip install --user hunknote
    fi

    success "Installed via pip"
}

# -----------------------------------------------------------------------------
# Uninstall
# -----------------------------------------------------------------------------

uninstall_hunknote() {
    print_banner
    info "Uninstalling Hunknote..."
    echo ""

    local found_any=false
    local install_dir="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"

    # Find hunknote binary locations
    local binary_locations=()

    # Check common locations
    for location in \
        "${install_dir}/hunknote" \
        "$HOME/.local/bin/hunknote" \
        "/usr/local/bin/hunknote" \
        "/usr/bin/hunknote"; do
        if [[ -f "$location" ]]; then
            binary_locations+=("$location")
        fi
    done

    # Check PATH
    local path_binary
    path_binary=$(command -v hunknote 2>/dev/null || true)
    if [[ -n "$path_binary" && ! " ${binary_locations[*]} " =~ " ${path_binary} " ]]; then
        binary_locations+=("$path_binary")
    fi

    # Remove binaries
    if [[ ${#binary_locations[@]} -gt 0 ]]; then
        for binary in "${binary_locations[@]}"; do
            if [[ -f "$binary" ]]; then
                info "Removing binary: $binary"
                if rm "$binary" 2>/dev/null; then
                    success "Removed: $binary"
                    found_any=true
                else
                    warn "Could not remove $binary (permission denied). Try: sudo rm $binary"
                fi
            fi
        done
    fi

    # Check for pipx installation
    if command -v pipx &> /dev/null; then
        if pipx list 2>/dev/null | grep -q "hunknote"; then
            info "Removing pipx installation..."
            if pipx uninstall hunknote 2>/dev/null; then
                success "Removed pipx installation"
                found_any=true
            fi
        fi
    fi

    # Check for pip installation
    for python_cmd in python3 python; do
        if command -v "$python_cmd" &> /dev/null; then
            if $python_cmd -m pip show hunknote &>/dev/null; then
                info "Removing pip installation..."
                if $python_cmd -m pip uninstall -y hunknote 2>/dev/null; then
                    success "Removed pip installation"
                    found_any=true
                fi
                break
            fi
        fi
    done

    # Ask about config directory
    if [[ -d "$HUNKNOTE_CONFIG_DIR" ]]; then
        echo ""
        echo -e "${YELLOW}Found configuration directory: $HUNKNOTE_CONFIG_DIR${NC}"

        if [[ -t 0 ]]; then
            # Interactive mode - ask user
            read -p "Do you want to remove configuration files? [y/N] " -n 1 -r
            echo ""
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                rm -rf "$HUNKNOTE_CONFIG_DIR"
                success "Removed configuration directory"
            else
                info "Keeping configuration files"
            fi
        else
            # Non-interactive mode - keep configs
            info "Keeping configuration files (run interactively to remove)"
        fi
    fi

    # Check for .hunknote directories in git repos (just inform, don't remove)
    echo ""
    if [[ "$found_any" == true ]]; then
        success "Hunknote has been uninstalled!"
        echo ""
        echo "Note: Per-repository .hunknote/ directories (if any) were not removed."
        echo "You can manually remove them from your git repositories if needed."
    else
        warn "No hunknote installation found."
        echo ""
        echo "Hunknote may have been installed via a different method, or already uninstalled."
    fi
    echo ""
}

# -----------------------------------------------------------------------------
# Help
# -----------------------------------------------------------------------------

show_help() {
    echo "Hunknote Installer"
    echo ""
    echo "Usage:"
    echo "  Install:    curl -fsSL https://hunknote.com/install.sh | bash"
    echo "  Uninstall:  curl -fsSL https://hunknote.com/install.sh | bash -s -- --uninstall"
    echo ""
    echo "Options:"
    echo "  --uninstall    Remove hunknote from the system"
    echo "  --help, -h     Show this help message"
    echo ""
    echo "Environment Variables:"
    echo "  INSTALL_DIR    Custom installation directory (default: ~/.local/bin)"
    echo "  GITHUB_TOKEN   GitHub token for API requests (avoids rate limiting)"
    echo ""
    echo "Documentation: https://docs.hunknote.com"
    echo "GitHub:        https://github.com/${GITHUB_REPO}"
    echo ""
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

main() {
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --uninstall)
                uninstall_hunknote
                exit 0
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                error "Unknown option: $1. Use --help for usage information."
                ;;
        esac
        shift
    done

    # Check for curl
    if ! command -v curl &> /dev/null; then
        error "curl is required but not installed. Please install curl and try again."
    fi

    print_banner
    info "Installing Hunknote..."
    echo ""

    # Detect platform
    local os arch
    os=$(detect_os)
    arch=$(detect_arch)
    info "Detected platform: ${os}/${arch}"

    # Get latest version
    info "Fetching latest version..."
    local version
    version=$(get_latest_version)
    version="${version#v}"  # Strip leading 'v' if present
    info "Latest version: ${version}"
    echo ""

    # Try to download pre-built binary
    local install_dir="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
    local install_path

    # Check if pre-built binary exists for this platform
    local archive_name="hunknote_${os}_${arch}.tar.gz"
    local check_url="https://github.com/${GITHUB_REPO}/releases/download/v${version}/${archive_name}"

    local binary_install_success=false
    if curl --output /dev/null --silent --head --fail "$check_url"; then
        if install_path=$(install_binary "$os" "$arch" "$version" "$install_dir"); then
            binary_install_success=true
        fi
    fi

    # Fallback to pip if binary install failed or wasn't available
    if [[ "$binary_install_success" != true ]]; then
        fallback_to_pip "$os" "$arch"
        install_path=$(command -v hunknote || echo "$HOME/.local/bin/hunknote")
    fi

    # Post-installation
    echo ""
    if print_path_instructions "$install_dir"; then
        print_next_steps
    fi
}

main "$@"

