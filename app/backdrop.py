from qfluentwidgets.common.config import qconfig, Theme
from qfluentwidgets.components.dialog_box.mask_dialog_base import MaskDialogBase

_WIDGET_BG = {
    Theme.LIGHT: "rgba(255, 255, 255, 210)",
    Theme.DARK: "rgba(32, 32, 32, 210)",
}


def apply_dialog_backdrop(dialog):
    widget = getattr(dialog, "widget", None)
    if widget is None:
        return
    bg = _WIDGET_BG[Theme.DARK if qconfig.theme == Theme.DARK else Theme.LIGHT]
    widget.setStyleSheet(f"#centerWidget {{ background-color: {bg}; }}")


_ORIG_SHOW_EVENT = MaskDialogBase.showEvent


def _patched_show_event(self, e):
    _ORIG_SHOW_EVENT(self, e)
    apply_dialog_backdrop(self)


MaskDialogBase.showEvent = _patched_show_event
