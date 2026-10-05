# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 6.x onedir spec for AronaAI - builds BOTH outputs in one run:
#   1) dist\AronaAI\      main program (no torch/gsv, TTS stays external)
#   2) dist\AronaAI-TTS\  standalone TTS module -> move into the main folder as TTS\
#      AronaAI/TTS/AronaAI-TTS.exe + AronaAI/TTS/_internal/...
# Voice packs (.ckpt/.pth in Assets/TTS) are part of neither package; the main
# program sends their absolute paths over the stdio JSON protocol.
# Build: .\.venv\Scripts\pyinstaller.exe AronaAI.spec --noconfirm --clean

import os

block_cipher = None


# ===========================================================================
# Shared helpers
# ===========================================================================

# Qt6 shared libraries that the 16 collected .pyd bindings and Qt6WebEngineCore
# actually link against (transitive closure, verified via bindepend).
QT6_KEEP = {
    'Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Network.dll', 'Qt6OpenGL.dll',
    'Qt6Positioning.dll', 'Qt6PrintSupport.dll', 'Qt6Qml.dll',
    'Qt6QmlMeta.dll', 'Qt6QmlModels.dll', 'Qt6QmlWorkerScript.dll',
    'Qt6Quick.dll', 'Qt6QuickWidgets.dll', 'Qt6Svg.dll', 'Qt6SvgWidgets.dll',
    'Qt6Multimedia.dll', 'Qt6MultimediaWidgets.dll',
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


def _prune_qt_binaries(toc):
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


def _prune_qt_datas(toc):
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


def _collect_tts_datas():
    extra = []

    # Data files loaded via importlib.resources / package paths at runtime.
    try:
        from PyInstaller.utils.hooks import collect_data_files, copy_metadata

        for pkg in ('pyopenjtalk', 'py3langid', 'wordsegment', 'jieba',
                    'sudachidict_core', 'sounddevice'):
            extra += collect_data_files(pkg)
        # torch/transformers read their version through importlib.metadata.
        extra += copy_metadata('torch')
    except Exception as exc:  # pragma: no cover - build-time only
        print(f'AronaAI-TTS: data collection failed: {exc}')

    # gsv_tts sources: SoVITS/commons.py applies @torch.jit.script at import
    # time, which needs the original .py via inspect/linecache (frozen
    # co_filename is PYZ-relative and resolves against the child cwd or MEIPASS).
    try:
        import importlib.util as ilu
        gsv_spec = ilu.find_spec('gsv_tts')
        if gsv_spec and gsv_spec.origin:
            gsv_pkg = os.path.dirname(gsv_spec.origin)
            gsv_root = os.path.dirname(gsv_pkg)
            for root, dirs, files in os.walk(gsv_pkg):
                dirs[:] = [d for d in dirs if d != '__pycache__']
                rel = os.path.relpath(root, gsv_root)
                for f in files:
                    if f.endswith('.py'):
                        extra.append((os.path.join(root, f), rel))
    except Exception as exc:  # pragma: no cover - build-time only
        print(f'AronaAI-TTS: gsv_tts sources not found: {exc}')

    # Pretrained base models (~1GB) are intentionally NOT bundled: the app
    # downloads them on first run into <exe_dir>\gsv_models (a single folder
    # next to AronaAI.exe) with a progress console.

    return extra


def _prune_tts_datas(toc):
    kept = []
    for dest, src, typecode in toc:
        rel = os.path.normpath(dest).replace('\\', '/')
        drop = False

        # torch dev files (headers / cmake / share) are useless at runtime.
        if rel.startswith(('torch/include/', 'torch/share/', 'torch/cmake/')):
            drop = True

        # Byte-compiled caches are never needed as data.
        if '__pycache__' in rel.split('/'):
            drop = True

        if not drop:
            kept.append((dest, src, typecode))
    return kept


# ===========================================================================
# 1) Main program -> dist\AronaAI\
# ===========================================================================

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('Assets/Font/WenYuanRoundedSC-Medium.ttf', 'Assets/Font'),
        ('Assets/Font/Quicksand-Medium.ttf', 'Assets/Font'),
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

a.binaries = _prune_qt_binaries(a.binaries)
a.datas = _prune_qt_datas(a.datas)

pyz_main = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe_main = EXE(
    pyz_main,
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

coll_main = COLLECT(
    exe_main,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='AronaAI',
)


# ===========================================================================
# 2) TTS module -> dist\AronaAI-TTS\  (move into the main folder as TTS\)
# ===========================================================================

b = Analysis(
    ['App/tts/tts_host.py'],
    pathex=[],
    binaries=[],
    datas=_collect_tts_datas(),
    hiddenimports=[
        # Insurance: reported at runtime once as a missing submodule even
        # though no static import exists in the installed package.
        'pyopenjtalk._known_symbols',
        'sudachidict_core',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'playwright', 'quickjs', 'torchvision'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

b.datas = _prune_tts_datas(b.datas)

pyz_tts = PYZ(b.pure, b.zipped_data, cipher=block_cipher)

exe_tts = EXE(
    pyz_tts,
    b.scripts,
    [],
    exclude_binaries=True,
    name='AronaAI-TTS',
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

coll_tts = COLLECT(
    exe_tts,
    b.binaries,
    b.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='AronaAI-TTS',
)
