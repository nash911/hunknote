# Quick PyPI Publishing Guide

## One-Time Setup

### 1. Create PyPI Account
- Go to https://pypi.org
- Click "Register"
- Verify your email

### 2. Generate API Token
- Log in to PyPI
- Go to https://pypi.org/manage/account/token/
- Click "Add API token"
- Name: `hunknote-publish`
- Scope: Select "Entire account" or create project-specific token later
- **Save the token** - you'll only see it once!

### 3. Configure Poetry
```bash
poetry config pypi-token.pypi pypi-YOUR_TOKEN_HERE
```

## Publishing a New Version

### Quick Steps
```bash
# 1. Update version
poetry version patch  # or minor, or major

# 2. Clean and build
rm -rf dist/
poetry build

# 3. Verify build
ls -lh dist/

# 4. Test locally (optional but recommended)
pip install dist/*.whl
hunknote --help
pip uninstall hunknote

# 5. Publish to PyPI
poetry publish

# 6. Verify
# Visit: https://pypi.org/project/hunknote/

# 7. Test install from PyPI
pipx install hunknote
hunknote --help
```

## For First-Time Publication

If this is the first time publishing `hunknote`:

```bash
# Make sure you're on version 1.0.0
# Check pyproject.toml:
# version = "1.0.0"

# Build
poetry build

# Publish (will create new project on PyPI)
poetry publish

# The package will now be available at:
# https://pypi.org/project/hunknote/
```

## Testing Before Publishing

Use Test PyPI to safely test the publishing workflow:

```bash
# 1. Create account at https://test.pypi.org
# 2. Generate token
# 3. Configure Poetry
poetry config repositories.test-pypi https://test.pypi.org/legacy/
poetry config pypi-token.test-pypi pypi-YOUR_TEST_TOKEN_HERE

# 4. Build and publish to Test PyPI
poetry build
poetry publish -r test-pypi

# 5. Test install
pipx install --index-url https://test.pypi.org/simple/ hunknote

# 6. Clean up test
pipx uninstall hunknote
```

## After Publishing

```bash
# Create git tag
git tag v1.0.0
git push origin v1.0.0

# Create GitHub Release
# Go to: https://github.com/your-repo/releases/new
# Select tag v1.0.0
# Add release notes
```

## Common Issues

### "File already exists"
- You're trying to upload a version that already exists
- Solution: Bump version number and rebuild

### "Invalid or non-existent authentication"
- API token is wrong or expired
- Solution: Regenerate token and reconfigure Poetry

### "Package name already taken"
- Someone else owns `hunknote` on PyPI
- Solution: Choose a different name in pyproject.toml

### Import errors after install
- Package structure issue
- Solution: Check `packages = [{include = "hunknote"}]` in pyproject.toml

## Version Numbering

Follow Semantic Versioning (semver.org):

- **MAJOR** (1.0.0 → 2.0.0): Breaking changes
- **MINOR** (1.0.0 → 1.1.0): New features, backwards compatible
- **PATCH** (1.0.0 → 1.0.1): Bug fixes only

```bash
# Bump versions with Poetry
poetry version patch   # 1.0.0 → 1.0.1
poetry version minor   # 1.0.0 → 1.1.0
poetry version major   # 1.0.0 → 2.0.0
```

## Installation Methods

Once published, users can install with:

```bash
# Recommended: pipx (isolated environment)
pipx install hunknote

# Alternative: pip
pip install hunknote

# Specific version
pipx install hunknote==1.0.0

# Upgrade
pipx upgrade hunknote
# or: pip install --upgrade hunknote
```

## Resources

- PyPI: https://pypi.org
- Test PyPI: https://test.pypi.org
- Poetry Docs: https://python-poetry.org/docs/libraries/
- Packaging Guide: https://packaging.python.org

