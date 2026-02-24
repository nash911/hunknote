"""AI Commit Message Generator CLI tool."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("hunknote")
except PackageNotFoundError:
    # Fallback for development mode
    __version__ = "0.0.0-dev"
