import json
import sys
from pathlib import Path
from PySide6.QtCore import QSettings
from qfluentwidgets.common.config import QConfig, OptionsConfigItem, OptionsValidator, BoolValidator, ConfigSerializer, ConfigItem, ConfigValidator, Theme, qconfig

from app.update_utils import list_spine_models

MOMOTALK = "MomoTalk"
MOMO_TITLEBAR_COLOR = "#FA94A6"
MOMO_NAV_COLOR = "#4A5A70"
MOMO_CONTENT_COLOR = "#FFFFFF"

ACCENT_LIGHT = "#009FAA"
ACCENT_DARK = "#29F1FF"
ACCENT_MOMO = "#FA94A6"


def get_accent_color() -> str:
    """ return accent color of current theme """
    if qconfig.get(qconfig.themeMode) == MOMOTALK:
        return ACCENT_MOMO
    return ACCENT_DARK if qconfig.theme == Theme.DARK else ACCENT_LIGHT


class _ThemeModeSerializer(ConfigSerializer):
    def serialize(self, value):
        return value.value if isinstance(value, Theme) else value

    def deserialize(self, value):
        for member in Theme:
            if member.value == value:
                return member
        return value


QConfig.themeMode = OptionsConfigItem(
    "QFluentWidgets", "ThemeMode", Theme.AUTO,
    OptionsValidator([Theme.LIGHT, Theme.DARK, Theme.AUTO, MOMOTALK]),
    _ThemeModeSerializer(),
)


QConfig.backgroundEffect = OptionsConfigItem(
    "AronaAI", "BackgroundEffect", "mica",
    OptionsValidator(["mica", "mica_alt", "acrylic"]),
)


QConfig.startToTray = OptionsConfigItem(
    "AronaAI", "StartToTray", True, BoolValidator(),
)


QConfig.manualStartToTray = OptionsConfigItem(
    "AronaAI", "ManualStartToTray", False, BoolValidator(),
)


# Tracks whether the autostart default has been applied once. First launch
# turns autostart ON by default; afterwards the user's explicit choice in the
# settings switch is respected (turning it off must not re-enable itself on
# the next start via the default-example path).
QConfig.autostartInitialized = OptionsConfigItem(
    "AronaAI", "AutostartInitialized", False, BoolValidator(),
)


class _SpineModelValidator(ConfigValidator):
    """Validate the desktop model against the available spine assets."""

    @property
    def options(self):
        return list_spine_models()

    def validate(self, value):
        return value in self.options

    def correct(self, value):
        models = self.options
        return value if value in models else (models[0] if models else "arona")


QConfig.spineModel = OptionsConfigItem(
    "AronaAI", "SpineModel", "arona",
    _SpineModelValidator(),
)


QConfig.voiceLang = OptionsConfigItem(
    "AronaAI", "VoiceLang", "cn",
    OptionsValidator(["cn", "jp"]),
)


class _PositiveIntValidator(ConfigValidator):
    def validate(self, value):
        return isinstance(value, int) and value >= 1

    def correct(self, value):
        try:
            return max(1, int(value))
        except Exception:
            return 100


QConfig.spineZoom = ConfigItem(
    "AronaAI", "SpineZoom", 35,
    _PositiveIntValidator(),
)


class _PosValidator(ConfigValidator):
    def validate(self, value):
        if value is None:
            return True
        return (isinstance(value, (tuple, list)) and len(value) == 2
                and all(isinstance(v, int) for v in value))

    def correct(self, value):
        if value is None:
            return None
        if isinstance(value, (tuple, list)) and len(value) == 2:
            try:
                return (int(value[0]), int(value[1]))
            except Exception:
                return None
        return None


class _TupleSerializer(ConfigSerializer):
    def serialize(self, value):
        if value is None:
            return None
        return [int(value[0]), int(value[1])]

    def deserialize(self, value):
        if isinstance(value, (list, tuple)) and len(value) == 2:
            try:
                return (int(value[0]), int(value[1]))
            except Exception:
                return None
        return None


QConfig.spinePosition = ConfigItem(
    "AronaAI", "SpinePosition", None,
    _PosValidator(), _TupleSerializer(),
)


QConfig.spineVisible = OptionsConfigItem(
    "AronaAI", "SpineVisible", True,
    BoolValidator(),
)


QConfig.spineVisibleAutostart = OptionsConfigItem(
    "AronaAI", "SpineVisibleAutostart", True,
    BoolValidator(),
)


QConfig.spineVisibleManual = OptionsConfigItem(
    "AronaAI", "SpineVisibleManual", True,
    BoolValidator(),
)


class _StrListValidator(ConfigValidator):
    def validate(self, value):
        return isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value)

    def correct(self, value):
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value]
        return []


class _StrListSerializer(ConfigSerializer):
    def serialize(self, value):
        return json.dumps(list(value or []))

    def deserialize(self, value):
        try:
            data = json.loads(value)
        except Exception:
            return []
        if isinstance(data, list):
            return [str(v) for v in data]
        return []


QConfig.spineTopRule = OptionsConfigItem(
    "AronaAI", "SpineTopRule", "always_top",
    OptionsValidator(["always_top", "no_fullscreen", "no_maximized", "always_bottom"]),
)


QConfig.spineTopWhiteList = ConfigItem(
    "AronaAI", "SpineTopWhiteList", [],
    _StrListValidator(), _StrListSerializer(),
)


QConfig.spineTopBlackList = ConfigItem(
    "AronaAI", "SpineTopBlackList", [],
    _StrListValidator(), _StrListSerializer(),
)


_ORIG_THEME_FGET = QConfig.theme.fget


def _momo_theme_getter(self):
    theme = _ORIG_THEME_FGET(self)
    return Theme.LIGHT if theme == MOMOTALK else theme


QConfig.theme = property(_momo_theme_getter, QConfig.theme.fset)


def get_close_behavior():
    return QSettings("AronaAI", "AronaAI").value("closeBehavior", "ask")


def set_close_behavior(value):
    settings = QSettings("AronaAI", "AronaAI")
    settings.setValue("closeBehavior", value)
    settings.sync()


def get_last_choice():
    return QSettings("AronaAI", "AronaAI").value("lastCloseChoice", "tray")


def set_last_choice(value):
    settings = QSettings("AronaAI", "AronaAI")
    settings.setValue("lastCloseChoice", value)
    settings.sync()


_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _autostart_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --autostart'
    launcher = Path(sys.executable)
    pythonw = launcher.with_name("pythonw.exe")
    if pythonw.exists():
        launcher = pythonw
    return f'"{launcher}" "{Path(__file__).resolve().parent.parent / "main.py"}" --autostart'


def is_autostart_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "AronaAI")
    except OSError:
        return False
    if value == _autostart_command():
        return True
    if getattr(sys, "frozen", False):
        return False
    legacy = f'"{sys.executable}" "{Path(__file__).resolve().parent.parent / "main.py"}" --autostart'
    return value == legacy


def set_autostart_enabled(enabled):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, "AronaAI", 0, winreg.REG_SZ, _autostart_command())
        else:
            try:
                winreg.DeleteValue(key, "AronaAI")
            except OSError:
                pass


def ensure_autostart_default():
    """Apply the 'autostart on by default' policy exactly once.

    The first run turns Windows autostart on and records that the default
    was applied. Subsequent runs keep the user's setting untouched, so
    switching the feature off in settings stays off.
    """
    if qconfig.get(qconfig.autostartInitialized):
        return
    if not is_autostart_enabled():
        set_autostart_enabled(True)
    qconfig.set(qconfig.autostartInitialized, True)


_AI_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.json"


def _read_ai_config() -> dict:
    if _AI_CONFIG_PATH.exists():
        try:
            data = json.loads(_AI_CONFIG_PATH.read_text(encoding="utf-8"))
            return data.get("AronaAI", {})
        except Exception:
            pass
    return {}


def _write_ai_config(data: dict):
    full = {}
    if _AI_CONFIG_PATH.exists():
        try:
            full = json.loads(_AI_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    full.setdefault("AronaAI", {}).update(data)
    _AI_CONFIG_PATH.write_text(json.dumps(full, ensure_ascii=False, indent=4), encoding="utf-8")


def get_ai_settings() -> dict:
    d = _read_ai_config()
    return {
        "api_key": d.get("api_key", ""),
        "base_url": d.get("base_url", ""),
        "model": d.get("model", ""),
    }


def set_ai_settings(api_key: str, base_url: str, model: str):
    d = _read_ai_config()
    d["api_key"] = api_key
    d["base_url"] = base_url
    d["model"] = model
    _write_ai_config(d)
