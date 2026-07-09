# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# Datas: (src_path, dest_dir_relative_to_bundle_root)
datas = [
    ('backend/app', 'backend/app'),
    ('frontend/dist/index.html', 'frontend/dist'),
    ('scripts', 'scripts'),
    ('tools/vendor/ndlocr-lite/src', 'tools/vendor/ndlocr-lite/src'),
    ('tools/vendor/ndlocr-lite/pyproject.toml', 'tools/vendor/ndlocr-lite'),
]

# Collect additional data files for installed libraries
datas += collect_data_files('pypdfium2')
try:
    datas += collect_data_files('gliner')
    datas += collect_data_files('glirel')
except Exception:
    pass

hiddenimports = [
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan.on',
    'uvicorn.loops.auto',
    'fastapi',
    'pypdfium2',
    'PIL',
    'deim',
    'parseq',
    'reading_order',
    'ndl_parser',
    'tcy_wrapper',
    'tablerecog',
    'huggingface_hub',
]

a = Analysis(
    ['backend/app/main.py'],
    pathex=['backend', 'tools/vendor/ndlocr-lite/src'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='koshu-ocr-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='koshu-ocr-backend',
)
