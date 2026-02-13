# Build and Release Checklist

Use this checklist before publishing a new version to PyPI.

## Pre-Release Checklist

### Code Quality
- [ ] All tests pass: `pytest tests/`
- [ ] No linting errors: `ruff check hunknote/` (if using ruff)
- [ ] Code is properly formatted
- [ ] All import statements are correct
- [ ] No debug print statements or commented code

### Documentation
- [ ] README.md is up to date
- [ ] CHANGELOG.md has entry for this version (if you maintain one)
- [ ] Docstrings are complete and accurate
- [ ] Installation instructions are correct
- [ ] Examples are tested and working

### Version Management
- [ ] Version number updated in `pyproject.toml`
- [ ] Version follows semantic versioning (MAJOR.MINOR.PATCH)
- [ ] Breaking changes are documented
- [ ] Git tag created for version: `git tag v1.0.0`

### Package Configuration
- [ ] `pyproject.toml` metadata is complete:
  - [ ] name
  - [ ] version
  - [ ] description
  - [ ] authors
  - [ ] license
  - [ ] homepage
  - [ ] repository
  - [ ] keywords
  - [ ] classifiers
- [ ] LICENSE file exists
- [ ] README.md exists
- [ ] All dependencies are listed with appropriate version constraints

### Build
- [ ] Clean previous builds: `rm -rf dist/`
- [ ] Build succeeds: `poetry build`
- [ ] Wheel file created: `dist/hunknote-*.whl`
- [ ] Source distribution created: `dist/hunknote-*.tar.gz`
- [ ] Inspect wheel contents: `unzip -l dist/hunknote-*.whl`
- [ ] Verify entry points are correct
- [ ] Verify all Python files are included
- [ ] Verify LICENSE is included

## Testing the Build

### Local Installation Test
- [ ] Install from wheel: `pip install dist/hunknote-*.whl`
- [ ] Verify command works: `hunknote --help`
- [ ] Verify git subcommand works: `git hunknote --help`
- [ ] Test basic functionality: `hunknote init`
- [ ] Test config commands: `hunknote config show`
- [ ] Uninstall: `pip uninstall hunknote`

### Test PyPI (Optional but Recommended)
- [ ] Configure Test PyPI repository
- [ ] Publish to Test PyPI: `poetry publish -r test-pypi`
- [ ] Install from Test PyPI: `pip install --index-url https://test.pypi.org/simple/ hunknote`
- [ ] Test all functionality
- [ ] Uninstall: `pip uninstall hunknote`

## Publishing to PyPI

### Final Verification
- [ ] All tests above passed
- [ ] Git working directory is clean (all changes committed)
- [ ] You're on the main/master branch
- [ ] All changes are pushed to remote repository

### Publish
- [ ] Configure PyPI token: `poetry config pypi-token.pypi your-token`
- [ ] Publish: `poetry publish`
- [ ] Verify publication at https://pypi.org/project/hunknote/

### Post-Publication
- [ ] Test installation from PyPI: `pipx install hunknote`
- [ ] Verify functionality: `hunknote --help`
- [ ] Create GitHub release with tag
- [ ] Update documentation with new version
- [ ] Announce release (if applicable)

## Version Bump Workflow

### Patch Release (1.0.0 → 1.0.1)
Bug fixes only, no new features.

```bash
poetry version patch
git add pyproject.toml
git commit -m "Bump version to 1.0.1"
git tag v1.0.1
# Follow build and release checklist
```

### Minor Release (1.0.0 → 1.1.0)
New features, backwards compatible.

```bash
poetry version minor
git add pyproject.toml
git commit -m "Bump version to 1.1.0"
git tag v1.1.0
# Follow build and release checklist
```

### Major Release (1.0.0 → 2.0.0)
Breaking changes.

```bash
poetry version major
git add pyproject.toml
git commit -m "Bump version to 2.0.0"
git tag v2.0.0
# Follow build and release checklist
# Update migration guide
```

## Troubleshooting

### Build Fails
- Check `pyproject.toml` syntax
- Ensure all files referenced exist
- Check for circular imports

### Installation Fails
- Verify dependencies are correct
- Check Python version compatibility
- Ensure package name isn't already taken

### Commands Not Working After Install
- Check entry_points in wheel
- Verify `[tool.poetry.scripts]` section
- Ensure CLI module has correct app object

### Cannot Upload to PyPI
- Verify API token is configured
- Check version doesn't already exist
- Ensure package name is available
- Check for file size limits

## Quick Command Reference

```bash
# Check configuration
poetry check

# Clean old builds
rm -rf dist/ build/ *.egg-info

# Build package
poetry build

# Inspect wheel
unzip -l dist/*.whl

# Install locally for testing
pip install dist/*.whl

# Publish to Test PyPI
poetry publish -r test-pypi

# Publish to PyPI
poetry publish

# Bump version
poetry version patch  # or minor, major

# Create git tag
git tag v1.0.0
git push origin v1.0.0
```

