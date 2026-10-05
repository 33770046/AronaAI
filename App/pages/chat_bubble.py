from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QTextOption
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSizePolicy, QApplication,
    QTextEdit,
)
from qfluentwidgets import (
    CardWidget, AvatarWidget, CaptionLabel, SimpleCardWidget,
    isDarkTheme, qconfig, RoundMenu, Action, FluentIcon as FIF,
)
from qfluentwidgets.common.font import getFont
from qfluentwidgets.common.style_sheet import (
    setCustomStyleSheet, styleSheetManager,
    CustomStyleSheetWatcher, DirtyStyleSheetWatcher,
    StyleSheetCompose, CustomStyleSheet,
)

from ..config import MOMOTALK, get_accent_color


class ChatBubble(QWidget):

    undoRequested = None
    quoteRequested = None

    def __init__(self, text: str, is_self: bool = False,
                 sender: str = "", avatar=None, msg_index=-1,
                 quotes=None, time: str = "", parent=None):
        super().__init__(parent)
        self._is_self = is_self
        self._sender = sender
        self._avatar = avatar
        self._text = text
        self._msg_index = msg_index
        self._quotes = quotes
        self._time = time if time else datetime.now().strftime("%H:%M:%S")
        self._setup_ui()

    def _setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 2)
        root.setSpacing(8)

        if not self._is_self:
            av = AvatarWidget(self._avatar) if self._avatar else AvatarWidget()
            av.setRadius(22)
            root.addWidget(av, 0, Qt.AlignmentFlag.AlignTop)

        if self._is_self:
            root.addStretch(1)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        if not self._is_self and self._sender:
            info_row = QHBoxLayout()
            info_row.setSpacing(6)
            info_row.setContentsMargins(0, 0, 0, 0)

            name_lbl = CaptionLabel(self._sender)
            name_lbl.setFont(getFont(11))
            info_row.addWidget(name_lbl)

            time_lbl = CaptionLabel(self._time)
            time_lbl.setFont(getFont(10))
            info_row.addWidget(time_lbl)

            info_row.addStretch()
            text_col.addLayout(info_row)

        self._bubble = _BubbleWidget(self._text, self._is_self, self._msg_index, self._quotes)
        self._bubble.undoRequested = self._on_undo
        self._bubble.quoteRequested = self._on_quote
        text_col.addWidget(self._bubble)

        if self._is_self:
            time_lbl = CaptionLabel(self._time)
            time_lbl.setFont(getFont(10))
            time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            text_col.addWidget(time_lbl)

        root.addLayout(text_col, 0)

        if not self._is_self:
            root.addStretch(1)

        self._name_lbl = name_lbl if (not self._is_self and self._sender) else None
        self._time_lbl = time_lbl
        self._apply_outer_theme()
        qconfig.themeChanged.connect(self._apply_outer_theme)

    def _apply_outer_theme(self):
        is_momo = qconfig.get(qconfig.themeMode) == MOMOTALK
        if is_momo:
            color = QColor("#282828")
        elif isDarkTheme():
            color = QColor("#D0D0D0")
        else:
            color = QColor("#282828")

        if self._time_lbl:
            self._time_lbl.setTextColor(color, color)
        if self._name_lbl:
            self._name_lbl.setTextColor(color, color)

    def _on_undo(self):
        if self.undoRequested and self._msg_index >= 0:
            self.undoRequested(self._msg_index)

    def _on_quote(self, msg_index=None):
        if self.quoteRequested:
            idx = msg_index if msg_index is not None else self._msg_index
            if idx >= 0:
                self.quoteRequested(idx)


class _MsgEdit(QTextEdit):
    contextMenuRequested = None

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setPlainText(text)
        self.setReadOnly(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QTextEdit.Shape.NoFrame)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setFont(getFont(14))
        self._maxBubbleWidth = 451
        QTimer.singleShot(0, self._sync_size)

    def setMaxBubbleWidth(self, w):
        self._maxBubbleWidth = w
        self._sync_size()

    def _sync_size(self):
        doc = self.document()
        doc.setTextWidth(-1)
        natural_w = int(doc.idealWidth()) + 2
        w = min(natural_w, self._maxBubbleWidth)
        self.setFixedWidth(w)
        doc.setTextWidth(w)
        h = int(doc.size().height()) + 2
        self.setMinimumHeight(h)
        self.setMaximumHeight(h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_size()

    def contextMenuEvent(self, e):
        if self.contextMenuRequested:
            self.contextMenuRequested(e)

    def wheelEvent(self, e):
        e.ignore()


class _BubbleWidget(CardWidget):

    undoRequested = None

    def __init__(self, text: str, is_self: bool, msg_index=-1, quotes=None, parent=None):
        self._is_self = is_self
        self._msg_index = msg_index
        self._quotes = quotes
        super().__init__(parent)
        self.setBorderRadius(12)
        self.setClickEnabled(False)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)

        inner = QVBoxLayout(self)
        inner.setContentsMargins(12, 8, 12, 8)
        inner.setSpacing(0)

        if self._quotes:
            quote_block = self._build_quote_block()
            inner.addWidget(quote_block)

        self._msg_edit = _MsgEdit(text)
        self._msg_edit.contextMenuRequested = self._show_menu
        if self._msg_edit not in styleSheetManager.widgets:
            self._msg_edit.destroyed.connect(lambda: styleSheetManager.deregister(self._msg_edit))
            self._msg_edit.installEventFilter(CustomStyleSheetWatcher(self._msg_edit))
            self._msg_edit.installEventFilter(DirtyStyleSheetWatcher(self._msg_edit))
            styleSheetManager.widgets[self._msg_edit] = StyleSheetCompose([CustomStyleSheet(self._msg_edit)])
        inner.addWidget(self._msg_edit)

        self._apply_theme()
        qconfig.themeChanged.connect(self._apply_theme)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            e.accept()
            from PySide6.QtGui import QContextMenuEvent
            ce = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, e.position().toPoint(), e.globalPosition().toPoint())
            self._show_menu(ce)
            return
        super().mousePressEvent(e)

    def _normalBackgroundColor(self):
        is_momo = qconfig.get(qconfig.themeMode) == MOMOTALK
        if is_momo:
            return QColor("#4A8ACB") if self._is_self else QColor("#4A5A70")
        elif self._is_self:
            return QColor(get_accent_color())
        elif isDarkTheme():
            return QColor("#373737")
        else:
            return QColor("#F0F0F0")

    def _hoverBackgroundColor(self):
        return self._normalBackgroundColor().lighter(108)

    def _pressedBackgroundColor(self):
        return self._normalBackgroundColor().darker(108)

    def _build_quote_block(self):
        block = QWidget()
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(0, 0, 0, 4)
        block_layout.setSpacing(2)

        accent = get_accent_color()

        for q in self._quotes:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)

            bar = SimpleCardWidget()
            bar.setFixedWidth(3)
            bar.setFixedHeight(30)
            bar.setBorderRadius(1)
            bar.setStyleSheet(f"background-color: {accent};")
            row_layout.addWidget(bar, 0, Qt.AlignmentFlag.AlignTop)

            col = QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(0)

            sender_lbl = CaptionLabel(q["sender"])
            sender_lbl.setFont(getFont(10))
            col.addWidget(sender_lbl)

            text = q["text"]
            text_elided = text if len(text) <= 40 else text[:38] + "..."
            text_lbl = CaptionLabel(text_elided)
            text_lbl.setFont(getFont(10))
            col.addWidget(text_lbl)

            row_layout.addLayout(col, 1)
            block_layout.addWidget(row)

        return block

    def setMaxBubbleWidth(self, w):
        self.setMaximumWidth(w)
        self._msg_edit.setMaxBubbleWidth(w - 24)

    def _apply_theme(self):
        is_momo = qconfig.get(qconfig.themeMode) == MOMOTALK
        self.setBackgroundColor(self._normalBackgroundColor())
        self.update()

        if is_momo:
            light = dark = QColor("#FFFFFF")
        elif self._is_self:
            light, dark = QColor("#FFFFFF"), QColor("#282828")
        else:
            light, dark = QColor("#282828"), QColor("#FFFFFF")

        setCustomStyleSheet(
            self._msg_edit,
            f"QTextEdit{{color:{light.name(QColor.NameFormat.HexArgb)}}}",
            f"QTextEdit{{color:{dark.name(QColor.NameFormat.HexArgb)}}}",
        )

        self._msg_edit.setFont(getFont(14))

    def _show_menu(self, e):
        cursor = self._msg_edit.textCursor()
        self._selected_text = cursor.selectedText()

        menu = RoundMenu(parent=self)

        copy = Action(FIF.COPY, "复制")
        copy.triggered.connect(self._copy_text)
        menu.addAction(copy)

        if self._is_self:
            undo = Action(FIF.CANCEL, "撤销")
            undo.triggered.connect(self._on_undo)
            menu.addAction(undo)

        quote = Action(FIF.MESSAGE, "引用")
        quote.triggered.connect(self._on_quote)
        menu.addAction(quote)

        menu.exec(e.globalPos())

    def _copy_text(self):
        text = self._selected_text if self._selected_text else self._msg_edit.toPlainText()
        QApplication.clipboard().setText(text)

    def _on_undo(self):
        if self.undoRequested:
            self.undoRequested()

    def _on_quote(self):
        if self.quoteRequested and self._msg_index >= 0:
            self.quoteRequested(self._msg_index)
