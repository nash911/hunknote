"""Tests for eval.environment — TargetEnv and TargetEnvManager."""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eval.environment import TargetEnv, TargetEnvManager
from eval.models import BuildSystemConfig


@pytest.fixture
def build_config():
    """Minimal build system config."""
    return BuildSystemConfig(
        type="python",
        install_commands=["pip install -r requirements.txt"],
        check_command="python -m py_compile {file}",
        import_check=True,
        test_command="python -m pytest -x",
        test_enabled=True,
    )


@pytest.fixture
def target_env(tmp_path, build_config):
    """A TargetEnv pointing at tmp_path (no real venv)."""
    venv_dir = tmp_path / ".eval_venv"
    venv_dir.mkdir()
    (venv_dir / "bin").mkdir()
    python_path = venv_dir / "bin" / "python"
    python_path.touch()
    return TargetEnv(
        repo_dir=tmp_path,
        venv_dir=venv_dir,
        python_path=python_path,
        config=build_config,
    )


class TestTargetEnvRun:
    def test_run_sets_virtual_env(self, target_env):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            target_env.run(["echo", "hello"])

        call_kwargs = mock_run.call_args
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env", {})
        assert env["VIRTUAL_ENV"] == str(target_env.venv_dir)

    def test_run_prepends_venv_bin_to_path(self, target_env):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            target_env.run(["echo", "test"])

        env = mock_run.call_args.kwargs.get("env") or mock_run.call_args[1].get("env", {})
        venv_bin = str(target_env.venv_dir / "bin")
        assert env["PATH"].startswith(venv_bin)

    def test_run_replaces_python_with_venv_python(self, target_env):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            target_env.run(["python", "-c", "print(1)"])

        resolved_cmd = mock_run.call_args[0][0]
        assert resolved_cmd[0] == str(target_env.python_path)
        assert resolved_cmd[1] == "-c"

    def test_run_does_not_replace_non_python_commands(self, target_env):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            target_env.run(["echo", "hello"])

        resolved_cmd = mock_run.call_args[0][0]
        assert resolved_cmd[0] == "echo"

    def test_run_uses_repo_dir_as_default_cwd(self, target_env):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            target_env.run(["echo", "test"])

        cwd = mock_run.call_args.kwargs.get("cwd") or mock_run.call_args[1].get("cwd")
        assert cwd == target_env.repo_dir

    def test_run_custom_cwd(self, target_env, tmp_path):
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            target_env.run(["echo", "test"], cwd=custom_dir)

        cwd = mock_run.call_args.kwargs.get("cwd") or mock_run.call_args[1].get("cwd")
        assert cwd == custom_dir

    def test_run_timeout_returns_negative_returncode(self, target_env):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="test", timeout=5)):
            result = target_env.run(["sleep", "100"], timeout=5)

        assert result.returncode == -1
        assert "timed out" in result.stderr.lower()

    def test_run_env_override(self, target_env):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            target_env.run(["echo"], env_override={"CUSTOM_VAR": "value"})

        env = mock_run.call_args.kwargs.get("env") or mock_run.call_args[1].get("env", {})
        assert env["CUSTOM_VAR"] == "value"

    def test_run_removes_pythonhome(self, target_env):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            with patch.dict(os.environ, {"PYTHONHOME": "/some/path"}):
                target_env.run(["echo", "test"])

        env = mock_run.call_args.kwargs.get("env") or mock_run.call_args[1].get("env", {})
        assert "PYTHONHOME" not in env


class TestTargetEnvCheckPythonVersion:
    def test_no_min_version_returns_true(self, target_env):
        target_env.config.python_version_min = None
        assert target_env.check_python_version() is True

    def test_compatible_version(self, target_env):
        target_env.config.python_version_min = "3.10"
        with patch.object(target_env, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Python 3.12.5", stderr=""
            )
            assert target_env.check_python_version() is True

    def test_incompatible_version(self, target_env):
        target_env.config.python_version_min = "3.13"
        with patch.object(target_env, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Python 3.12.5", stderr=""
            )
            assert target_env.check_python_version() is False

    def test_exact_version_match(self, target_env):
        target_env.config.python_version_min = "3.12"
        with patch.object(target_env, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Python 3.12.0", stderr=""
            )
            assert target_env.check_python_version() is True

    def test_version_check_failed_returns_false(self, target_env):
        target_env.config.python_version_min = "3.10"
        with patch.object(target_env, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="error"
            )
            assert target_env.check_python_version() is False

    def test_unparseable_version_returns_false(self, target_env):
        target_env.config.python_version_min = "3.10"
        with patch.object(target_env, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Python garbage", stderr=""
            )
            assert target_env.check_python_version() is False


class TestTargetEnvInstallDeps:
    def test_install_success(self, target_env):
        with patch.object(target_env, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            assert target_env.install_deps() is True
            assert target_env.is_ready is True

    def test_install_failure(self, target_env):
        with patch.object(target_env, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="error installing"
            )
            assert target_env.install_deps() is False
            assert target_env.is_ready is False
            assert len(target_env._setup_errors) > 0

    def test_pip_commands_use_python_m_pip(self, target_env):
        target_env.config.install_commands = ["pip install flask"]
        with patch.object(target_env, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            target_env.install_deps()

        call_args = mock_run.call_args[0][0]
        assert call_args[:3] == ["python", "-m", "pip"]
        assert "flask" in call_args

    def test_multiple_install_commands(self, target_env):
        target_env.config.install_commands = [
            "pip install -r requirements.txt",
            "pip install zstandard",
        ]
        with patch.object(target_env, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            assert target_env.install_deps() is True
            assert mock_run.call_count == 2

    def test_second_command_not_run_if_first_fails(self, target_env):
        target_env.config.install_commands = ["pip install bad", "pip install good"]
        with patch.object(target_env, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="fail"
            )
            assert target_env.install_deps() is False
            assert mock_run.call_count == 1


class TestTargetEnvDestroy:
    def test_destroy_removes_venv_dir(self, target_env):
        assert target_env.venv_dir.exists()
        target_env.destroy()
        assert not target_env.venv_dir.exists()

    def test_destroy_nonexistent_dir_no_error(self, target_env):
        target_env.venv_dir = target_env.repo_dir / "nonexistent"
        target_env.destroy()  # Should not raise


class TestTargetEnvManager:
    def test_create_env_creates_venv(self, tmp_path, build_config):
        env = TargetEnvManager.create_env(tmp_path, build_config)
        assert env.venv_dir.exists()
        assert env.python_path.exists()
        assert env.repo_dir == tmp_path
        assert env.is_ready is False  # Deps not yet installed

        # Cleanup
        env.destroy()

    def test_create_env_overwrites_existing_venv(self, tmp_path, build_config):
        venv_dir = tmp_path / ".eval_venv"
        venv_dir.mkdir()
        marker = venv_dir / "old_marker"
        marker.touch()

        env = TargetEnvManager.create_env(tmp_path, build_config)
        assert not marker.exists()

        env.destroy()

