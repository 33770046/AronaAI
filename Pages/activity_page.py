from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QApplication
from PyQt5.QtCore import Qt, QSettings, QTimer, QThread, pyqtSignal
from qfluentwidgets import CardWidget, ComboBox, PrimaryPushButton, ScrollArea, setTheme, Theme
from qfluentwidgets import qconfig
from crawlers.schale_db import SchaleDBCrawler


class ActivityLoader(QThread):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, crawler, region):
        super().__init__()
        self._crawler = crawler
        self._region = region

    def run(self):
        try:
            data = self._crawler.get_current_activities(self._region)
            self.finished.emit(data)
        except Exception as e:
            self.error.emit(str(e))


class ActivityPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('activity')
        self._crawler = SchaleDBCrawler(cache_dir=None)
        self._settings = QSettings("AronaAI", "Settings")
        self._isInitializing = True
        self._loader = None
        self._setupUi()
        self._loadSettings()

        settings = QSettings("AronaAI", "Settings")
        themeIndex = settings.value("theme", 0, type=int)
        setTheme([Theme.AUTO, Theme.LIGHT, Theme.DARK][themeIndex])

        self._isInitializing = False
        qconfig.themeChanged.connect(self._onThemeChanged)

    def _setupUi(self):
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(24, 24, 24, 24)
        self._layout.setSpacing(12)

        title = QLabel("活动", self)
        title.setObjectName("pageTitle")
        self._layout.addWidget(title)

        toolbar = QWidget(self)
        toolbarLayout = QHBoxLayout(toolbar)
        toolbarLayout.setContentsMargins(0, 0, 0, 0)
        toolbarLayout.setSpacing(8)

        self._regionCombo = ComboBox(toolbar)
        self._regionCombo.setFixedWidth(150)
        self._regionCombo.setFixedHeight(36)
        self._regionCombo.setStyleSheet("font-size: 14px;")
        self._regionCombo.setMaxVisibleItems(10)
        self._regionCombo.setMinimumWidth(150)
        self._regionCombo.addItem("日服 (JP)", userData="Jp")
        self._regionCombo.addItem("国际服 (Global)", userData="Global")
        self._regionCombo.addItem("国服 (CN)", userData="Cn")
        self._regionCombo.currentIndexChanged.connect(self._onRegionChanged)

        self._refreshBtn = PrimaryPushButton("刷新", toolbar)
        self._refreshBtn.setFixedWidth(100)
        self._refreshBtn.setFixedHeight(36)
        self._refreshBtn.clicked.connect(self._onRefresh)

        self._statusLabel = QLabel("", toolbar)
        self._statusLabel.setObjectName("status-label")

        toolbarLayout.addWidget(self._regionCombo)
        toolbarLayout.addWidget(self._refreshBtn)
        toolbarLayout.addWidget(self._statusLabel, 1)
        toolbarLayout.addStretch()

        self._layout.addWidget(toolbar)

        self._scrollArea = ScrollArea(self)
        self._scrollArea.setWidgetResizable(True)
        self._scrollArea.setFrameShape(0)
        self._scrollContent = QWidget(self._scrollArea)
        self._scrollLayout = QVBoxLayout(self._scrollContent)
        self._scrollLayout.setContentsMargins(0, 0, 0, 0)
        self._scrollLayout.setSpacing(12)
        self._scrollLayout.addStretch()
        self._scrollArea.setWidget(self._scrollContent)
        self._layout.addWidget(self._scrollArea, 1)

    def _loadSettings(self):
        themeIndex = self._settings.value("theme", 0, type=int)
        theme = [Theme.AUTO, Theme.LIGHT, Theme.DARK][themeIndex]
        setTheme(theme)
        self._applyStyles()
        QTimer.singleShot(100, self._loadActivities)

    def _onThemeChanged(self):
        QTimer.singleShot(50, self._applyStyles)

    def _applyStyles(self):
        isDark = qconfig.theme == Theme.DARK
        if qconfig.theme == Theme.AUTO:
            isDark = QApplication.palette().window().color().lightness() < 128
        if isDark:
            fg = "#ffffff"
            fg_secondary = "rgba(255,255,255,0.6)"
            accent = "#60CDFF"
        else:
            fg = "#000000"
            fg_secondary = "rgba(0,0,0,0.6)"
            accent = "#0078D4"

        self.findChild(QLabel, "pageTitle").setStyleSheet(f"font-size: 28px; font-weight: bold; color: {fg};")
        self.findChild(QLabel, "status-label").setStyleSheet(f"font-size: 13px; color: {fg_secondary};")
        for label in self.findChildren(QLabel, "section-title"):
            label.setStyleSheet(f"font-size: 28px; font-weight: bold; color: {fg}; margin-top: 12px;")
        self._scrollArea.setStyleSheet(f"ScrollArea {{ background: transparent; border: none; }}")
        self._scrollContent.setStyleSheet(f"background: transparent;")

        for label in self.findChildren(QLabel, "birthday-column-title"):
            label.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {fg}; margin-bottom: 4px;")
        for label in self.findChildren(QLabel, "card-title"):
            label.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {fg};")
        for label in self.findChildren(QLabel, "card-desc"):
            label.setStyleSheet(f"font-size: 13px; color: {fg_secondary};")
        for label in self.findChildren(QLabel, "card-remain"):
            label.setStyleSheet(f"font-size: 13px; color: {accent}; font-weight: bold;")
        for label in self.findChildren(QLabel, "tag-active"):
            label.setStyleSheet(f"font-size: 12px; color: #ffffff; background-color: #4caf50; border-radius: 4px; padding: 2px 10px;")

    def _onRegionChanged(self, index):
        if self._isInitializing:
            return
        self._loadActivities()

    def _onRefresh(self):
        self._crawler.clear_cache()
        self._loadActivities()

    def _loadActivities(self):
        if self._loader and self._loader.isRunning():
            self._loader.quit()
            self._loader.wait(2000)
        self._statusLabel.setText("正在获取活动数据...")
        self._refreshBtn.setEnabled(False)

        region = self._regionCombo.currentData()
        self._loader = ActivityLoader(self._crawler, region)
        self._loader.finished.connect(self._displayActivities)
        self._loader.error.connect(self._showError)
        self._loader.start()

    def _displayActivities(self, data):
        self._clearCards()
        hasContent = False

        for ev in data["events"]:
            self._addCard("活动", ev["name"], ev["start_str"], ev["end_str"], ev["remaining"])
            hasContent = True

        for rd in data["raids"]:
            self._addCard(rd["type_cn"], rd["name"], rd["start_str"], rd["end_str"], rd["remaining"])
            hasContent = True

        for gb in data["gacha"]:
            self._addCard("招募", f"「{', '.join(gb['char_names'])}」", gb["start_str"], gb["end_str"], gb["remaining"])
            hasContent = True

        bdays = data.get("birthdays", [])
        if bdays:
            def base_name(n):
                import re
                return re.split(r'[（(]', n)[0].strip()

            today_bdays = [b for b in bdays if b.get("today")]
            upcoming_bdays = [b for b in bdays if not b.get("today")]

            def dedup(items):
                seen = {}
                for b in items:
                    key = base_name(b["name"])
                    if key not in seen or b["name"] == key:
                        seen[key] = b
                return list(seen.values())

            today_bdays = dedup(today_bdays)
            upcoming_bdays = dedup(upcoming_bdays)

            if today_bdays or upcoming_bdays:
                bdTitle = QLabel("生日", self._scrollContent)
                bdTitle.setObjectName("section-title")
                self._scrollLayout.insertWidget(self._scrollLayout.count() - 1, bdTitle)

                card = CardWidget(self._scrollContent)
                columns = QHBoxLayout(card)
                columns.setContentsMargins(20, 16, 20, 16)
                columns.setSpacing(24)

                def make_column(title, items, parent):
                    col = QVBoxLayout()
                    col.setSpacing(6)
                    hdr = QLabel(title, parent)
                    hdr.setObjectName("birthday-column-title")
                    col.addWidget(hdr)
                    if not items:
                        empty = QLabel("暂无", parent)
                        empty.setObjectName("card-desc")
                        col.addWidget(empty)
                    else:
                        for b in items:
                            line = QLabel(f"{b['name']}  {b['month']}月{b['day']}日", parent)
                            line.setObjectName("card-desc")
                            col.addWidget(line)
                    col.addStretch()
                    return col

                columns.addLayout(make_column("今天", today_bdays, card), 1)
                columns.addLayout(make_column("即将到来", upcoming_bdays, card), 1)

                self._scrollLayout.insertWidget(self._scrollLayout.count() - 1, card)
                hasContent = True

        if not hasContent:
            card = CardWidget(self._scrollContent)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(20, 16, 20, 16)
            label = QLabel("当前暂无活动数据", card)
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label)
            self._scrollLayout.insertWidget(self._scrollLayout.count() - 1, card)

        QTimer.singleShot(50, self._applyStyles)
        self._statusLabel.setText("")
        self._refreshBtn.setEnabled(True)

    def _addCard(self, title, subtitle, start, end, remaining):
        card = CardWidget(self._scrollContent)
        card.setMinimumHeight(100)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        nameLabel = QLabel(f"{title} {subtitle}", card)
        nameLabel.setObjectName("card-title")
        row1.addWidget(nameLabel)
        row1.addStretch()

        tagLabel = QLabel("进行中", card)
        tagLabel.setObjectName("tag-active")
        tagLabel.setAlignment(Qt.AlignCenter)
        tagLabel.setFixedHeight(24)
        row1.addWidget(tagLabel)

        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        periodLabel = QLabel(f"{start} ~ {end}", card)
        periodLabel.setObjectName("card-desc")
        row2.addWidget(periodLabel)
        row2.addStretch()
        remainLabel = QLabel(remaining, card)
        remainLabel.setObjectName("card-remain")
        row2.addWidget(remainLabel)

        layout.addLayout(row2)

        self._scrollLayout.insertWidget(self._scrollLayout.count() - 1, card)

    def _clearCards(self):
        for i in range(self._scrollLayout.count() - 1, -1, -1):
            item = self._scrollLayout.itemAt(i)
            w = item.widget()
            if w and (isinstance(w, CardWidget) or isinstance(w, QLabel)):
                w.deleteLater()

    def _showError(self, msg):
        self._clearCards()
        card = CardWidget(self._scrollContent)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        label = QLabel(f"获取数据失败: {msg}", card)
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        self._scrollLayout.insertWidget(self._scrollLayout.count() - 1, card)

        QTimer.singleShot(50, self._applyStyles)
        self._statusLabel.setText("加载失败")
        self._refreshBtn.setEnabled(True)
