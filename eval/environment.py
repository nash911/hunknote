"""Target project virtual environment management.

Creates isolated venvs for target projects so mechanical validation
(py_compile, import checks, pytest) runs against the target's own
dependencies, not hunknote's.
"""

import logging
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from eval.config import EVAL_VENVS_CACHE_DIR
from eval.models import BuildSystemConfig

logger = logging.getLogger(__name__)


@dataclass
class TargetEnv:
    """An isolated virtual environment for a target project."""

    repo_dir: Path
    venv_dir: Path
    python_path: Path
    config: BuildSystemConfig
    is_ready: bool = False
    _setup_errors: list[str] = field(default_factory=list)

    def run(
        self,
        cmd: list[str],
        timeout: int = 120,
        cwd: Optional[Path] = None,
        env_override: Optional[dict] = None,
    ) -> subprocess.CompletedProcess:
        """Run a command using the target venv's Python.

        All subprocess calls for validation go through this method.
        It prepends the venv's bin/ to PATH and sets VIRTUAL_ENV.

        Args:
            cmd: Command to run. "python" is replaced with the venv's interpreter.
            timeout: Timeout in seconds.
            cwd: Working directory (default: repo_dir).
            env_override: Additional environment variables.

        Returns:
            CompletedProcess with stdout, stderr, returncode.
        """
        env = os.environ.copy()
        env["VIRTUAL_ENV"] = str(self.venv_dir)
        env["PATH"] = str(self.venv_dir / "bin") + ":" + env.get("PATH", "")
        # Remove PYTHONHOME if set (can interfere with venv activation)
        env.pop("PYTHONHOME", None)

        if env_override:
            env.update(env_override)

        # Replace "python" with the venv's Python
        resolved_cmd = list(cmd)
        if resolved_cmd and resolved_cmd[0] == "python":
            resolved_cmd[0] = str(self.python_path)

        try:
            return subprocess.run(
                resolved_cmd,
                capture_output=True,
                text=True,
                cwd=cwd or self.repo_dir,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Command timed out after %ds: %s", timeout, " ".join(resolved_cmd))
            return subprocess.CompletedProcess(
                args=resolved_cmd,
                returncode=-1,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
            )

    def check_python_version(self) -> bool:
        """Verify the venv Python meets the minimum version requirement.

        Returns:
            True if compatible, False otherwise.
        """
        if not self.config.python_version_min:
            return True

        result = self.run(["python", "--version"])
        if result.returncode != 0:
            logger.warning("Failed to get Python version: %s", result.stderr)
            return False

        # Parse "Python 3.11.5"
        version_str = result.stdout.strip().split()[-1]
        try:
            parts = [int(x) for x in version_str.split(".")[:2]]
            min_parts = [int(x) for x in self.config.python_version_min.split(".")[:2]]
            return parts >= min_parts
        except (ValueError, IndexError):
            logger.warning("Could not parse Python version: %s", version_str)
            return False

    def install_deps(self) -> bool:
        """Install target project dependencies in the venv.

        Runs each command from config.install_commands using the venv's pip.

        Returns:
            True if all installations succeeded.
        """
        for cmd_str in self.config.install_commands:
            parts = shlex.split(cmd_str)
            if parts and parts[0] == "pip":
                parts = ["python", "-m", "pip"] + parts[1:]

            logger.info("Installing deps: %s", cmd_str)
            result = self.run(parts, timeout=300)  # 5 min timeout
            if result.returncode != 0:
                error_msg = f"Dep install failed: {cmd_str}\n{result.stderr}"
                logger.error(error_msg)
                self._setup_errors.append(error_msg)
                return False

        self.is_ready = True
        return True

    def destroy(self) -> None:
        """Remove the venv directory."""
        if self.venv_dir.exists():
            shutil.rmtree(self.venv_dir, ignore_errors=True)
            logger.debug("Destroyed venv at %s", self.venv_dir)


class TargetEnvManager:
    """Manages creation, caching, and cleanup of target project environments."""

    CACHE_DIR = EVAL_VENVS_CACHE_DIR

    @classmethod
    def create_env(
        cls,
        repo_dir: Path,
        config: BuildSystemConfig,
        use_cache: bool = True,
    ) -> TargetEnv:
        """Create an isolated venv for the target project.

        Args:
            repo_dir: Path to the extracted repo directory.
            config: Build system configuration.
            use_cache: Whether to use venv caching (reserved for future use).

        Returns:
            A TargetEnv instance (deps NOT yet installed — call install_deps()).
        """
        venv_dir = repo_dir / ".eval_venv"

        if venv_dir.exists():
            shutil.rmtree(venv_dir)

        # Create venv using the same Python that runs hunknote
        logger.info("Creating venv at %s", venv_dir)
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True,
            capture_output=True,
        )

        # Determine Python path in the venv
        python_path = venv_dir / "bin" / "python"
        if not python_path.exists():
            python_path = venv_dir / "Scripts" / "python.exe"  # Windows

        if not python_path.exists():
            raise RuntimeError(f"Could not find Python in venv at {venv_dir}")

        target_env = TargetEnv(
            repo_dir=repo_dir,
            venv_dir=venv_dir,
            python_path=python_path,
            config=config,
        )

        # Upgrade pip silently
        target_env.run(
            ["python", "-m", "pip", "install", "--upgrade", "pip", "-q"],
            timeout=120,
        )

        return target_env

    @classmethod
    def cleanup_cache(cls) -> None:
        """Remove all cached venvs."""
        if cls.CACHE_DIR.exists():
            shutil.rmtree(cls.CACHE_DIR)
            logger.info("Cleaned up venv cache at %s", cls.CACHE_DIR)
