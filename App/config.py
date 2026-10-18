import json
import sys
from pathlib import Path
from PySide6.QtCore import QSettings
from qfluentwidgets.common.config import QConfig, OptionsConfigItem, OptionsValidator, BoolValidator, ConfigSerializer, ConfigItem, ConfigValidator, Theme, qconfig

from App.update_utils import list_spine_models, get_base_dir

MOMOTALK = "MomoTalk"
MOMO_TITLEBAR_COLOR = "#FA94A6"
MOMO_NAV_COLOR = "#4A5A70"
MOMO_CONTENT_COLOR = "#FFFFFF"

ACCENT_LIGHT = "#009FAA"
ACCENT_DARK = "#29F1FF"
ACCENT_MOMO = "#FA94A6"


def get_accent_color() -> str:
    """返回当前主题的强调色"""
    if qconfig.get(qconfig.themeMode) == MOMOTALK:
        return ACCENT_MOMO
    # 用 isDarkTheme() 读已生效的主题；直接读 qconfig.theme 在切换途中
    # 还是旧值，会拿到上一套主题的强调色
    from qfluentwidgets import isDarkTheme
    return ACCENT_DARK if isDarkTheme() else ACCENT_LIGHT


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


# 记录「开机自启默认为开」这条策略是否已经执行过。首次启动会把自启打开，
# 之后就以用户在设置里的选择为准——用户关掉后不能因为默认值又被打开。
QConfig.autostartInitialized = OptionsConfigItem(
    "AronaAI", "AutostartInitialized", False, BoolValidator(),
)


class _SpineModelValidator(ConfigValidator):
    """校验桌面模型名是否存在于 Assets/Spine 里。"""

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


QConfig.apiKey = ConfigItem("AronaAI", "api_key", "")
QConfig.baseUrl = ConfigItem("AronaAI", "base_url", "")
QConfig.aiModel = ConfigItem("AronaAI", "model", "")


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


# 置顶规则（多选）：勾选的每个条件都会让模型在该条件下不压住前台窗口。
# 空列表 = 始终置顶（旧版的 always_top）。
TOP_RULE_FULLSCREEN = "no_fullscreen"
TOP_RULE_MAXIMIZED = "no_maximized"
TOP_RULE_TOP = "always_top"
TOP_RULE_BOTTOM = "always_bottom"
TOP_RULES = [
    TOP_RULE_FULLSCREEN, TOP_RULE_MAXIMIZED, TOP_RULE_TOP, TOP_RULE_BOTTOM,
]


class _RuleListValidator(ConfigValidator):
    """校验置顶规则列表，只保留已知项并按固定顺序排列。"""

    def validate(self, value):
        if not isinstance(value, (list, tuple)):
            return False
        return all(v in TOP_RULES for v in value)

    def correct(self, value):
        if isinstance(value, str):
            # 旧版 config.json 里是单个字符串
            value = [value]
        if not isinstance(value, (list, tuple)):
            return []
        seen = [v for v in value if v in TOP_RULES]
        return [r for r in TOP_RULES if r in seen]


class _RuleListSerializer(ConfigSerializer):
    def serialize(self, value):
        return json.dumps(list(value or []))

    def deserialize(self, value):
        if isinstance(value, str):
            try:
                data = json.loads(value)
            except Exception:
                # 也可能是旧版直接存枚举字符串（"no_fullscreen"）
                return [value] if value in TOP_RULES else []
        else:
            data = value
        if not isinstance(data, (list, tuple)):
            return []
        seen = [v for v in data if v in TOP_RULES]
        return [r for r in TOP_RULES if r in seen]


QConfig.spineTopRules = ConfigItem(
    "AronaAI", "SpineTopRules", [],
    _RuleListValidator(), _RuleListSerializer(),
)


QConfig.spineTopWhiteList = ConfigItem(
    "AronaAI", "SpineTopWhiteList", [],
    _StrListValidator(), _StrListSerializer(),
)


QConfig.spineTopBlackList = ConfigItem(
    "AronaAI", "SpineTopBlackList", [],
    _StrListValidator(), _StrListSerializer(),
)


QConfig.ttsEnabled = OptionsConfigItem(
    "AronaAI", "TtsEnabled", False, BoolValidator(),
)


QConfig.ttsSpine = OptionsConfigItem(
    "AronaAI", "TtsSpine", False, BoolValidator(),
)


QConfig.ttsChat = OptionsConfigItem(
    "AronaAI", "TtsChat", False, BoolValidator(),
)


QConfig.ttsUseGpu = OptionsConfigItem(
    "AronaAI", "TtsUseGpu", False, BoolValidator(),
)


# 播放与合成并行：长文本按句切分后，合成完一句就送播，边播边合成下一句。
# 按当前设备分别配置（CPU 慢、GPU 快，取舍不同）。
QConfig.ttsStreamCpu = OptionsConfigItem(
    "AronaAI", "TtsStreamCpu", False, BoolValidator(),
)


QConfig.ttsStreamGpu = OptionsConfigItem(
    "AronaAI", "TtsStreamGpu", True, BoolValidator(),
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
    """「默认开启开机自启」这条策略只执行一次。

    首次运行打开 Windows 自启并记下已执行；之后不再改动用户的选择，
    用户在设置里关掉就是关掉。
    """
    if qconfig.get(qconfig.autostartInitialized):
        return
    if not is_autostart_enabled():
        set_autostart_enabled(True)
    qconfig.set(qconfig.autostartInitialized, True)


AI_CONFIG_FILE = get_base_dir() / "config" / "config.json"
AI_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)


def get_ai_settings() -> dict:
    return {
        "api_key": qconfig.get(QConfig.apiKey) or "",
        "base_url": qconfig.get(QConfig.baseUrl) or "",
        "model": qconfig.get(QConfig.aiModel) or "",
    }


def set_ai_settings(api_key: str, base_url: str, model: str):
    # 必须走 qconfig：直接写文件的话，内存里的配置项不会更新，下一次
    # qconfig.save()（比如切换任意其它设置）就会把它覆盖掉，key 悄悄丢失。
    qconfig.set(QConfig.apiKey, api_key, save=False)
    qconfig.set(QConfig.baseUrl, base_url, save=False)
    qconfig.set(QConfig.aiModel, model, save=False)
    qconfig.save()
