# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for building hunknote standalone binary.

Usage:
    pyinstaller hunknote.spec
"""

import sys
from pathlib import Path

# Get the project root
project_root = Path(SPECPATH)

a = Analysis(
    ['hunknote/__main__.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Core hunknote modules
        'hunknote',
        'hunknote.cli',
        'hunknote.cli.main',
        'hunknote.cli.commit',
        'hunknote.cli.compose',
        'hunknote.cli.config_cmd',
        'hunknote.cli.scope',
        'hunknote.cli.styles',
        'hunknote.cli.utils',
        'hunknote.compose',
        'hunknote.compose.models',
        'hunknote.compose.parser',
        'hunknote.compose.inventory',
        'hunknote.compose.validation',
        'hunknote.compose.patch',
        'hunknote.compose.prompt',
        'hunknote.compose.executor',
        'hunknote.compose.cleanup',
        'hunknote.cache',
        'hunknote.cache.models',
        'hunknote.cache.paths',
        'hunknote.cache.commit',
        'hunknote.cache.compose',
        'hunknote.git',
        'hunknote.git.context',
        'hunknote.git.operations',
        'hunknote.styles',
        'hunknote.styles.models',
        'hunknote.styles.profiles',
        'hunknote.styles.formatters',
        'hunknote.llm',
        'hunknote.llm.base',
        'hunknote.llm.prompts',
        'hunknote.llm.providers',
        'hunknote.config',
        'hunknote.user_config',
        'hunknote.global_config',
        'hunknote.scope',
        'hunknote.formatters',
        # LLM provider SDKs
        'anthropic',
        'openai',
        'google.genai',
        'google.generativeai',
        'mistralai',
        'cohere',
        'groq',
        # Dependencies
        'typer',
        'click',
        'pydantic',
        'pydantic_core',
        'dotenv',
        'yaml',
        'httpx',
        'httpcore',
        'anyio',
        'sniffio',
        'certifi',
        'idna',
        'charset_normalizer',
        'urllib3',
        'requests',
        # Keyring and backends
        'keyring',
        'keyring.backends',
        'keyring.backend',
        'secretstorage',
        'jeepney',
        'jaraco',
        'jaraco.classes',
        'jaraco.context',
        'jaraco.functools',
        # Encoding support
        'encodings',
        'codecs',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude test modules
        'pytest',
        'pytest_mock',
        '_pytest',
        # Exclude development tools
        'pip',
        'setuptools',
        'wheel',
        # Exclude unnecessary stdlib
        'tkinter',
        'unittest',
        'xml.etree.ElementTree',
    ],
    noarchive=False,
    optimize=2,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=None,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='hunknote',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

