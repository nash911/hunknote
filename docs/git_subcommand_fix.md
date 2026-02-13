# Git Subcommand Issue and Solution

## Problem

When running `git hunknote --help`, you get:
```
No manual entry for git-hunknote
```

## Root Cause

Git looks for executables named `git-<subcommand>` in the PATH. The console scripts defined in `pyproject.toml` need to be installed via `poetry install` for them to be created in the virtualenv's `bin/` directory.

## Solution

After running `poetry install`, the following executables should be created:
- `~/.cache/pypoetry/virtualenvs/hunknote-*/bin/hunknote`
- `~/.cache/pypoetry/virtualenvs/hunknote-*/bin/git-hunknote`

When you activate the virtualenv with `poetry shell`, these executables are added to PATH, allowing `git hunknote` to work.

## Verification Steps

1. After `poetry install`, check if scripts exist:
   ```bash
   ls -la $(poetry env info --path)/bin/hunknote
   ls -la $(poetry env info --path)/bin/git-hunknote
   ```

2. In poetry shell, verify PATH includes virtualenv bin:
   ```bash
   echo $PATH | grep -o '[^:]*poetry[^:]*'
   ```

3. Test that `git hunknote` works:
   ```bash
   git hunknote --help
   ```

## Alternative: Manual Script Creation (Temporary Workaround)

If poetry install doesn't create the scripts, you can manually create a symlink or wrapper script:

```bash
# Create a simple wrapper script
cat > /tmp/git-hunknote << 'EOF'
#!/usr/bin/env python
import sys
from hunknote.cli import app
if __name__ == "__main__":
    app()
EOF

chmod +x /tmp/git-hunknote

# Add to PATH or move to a directory in PATH
# For testing:
export PATH="/tmp:$PATH"
git hunknote --help
```

## For Distribution

When the package is installed via pip/pipx globally, the console scripts will be installed system-wide, and `git hunknote` will work automatically.

