# -*- mode: python ; coding: utf-8 -*-
# AronaAI 的 PyInstaller 6.x onedir 配置，一次构建出两个产物：
#   1) dist\AronaAI\      主程序（不含 torch/gsv，TTS 保持外置）
#   2) dist\AronaAI-TTS\  独立 TTS 模块 -> 移进主目录后成为 TTS\
#      AronaAI/TTS/AronaAI-TTS.exe + AronaAI/TTS/_internal/...
# 语音包（Assets/TTS 里的 .ckpt/.pth）不属于任何一个包；
# 主程序通过 stdio JSON 协议把它们的绝对路径传给 TTS 进程。
# 构建：.\.venv\Scripts\pyinstaller.exe AronaAI.spec --noconfirm --clean

import os
import sys

block_cipher = None


# ===========================================================================
# 公共辅助
# ===========================================================================

# 收集到的 PySide6 .pyd 实际链接的 Qt6 动态库（传递闭包，用 bindepend 核实）。
# WebEngine 和 WebChannel 在第四阶段已移除（桌宠改用 WebView2）。
QT6_KEEP = {
    'Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Network.dll', 'Qt6OpenGL.dll',
    'Qt6Positioning.dll', 'Qt6PrintSupport.dll', 'Qt6Qml.dll',
    'Qt6QmlMeta.dll', 'Qt6QmlModels.dll', 'Qt6QmlWorkerScript.dll',
    'Qt6Quick.dll', 'Qt6QuickWidgets.dll', 'Qt6Svg.dll', 'Qt6SvgWidgets.dll',
    'Qt6Multimedia.dll', 'Qt6MultimediaWidgets.dll',
    'Qt6Widgets.dll', 'Qt6Xml.dll',
}

# 本应用用不到的 QML 模块（QtWebEngine/Quick 相关）。
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

# 只为已剔除的 Qt 模块存在的插件（每个都链接了一个被剔除的 Qt6 dll）。
PLUGIN_DROP_DIRS = {
    'platforminputcontexts', 'position', 'qmltooling',
}
PLUGIN_DROP_FILES = {
    # imageformats/qpdf.dll 依赖已被剔除的 Qt6Pdf.dll。
    'imageformats/qpdf.dll',
}

TRANSLATION_KEEP_TAILS = ('_zh_CN.qm', '_en.qm', '_zh.qm', '_en_US.qm')


def _prune_qt_binaries(toc):
    kept = []
    for dest, src, typecode in toc:
        rel = os.path.normpath(dest).replace('\\', '/')
        head, base = os.path.split(rel)
        drop = False

        # 不在保留清单里的顶层 Qt6*.dll。
        if head == 'PySide6' and base.startswith('Qt6') and base.endswith('.dll'):
            if base not in QT6_KEEP:
                drop = True

        # 没用到的 Qt 插件。
        if head.startswith('PySide6/plugins/'):
            plugin_rel = head[len('PySide6/plugins/'):]
            plugin_type = plugin_rel.split('/')[0]
            if plugin_type in PLUGIN_DROP_DIRS:
                drop = True
            if plugin_rel + '/' + base in PLUGIN_DROP_FILES:
                drop = True

        # 无用模块的 QML 插件与二进制。
        if head.startswith('PySide6/qml/'):
            qml_rel = head[len('PySide6/qml/'):]
            parts = qml_rel.split('/')
            if parts and parts[0] in QML_DROP_TOP:
                drop = True
            elif parts and parts[0] == 'QtQuick' and len(parts) > 1 and parts[1] in QML_DROP_QUICK:
                drop = True

        # 仅调试用的 webengine 资源（release 版的 pak 保留）。
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

        # 无用模块的 QML 模块数据。
        if head.startswith('PySide6/qml/'):
            qml_rel = head[len('PySide6/qml/'):]
            parts = qml_rel.split('/')
            if parts and parts[0] in QML_DROP_TOP:
                drop = True
            elif parts and parts[0] == 'QtQuick' and len(parts) > 1 and parts[1] in QML_DROP_QUICK:
                drop = True

        # 仅调试用的 webengine 资源。
        if head == 'PySide6/resources' and '.debug.' in base:
            drop = True

        # 只保留少量 Qt 翻译（本应用没有用 QTranslator）。
        if head == 'PySide6/translations' and not base.endswith(TRANSLATION_KEEP_TAILS):
            drop = True

        if not drop:
            kept.append((dest, src, typecode))
    return kept


def _collect_tts_datas():
    extra = []

    # 运行时通过 importlib.resources / 包路径加载的数据文件。
    try:
        from PyInstaller.utils.hooks import collect_data_files, copy_metadata

        for pkg in ('py3langid', 'wordsegment', 'jieba', 'sounddevice'):
            extra += collect_data_files(pkg)
        # JP 字典不打进包，启动预取时下（tts_child._prefetch，语音语言=jp 时，
        # 基础模型下完之后），首次日配合成仍会兜底补齐：
        #  - pyopenjtalk dictionary/（sys.dic 等 ~102MB）：从 PyPI
        #    pyopenjtalk-plus wheel 解出，经 OPEN_JTALK_DICT_DIR 生效
        #  - sudachidict_core resources/system.dic（202MB）：从 PyPI
        #    sudachidict-core wheel 解出，经 sudachi.json 显式注入
        #    （冻结包无 entry point 元数据，bare Dictionary() 会崩）。
        #    run_frontend 后处理 modify_kanji_yomi -> sudachi_analyze 依赖它。
        # 这里 pyopenjtalk 只打包 htsvoice / yomi_model 等小文件。
        extra += collect_data_files('pyopenjtalk', excludes=['dictionary/*'])
        extra += collect_data_files('pyopenjtalk', excludes=['dictionary/*'])
        # torch/transformers 通过 importlib.metadata 读取各自的版本号。
        extra += copy_metadata('torch')
    except Exception as exc:  # pragma: no cover - build-time only
        print(f'AronaAI-TTS: data collection failed: {exc}')

    # 保留 gsv_tts 的源码：SoVITS/commons.py 在 import 时就会执行
    # @torch.jit.script，这需要能通过 inspect/linecache 读到原始 .py
    # （冻结后 co_filename 是 PYZ 相对路径，会去子进程 cwd 或 MEIPASS 里找）。
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

    # 预训练基础模型（约 1GB）有意不打包：应用首次运行时下载到
    # <exe_dir>\gsv_models（即 AronaAI.exe 旁的一个目录），并显示进度。

    return extra


def _prune_tts_datas(toc):
    kept = []
    for dest, src, typecode in toc:
        rel = os.path.normpath(dest).replace('\\', '/')
        drop = False

        # torch 的开发文件（headers / cmake / share）运行时用不到。
        if rel.startswith(('torch/include/', 'torch/share/', 'torch/cmake/')):
            drop = True

        # 第二道保险：两份日文字典都是按需下载的
        # （tts_child._ensure_jp_langpack + OPEN_JTALK_DICT_DIR / sudachi.json），
        # 无论哪个 hook 想把它们加进来，都必须剔除。
        if 'sudachidict' in rel or rel.startswith('pyopenjtalk/dictionary/'):
            drop = True

        # 字节码缓存不需要作为数据打包。
        if '__pycache__' in rel.split('/'):
            drop = True

        if not drop:
            kept.append((dest, src, typecode))
    return kept


# ===========================================================================
# 1) 主程序 -> dist\AronaAI\
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
        ('Assets/Spine/web/bridge-shim.js', 'Assets/Spine/web'),
        ('LICENSE', '.'),
        ('COPYRIGHT', '.'),
    ],
    hiddenimports=[],
    hookspath=['App/hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'playwright', 'numpy', 'quickjs'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# qtwebview2 自带的 PyInstaller hook 会把它的 lib/ 数据装到
# qtwebview2/lib 下，但该包在冻结状态下是从 sys._MEIPASS/lib 解析 WebView2
# 程序集的（utils.get_absolute_path）。所以把整棵树挪到 _internal/lib，
# clr.AddReference 才能在那里找到 Microsoft.Web.WebView2.*。
QTVIEW2_LIB = os.path.join(sys.prefix, 'Lib', 'site-packages',
                           'qtwebview2', 'lib')
_a = lambda toc: [d for d in toc
                  if not d[0].replace('\\', '/').startswith('qtwebview2/lib')]
a.datas = _a(a.datas)
a.binaries = _a(a.binaries)
for _root, _dirs, _files in os.walk(QTVIEW2_LIB):
    for _f in _files:
        _src = os.path.join(_root, _f)
        _rel = os.path.relpath(_src, QTVIEW2_LIB).replace('\\', '/')
        a.datas.append(('lib/' + _rel, _src, 'DATA'))

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
# 2) TTS 模块 -> dist\AronaAI-TTS\  （移到主目录后即 TTS\）
# ===========================================================================

b = Analysis(
    ['App/tts/tts_host.py'],
    pathex=[],
    binaries=[],
    datas=_collect_tts_datas(),
    hiddenimports=[
        # 保险起见加上：运行时会被报成缺失子模块，
        # 尽管已安装的包里并不存在对它的静态 import。
        'pyopenjtalk._known_symbols',
    ],
    hookspath=['App/hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt5', 'playwright', 'quickjs', 'torchvision',
        # 依据（打包冒烟 + dev 模块探测）：transformers 的 Hubert ->
        # masking_utils 链路会在模块级急切导入 torch._dynamo（连带约 95 个
        # dynamo + 17 个 inductor 模块），排除它们会让预热流程崩溃。
        # 整个 compile 栈在 PYZ 里只占约 5.6MB，不值得为此牺牲功能，
        # 所以 dynamo/inductor/sympy/mpmath 一并打包。
        # networkx 在任何实际执行路径中都没被导入（已验证）-> 排除。
        'networkx',
    ],
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
