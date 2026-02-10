# Distribution Plan: Shipping aicommit as a Standalone CLI Tool

## Overview

This document outlines the plan to ship `aicommit` as a standalone CLI tool installable via:
- `apt-get install aicommit` on Debian/Ubuntu Linux
- `brew install aicommit` on macOS

## Current State

- Python 3.12+ CLI tool using Poetry for dependency management
- Multiple LLM provider support (Anthropic, OpenAI, Google, Mistral, Cohere, Groq, OpenRouter)
- Configuration currently stored in:
  - `aicommit/config.py` (provider/model selection)
  - `<repo>/.aicommit/config.yaml` (per-repo ignore patterns)
  - Environment variables for API keys

## Goals

1. **Global installation**: Install once, use in any git repository
2. **User configuration**: Store settings in `~/.aicommit/` (home directory)
3. **Easy setup**: Simple commands to configure API keys and preferences
4. **Package distribution**: Available via apt and brew

---

## Phase 1: Global User Configuration

### 1.1 Configuration Directory Structure

```
~/.aicommit/
├── config.yaml       # Global settings (provider, model, preferences)
├── credentials       # API keys (secured file permissions)
└── cache/            # Optional: global cache for cross-repo usage
```

### 1.2 config.yaml Format

```yaml
# ~/.aicommit/config.yaml
provider: google                    # anthropic, openai, google, mistral, cohere, groq, openrouter
model: gemini-2.0-flash            # Model name for the selected provider

# Optional settings
max_tokens: 1500
temperature: 0.3
editor: gedit                       # Preferred editor for -e flag

# Default ignore patterns (merged with repo-specific patterns)
default_ignore:
  - poetry.lock
  - package-lock.json
  - "*.min.js"
```

### 1.3 credentials File Format

```
# ~/.aicommit/credentials
# This file should have restricted permissions (chmod 600)

ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AI...
MISTRAL_API_KEY=...
COHERE_API_KEY=...
GROQ_API_KEY=gsk_...
OPENROUTER_API_KEY=sk-or-...
```

### 1.4 New CLI Commands for Configuration

```bash
# Initialize configuration (interactive setup)
aicommit init

# Set/update API key for a provider
aicommit config set-key anthropic
aicommit config set-key google

# Set provider and model
aicommit config set-provider google
aicommit config set-model gemini-2.0-flash

# View current configuration
aicommit config show

# List available providers and models
aicommit config list-providers
aicommit config list-models [provider]
```

---

## Phase 2: Code Changes

### 2.1 New Module: `aicommit/global_config.py`

Handles reading/writing global configuration from `~/.aicommit/`:

```python
# Key functions:
- get_global_config_dir() -> Path       # Returns ~/.aicommit/
- load_global_config() -> dict          # Loads config.yaml
- save_global_config(config: dict)      # Saves config.yaml
- load_credentials() -> dict            # Loads API keys from credentials file
- save_credential(provider, key)        # Saves an API key securely
- get_active_provider() -> LLMProvider  # Gets provider from config
- get_active_model() -> str             # Gets model from config
```

### 2.2 Update `aicommit/config.py`

Change from hardcoded values to loading from global config:

```python
# Instead of:
ACTIVE_PROVIDER = LLMProvider.GOOGLE
ACTIVE_MODEL = "gemini-2.0-flash"

# Load from global config with fallback defaults:
_global_config = load_global_config()
ACTIVE_PROVIDER = _global_config.get("provider", LLMProvider.GOOGLE)
ACTIVE_MODEL = _global_config.get("model", "gemini-2.0-flash")
```

### 2.3 Update LLM Providers

Modify API key loading to check:
1. Environment variable (highest priority - for CI/CD)
2. `~/.aicommit/credentials` file
3. Repo-level `.env` file (lowest priority)

### 2.4 Update CLI (`aicommit/cli.py`)

Add new subcommand groups:
- `aicommit init` - Interactive setup wizard
- `aicommit config` - Configuration management

---

## Phase 3: PyPI Distribution

### 3.1 Prepare for PyPI

1. Update `pyproject.toml` with complete metadata:
   ```toml
   [tool.poetry]
   name = "aicommit-cli"
   version = "1.0.0"
   description = "AI-powered git commit message generator"
   authors = ["Your Name <email@example.com>"]
   license = "MIT"
   homepage = "https://github.com/username/aicommit"
   repository = "https://github.com/username/aicommit"
   keywords = ["git", "commit", "ai", "llm", "cli"]
   classifiers = [
       "Development Status :: 4 - Beta",
       "Environment :: Console",
       "Intended Audience :: Developers",
       "Topic :: Software Development :: Version Control :: Git",
   ]
   ```

2. Create `LICENSE` file (MIT)

3. Build and publish:
   ```bash
   poetry build
   poetry publish
   ```

### 3.2 Installation via pip/pipx

Once on PyPI:
```bash
# Using pipx (recommended - isolated environment)
pipx install aicommit-cli

# Using pip
pip install aicommit-cli
```

---

## Phase 4: Homebrew Distribution (macOS)

### 4.1 Create Homebrew Formula

Create a formula at `Formula/aicommit.rb`:

```ruby
class Aicommit < Formula
  include Language::Python::Virtualenv

  desc "AI-powered git commit message generator"
  homepage "https://github.com/username/aicommit"
  url "https://files.pythonhosted.org/packages/.../aicommit-cli-1.0.0.tar.gz"
  sha256 "..."
  license "MIT"

  depends_on "python@3.12"

  # Dependencies would be listed here
  
  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/aicommit", "--help"
  end
end
```

### 4.2 Distribution Options

**Option A: Personal Tap (Easiest)**
```bash
# Create a tap repository: homebrew-aicommit
# Users install with:
brew tap username/aicommit
brew install aicommit
```

**Option B: Homebrew Core (Requires approval)**
- Submit PR to homebrew-core
- Requires meeting Homebrew's criteria (popularity, stability)

---

## Phase 5: APT Distribution (Debian/Ubuntu)

### 5.1 Create Debian Package

Structure:
```
aicommit_1.0.0-1/
├── DEBIAN/
│   ├── control           # Package metadata
│   ├── postinst          # Post-installation script
│   └── prerm             # Pre-removal script
├── usr/
│   ├── bin/
│   │   └── aicommit      # Entry point script
│   └── lib/
│       └── aicommit/     # Python package
└── etc/
    └── aicommit/         # Default config (optional)
```

### 5.2 control File

```
Package: aicommit
Version: 1.0.0-1
Section: devel
Priority: optional
Architecture: all
Depends: python3 (>= 3.12), python3-pip
Maintainer: Your Name <email@example.com>
Description: AI-powered git commit message generator
 Generate high-quality git commit messages from staged
 changes using various LLM providers.
```

### 5.3 Distribution Options

**Option A: Personal PPA (Easiest)**
```bash
# Create a PPA on Launchpad
# Users install with:
sudo add-apt-repository ppa:username/aicommit
sudo apt update
sudo apt install aicommit
```

**Option B: GitHub Releases with .deb files**
```bash
# Users download and install:
wget https://github.com/username/aicommit/releases/download/v1.0.0/aicommit_1.0.0-1_all.deb
sudo dpkg -i aicommit_1.0.0-1_all.deb
```

**Option C: Official Debian/Ubuntu repos (Requires approval)**
- Long process, requires package sponsorship

---

## Phase 6: Alternative - Self-Contained Binary

Using **PyInstaller** or **Nuitka** to create standalone executables:

### 6.1 Benefits
- No Python installation required by users
- Single binary distribution
- Easier packaging for apt/brew

### 6.2 Build Process

```bash
# Using PyInstaller
pyinstaller --onefile --name aicommit aicommit/cli.py

# Output: dist/aicommit (single executable)
```

### 6.3 Distribution
- GitHub Releases with binaries for Linux/macOS
- Homebrew formula pointing to binary
- .deb package containing binary

---

## Implementation Priority

### ✅ Immediate (Phase 1-2): Global Config Support - COMPLETED
1. ✅ Create `global_config.py` module
2. ✅ Add `~/.aicommit/` configuration support
3. ✅ Add `aicommit init` and `aicommit config` commands
4. ✅ Update API key loading to use credentials file
5. Update tests (in progress)

### Short-term (Phase 3): PyPI
1. Finalize package metadata
2. Publish to PyPI
3. Document `pipx install aicommit-cli`

### Medium-term (Phase 4-5): Package Managers
1. Create Homebrew tap and formula
2. Create .deb package or PPA
3. Document installation methods

### Optional (Phase 6): Standalone Binary
1. Evaluate PyInstaller/Nuitka
2. Set up CI/CD for binary builds
3. Distribute via GitHub Releases

---

## Recommended First Steps

1. **Implement Phase 1-2** (global config, CLI commands)
2. **Publish to PyPI** (enables `pipx install`)
3. **Create Homebrew tap** (easiest path for macOS)
4. **Create .deb on GitHub Releases** (easiest path for Linux)

This approach provides:
- Quick time to usable distribution
- No need for official package repository approval
- Easy updates via existing tools

---

## User Experience After Implementation

```bash
# macOS Installation
brew tap username/aicommit
brew install aicommit

# Ubuntu/Debian Installation
# Option 1: Download .deb from releases
wget https://github.com/.../aicommit_1.0.0_all.deb
sudo dpkg -i aicommit_1.0.0_all.deb

# Option 2: Use PPA
sudo add-apt-repository ppa:username/aicommit
sudo apt install aicommit

# First-time Setup (same on all platforms)
aicommit init
# Interactive prompts:
# > Select LLM provider: [google]
# > Enter your Google API key: [AI...]
# > Configuration saved to ~/.aicommit/

# Usage (in any git repo)
cd my-project
git add .
aicommit
```

---

## Questions to Resolve

1. **Package name**: `aicommit` vs `aicommit-cli` vs `ai-commit`?
2. **Minimum Python version**: Keep 3.12+ or support 3.10+?
3. **Binary distribution**: Worth the added complexity?
4. **Update mechanism**: How should users update?

---

## Next Steps

Once this plan is approved, I will implement:
1. Phase 1: Global configuration module (`~/.aicommit/`)
2. Phase 2: New CLI commands (`init`, `config`)
3. Update documentation and tests
