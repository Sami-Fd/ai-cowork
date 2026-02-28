# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for AI Cowork.

Build with:
    pip install pyinstaller
    pyinstaller ai-cowork.spec

Output: dist/ai-cowork/  (folder with ai-cowork.exe)
"""

import os
import sys

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('.env.example', '.'),
    ],
    hiddenimports=[
        # Screen capture
        'mss', 'mss.windows', 'mss.base', 'mss.screenshot',
        # OCR
        'pytesseract',
        # Image processing
        'PIL', 'PIL.Image', 'PIL.ImageEnhance', 'PIL.ImageFilter', 'PIL.ImageOps',
        # Web server
        'flask', 'flask.json', 'flask_cors',
        'jinja2', 'markupsafe',
        'werkzeug', 'werkzeug.serving', 'werkzeug.debug',
        # HTTP client
        'requests', 'urllib3', 'certifi', 'charset_normalizer', 'idna',
        # Config
        'dotenv', 'python-dotenv',
        # Windows APIs
        'ctypes', 'ctypes.wintypes',
        # Standard library
        'json', 'io', 'threading', 'time', 'webbrowser', 'logging',
        'collections', 'shutil',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'unittest', 'test',
        'numpy', 'scipy', 'pandas', 'matplotlib',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ai-cowork',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # console=True keeps a terminal window open to show logs
    # Set to False for a cleaner look (no terminal)
    console=True,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ai-cowork',
)
