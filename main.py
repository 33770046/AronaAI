import os
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QFont, QIcon
from qfluentwidgets import qconfig
from qfluentwidgets.common import font as qfont

from app.scale_utils import init_scale
from app.update_utils import (
    get_base_dir, get_assets_dir, cleanup_leftovers,
)

BASE = get_base_dir()
ASSETS = get_assets_dir()

_DEFAULT_AI_CONFIG = {
    "AronaAI": {
        "api_key": "",
        "base_url": "",
        "model": "",
    }
}


def _ensure_config():
    config_dir = BASE / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"
    if not config_file.exists():
        import json
        config_file.write_text(json.dumps(_DEFAULT_AI_CONFIG, ensure_ascii=False, indent=4), encoding="utf-8")


if __name__ == "__main__":
    # Cap the Spine QtWebEngine renderer's committed memory. Only a subset of
    # Chromium switches is forwarded by QtWebEngine; --js-flags with the V8
    # max-old-space-size limit is the one that actually reaches the renderer
    # and forces the GC to run early, keeping WebEngine around ~200MB instead
    # of growing to ~600MB.
    os.environ.setdefault(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--js-flags=--max-old-space-size=128"
        " --enable-low-end-device-mode"
        " --disable-features=Translate,WebNfc,WebUsb,WebSerial,SharedArrayBuffer",
    )
    cleanup_leftovers()
    _ensure_config()
    import app.config
    import app.backdrop
    qconfig.file = BASE / "config" / "config.json"
    qconfig.load()
    app.config.ensure_autostart_default()
    init_scale()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.AA_SynthesizeMouseForUnhandledTouchEvents, True)
    QApplication.setAttribute(Qt.AA_SynthesizeTouchForUnhandledMouseEvents, False)
    app = QApplication(sys.argv)

    font_path = ASSETS / "Font" / "ResourceHanRoundedCN-Medium.ttf"
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    custom_family = None
    if font_id >= 0:
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            custom_family = families[0]

    if custom_family:
        app.setFont(QFont(custom_family))
        qfont.setFontFamilies([custom_family])
        app.setStyleSheet(f"*{{font-family: '{custom_family}'}}")

    app.setWindowIcon(QIcon(str(ASSETS / "Logo" / "Logo.png")))

    # Remove bold everywhere: force Normal weight at the font-utility level and
    # strip any DemiBold applied by widgets as they are polished.
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QWidget as _QWidget

    _orig_getFont = qfont.getFont

    def _no_bold_getFont(fontSize=14, weight=None):
        return _orig_getFont(fontSize, QFont.Weight.Normal)

    qfont.getFont = _no_bold_getFont

    class _RegularWeightFilter(QObject):
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Type.Polish and isinstance(obj, _QWidget):
                f = obj.font()
                if f.weight() != QFont.Weight.Normal:
                    f.setWeight(QFont.Weight.Normal)
                    obj.setFont(f)
            return False

    app.installEventFilter(_RegularWeightFilter(app))

    from app.main_window import MainWindow
    w = MainWindow()
    w.setWindowIcon(QIcon(str(ASSETS / "Logo" / "Logo.png")))
    if "--autostart" in sys.argv:
        to_tray = qconfig.get(qconfig.startToTray)
        show_model = qconfig.get(qconfig.spineVisibleAutostart)
    else:
        to_tray = qconfig.get(qconfig.manualStartToTray)
        show_model = qconfig.get(qconfig.spineVisibleManual)
    if to_tray:
        w.hide()
        w.trayIcon.show()
    else:
        w.show()
    if qconfig.get(qconfig.spineVisible) and show_model:
        w.spineWindow.show()
    sys.exit(app.exec())
