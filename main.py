import os
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QFont, QIcon
from qfluentwidgets import qconfig
from qfluentwidgets.common import font as qfont

try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except Exception:
    pass

from App.update_utils import (
    get_assets_dir, cleanup_leftovers,
)

ASSETS = get_assets_dir()

_DEFAULT_AI_CONFIG = {
    "AronaAI": {
        "api_key": "",
        "base_url": "",
        "model": "",
    }
}


def _ensure_config():
    from App.config import AI_CONFIG_FILE
    AI_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not AI_CONFIG_FILE.exists():
        import json
        AI_CONFIG_FILE.write_text(json.dumps(_DEFAULT_AI_CONFIG, ensure_ascii=False, indent=4), encoding="utf-8")


if __name__ == "__main__":
    cleanup_leftovers()
    _ensure_config()
    import App.config as app_config
    import App.backdrop
    qconfig.file = app_config.AI_CONFIG_FILE
    qconfig.load()
    app_config.ensure_autostart_default()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.AA_SynthesizeMouseForUnhandledTouchEvents, True)
    QApplication.setAttribute(Qt.AA_SynthesizeTouchForUnhandledMouseEvents, False)
    app = QApplication(sys.argv)

    cn_font_path = ASSETS / "Font" / "WenYuanRoundedSC-Medium.ttf"
    en_font_path = ASSETS / "Font" / "Quicksand-Medium.ttf"

    cn_font_id = QFontDatabase.addApplicationFont(str(cn_font_path))
    en_font_id = QFontDatabase.addApplicationFont(str(en_font_path))

    cn_family = None
    if cn_font_id >= 0:
        families = QFontDatabase.applicationFontFamilies(cn_font_id)
        if families:
            cn_family = families[0]

    en_family = None
    if en_font_id >= 0:
        families = QFontDatabase.applicationFontFamilies(en_font_id)
        if families:
            en_family = families[0]

    font_families = [f for f in [en_family, cn_family] if f]
    if font_families:
        qfont.setFontFamilies(font_families)
        family_list = ", ".join(f"'{f}'" for f in font_families)
        app.setStyleSheet(f"*{{font-family: {family_list}}}")

    app.setWindowIcon(QIcon(str(ASSETS / "Logo" / "Logo.png")))

    # 全局去掉粗体：在字体工具层强制 Normal 字重，同时把控件 polish 时
    # 自行加上的 DemiBold 也改回 Normal。
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

    from App.main_window import MainWindow
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
