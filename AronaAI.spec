# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('Assets', 'Assets'),
        ('Audio', 'Audio'),
        ('Images', 'Images'),
        ('fonts', 'fonts'),
        # 必须替换为你的实际 win32com 路径！
        ('E:\\py\\AronaAI\\.venv\\lib\\site-packages\\win32com', 'win32com'),
        # 也复制 pywin32_system32（如果存在）
        ('E:\\py\\AronaAI\\.venv\\lib\\site-packages\\pywin32_system32', 'pywin32_system32'),
    ],
    hiddenimports=[
        'pythoncom',
        'pywintypes',
        'win32com',
        'win32com.client',
        'win32com.server',
        'PyQt5',            # 可选
        'qfluentwidgets',   # 可选
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
    name='AronaAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='Assets\\icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AronaAI',
)