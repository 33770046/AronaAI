import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QApplication, QLayout, QLayoutItem,
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, QSize, QRect, QPoint
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QFontMetrics, QColor
from qfluentwidgets import (
    qconfig, Theme, ScrollArea,
    CardWidget, CaptionLabel, BodyLabel, PushButton, ImageLabel,
)
from qfluentwidgets.common.font import getFont

from ..crawler import GameKeeActivity, fetch_all_activities
from ..crawler.images import download_all_images, image_path
from ..config import get_accent_color
from ..scroll_utils import enable_touch_scroll

SERVER_IDS = {"国服": 16, "国际服": 17, "日服": 15}
SERVER_NAMES = {16: "国服", 17: "国际服", 15: "日服"}
SERVER_TABS = ["国服", "国际服", "日服"]

CARD_W = 200
CARD_H = 218
BANNER_H = 112


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=12):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._doLayout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _doLayout(self, rect, testOnly):
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        line_height = 0
        spacing = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width()
            if next_x > rect.right() - m.right() + 1 and line_height > 0:
                x = rect.x() + m.left()
                y = y + line_height + spacing
                next_x = x + hint.width()
                line_height = 0
            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x + spacing
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + m.bottom()


def _rounded_top_pixmap(pm: QPixmap, radius: int) -> QPixmap:
    out = QPixmap(pm.size())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, pm.width(), pm.height(), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pm)
    painter.end()
    return out


class CrawlWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, force: bool = False, parent=None):
        super().__init__(parent)
        self._force = force

    def run(self):
        try:
            result = fetch_all_activities([16, 17, 15], force=self._force)
            if not self.isInterruptionRequested():
                self.finished.emit(result)
        except Exception as e:
            if not self.isInterruptionRequested():
                self.error.emit(str(e))


class ImageWorker(QThread):
    finished = Signal()
    error = Signal(str)

    def run(self):
        try:
            download_all_images(self._activities)
            if not self.isInterruptionRequested():
                self.finished.emit()
        except Exception as e:
            if not self.isInterruptionRequested():
                self.error.emit(str(e))

    def setActivities(self, activities: list):
        self._activities = activities


class ActivityCard(CardWidget):
    def __init__(self, activity: GameKeeActivity, parent=None):
        super().__init__(parent=parent)
        self._activity = activity
        self.setBorderRadius(8)
        self.setFixedSize(CARD_W, CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setupUi()
        self._applyStyles()

    def _setupUi(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._banner = ImageLabel(self)
        self._banner.setFixedSize(CARD_W, BANNER_H)
        self._loadBanner()
        layout.addWidget(self._banner)

        info = QWidget(self)
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(8, 8, 8, 8)
        info_layout.setSpacing(4)

        self._title = BodyLabel(self._activity.title)
        self._title.setWordWrap(True)
        self._title.setFixedHeight(36)
        info_layout.addWidget(self._title)

        self._desc = CaptionLabel()
        self._desc.setFixedHeight(16)
        if self._activity.description:
            fm = QFontMetrics(self._desc.font())
            elided = fm.elidedText(self._activity.description, Qt.TextElideMode.ElideRight, CARD_W - 16)
            self._desc.setText(elided)
        else:
            self._desc.hide()
        info_layout.addWidget(self._desc)

        status_row = QHBoxLayout()
        status_row.setSpacing(4)
        state_map = {1: "进行中", 2: "将开始"}
        self._state_label = BodyLabel(state_map.get(self._activity.activity_state, ""))
        self._state_label.setFixedHeight(20)
        self._state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_row.addWidget(self._state_label)
        status_row.addStretch()
        self._time_label = CaptionLabel(self._activity.remaining_text())
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self._time_label)
        info_layout.addLayout(status_row)
        info_layout.addStretch()

        layout.addWidget(info, 1)

    def _applyStyles(self):
        self._title.setTextColor(QColor("#333333"), QColor(255, 255, 255, 235))
        self._desc.setTextColor(QColor("#666666"), QColor(255, 255, 255, 153))
        self._time_label.setTextColor(QColor("#666666"), QColor(255, 255, 255, 153))

        state_text = {1: "进行中", 2: "将开始"}.get(self._activity.activity_state, "")
        badge_bg = "#28BF5D"
        if state_text == "将开始":
            badge_bg = "#FF9045"
        elif not state_text:
            badge_bg = "#999999"
        self._state_label.setFont(getFont(12))
        self._state_label.setStyleSheet(
            f"background: {badge_bg}; color: #FFFFFF; border-radius: 4px; padding: 0 6px;"
        )

    def _loadBanner(self):
        path = image_path(self._activity)
        if path is not None and path.exists():
            pm = QPixmap(str(path))
            if not pm.isNull():
                scaled = pm.scaled(
                    CARD_W, BANNER_H,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                x = (scaled.width() - CARD_W) // 2
                y = (scaled.height() - BANNER_H) // 2
                cropped = scaled.copy(x, y, CARD_W, BANNER_H)
                self._banner.setPixmap(_rounded_top_pixmap(cropped, 8))
                self._banner.setFixedSize(CARD_W, BANNER_H)
                self._banner.show()
                return
        self._banner.clear()
        self._banner.hide()


class SchedulePage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("schedulePage")

        self._activities: list[GameKeeActivity] = []
        self._current_server = 16
        self._all_data: dict[int, list[GameKeeActivity]] = {}
        self._worker = None
        self._img_worker = None
        self._section_labels: list[BodyLabel] = []
        self._cards: list[ActivityCard] = []

        self._setupUi()
        self._applyStaticStyles()
        self._applyTabStyles()
        self._loadAll()

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._stopWorker)
        qconfig.themeChanged.connect(self._onThemeChanged)
        self.destroyed.connect(self._onDestroy)
    def _setupUi(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = ScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("ScrollArea { background: transparent; border: none; }")

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        self._title = BodyLabel("活动日程")
        self._title.setFont(getFont(18))
        layout.addWidget(self._title)

        tab_row = QHBoxLayout()
        tab_row.setSpacing(8)
        self._tab_buttons = {}
        for name in SERVER_TABS:
            btn = PushButton(name)
            btn.setFont(getFont(14))
            btn.setFixedHeight(30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            sid = SERVER_IDS[name]
            btn.clicked.connect(lambda checked, s=sid: self._switchServer(s))
            tab_row.addWidget(btn)
            self._tab_buttons[sid] = btn
        self._tab_buttons[16].setProperty("active", True)
        tab_row.addStretch()

        self._loading_label = BodyLabel("加载中...")
        self._loading_label.setFont(getFont(14))
        self._loading_label.hide()
        tab_row.addWidget(self._loading_label)

        self._refresh_btn = PushButton("刷新")
        self._refresh_btn.setFont(getFont(14))
        self._refresh_btn.setFixedHeight(30)
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.clicked.connect(lambda: self._loadAll(force=True))
        tab_row.addWidget(self._refresh_btn)

        layout.addLayout(tab_row)

        self._scroll_layout = QVBoxLayout()
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(12)
        layout.addLayout(self._scroll_layout, 1)

        self._scroll.setWidget(content)
        enable_touch_scroll(self._scroll)
        outer.addWidget(self._scroll, 1)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(lambda: self._loadAll(force=True))
        self._refresh_timer.start(600000)

    def _applyStaticStyles(self):
        is_dark = self._isDarkTheme()
        fg = "rgba(255,255,255,0.92)" if is_dark else "rgba(0,0,0,0.9)"
        sub = "rgba(255,255,255,0.6)" if is_dark else "rgba(0,0,0,0.6)"
        self._title.setFont(getFont(18))
        self._title.setStyleSheet(f"color: {fg};")
        self._loading_label.setFont(getFont(14))
        self._loading_label.setStyleSheet(f"color: {sub};")

    def _switchServer(self, server_id: int):
        self._current_server = server_id
        for sid, btn in self._tab_buttons.items():
            btn.setProperty("active", sid == server_id)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._applyTabStyles()
        if server_id in self._all_data:
            self._activities = self._all_data[server_id]
            self._rebuildList()
            self._loading_label.hide()
        else:
            self._loading_label.setText("暂无数据")
            self._loading_label.show()

    def _loadAll(self, force: bool = False):
        if self._worker is not None:
            return
        self._loading_label.setText("正在加载数据...")
        self._loading_label.show()
        worker = CrawlWorker(force=force)
        worker.finished.connect(self._onAllData)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(self._onError)
        worker.error.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _onAllData(self, data: dict):
        self._worker = None
        self._all_data = data
        if self._current_server in data:
            self._activities = data[self._current_server]
            self._rebuildList()
        self._loading_label.hide()
        self._startImageDownload()

    def _startImageDownload(self):
        if self._img_worker is not None:
            return
        activities = [
            a for items in self._all_data.values()
            for a in items if a.activity_state in (1, 2)
        ]
        if not any(image_path(a) is not None and not image_path(a).exists() for a in activities):
            return
        worker = ImageWorker()
        worker.setActivities(activities)
        worker.finished.connect(self._onImagesReady)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        self._img_worker = worker
        worker.start()

    def _onImagesReady(self):
        self._img_worker = None
        self._restyleCards()

    def _onError(self, msg: str):
        self._loading_label.setText("加载失败: " + msg)
        self._worker = None

    def _rebuildList(self):
        while self._scroll_layout.count():
            item = self._scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                sub = item.layout()
                while sub.count():
                    si = sub.takeAt(0)
                    if si.widget():
                        si.widget().deleteLater()
                sub.deleteLater()
        self._section_labels = []
        self._cards = []

        items = self._activities
        if not items:
            placeholder = BodyLabel("暂无活动数据")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setFont(getFont(14))
            sub = "rgba(255,255,255,0.6)" if self._isDarkTheme() else "rgba(0,0,0,0.6)"
            placeholder.setStyleSheet(f"color: {sub};")
            self._scroll_layout.addWidget(placeholder)
            self._scroll_layout.addStretch()
            return

        ongoing = [a for a in items if a.activity_state == 1]
        upcoming = [a for a in items if a.activity_state == 2]

        for section_title, section_items in [("进行中", ongoing), ("将开始", upcoming)]:
            if not section_items:
                continue
            label = BodyLabel(section_title)
            self._section_labels.append(label)
            is_dark = self._isDarkTheme()
            sec = "rgba(255,255,255,0.6)" if is_dark else "rgba(0,0,0,0.6)"
            label.setFont(getFont(16))
            label.setStyleSheet(f"padding: 8px 0 4px 0; color: {sec};")
            self._scroll_layout.addWidget(label)
            flow = FlowLayout(spacing=12)
            for item in section_items:
                card = ActivityCard(item)
                self._cards.append(card)
                flow.addWidget(card)
            self._scroll_layout.addLayout(flow)
        self._scroll_layout.addStretch()

    def _restyleSectionLabels(self):
        is_dark = self._isDarkTheme()
        sec = "rgba(255,255,255,0.6)" if is_dark else "rgba(0,0,0,0.6)"
        for label in self._section_labels:
            label.setStyleSheet(f"padding: 8px 0 4px 0; color: {sec};")

    def _applyTabStyles(self):
        is_dark = self._isDarkTheme()
        active_bg = get_accent_color()
        active_fg = "#000000" if is_dark else "#FFFFFF"
        inactive_bg = "rgba(128,128,128,0.15)" if is_dark else "rgba(0,0,0,0.07)"
        inactive_fg = "rgba(255,255,255,0.8)" if is_dark else "rgba(0,0,0,0.8)"

        for btn in self._tab_buttons.values():
            active = btn.property("active")
            if active:
                btn.setStyleSheet(
                    f"QPushButton {{ background: {active_bg}; color: {active_fg}; "
                    f"border-radius: 6px; padding: 4px 14px; border: none; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background: {inactive_bg}; color: {inactive_fg}; "
                    f"border-radius: 6px; padding: 4px 14px; border: none; }}"
                    f"QPushButton:hover {{ background: {active_bg}; color: {active_fg}; }}"
                )
        self._refresh_btn.setStyleSheet(
            f"QPushButton {{ background: {inactive_bg}; color: {inactive_fg}; "
            f"border-radius: 6px; padding: 4px 14px; border: none; }}"
            f"QPushButton:hover {{ background: {active_bg}; color: {active_fg}; }}"
        )

    def _restyleCards(self):
        for card in self._cards:
            card._applyStyles()
            card._loadBanner()

    def _stopWorker(self):
        worker = self._worker
        self._worker = None
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            worker.wait(1000)
            if worker.isRunning():
                worker.terminate()
                worker.wait()
            worker.deleteLater()
        img = self._img_worker
        self._img_worker = None
        if img is not None and img.isRunning():
            img.requestInterruption()
            img.wait(1000)
            if img.isRunning():
                img.terminate()
                img.wait()
            img.deleteLater()

    def _onDestroy(self):
        self._refresh_timer.stop()
        self._stopWorker()

    def _onThemeChanged(self):
        self._applyStaticStyles()
        self._applyTabStyles()
        self._restyleSectionLabels()
        self._restyleCards()

    def _isDarkTheme(self):
        return qconfig.theme == Theme.DARK
