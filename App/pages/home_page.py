import time
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QApplication
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QEasingCurve, QRectF
from PySide6.QtGui import QPixmap, QPainter, QColor, QImage, QLinearGradient, QPainterPath
from qfluentwidgets import (
    qconfig, Theme, ScrollArea,
    CardWidget, BodyLabel,
    Pivot, PopUpAniStackedWidget,
)
from qfluentwidgets.common.font import getFont

from ..crawler import fetch_all_activities
from ..config import get_accent_color, MOMOTALK
from ..scroll_utils import enable_touch_scroll
from ..update_utils import get_assets_dir

SERVER_NAMES = {16: "国服", 17: "国际服", 15: "日服"}
SERVER_ORDER = [16, 17, 15]


class BannerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        path = str(get_assets_dir() / "HomePage" / "homepage.png")
        self._original = QPixmap(path)
        self._scaled = QPixmap()
        self._lastWidth = 0
        QTimer.singleShot(0, self._refresh)

    def _build(self, w, h):
        scaled = self._original.scaled(
            w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        img = scaled.toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)

        mask = QImage(w, h, QImage.Format_Alpha8)
        mask.fill(Qt.GlobalColor.transparent)
        mp = QPainter(mask)
        grad = QLinearGradient(0, h * 0.7, 0, h)
        grad.setColorAt(0, QColor(255, 255, 255, 255))
        grad.setColorAt(1, QColor(255, 255, 255, 0))
        mp.fillRect(mask.rect(), grad)
        mp.end()

        img.setAlphaChannel(mask)
        return QPixmap.fromImage(img)

    def _refresh(self):
        w = self.width()
        if w <= 0 or self._original.isNull():
            return
        if w != self._lastWidth:
            self._lastWidth = w
            ratio = w / self._original.width()
            h = int(self._original.height() * ratio)
            self.setFixedHeight(h)
            self._scaled = self._build(w, h)
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        if not self._scaled.isNull():
            if qconfig.get(qconfig.themeMode) != MOMOTALK:
                radius = 6
                path = QPainterPath()
                w, h = self.width(), self.height()
                path.moveTo(radius, 0)
                path.lineTo(w, 0)
                path.lineTo(w, h)
                path.lineTo(0, h)
                path.lineTo(0, radius)
                path.arcTo(0, 0, 2 * radius, 2 * radius, 180, -90)
                path.closeSubpath()
                painter.setClipPath(path)
            painter.drawPixmap(self.rect(), self._scaled)


class HomeDataWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def run(self):
        try:
            result = fetch_all_activities([16, 17, 15])
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class HomePage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName('home')
        self._all_data = {}
        self._worker = None
        self._remain_labels: list = []
        self._setupUi()
        self._applyWelcomeStyles()
        qconfig.themeChanged.connect(self._onThemeChanged)
        qconfig.backgroundEffect.valueChanged.connect(self._banner.update)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._stopWorker)
        self.destroyed.connect(self._onDestroy)
        self._loadAll()

    def _setupUi(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scrollArea = ScrollArea(self)
        self._scrollArea.setWidgetResizable(True)
        self._scrollArea.setFrameShape(QFrame.Shape.NoFrame)
        self._scrollArea.setStyleSheet("ScrollArea { background: transparent; border: none; }")

        self._scrollContent = QWidget()
        self._scrollContent.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self._scrollContent)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._banner = BannerWidget(self._scrollContent)
        layout.addWidget(self._banner)

        content = QWidget(self._scrollContent)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 16, 24, 24)
        content_layout.setSpacing(16)

        columns = QHBoxLayout()
        columns.setSpacing(16)

        left_col = QWidget(content)
        left_layout = QVBoxLayout(left_col)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self._welcome = BodyLabel("欢迎回来，老师！", left_col)
        self._welcome.setObjectName("welcome")
        left_layout.addWidget(self._welcome)

        self._desc = BodyLabel("「欢迎来到夏莱的办公桌！」", left_col)
        left_layout.addWidget(self._desc)

        left_layout.addStretch()
        columns.addWidget(left_col)

        right_col = QWidget(content)
        right_layout = QVBoxLayout(right_col)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self._schedule_card = CardWidget(right_col)
        schedule_layout = QVBoxLayout(self._schedule_card)
        schedule_layout.setContentsMargins(16, 12, 16, 12)
        schedule_layout.setSpacing(8)

        self._server_pivot = Pivot(self._schedule_card)
        self._server_pivot.addItem("16", "国服")
        self._server_pivot.addItem("17", "国际服")
        self._server_pivot.addItem("15", "日服")
        self._server_pivot.setItemFontSize(15)
        self._server_pivot.currentItemChanged.connect(self._onServerChanged)
        self._server_pivot.blockSignals(True)
        self._server_pivot.setCurrentItem("16")
        self._server_pivot.blockSignals(False)
        schedule_layout.addWidget(self._server_pivot)

        self._stack = PopUpAniStackedWidget(self._schedule_card)
        self._stack_layouts = {}
        for sid in SERVER_ORDER:
            page = QWidget()
            page.setStyleSheet("background: transparent;")
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(2)
            self._stack_layouts[sid] = page_layout
            self._stack.addWidget(page, deltaX=0, deltaY=150)
        schedule_layout.addWidget(self._stack)

        right_layout.addWidget(self._schedule_card)
        right_layout.addStretch()

        columns.addWidget(right_col, 1)

        content_layout.addLayout(columns)

        layout.addWidget(content)

        self._scrollArea.setWidget(self._scrollContent)
        enable_touch_scroll(self._scrollArea)
        outer.addWidget(self._scrollArea)

    def _applyWelcomeStyles(self):
        is_dark = self._isDarkTheme()
        accent = get_accent_color()
        item = "rgba(255,255,255,0.6)" if is_dark else "rgba(0,0,0,0.6)"
        self._welcome.setFont(getFont(30))
        self._welcome.setStyleSheet(f"color: {accent};")
        self._desc.setFont(getFont(15))
        self._desc.setStyleSheet(f"font-style: italic; color: {item};")
        remain_style = "color: rgba(255,255,255,0.6);" if is_dark else "color: rgba(0,0,0,0.55);"
        for lbl in self._remain_labels:
            lbl.setStyleSheet(remain_style)

    def _onServerChanged(self, route_key: str):
        sid = int(route_key)
        idx = SERVER_ORDER.index(sid)
        self._stack.setCurrentIndex(idx, needPopOut=False, duration=250, easingCurve=QEasingCurve.OutQuad)

    def _loadAll(self):
        for layout in self._stack_layouts.values():
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        self._remain_labels = []
        for layout in self._stack_layouts.values():
            loading = BodyLabel("加载中...")
            loading.setFont(getFont(15))
            layout.addWidget(loading)
        self._worker = HomeDataWorker()
        self._worker.finished.connect(self._onData)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.error.connect(self._onError)
        self._worker.error.connect(self._worker.deleteLater)
        self._worker.start()

    def _onData(self, data: dict):
        self._all_data = data
        self._remain_labels = []
        for sid in SERVER_ORDER:
            layout = self._stack_layouts[sid]
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            activities = data.get(sid, [])
            active = [a for a in activities if a.activity_state == 1]
            if not active:
                empty = BodyLabel("暂无进行中的活动")
                empty.setFont(getFont(15))
                layout.addWidget(empty)
            else:
                for a in active:
                    row = QWidget()
                    row_layout = QHBoxLayout(row)
                    row_layout.setContentsMargins(0, 0, 0, 0)
                    row_layout.setSpacing(8)
                    title = BodyLabel(a.title)
                    title.setFont(getFont(15))
                    title.setWordWrap(True)
                    row_layout.addWidget(title, 1)
                    remain = BodyLabel(a.remaining_text())
                    remain.setWordWrap(False)
                    remain.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    remain.setFont(getFont(13))
                    remain.setStyleSheet(
                        "color: rgba(255,255,255,0.6);"
                        if self._isDarkTheme()
                        else "color: rgba(0,0,0,0.55);"
                    )
                    self._remain_labels.append(remain)
                    row_layout.addWidget(remain)
                    layout.addWidget(row)
        self._worker = None

    def _onError(self, msg: str):
        for layout in self._stack_layouts.values():
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        self._remain_labels = []
        failed = BodyLabel("活动加载失败")
        failed.setFont(getFont(15))
        self._stack_layouts[SERVER_ORDER[0]].addWidget(failed)
        self._worker = None

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

    def _onDestroy(self):
        self._stopWorker()

    def _onThemeChanged(self):
        self._banner.update()
        self._applyWelcomeStyles()

    def _isDarkTheme(self):
        return qconfig.theme == Theme.DARK
