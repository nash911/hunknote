# Git Subcommand Issue and Solution

## Problem

When running `git aicommit --help`, you get:
```
No manual entry for git-aicommit
```

## Root Cause

Git looks for executables named `git-<subcommand>` in the PATH. The console scripts defined in `pyproject.toml` need to be installed via `poetry install` for them to be created in the virtualenv's `bin/` directory.

## Solution

After running `poetry install`, the following executables should be created:
- `~/.cache/pypoetry/virtualenvs/aicommit-*/bin/aicommit`
- `~/.cache/pypoetry/virtualenvs/aicommit-*/bin/git-aicommit`

When you activate the virtualenv with `poetry shell`, these executables are added to PATH, allowing `git aicommit` to work.

## Verification Steps

1. After `poetry install`, check if scripts exist:
   ```bash
   ls -la $(poetry env info --path)/bin/aicommit
   ls -la $(poetry env info --path)/bin/git-aicommit
   ```

2. In poetry shell, verify PATH includes virtualenv bin:
   ```bash
   echo $PATH | grep -o '[^:]*poetry[^:]*'
   ```

3. Test that `git aicommit` works:
   ```bash
   git aicommit --help
   ```

## Alternative: Manual Script Creation (Temporary Workaround)

If poetry install doesn't create the scripts, you can manually create a symlink or wrapper script:

```bash
# Create a simple wrapper script
cat > /tmp/git-aicommit << 'EOF'
#!/usr/bin/env python
import sys
from aicommit.cli import app
if __name__ == "__main__":
    app()
EOF

chmod +x /tmp/git-aicommit

# Add to PATH or move to a directory in PATH
# For testing:
export PATH="/tmp:$PATH"
git aicommit --help
```

## For Distribution

When the package is installed via pip/pipx globally, the console scripts will be installed system-wide, and `git aicommit` will work automatically.

