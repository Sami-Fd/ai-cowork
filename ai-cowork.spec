# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for AI Cowork."""

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
        'mss', 'mss.windows',
        'pytesseract',
        'PIL', 'PIL.Image', 'PIL.ImageEnhance', 'PIL.ImageFilter', 'PIL.ImageOps',
        'flask', 'flask_cors',
        'dotenv',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
