import json
from urllib.parse import unquote

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout

from App.update_utils import get_assets_dir

_WSGI_HOST = "qtwebview2.local"
_WSGI_BASE = f"http://{_WSGI_HOST}"

_ROOT = (get_assets_dir() / "Spine").resolve()

_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript",
    ".css": "text/css",
    ".skel": "application/octet-stream",
    ".atlas": "text/plain",
    ".png": "image/png",
    ".json": "application/json",
    ".ogg": "audio/ogg",
}

_REWRITE_SUFFIXES = (".html", ".js")


def _finalize_wsgi_response_buffered(self, args, deferral, status, headers,
                                     iterator):
    """替换 QtWebView2Widget 的响应槽，避免任何反向 .NET 回调。

    qtwebview2 0.5.0 原本把响应体交给 PythonGeneratorStream，WebView2 的 COM
    线程会经 pythonnet 回调进 Python 的 Read（Marshal.Copy 路径），在 GC 或
    异常分发时触发 0xC0000005 AccessViolation。这里改成在 Python 侧先把响应体
    整个读出来，再用纯 .NET MemoryStream 交给 CreateWebResourceResponse。
    """
    from qtwebview2 import _dotnet_bridge as dotnet
    from qtwebview2.logger import logger

    try:
        if not status or status.startswith('500') or iterator is None:
            reason_phrase = "Internal Server Error"
            status_code = 500
            content_stream = None
        else:
            parts = status.split(' ', 1)
            status_code = int(parts[0])
            reason_phrase = parts[1] if len(parts) > 1 else "OK"
            try:
                body = b"".join(iterator)
            finally:
                if hasattr(iterator, 'close'):
                    try:
                        iterator.close()
                    except Exception:
                        pass
            content_stream = dotnet.System_.IO.MemoryStream(body)

        env = self._webview.CoreWebView2.Environment
        response = env.CreateWebResourceResponse(
            content_stream,
            status_code,
            reason_phrase,
            ""
        )

        if headers:
            for name, value in headers:
                try:
                    response.Headers.AppendHeader(name, value)
                except Exception:
                    pass

        args.Response = response
    except Exception as e:
        logger.error(f"Error finalizing WSGI response: {e}", exc_info=True)
    finally:
        if deferral:
            try:
                deferral.Complete()
            except Exception as e:
                logger.warning(
                    f"Failed to complete deferral (page might be closed): {e}")


_patch_applied = False


def _apply_qtwebview2_patch():
    global _patch_applied
    if _patch_applied:
        return
    from qtwebview2 import QtWebView2Widget
    QtWebView2Widget._finalize_wsgi_response = \
        _finalize_wsgi_response_buffered
    _patch_applied = True


def _rewrite(data: bytes, suffix: str) -> bytes:
    if suffix not in _REWRITE_SUFFIXES:
        return data
    text = data.decode("utf-8")
    text = text.replace("qrc:///qtwebchannel/qwebchannel.js",
                        "/web/bridge-shim.js")
    text = text.replace("spine://local", _WSGI_BASE)
    return text.encode("utf-8")


def _wsgi_app(environ, start_response):
    path = unquote(environ.get("PATH_INFO", "/"))
    try:
        full = (_ROOT / path.lstrip("/")).resolve()
        full.relative_to(_ROOT)
    except (ValueError, OSError):
        start_response("403 Forbidden",
                       [("Content-Type", "text/plain")])
        return [b"Forbidden"]
    if not full.is_file():
        start_response("404 Not Found",
                       [("Content-Type", "text/plain")])
        return [b"Not Found"]
    data = full.read_bytes()
    data = _rewrite(data, full.suffix.lower())
    start_response("200 OK", [
        ("Content-Type", _TYPES.get(full.suffix.lower(),
                                    "application/octet-stream")),
        ("Content-Length", str(len(data))),
        ("Cache-Control", "no-store"),
    ])
    return [data]


class SpineWebView(QWidget):
    """承载桌宠页面的 WebView2 宿主（用来替换 WebEngine）。

    用进程内的 WSGI 服务把 Assets/Spine 提供出去（http://qtwebview2.local），
    并把 QWebChannel 的协议翻译成 qtwebview2 的桥接调用。
    """

    def __init__(self, parent=None, bridge=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self._bridge = bridge

        from qtwebview2 import QtWebView2Widget
        _apply_qtwebview2_patch()
        self._inner = QtWebView2Widget(
            transparent=True,
            js_apis={"wcMessage": self._on_wc_message},
            wsgi_app=_wsgi_app,
            wsgi_host_name=_WSGI_HOST,
            parent=self,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._inner)

        if bridge is not None:
            bridge.layoutChanged.connect(
                lambda x, y, w, h: self._push_signal("layoutChanged",
                                                     [x, y, w, h]))
            bridge.moveTo.connect(
                lambda x, y: self._push_signal("moveTo", [x, y]))
            bridge.cursorMoved.connect(
                lambda x, y: self._push_signal("cursorMoved", [x, y]))

    def setUrl(self, url):
        self._inner.load_url(str(url))

    def run_js(self, script):
        self._inner.evaluate_js(script)

    def _push_signal(self, name, args):
        payload = json.dumps({"m": name, "a": list(args)},
                             ensure_ascii=True)
        script = (
            "(function(){var t=window.qt&&window.qt.webChannelTransport;"
            "if(t&&t.onmessage){t.onmessage({data:"
            + json.dumps(payload)
            + "});}})();"
        )
        self._inner.evaluate_js(script)

    def _on_wc_message(self, payload):
        if self._bridge is None:
            return None
        try:
            msg = json.loads(payload)
            name = msg.get("m")
            args = msg.get("a") or []
        except (ValueError, AttributeError, TypeError):
            return None
        b = self._bridge
        if name == "setModelSize" and len(args) >= 2:
            b.setModelSize(int(args[0]), int(args[1]))
        elif name == "setModelRect" and len(args) >= 4:
            b.setModelRect(int(args[0]), int(args[1]),
                           int(args[2]), int(args[3]))
        elif name == "showError" and args:
            b.showError(str(args[0]))
        elif name == "onDoubleClick":
            b.onDoubleClick()
        elif name == "sendTextToModel" and args:
            b.sendTextToModel.emit(str(args[0]))
        elif name == "patZone" and len(args) >= 4:
            b.patZone(int(args[0]), int(args[1]),
                      int(args[2]), int(args[3]))
        elif name == "patState" and args:
            b.patState(int(args[0]))
        elif name == "chatZone" and len(args) >= 4:
            b.chatZone(int(args[0]), int(args[1]),
                       int(args[2]), int(args[3]))
        elif name == "dragState" and args:
            b.dragState(int(args[0]))
        return None
