from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QListWidgetItem,
)
from PySide6.QtCore import Qt, QTimer, QSize, Signal
from PySide6.QtGui import QPixmap, QIcon, QPainter, QPainterPath, QTextOption
from qfluentwidgets import (
    ScrollArea, PrimaryPushButton, ListWidget, BodyLabel,
    RoundMenu, Action, FluentIcon as FIF, PlainTextEdit,
    SimpleCardWidget, TransparentToolButton, CaptionLabel,
)
from qfluentwidgets.common.font import getFont

from ..update_utils import get_assets_dir
from ..scroll_utils import enable_touch_scroll
from .chat_bubble import ChatBubble
from ..ai_chat import AIWorker, load_history, write_history


class _InputEdit(PlainTextEdit):
    enterPressed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._min_height = 36
        self._max_height = 150
        self.setFixedHeight(self._min_height)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.textChanged.connect(self._adjust_height)

    def _adjust_height(self):
        line_h = self.fontMetrics().lineSpacing()
        lines = max(1, int(self.document().size().height()))
        h = max(self._min_height, min(lines * line_h + 16, self._max_height))
        self.setFixedHeight(h)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.textCursor().insertText("\n")
                return
            else:
                self.enterPressed.emit()
                return
        super().keyPressEvent(e)

    def contextMenuEvent(self, e):
        has_selection = self.textCursor().hasSelection()

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


class _QuoteCard(SimpleCardWidget):
    removeRequested = Signal(int)

    def __init__(self, index: int, sender: str, text: str, compact=False, parent=None):
        super().__init__(parent)
        self._index = index
        self.setFixedHeight(48 if not compact else 36)
        self.setMinimumWidth(160)
        self.setMaximumWidth(200)
        self.setBorderRadius(6)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 4, 4)
        layout.setSpacing(4)

        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        text_col.setContentsMargins(0, 0, 0, 0)

        sender_lbl = CaptionLabel(sender)
        sender_lbl.setFont(getFont(10))
        text_col.addWidget(sender_lbl)

        text_lbl = CaptionLabel(text)
        text_lbl.setFont(getFont(10))
        text_lbl.setMaximumWidth(170)
        text_elided = text if len(text) <= 30 else text[:28] + "..."
        text_lbl.setText(text_elided)
        text_col.addWidget(text_lbl)

        layout.addLayout(text_col, 1)

        if not compact:
            close_btn = TransparentToolButton(FIF.CLOSE)
            close_btn.setFixedSize(20, 20)
            close_btn.clicked.connect(lambda: self.removeRequested.emit(self._index))
            layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)


def crop_circle(pixmap: QPixmap) -> QPixmap:
    if pixmap.isNull():
        return pixmap
    w, h = pixmap.width(), pixmap.height()
    size = min(w, h)
    x = (w - size) // 2
    y = (h - size) // 2
    square = pixmap.copy(x, y, size, size)

    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, square)
    painter.end()
    return out


class ChatPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("chatPage")
        self._contacts = {}
        self._avatar_pixmaps = {}
        self._messages = {}
        self._quoted_messages = []
        self._current_contact = None
        self._ai_worker = None
        self._thinking_bubble = None
        self._undoing = False
        self._setup_ui()
        self._load_contacts()

    def _setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        contact_panel = QWidget()
        contact_panel.setFixedWidth(280)
        contact_panel.setStyleSheet("background: transparent;")
        contact_layout = QVBoxLayout(contact_panel)
        contact_layout.setContentsMargins(12, 16, 8, 16)
        contact_layout.setSpacing(8)

        header = BodyLabel("成员")
        header.setFont(getFont(14))
        contact_layout.addWidget(header)

        self._contact_list = ListWidget()
        self._contact_list.setStyleSheet(
            "ListWidget { background: transparent; border: none; }"
        )
        self._contact_list.setIconSize(QSize(48, 48))
        self._contact_list.currentItemChanged.connect(self._on_contact_selected)
        contact_layout.addWidget(self._contact_list)

        root.addWidget(contact_panel)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setStyleSheet("color: rgba(0,0,0,0.12);")
        root.addWidget(separator)

        chat_area = QWidget()
        chat_area.setStyleSheet("background: transparent;")
        chat_layout = QVBoxLayout(chat_area)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)

        self._scroll_area = ScrollArea(chat_area)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setStyleSheet(
            "ScrollArea { background: transparent; border: none; }"
        )

        self._msg_container = QWidget()
        self._msg_container.setStyleSheet("background: transparent;")
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(24, 16, 24, 16)
        self._msg_layout.setSpacing(0)
        self._msg_layout.addStretch()

        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setWidget(self._msg_container)
        enable_touch_scroll(self._scroll_area)
        chat_layout.addWidget(self._scroll_area, 1)

        self._quote_bar = QWidget()
        self._quote_bar.setStyleSheet("background: transparent;")
        self._quote_bar.hide()
        quote_bar_layout = QHBoxLayout(self._quote_bar)
        quote_bar_layout.setContentsMargins(16, 4, 8, 4)
        quote_bar_layout.setSpacing(4)

        self._quote_scroll = ScrollArea()
        self._quote_scroll.setFixedHeight(56)
        self._quote_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._quote_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._quote_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._quote_scroll.setStyleSheet(
            "ScrollArea { background: transparent; border: none; }"
        )

        self._quote_container = QWidget()
        self._quote_container.setStyleSheet("background: transparent;")
        self._quote_layout = QHBoxLayout(self._quote_container)
        self._quote_layout.setContentsMargins(4, 2, 4, 2)
        self._quote_layout.setSpacing(6)
        self._quote_layout.addStretch()

        self._quote_scroll.setWidgetResizable(True)
        self._quote_scroll.setWidget(self._quote_container)
        quote_bar_layout.addWidget(self._quote_scroll, 1)

        clear_all_btn = TransparentToolButton(FIF.CLOSE)
        clear_all_btn.setFixedSize(28, 28)
        clear_all_btn.clicked.connect(self._clear_quotes)
        quote_bar_layout.addWidget(clear_all_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        chat_layout.addWidget(self._quote_bar)

        input_bar = QWidget()
        input_bar.setStyleSheet("background: transparent;")
        input_bar_layout = QHBoxLayout(input_bar)
        input_bar_layout.setContentsMargins(16, 8, 16, 12)
        input_bar_layout.setSpacing(8)

        self._input = _InputEdit()
        self._input.setPlaceholderText("输入消息...")
        self._input.setFont(getFont(14))
        self._input.enterPressed.connect(self._send_message)
        input_bar_layout.addWidget(self._input, 1)

        self._send_btn = PrimaryPushButton(FIF.SEND, "发送")
        self._send_btn.setFixedWidth(80)
        self._send_btn.setMinimumHeight(36)
        self._send_btn.clicked.connect(self._send_message)
        input_bar_layout.addWidget(self._send_btn)

        chat_layout.addWidget(input_bar)

        root.addWidget(chat_area, 1)

    def _load_contacts(self):
        config_path = get_assets_dir() / "Chat" / "config.ini"
        if not config_path.exists():
            return

        for line in config_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, name = line.split("=", 1)
            key = key.strip()
            name = name.strip()
            self._contacts[key] = name

            avatar_path = get_assets_dir() / "Chat" / key.lower() / "logo.png"
            icon = QIcon()
            pixmap = QPixmap()
            if avatar_path.exists():
                pixmap = QPixmap(str(avatar_path))
                if not pixmap.isNull():
                    icon = QIcon(crop_circle(pixmap))
                    self._avatar_pixmaps[key] = pixmap

            item = QListWidgetItem(icon, name)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setSizeHint(QSize(0, 56))
            self._contact_list.addItem(item)

        if self._contact_list.count() > 0:
            self._contact_list.setCurrentRow(0)

    def _on_contact_selected(self, current, _previous):
        if current is None:
            return
        key = current.data(Qt.ItemDataRole.UserRole)
        if key == self._current_contact:
            return
        self._current_contact = key
        self._load_history(key)
        self._reload_messages()

    def _load_history(self, contact_key):
        history = load_history(contact_key)
        msgs = []
        avatar = self._avatar_pixmaps.get(contact_key)
        for h in history:
            ts = h.get("timestamp", "")
            if h["role"] == "user":
                msgs.append({
                    "text": h["content"], "is_self": True,
                    "sender": "老师", "avatar": None, "time": ts,
                })
            elif h["role"] == "assistant":
                name = self._contacts.get(contact_key, contact_key)
                msgs.append({
                    "text": h["content"], "is_self": False,
                    "sender": name, "avatar": avatar, "time": ts,
                })
        self._messages[contact_key] = msgs

    def _reload_messages(self):
        for i in range(self._msg_layout.count()):
            item = self._msg_layout.itemAt(i)
            if item and item.widget():
                w = item.widget()
                if w is not self._msg_container:
                    w.deleteLater()

        messages = self._messages.get(self._current_contact, [])
        for idx, msg in enumerate(messages):
            bubble = ChatBubble(
                text=msg["text"],
                is_self=msg["is_self"],
                sender=msg["sender"],
                avatar=msg.get("avatar"),
                msg_index=idx,
                quotes=msg.get("quotes"),
                time=msg.get("time", ""),
            )
            bubble.undoRequested = self._undo_message
            bubble.quoteRequested = self._quote_message
            self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)

        self._sync_bubble_widths()
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _quote_message(self, msg_index):
        messages = self._messages.get(self._current_contact, [])
        if msg_index < 0 or msg_index >= len(messages):
            return
        msg = messages[msg_index]
        self._quoted_messages.append({
            "index": msg_index,
            "text": msg["text"],
            "sender": msg["sender"],
        })
        self._refresh_quote_bar()

    def _remove_quote(self, index):
        self._quoted_messages = [q for q in self._quoted_messages if q["index"] != index]
        self._refresh_quote_bar()

    def _clear_quotes(self):
        self._quoted_messages.clear()
        self._refresh_quote_bar()

    def _refresh_quote_bar(self):
        for i in range(self._quote_layout.count()):
            item = self._quote_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

        if not self._quoted_messages:
            self._quote_bar.hide()
            return

        for q in self._quoted_messages:
            card = _QuoteCard(q["index"], q["sender"], q["text"])
            card.removeRequested.connect(self._remove_quote)
            self._quote_layout.insertWidget(self._quote_layout.count() - 1, card)

        self._quote_bar.show()

    def _undo_message(self, index):
        messages = self._messages.get(self._current_contact, [])
        if index < 0 or index >= len(messages):
            return

        undone = messages[index]
        self._messages[self._current_contact] = messages[:index]

        if undone["is_self"]:
            # Prevent the restored text from being auto‑sent
            self._undoing = True
            self._input.setPlainText(undone["text"])
            self._undoing = False

        self._reload_messages()

        contact = self._current_contact
        if contact:
            write_history(contact, [{"role": "user" if m["is_self"] else "assistant",
                                     "content": m["text"],
                                     "timestamp": m.get("time", "")}
                                    for m in self._messages[contact]])

    def send_message(self, text: str, is_self: bool = True,
                     sender: str = "", avatar=None, contact=None, quotes=None):
        from datetime import datetime
        contact = contact or self._current_contact
        ts = datetime.now().strftime("%H:%M:%S")
        if contact:
            self._messages.setdefault(contact, []).append({
                "text": text, "is_self": is_self,
                "sender": sender, "avatar": avatar,
                "quotes": quotes, "time": ts,
            })

        if contact == self._current_contact:
            idx = len(self._messages[contact]) - 1
            bubble = ChatBubble(
                text=text,
                is_self=is_self,
                sender=sender,
                avatar=avatar,
                msg_index=idx,
                quotes=quotes,
                time=ts,
            )
            bubble.undoRequested = self._undo_message
            bubble.quoteRequested = self._quote_message
            self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)
            self._sync_bubble_widths()
            QTimer.singleShot(50, self._scroll_to_bottom)

    def _send_message(self):
        text = self._input.toPlainText().strip()
        if not text or not self._current_contact:
            return
        if self._ai_worker and self._ai_worker.isRunning():
            return
        # Prevent sending a message that was restored by an undo operation
        if getattr(self, "_undoing", False):
            return
        quotes = list(self._quoted_messages) if self._quoted_messages else None
        self._quoted_messages.clear()
        self._refresh_quote_bar()
        self.send_message(text, is_self=True, sender="老师", quotes=quotes)
        self._input.clear()
        self._start_ai_reply(text)

    def _start_ai_reply(self, user_text):
        contact = self._current_contact
        if not contact:
            return
        self._show_thinking(contact)
        history = self._messages.get(contact, [])
        api_history = []
        for m in history[:-1]:
            role = "user" if m["is_self"] else "assistant"
            api_history.append({"role": role, "content": m["text"]})
        self._ai_worker = AIWorker(contact, user_text, api_history)
        self._ai_worker.finished.connect(self._on_ai_reply)
        self._ai_worker.error.connect(self._on_ai_error)
        self._ai_worker.start()

    def _show_thinking(self, contact_key):
        name = self._contacts.get(contact_key, contact_key)
        avatar = self._avatar_pixmaps.get(contact_key)
        bubble = ChatBubble("思考中...", is_self=False, sender=name, avatar=avatar)
        bubble.setDisabled(True)
        self._thinking_bubble = bubble
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)
        self._sync_bubble_widths()
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _on_ai_reply(self, reply_text):
        if self._thinking_bubble:
            try:
                self._thinking_bubble.setParent(None)
            except RuntimeError:
                pass
            try:
                self._thinking_bubble.deleteLater()
            except RuntimeError:
                pass
            self._thinking_bubble = None
        contact = self._current_contact
        if not contact:
            return
        name = self._contacts.get(contact, contact)
        avatar = self._avatar_pixmaps.get(contact)
        self.send_message(reply_text, is_self=False, sender=name, avatar=avatar)
        history = self._messages.get(contact, [])
        write_history(contact, [{"role": "user" if m["is_self"] else "assistant",
                                 "content": m["text"],
                                 "timestamp": m.get("time", "")} for m in history])

    def _on_ai_error(self, error_msg):
        if self._thinking_bubble:
            try:
                self._thinking_bubble.setParent(None)
            except RuntimeError:
                pass
            try:
                self._thinking_bubble.deleteLater()
            except RuntimeError:
                pass
            self._thinking_bubble = None
        contact = self._current_contact
        if not contact:
            return
        name = self._contacts.get(contact, contact)
        avatar = self._avatar_pixmaps.get(contact)
        self.send_message(f"[错误] {error_msg}", is_self=False, sender=name, avatar=avatar)

    def _scroll_to_bottom(self):
        sb = self._scroll_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._sync_bubble_widths)

    def _sync_bubble_widths(self):
        vw = self._scroll_area.viewport().width()
        max_w = max(200, int(vw * 2 / 3))
        for i in range(self._msg_layout.count()):
            item = self._msg_layout.itemAt(i)
            if item and item.widget() and hasattr(item.widget(), '_bubble'):
                item.widget()._bubble.setMaxBubbleWidth(max_w)
