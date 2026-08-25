# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 6.x onedir spec for AronaAI
# Build: .\.venv\Scripts\pyinstaller.exe AronaAI.spec --noconfirm --clean

import os

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('Assets/Font/ResourceHanRoundedCN-Medium.ttf', 'Assets/Font'),
        ('Assets/homepage.png', 'Assets'),
        ('Assets/HomePage/homepage.png', 'Assets/HomePage'),
        ('Assets/Logo/icon.ico', 'Assets/Logo'),
        ('Assets/Logo/Logo.png', 'Assets/Logo'),
        ('Assets/Chat/config.ini', 'Assets/Chat'),
        ('Assets/Chat/arona/logo.png', 'Assets/Chat/arona'),
        ('Assets/Chat/plana/logo.png', 'Assets/Chat/plana'),
        ('Assets/Spine/config.ini', 'Assets/Spine'),
        ('Assets/Spine/web/index.html', 'Assets/Spine/web'),
        ('LICENSE', '.'),
        ('COPYRIGHT', '.'),
    ],
    hiddenimports=[
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebChannel',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'playwright', 'numpy', 'quickjs'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)



# Qt6 shared libraries that the 16 collected .pyd bindings and Qt6WebEngineCore
# actually link against (transitive closure, verified via bindepend).
QT6_KEEP = {
    'Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Network.dll', 'Qt6OpenGL.dll',
    'Qt6Positioning.dll', 'Qt6PrintSupport.dll', 'Qt6Qml.dll',
    'Qt6QmlMeta.dll', 'Qt6QmlModels.dll', 'Qt6QmlWorkerScript.dll',
    'Qt6Quick.dll', 'Qt6QuickWidgets.dll', 'Qt6Svg.dll', 'Qt6SvgWidgets.dll',
    'Qt6WebChannel.dll', 'Qt6WebEngineCore.dll', 'Qt6WebEngineWidgets.dll',
    'Qt6Widgets.dll', 'Qt6Xml.dll',
}

# QML modules that QtWebEngine/Quick does not use in this app.
QML_DROP_TOP = {
    'Qt3D', 'Qt5Compat', 'QtCharts', 'QtDataVisualization', 'QtGraphs',
    'QtLocation', 'QtMultimedia', 'QtPositioning', 'QtQuick3D',
    'QtRemoteObjects', 'QtScxml', 'QtSensors', 'QtTest', 'QtTextToSpeech',
    'QtVirtualKeyboard', 'QtWebSockets', 'QtWebView',
}
QML_DROP_QUICK = {
    'Controls', 'Dialogs', 'Effects', 'LocalStorage', 'NativeStyle',
    'Particles', 'Pdf', 'Scene2D', 'Scene3D', 'Shapes', 'Templates',
    'Timeline', 'VectorImage', 'VirtualKeyboard', 'Window',
}

# Plugins that exist only to serve dropped Qt modules (each links a dropped Qt6 dll).
PLUGIN_DROP_DIRS = {
    'platforminputcontexts', 'position', 'qmltooling',
}
PLUGIN_DROP_FILES = {
    # imageformats/qpdf.dll depends on Qt6Pdf.dll, which is pruned.
    'imageformats/qpdf.dll',
}

TRANSLATION_KEEP_TAILS = ('_zh_CN.qm', '_en.qm', '_zh.qm', '_en_US.qm')


def _prune_binaries(toc):
    kept = []
    for dest, src, typecode in toc:
        rel = os.path.normpath(dest).replace('\\', '/')
        head, base = os.path.split(rel)
        drop = False

        # Top-level Qt6*.dll not in the keep-set.
        if head == 'PySide6' and base.startswith('Qt6') and base.endswith('.dll'):
            if base not in QT6_KEEP:
                drop = True

        # Unused Qt plugins.
        if head.startswith('PySide6/plugins/'):
            plugin_rel = head[len('PySide6/plugins/'):]
            plugin_type = plugin_rel.split('/')[0]
            if plugin_type in PLUGIN_DROP_DIRS:
                drop = True
            if plugin_rel + '/' + base in PLUGIN_DROP_FILES:
                drop = True

        # QML plugins/binaries for modules we do not use.
        if head.startswith('PySide6/qml/'):
            qml_rel = head[len('PySide6/qml/'):]
            parts = qml_rel.split('/')
            if parts and parts[0] in QML_DROP_TOP:
                drop = True
            elif parts and parts[0] == 'QtQuick' and len(parts) > 1 and parts[1] in QML_DROP_QUICK:
                drop = True

        # Debug-only webengine resources (release paks are kept).
        if head == 'PySide6/resources' and '.debug.' in base:
            drop = True

        if not drop:
            kept.append((dest, src, typecode))
    return kept


def _prune_datas(toc):
    kept = []
    for dest, src, typecode in toc:
        rel = os.path.normpath(dest).replace('\\', '/')
        head, base = os.path.split(rel)
        drop = False

        # QML module data for modules we do not use.
        if head.startswith('PySide6/qml/'):
            qml_rel = head[len('PySide6/qml/'):]
            parts = qml_rel.split('/')
            if parts and parts[0] in QML_DROP_TOP:
                drop = True
            elif parts and parts[0] == 'QtQuick' and len(parts) > 1 and parts[1] in QML_DROP_QUICK:
                drop = True

        # Debug-only webengine resources.
        if head == 'PySide6/resources' and '.debug.' in base:
            drop = True

        # Keep only a slim set of Qt translations (app has no QTranslator).
        if head == 'PySide6/translations' and not base.endswith(TRANSLATION_KEEP_TAILS):
            drop = True

        if not drop:
            kept.append((dest, src, typecode))
    return kept


a.binaries = _prune_binaries(a.binaries)
a.datas = _prune_datas(a.datas)

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
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['Assets/Logo/icon.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='AronaAI',
)
