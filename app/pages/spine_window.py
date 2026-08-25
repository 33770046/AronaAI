import ctypes
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QBuffer, QIODevice, QObject, Slot, Signal, QEvent, QTimer
from PySide6.QtGui import QCursor, QTextOption
from PySide6.QtWidgets import QWidget, QApplication, QVBoxLayout, QHBoxLayout, QLabel
from qfluentwidgets.common.config import qconfig
from qfluentwidgets.common.font import getFont
from qfluentwidgets import CardWidget, PlainTextEdit, TransparentToolButton, FluentIcon as FIF, isDarkTheme, RoundMenu, Action

from app.update_utils import get_assets_dir, list_spine_models, ensure_spine_runtime
from app.ai_chat import AIWorker, load_history, save_history

_MODELS = list_spine_models()

# Bump when Assets/spine/web/* changes so the persistent WebEngine profile
# does not serve a cached copy of the spine page.
_SPINE_ASSET_VERSION = "11"

_SCHEME_REGISTERED = False

_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOPMOST = 0x00000008

# Device px of transparent padding kept around the model box so the chat
# bubble and the model's drop shadow stay inside the window. Keeping the
# window small (instead of spanning the whole screen) is what bounds the
# WebEngine compositing surface and therefore the renderer's memory.
_PAD_DEV = 48

_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020

_HWND_BOTTOM = 1
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2

_Z_TOP = 0
_Z_BOTTOM = 1
_Z_NORMAL = 2

_MONITOR_DEFAULTTONEAREST = 2
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _setup_win32_signatures():
    """Set ctypes argtypes/restype so HWNDs are passed as pointers.

    Without argtypes ctypes converts integer HWNDs to c_int, truncating the
    64-bit handle and making SetWindowPos/GetWindowLongW fail silently.
    """
    if sys.platform != "win32":
        return
    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    HWND = ctypes.c_void_p
    BOOL = ctypes.c_int
    DWORD = ctypes.c_ulong
    LONG = ctypes.c_long
    UINT = ctypes.c_uint
    INT = ctypes.c_int

    u.GetWindowLongW.argtypes = [HWND, INT]
    u.GetWindowLongW.restype = LONG
    u.SetWindowLongW.argtypes = [HWND, INT, LONG]
    u.SetWindowLongW.restype = LONG
    u.SetWindowPos.argtypes = [HWND, HWND, INT, INT, INT, INT, UINT]
    u.SetWindowPos.restype = BOOL
    u.GetWindow.argtypes = [HWND, UINT]
    u.GetWindow.restype = HWND
    u.IsWindowVisible.argtypes = [HWND]
    u.IsWindowVisible.restype = BOOL
    u.IsZoomed.argtypes = [HWND]
    u.IsZoomed.restype = BOOL
    u.MonitorFromWindow.argtypes = [HWND, DWORD]
    u.MonitorFromWindow.restype = HWND
    u.GetMonitorInfoW.argtypes = [HWND, ctypes.c_void_p]
    u.GetMonitorInfoW.restype = BOOL
    u.GetWindowRect.argtypes = [HWND, ctypes.c_void_p]
    u.GetWindowRect.restype = BOOL
    u.GetWindowTextLengthW.argtypes = [HWND]
    u.GetWindowTextLengthW.restype = INT
    u.GetWindowTextW.argtypes = [HWND, ctypes.c_wchar_p, INT]
    u.GetWindowTextW.restype = INT
    u.GetClassNameW.argtypes = [HWND, ctypes.c_wchar_p, INT]
    u.GetClassNameW.restype = INT
    u.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(DWORD)]
    u.GetWindowThreadProcessId.restype = DWORD
    u.GetForegroundWindow.argtypes = []
    u.GetForegroundWindow.restype = HWND

    k.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
    k.OpenProcess.restype = HWND
    k.QueryFullProcessImageNameW.argtypes = [HWND, DWORD, ctypes.c_wchar_p, ctypes.POINTER(DWORD)]
    k.QueryFullProcessImageNameW.restype = BOOL
    k.CloseHandle.argtypes = [HWND]
    k.CloseHandle.restype = BOOL


_setup_win32_signatures()


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long), ("top", ctypes.c_long),
        ("right", ctypes.c_long), ("bottom", ctypes.c_long),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_ulonglong),
        ("lParam", ctypes.c_longlong),
        ("time", ctypes.c_ulong),
        ("pt", _POINT),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


def _register_scheme():
    global _SCHEME_REGISTERED
    if _SCHEME_REGISTERED:
        return
    from PySide6.QtWebEngineCore import QWebEngineUrlScheme

    scheme = QWebEngineUrlScheme(b"spine")
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.HostAndPort)
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme
        | QWebEngineUrlScheme.Flag.LocalScheme
    )
    QWebEngineUrlScheme.registerScheme(scheme)
    _SCHEME_REGISTERED = True


class _SpineSchemeHandler:
    TYPES = {
        ".html": "text/html",
        ".js": "application/javascript",
        ".css": "text/css",
        ".skel": "application/octet-stream",
        ".atlas": "text/plain",
        ".png": "image/png",
        ".json": "application/json",
        ".ogg": "audio/ogg",
    }

    def __init__(self, root: Path):
        from PySide6.QtWebEngineCore import QWebEngineUrlSchemeHandler

        self.root = root

        class Handler(QWebEngineUrlSchemeHandler):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.owner = None

            def requestStarted(self, job):
                self.owner._requestStarted(job)

        self.handler = Handler()
        self.handler.owner = self

    def _requestStarted(self, job):
        from PySide6.QtWebEngineCore import QWebEngineUrlRequestJob

        path = job.requestUrl().path().lstrip("/")
        full = (self.root / path).resolve()
        try:
            data = full.read_bytes()
            buf = QBuffer(self.handler)
            buf.setData(data)
            buf.open(QIODevice.OpenModeFlag.ReadOnly)
            ctype = self.TYPES.get(full.suffix.lower(), "application/octet-stream")
            job.reply(ctype.encode(), buf)
        except Exception:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)


class _Bridge(QObject):
    layoutChanged = Signal(int, int, int, int)
    moveTo = Signal(int, int)
    cursorMoved = Signal(int, int)
    sendTextToModel = Signal(str)

    def __init__(self, window):
        super().__init__()
        self._window = window

    @Slot(int, int)
    def setModelSize(self, width, height):
        self._window._on_model_size(width, height)

    @Slot(int, int, int, int)
    def setModelRect(self, x, y, w, h):
        self._window._on_model_rect(x, y, w, h)

    @Slot(str)
    def showError(self, msg):
        self._window.on_page_error(msg)

    @Slot()
    def onDoubleClick(self):
        self._window._handle_double_click()


class _MiddleDragFilter(QObject):
    """Holds and drags the character with the middle button after a 400ms long-press."""

    LONG_PRESS_MS = 400

    def __init__(self, window):
        super().__init__()
        self._window = window
        self._armed = False
        self._dragging = False
        self._press_global = None
        self._drag_offset = None
        self._press_timer = QTimer(self)
        self._press_timer.setSingleShot(True)
        self._press_timer.setInterval(self.LONG_PRESS_MS)
        self._press_timer.timeout.connect(self._activate)
        self._move_timer = QTimer(self)
        self._move_timer.setInterval(16)
        self._move_timer.timeout.connect(self._poll_move)

    def _is_ours(self, obj):
        if not isinstance(obj, QWidget):
            return False
        return obj.window() is self._window

    def eventFilter(self, obj, event):
        if not self._is_ours(obj):
            return False
        t = event.type()
        if t == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.MiddleButton:
                self._press_global = event.globalPosition().toPoint()
                self._armed = True
                self._dragging = False
                self._press_timer.start()
            return False
        if t == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.MiddleButton:
                self._press_timer.stop()
                if self._dragging:
                    self._dragging = False
                    self._move_timer.stop()
                    self._window._save_position()
                self._armed = False
                self._drag_offset = None
                self._press_global = None
            return False
        return False

    def _activate(self):
        if not self._armed or self._press_global is None:
            return
        win = self._window
        scale = win._scale
        p = self._press_global
        x, y, w, h = win._char_rect
        if w > 0 and h > 0:
            zx = x + w * 0.35
            zw = w * 0.30
            zy = y + h * 0.33
            zh = h * 0.13
            left = win.x() + zx * scale
            top = win.y() + zy * scale
            if not (left <= p.x() <= left + zw * scale and
                    top <= p.y() <= top + zh * scale):
                return
        self._dragging = True
        win._user_positioned = True
        cx, cy = win._char_screen_css()
        self._drag_offset = (
            p.x() / scale - cx,
            p.y() / scale - cy,
        )
        self._move_timer.start()

    def _poll_move(self):
        if not self._dragging or self._drag_offset is None:
            return
        win = self._window
        scale = win._scale
        p = QCursor.pos()
        dx, dy = self._drag_offset
        win._move_character(
            p.x() / scale - dx,
            p.y() / scale - dy,
        )


class _SpineChatBubble(QWidget):
    """Floating chat bubble displayed above the model in the spine window."""

    def __init__(self, text: str, is_self: bool = False, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._card = QWidget()
        self._card.setObjectName("bubbleCard")

        inner = QVBoxLayout(self._card)
        inner.setContentsMargins(12, 8, 12, 8)

        self._label = QLabel(text)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(220)
        self._label.setFont(getFont(13))
        inner.addWidget(self._label)

        layout.addWidget(self._card)
        self.setFixedWidth(240)
        self._apply_theme(is_self)
        self._theme_func = lambda: self._apply_theme(is_self)
        qconfig.themeChanged.connect(self._theme_func)

    def _apply_theme(self, is_self: bool):
        from ..config import MOMOTALK
        mode = qconfig.get(qconfig.themeMode)
        is_momo = mode == MOMOTALK
        if is_momo:
            bg = "#4A5A70" if not is_self else "#FA94A6"
            text_color = "#FFFFFF"
        elif isDarkTheme():
            bg = "#373737" if not is_self else "#29F1FF"
            text_color = "#FFFFFF"
        else:
            bg = "#F0F0F0" if not is_self else "#009FAA"
            text_color = "#282828" if not is_self else "#FFFFFF"

        r, g, b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
        alpha = 230
        self._card.setStyleSheet(
            f"#bubbleCard{{background-color:rgba({r},{g},{b},{alpha}); border-radius:10px;}}"
        )
        self._label.setStyleSheet(f"QLabel{{color:{text_color}; background:transparent;}}")

    def position_above(self, spine_x, spine_y, char_x, char_y, char_w, char_h, scale):
        bx = spine_x + round((char_x + char_w * 0.5) * scale) - 120
        by = spine_y + round(char_y * scale) - 60
        self.move(bx, by)


class _InputEdit(PlainTextEdit):
    """PlainTextEdit with custom right-click menu."""
    def contextMenuEvent(self, e):
        cursor = self.textCursor()
        has_selection = cursor.hasSelection()

        menu = RoundMenu(parent=self)

        cut_action = Action(FIF.CUT, "剪切")
        cut_action.setShortcut("Ctrl+X")
        cut_action.setEnabled(has_selection)
        cut_action.triggered.connect(self.cut)
        menu.addAction(cut_action)

        copy_action = Action(FIF.COPY, "复制")
        copy_action.setShortcut("Ctrl+C")
        copy_action.setEnabled(has_selection)
        copy_action.triggered.connect(self.copy)
        menu.addAction(copy_action)

        paste_action = Action(FIF.PASTE, "粘贴")
        paste_action.setShortcut("Ctrl+V")
        paste_action.triggered.connect(self.paste)
        menu.addAction(paste_action)

        menu.addSeparator()

        select_all = Action(FIF.CHECKBOX, "全选")
        select_all.setShortcut("Ctrl+A")
        select_all.triggered.connect(self.selectAll)
        menu.addAction(select_all)

        menu.exec(e.globalPos())


class _SpineTextInput(QWidget):
    """Text input widget that matches the chat bubble style."""

    submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        self._drag_pos = None
        self._setup_ui()
        self.hide()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._bubble = CardWidget()
        self._bubble.setBorderRadius(12)
        self._bubble.setClickEnabled(False)

        inner = QHBoxLayout(self._bubble)
        inner.setContentsMargins(12, 8, 8, 8)
        inner.setSpacing(6)

        self._input = _InputEdit()
        self._input.setPlaceholderText("输入消息...")
        self._input.setMinimumHeight(36)
        self._input.setMaximumHeight(80)
        self._input.setFrameShape(PlainTextEdit.Shape.NoFrame)
        self._input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._input.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._input.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self._input.installEventFilter(self)
        inner.addWidget(self._input)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(0)
        btn_col.setContentsMargins(0, 0, 0, 0)

        self._close_btn = TransparentToolButton(FIF.CLOSE)
        self._close_btn.setFixedSize(28, 28)
        self._close_btn.clicked.connect(self.hide)
        btn_col.addWidget(self._close_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        btn_col.addStretch()

        self._send_btn = TransparentToolButton(FIF.SEND)
        self._send_btn.setFixedSize(28, 28)
        self._send_btn.clicked.connect(self._on_submit)
        btn_col.addWidget(self._send_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        inner.addLayout(btn_col)

        layout.addWidget(self._bubble)
        self.setFixedWidth(260)
        self._apply_theme()
        qconfig.themeChanged.connect(self._apply_theme)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
            event.accept()

    def _apply_theme(self):
        from ..config import MOMOTALK
        is_momo = qconfig.get(qconfig.themeMode) == MOMOTALK
        if is_momo:
            bg = "#4A5A70"
            text_color = "#000000"
        elif isDarkTheme():
            bg = "#373737"
            text_color = "#FFFFFF"
        else:
            bg = "#F0F0F0"
            text_color = "#282828"

        r, g, b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
        alpha = 178
        self._bubble.setStyleSheet(
            f"CardWidget{{background-color:rgba({r},{g},{b},{alpha}); border-radius:12px;}}"
        )
        self._input.setStyleSheet(
            f"QPlainTextEdit{{color:{text_color}; background:transparent;}}"
        )
        self._input.setFont(getFont(14))

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self._input.textCursor().insertText("\n")
                    return True
                else:
                    self._on_submit()
                    return True
            if event.key() == Qt.Key.Key_Escape:
                self.hide()
                return True
        return super().eventFilter(obj, event)

    def _on_submit(self):
        text = self._input.toPlainText().strip()
        if text:
            self.submitted.emit(text)
            self._input.clear()

    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self._input.clear()
            self.show()
            self._input.setFocus()
            self.raise_()

    def showEvent(self, event):
        super().showEvent(event)
        self._input.setFocus()


class SpineWindow(QWidget):
    visibilityChangedSignal = Signal(bool)

    def __init__(self):
        _register_scheme()
        super().__init__(None)

        self._model = qconfig.get(qconfig.spineModel)
        if self._model not in _MODELS:
            self._model = _MODELS[0]
        self._view = None
        self._bridge = _Bridge(self)
        self._error = False
        self._base_size = (0, 0)
        self._char_rect = (0, 0, 0, 0)
        self._user_positioned = False

        self._text_input = _SpineTextInput()
        self._text_input.submitted.connect(self._on_text_submitted)

        self._ai_worker = None
        self._chat_bubbles = []
        self._chat_history = []

        self._bridge.sendTextToModel.connect(self._send_text_to_model)

        self.setWindowTitle("AronaAI Spine")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self._hotkey_id = 1

        self._drag_filter = _MiddleDragFilter(self)
        QApplication.instance().installEventFilter(self._drag_filter)

        self._hit_timer = QTimer(self)
        self._hit_timer.setInterval(16)
        self._hit_timer.timeout.connect(self._poll_hit_test)
        self._hit_timer.start()

        # Re-evaluate the model's z-order quickly based on the active window
        # (rule + whitelist/blacklist) so a foreground change takes effect
        # immediately. Default is unconditional topmost; the whitelist forces
        # topmost over listed apps and the blacklist sinks the model beneath
        # listed apps, regardless of fullscreen/maximized/windowed state.
        self._z_fg = None
        self._z_fg_proc = ""
        self._z_fg_title = ""
        # None forces a full re-pin on the first tick after startup/show.
        self._z_state = None
        self._z_timer = QTimer(self)
        self._z_timer.setInterval(100)
        self._z_timer.timeout.connect(self._set_z_order)
        self._z_timer.start()

        self._apply_initial_geometry()
        self._runtime_ok = True
        try:
            ensure_spine_runtime()
        except Exception as e:
            self._runtime_ok = False
            print(f"[Spine] 运行时下载失败: {e}", file=sys.stderr)
        self._create_view()
        qconfig.spineModel.valueChanged.connect(self._on_model_changed)
        qconfig.spineZoom.valueChanged.connect(self.set_zoom)
        qconfig.spineVisible.valueChanged.connect(self._on_visible_changed)
        qconfig.voiceLang.valueChanged.connect(self._on_voice_changed)

    def _register_hotkey(self):
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
        except Exception:
            return
        user32 = ctypes.windll.user32
        MOD_CTRL = 0x0002
        MOD_SHIFT = 0x0004
        MOD_ALT = 0x0001
        VK_RETURN = 0x0D
        ok = user32.RegisterHotKey(hwnd, self._hotkey_id, MOD_CTRL | MOD_SHIFT | MOD_ALT, VK_RETURN)
        if not ok:
            err = ctypes.windll.kernel32.GetLastError()
            print(f"[Spine] RegisterHotKey failed: error {err}", file=sys.stderr)

    def _unregister_hotkey(self):
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
        except Exception:
            return
        user32 = ctypes.windll.user32
        user32.UnregisterHotKey(hwnd, self._hotkey_id)

    def nativeEvent(self, eventType, message):
        if sys.platform == "win32" and eventType == b"windows_generic_MSG":
            msg = ctypes.cast(int(message), ctypes.POINTER(MSG)).contents
            if msg.message == 0x0312 and msg.wParam == self._hotkey_id:
                self._toggle_text_input()
                return True, 0
        return super().nativeEvent(eventType, message)

    @property
    def _scale(self):
        return self.devicePixelRatio() or 1.0

    def _apply_initial_geometry(self):
        """Place the window at the saved (or default) position before the
        model reports its size, using a small default box."""
        scale = self._scale
        pad = round(_PAD_DEV / scale)
        percent = max(10, int(qconfig.get(qconfig.spineZoom)))
        w = max(10, round(self._base_size[0] * percent / 100 / scale))
        h = max(10, round(self._base_size[1] * percent / 100 / scale))
        screen = QApplication.primaryScreen()
        sw, sh = 1920, 1080
        if screen:
            geo = screen.geometry()
            sw, sh = round(geo.width() / scale), round(geo.height() / scale)
        margin = round(24 / scale)
        cx = max(0, sw - w - margin)
        cy = max(0, sh - h - margin)
        pos = qconfig.get(qconfig.spinePosition)
        if pos is not None:
            self._user_positioned = True
            cx = max(0, min(int(pos[0]), max(0, sw - 20)))
            cy = max(0, min(int(pos[1]), max(0, sh - 20)))
        self._char_rect = (pad, pad, w, h)
        self.setGeometry(
            round(cx * scale) - _PAD_DEV,
            round(cy * scale) - _PAD_DEV,
            round(w * scale) + 2 * _PAD_DEV,
            round(h * scale) + 2 * _PAD_DEV,
        )
        self._ensure_noactivate()

    def _ensure_noactivate(self):
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
        except Exception:
            return
        user32 = ctypes.windll.user32
        ex = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        if not ex & _WS_EX_NOACTIVATE:
            user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex | _WS_EX_NOACTIVATE)
            user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER
                | _SWP_NOACTIVATE | _SWP_FRAMECHANGED,
            )

    def _char_screen_css(self):
        """Character top-left in CSS px relative to the screen origin."""
        scale = self._scale
        return ((self.x() + _PAD_DEV) / scale, (self.y() + _PAD_DEV) / scale)

    def _set_char_geometry(self, cx, cy, css_w, css_h):
        """Set the window around the model box.

        cx/cy is the character's top-left in CSS px relative to the screen
        origin. The window is slightly larger than the box (padding) and moves
        with the character; the web page keeps the player at the same padding
        inside the window, so JS continues to work in window-local coordinates.
        """
        scale = self._scale
        pad = round(_PAD_DEV / scale)
        self._char_rect = (pad, pad, css_w, css_h)
        self.setGeometry(
            round(cx * scale) - _PAD_DEV,
            round(cy * scale) - _PAD_DEV,
            round(css_w * scale) + 2 * _PAD_DEV,
            round(css_h * scale) + 2 * _PAD_DEV,
        )
        if self._bridge is not None:
            self._bridge.layoutChanged.emit(pad, pad, css_w, css_h)

    def _create_view(self):
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
        from PySide6.QtWebChannel import QWebChannel

        self._view = QWebEngineView(self)
        self._view.setGeometry(0, 0, self.width(), self.height())
        self._view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._view.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

        profile = QWebEngineProfile("spine", self)
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        handler = _SpineSchemeHandler(get_assets_dir() / "Spine")
        profile.installUrlSchemeHandler(b"spine", handler.handler)
        self._scheme_handler = handler

        self._page = QWebEnginePage(profile, self._view)
        self._view.setPage(self._page)
        self._page.setBackgroundColor(Qt.GlobalColor.transparent)

        channel = QWebChannel(self._page)
        channel.registerObject("bridge", self._bridge)
        self._page.setWebChannel(channel)

        self._reload_view()

    def _send_text_to_model(self, text):
        if self._page:
            js_code = f"if(window.onTextFromPython)window.onTextFromPython({repr(text)});"
            self._page.runJavaScript(js_code)

    def _on_model_size(self, width, height):
        self._base_size = (max(50, int(width)), max(50, int(height)))
        self._apply_layout()

    def _on_model_rect(self, x, y, w, h):
        self._char_rect = (max(0, int(x)), max(0, int(y)), int(w), int(h))

    def _apply_layout(self):
        if not self._base_size[0] or not self._base_size[1]:
            return
        percent = max(10, int(qconfig.get(qconfig.spineZoom)))
        scale = self._scale
        css_w = max(10, round(self._base_size[0] * percent / 100 / scale))
        css_h = max(10, round(self._base_size[1] * percent / 100 / scale))
        screen = QApplication.primaryScreen()
        sw, sh = 1920, 1080
        if screen:
            geo = screen.geometry()
            sw, sh = round(geo.width() / scale), round(geo.height() / scale)
        pos = qconfig.get(qconfig.spinePosition)
        if pos is not None:
            self._user_positioned = True
            cx = max(0, min(int(pos[0]), max(0, sw - 20)))
            cy = max(0, min(int(pos[1]), max(0, sh - 20)))
        else:
            self._user_positioned = False
            margin = round(24 / scale)
            cx = max(0, sw - css_w - margin)
            cy = max(0, sh - css_h - margin)
        self._set_char_geometry(cx, cy, css_w, css_h)

    def _move_character(self, css_x, css_y):
        x = max(0, int(css_x))
        y = max(0, int(css_y))
        self._set_char_geometry(x, y, self._char_rect[2], self._char_rect[3])

    def _save_position(self):
        scale = self._scale
        qconfig.set(qconfig.spinePosition, (
            round((self.x() + _PAD_DEV) / scale),
            round((self.y() + _PAD_DEV) / scale),
        ))

    def _hwnd(self):
        try:
            return int(self.winId())
        except Exception:
            return None

    @staticmethod
    def _matches(proc, title, entries):
        if not entries:
            return False
        text = (proc + " " + title).lower()
        for entry in entries:
            e = (entry or "").strip().lower()
            if e and e in text:
                return True
        return False

    @staticmethod
    def _is_fullscreen(hwnd):
        if not hwnd:
            return False
        user32 = ctypes.windll.user32
        if not user32.IsWindowVisible(hwnd):
            return False
        hmon = user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
        if not hmon:
            return False
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return False
        rect = _RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        m = info.rcMonitor
        return (rect.left <= m.left and rect.top <= m.top
                and rect.right >= m.right and rect.bottom >= m.bottom)

    def _fg_identity(self, hwnd):
        """Return (process_name, window_title) of a window handle."""
        if not hwnd:
            return "", ""
        user32 = ctypes.windll.user32
        title = ""
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
        proc = ""
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        kernel32 = ctypes.windll.kernel32
        hproc = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if hproc:
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = ctypes.c_ulong(len(buf))
                if kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
                    proc = Path(buf.value).name
            finally:
                kernel32.CloseHandle(hproc)
        return proc, title

    def _compute_z_state(self, fg, fullscreen, maximized, proc, title):
        white = qconfig.get(qconfig.spineTopWhiteList) or []
        black = qconfig.get(qconfig.spineTopBlackList) or []
        # Whitelist: keep the model above the listed app no matter its state.
        if fg and self._matches(proc, title, white):
            return _Z_TOP
        # Blacklist: sink the model beneath the listed app no matter its state.
        if fg and self._matches(proc, title, black):
            return _Z_BOTTOM
        rule = qconfig.get(qconfig.spineTopRule)
        if rule == "always_bottom":
            return _Z_BOTTOM
        if rule == "no_fullscreen" and fullscreen:
            return _Z_NORMAL
        if rule == "no_maximized" and maximized:
            return _Z_NORMAL
        return _Z_TOP

    def _set_z_order(self):
        if sys.platform != "win32" or not self.isVisible():
            return
        hwnd = self._hwnd()
        if not hwnd:
            return
        user32 = ctypes.windll.user32
        fg = user32.GetForegroundWindow()
        if fg != self._z_fg:
            self._z_fg = fg
            self._z_fg_proc, self._z_fg_title = self._fg_identity(fg)
        fullscreen = self._is_fullscreen(fg)
        maximized = bool(fg and user32.IsZoomed(fg))
        state = self._compute_z_state(
            fg, fullscreen, maximized, self._z_fg_proc, self._z_fg_title)

        if state == self._z_state and state == _Z_NORMAL:
            return
        changed = state != self._z_state
        self._z_state = state

        flags = _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE
        if state == _Z_NORMAL:
            # Not on top: demote out of the topmost band and drop the model
            # directly below the active window.
            if user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & _WS_EX_TOPMOST:
                user32.SetWindowPos(hwnd, _HWND_NOTOPMOST, 0, 0, 0, 0, flags)
            if changed and fg and fg != hwnd:
                user32.SetWindowPos(hwnd, fg, 0, 0, 0, 0, flags)
            if self._text_input.isVisible():
                try:
                    thwnd = int(self._text_input.winId())
                    tu32 = ctypes.windll.user32
                    tex = tu32.GetWindowLongW(thwnd, _GWL_EXSTYLE)
                    if tex & _WS_EX_TOPMOST:
                        tu32.SetWindowPos(thwnd, _HWND_NOTOPMOST, 0, 0, 0, 0, flags)
                except Exception:
                    pass
            return
        if state == _Z_BOTTOM:
            if user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & _WS_EX_TOPMOST:
                user32.SetWindowPos(hwnd, _HWND_NOTOPMOST, 0, 0, 0, 0, flags)
            if changed:
                user32.SetWindowPos(hwnd, _HWND_BOTTOM, 0, 0, 0, 0, flags)
            if self._text_input.isVisible():
                try:
                    thwnd = int(self._text_input.winId())
                    tu32 = ctypes.windll.user32
                    tex = tu32.GetWindowLongW(thwnd, _GWL_EXSTYLE)
                    if tex & _WS_EX_TOPMOST:
                        tu32.SetWindowPos(thwnd, _HWND_NOTOPMOST, 0, 0, 0, 0, flags)
                    tu32.SetWindowPos(thwnd, _HWND_BOTTOM, 0, 0, 0, 0, flags)
                except Exception:
                    pass
            return
        # _Z_TOP: unconditional topmost. The model carries WS_EX_TOPMOST and
        # covers everything, including the taskbar, regardless of focus or any
        # foreground window. WS_EX_TOPMOST is sticky, so a plain window can
        # never raise itself over the model; only re-apply if the bit is lost.
        ex = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        if not (ex & _WS_EX_TOPMOST):
            user32.SetWindowPos(hwnd, _HWND_TOPMOST, 0, 0, 0, 0, flags)

        if self._text_input.isVisible():
            try:
                thwnd = int(self._text_input.winId())
                tu32 = ctypes.windll.user32
                tex = tu32.GetWindowLongW(thwnd, _GWL_EXSTYLE)
                if not (tex & _WS_EX_TOPMOST):
                    tu32.SetWindowPos(
                        thwnd, _HWND_TOPMOST, 0, 0, 0, 0, flags,
                    )
            except Exception:
                pass

    def _poll_hit_test(self):
        if not self.isVisible():
            return
        scale = self._scale
        p = QCursor.pos()
        ox, oy = self.x(), self.y()
        mx = (p.x() - ox) / scale
        my = (p.y() - oy) / scale

        if self._bridge is not None:
            self._bridge.cursorMoved.emit(int(mx), int(my))

        hwnd = int(self.winId())
        x, y, w, h = self._char_rect
        if w > 0 and h > 0:
            zx = x + w * 0.35
            zw = w * 0.30
            zy = y + h * 0.33
            zh = h * 0.13
            in_zone = (zx <= mx <= zx + zw and zy <= my <= zy + zh)
        else:
            in_zone = False

        u32 = ctypes.windll.user32
        ex = u32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        if in_zone:
            new_ex = ex & ~_WS_EX_TRANSPARENT
        else:
            new_ex = ex | _WS_EX_TRANSPARENT
        if new_ex != ex:
            u32.SetWindowLongW(hwnd, _GWL_EXSTYLE, new_ex)

    def on_page_error(self, msg):
        self._error = True

    def _reload_view(self):
        if not self._view:
            return
        self._base_size = (0, 0)
        self._view.setUrl(QUrl(
            f"spine://local/web/index.html?model={self._model}"
            f"&voice={qconfig.get(qconfig.voiceLang)}&v={_SPINE_ASSET_VERSION}"
        ))

    def set_model(self, model):
        if model not in _MODELS or model == self._model:
            return
        self._model = model
        self._chat_history = load_history(model)
        self._reload_view()

    def _on_voice_changed(self, voice):
        self._reload_view()

    def set_zoom(self, percent):
        if self._view:
            self._apply_layout()

    def _on_model_changed(self, model):
        self.set_model(model)

    def _on_visible_changed(self, visible):
        if visible and not self.isVisible():
            self.show()
        elif not visible and self.isVisible():
            self.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._view:
            self._view.setGeometry(0, 0, self.width(), self.height())

    def _toggle_text_input(self):
        if self._text_input.isVisible():
            self._text_input.hide()
        else:
            scale = self._scale
            x, y, w, h = self._char_rect
            if w <= 0 or h <= 0:
                return
            input_x = self.x() + round((x + w * 0.5) * scale) - 130
            input_y = self.y() + round((y + h * 0.46) * scale) + 10
            self._text_input.move(input_x, input_y)
            self._text_input.show()
            self._text_input.raise_()
            self._text_input._input.setFocus()

    def _on_text_submitted(self, text):
        if not text.strip():
            return
        if self._ai_worker and self._ai_worker.isRunning():
            return

        contact_key = self._model
        ts = datetime.now().strftime("%H:%M:%S")

        self._chat_history = load_history(contact_key)
        self._chat_history.append({"role": "user", "content": text, "timestamp": ts})
        self._save_chat_history()
        self._text_input._input.clear()

        self._show_bubble("思考中...", is_self=False)

        api_history = [{"role": m["role"], "content": m["content"]}
                       for m in self._chat_history[:-1]]
        self._ai_worker = AIWorker(contact_key, text, api_history)
        self._ai_worker.finished.connect(self._on_ai_reply)
        self._ai_worker.error.connect(self._on_ai_error)
        self._ai_worker.start()

    def _on_ai_reply(self, reply_text):
        contact_key = self._model
        ts = datetime.now().strftime("%H:%M:%S")
        self._chat_history = load_history(contact_key)
        self._chat_history.append({"role": "assistant", "content": reply_text, "timestamp": ts})
        self._save_chat_history()
        self._show_bubble(reply_text, is_self=False)

    def _on_ai_error(self, error_msg):
        self._show_bubble(f"[错误] {error_msg}", is_self=False)

    def _save_chat_history(self):
        contact_key = self._model
        save_history(contact_key, self._chat_history)

    def _show_bubble(self, text, is_self=False):
        for b in self._chat_bubbles:
            try:
                qconfig.themeChanged.disconnect(b._theme_func)
            except RuntimeError:
                pass
            b.setParent(None)
            b.deleteLater()
        self._chat_bubbles.clear()

        bubble = _SpineChatBubble(text, is_self=is_self)
        self._chat_bubbles.append(bubble)
        x, y, w, h = self._char_rect
        bubble.position_above(self.x(), self.y(), x, y, w, h, self._scale)
        bubble.show()
        bubble.raise_()

        QTimer.singleShot(5000, lambda b=bubble: self._fade_bubble(b))

    def _fade_bubble(self, bubble):
        if bubble in self._chat_bubbles:
            try:
                qconfig.themeChanged.disconnect(bubble._theme_func)
            except RuntimeError:
                pass
            bubble.setParent(None)
            bubble.deleteLater()
            self._chat_bubbles.remove(bubble)

    def _handle_double_click(self):
        self._toggle_text_input()

    def closeEvent(self, event):
        self._unregister_hotkey()
        self._text_input.hide()
        event.ignore()
        self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        self._ensure_noactivate()
        try:
            hwnd = int(self.winId())
            u32 = ctypes.windll.user32
            ex = u32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            if not ex & _WS_EX_TRANSPARENT:
                u32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex | _WS_EX_TRANSPARENT)
        except Exception:
            pass
        self._set_z_order()
        self._poll_hit_test()
        self._register_hotkey()
        self.visibilityChangedSignal.emit(True)
        if not self._chat_history:
            self._chat_history = load_history(self._model)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.visibilityChangedSignal.emit(False)
