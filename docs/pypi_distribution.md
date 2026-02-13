# PyPI Distribution Guide

This guide explains how to build and publish `hunknote` to PyPI.

## Prerequisites

1. **Poetry installed**: `pip install poetry`
2. **PyPI account**: Create account at https://pypi.org
3. **PyPI API token**: Generate at https://pypi.org/manage/account/token/
4. **Test PyPI account** (optional): For testing at https://test.pypi.org

## Configuration

### 1. Configure Poetry with PyPI Credentials

```bash
# Configure PyPI token
poetry config pypi-token.pypi your-api-token-here

# Optional: Configure Test PyPI
poetry config repositories.test-pypi https://test.pypi.org/legacy/
poetry config pypi-token.test-pypi your-test-api-token-here
```

### 2. Verify Package Metadata

Check that `pyproject.toml` has all required fields:
- `name`: "hunknote"
- `version`: Semantic version (e.g., "1.0.0")
- `description`: Brief description
- `authors`: List of authors
- `license`: "MIT"
- `readme`: "README.md"
- `homepage`, `repository`, `documentation`: URLs
- `keywords`: Searchable terms
- `classifiers`: PyPI classifiers

## Building the Package

### 1. Clean Previous Builds

```bash
# Remove old build artifacts
rm -rf dist/
rm -rf build/
rm -rf *.egg-info
```

### 2. Build Distribution Files

```bash
# Build both wheel and source distribution
poetry build
```

This creates:
- `dist/hunknote-1.0.0-py3-none-any.whl` (wheel)
- `dist/hunknote-1.0.0.tar.gz` (source distribution)

### 3. Verify Build

```bash
# Check the contents of the wheel
unzip -l dist/hunknote-1.0.0-py3-none-any.whl

# Check the contents of the tarball
tar -tzf dist/hunknote-1.0.0.tar.gz
```

## Testing Locally

### 1. Install from Local Build

```bash
# Install in a test environment
pipx install dist/hunknote-1.0.0-py3-none-any.whl

# Or with pip
pip install dist/hunknote-1.0.0-py3-none-any.whl
```

### 2. Test Installation

```bash
# Verify command is available
which hunknote

# Test help
hunknote --help

# Test git subcommand
git hunknote --help

# Test init
hunknote init
```

### 3. Uninstall

```bash
pipx uninstall hunknote
# Or: pip uninstall hunknote
```

## Publishing to Test PyPI (Optional but Recommended)

### 1. Publish to Test PyPI

```bash
poetry publish -r test-pypi
```

### 2. Install from Test PyPI

```bash
pipx install --index-url https://test.pypi.org/simple/ hunknote
```

### 3. Test and Verify

Run all your tests to ensure the package works correctly.

## Publishing to PyPI

### 1. Final Checks

- [ ] All tests pass: `pytest tests/`
- [ ] Version number updated in `pyproject.toml`
- [ ] CHANGELOG.md updated (if you have one)
- [ ] README.md is up to date
- [ ] LICENSE file exists
- [ ] Build is clean: `poetry build`

### 2. Publish to PyPI

```bash
# This will upload to PyPI
poetry publish
```

You'll be prompted to confirm. Type 'yes' to proceed.

### 3. Verify Publication

Visit: https://pypi.org/project/hunknote/

## Post-Publication

### 1. Test Installation from PyPI

```bash
# Install using pipx (recommended)
pipx install hunknote

# Verify it works
hunknote --help
```

### 2. Update Documentation

Update README.md and other docs to reflect the new version:

```markdown
## Installation

```bash
# Using pipx (recommended - isolated environment)
pipx install hunknote

# Using pip
pip install hunknote
```
```

### 3. Create Git Tag

```bash
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0
```

### 4. Create GitHub Release

1. Go to your repository on GitHub
2. Click "Releases" → "Create a new release"
3. Select the tag you just created
4. Add release notes
5. Attach build artifacts (optional)

## Updating an Existing Package

### 1. Bump Version

Edit `pyproject.toml`:
```toml
version = "1.0.1"  # Increment version
```

Or use Poetry:
```bash
# Patch version (1.0.0 -> 1.0.1)
poetry version patch

# Minor version (1.0.0 -> 1.1.0)
poetry version minor

# Major version (1.0.0 -> 2.0.0)
poetry version major
```

### 2. Rebuild and Republish

```bash
# Clean old builds
rm -rf dist/

# Build new version
poetry build

# Publish
poetry publish
```

## Troubleshooting

### "File already exists" Error

This means you're trying to upload a version that already exists on PyPI. You must:
1. Increment the version number in `pyproject.toml`
2. Rebuild: `poetry build`
3. Republish: `poetry publish`

Note: You **cannot** replace an existing version on PyPI.

### Import Errors After Installation

Ensure `pyproject.toml` has the correct package configuration:
```toml
packages = [{include = "hunknote"}]
```

### Missing Dependencies

Check that all dependencies are listed in `[tool.poetry.dependencies]` section.

### Console Scripts Not Working

Verify `[tool.poetry.scripts]` section:
```toml
[tool.poetry.scripts]
hunknote = "hunknote.cli:app"
git-hunknote = "hunknote.cli:app"
```

## Best Practices

1. **Always test locally first**: Install from local wheel before publishing
2. **Use Test PyPI**: Test the full upload/download cycle
3. **Semantic versioning**: Follow semver.org
4. **Keep dependencies minimal**: Only include what's necessary
5. **Pin major versions**: Use `^` for dependencies (e.g., `^1.0.0`)
6. **Document breaking changes**: In CHANGELOG.md and release notes
7. **Automated CI/CD**: Consider GitHub Actions for automated publishing

## Example GitHub Actions Workflow

Create `.github/workflows/publish.yml`:

```yaml
name: Publish to PyPI

on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      
      - name: Install Poetry
        run: pip install poetry
      
      - name: Build package
        run: poetry build
      
      - name: Publish to PyPI
        env:
          POETRY_PYPI_TOKEN_PYPI: ${{ secrets.PYPI_API_TOKEN }}
        run: poetry publish
```

## Resources

- Poetry documentation: https://python-poetry.org/docs/
- PyPI: https://pypi.org
- Test PyPI: https://test.pypi.org
- Packaging Python Projects: https://packaging.python.org/tutorials/packaging-projects/
- Semantic Versioning: https://semver.org

