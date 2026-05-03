import datetime
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QGridLayout, QScrollArea
from PyQt5.QtCore import Qt, QSettings, pyqtSignal, QTimer, QUrl
from PyQt5.QtGui import QFont, QPixmap, QDesktopServices, QCursor
from qfluentwidgets import CardWidget, ComboBox, SwitchButton, PrimaryPushButton
from qfluentwidgets import qconfig, Theme


class AboutPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('about')
        self._settings = QSettings("AronaAI", "Settings")
        self._isInitializing = True
        self._setupUi()
        self._loadSettings()
        
        settings = QSettings("AronaAI", "Settings")
        themeIndex = settings.value("theme", 0, type=int)
        from qfluentwidgets import setTheme, Theme
        setTheme([Theme.AUTO, Theme.LIGHT, Theme.DARK][themeIndex])
        
        self._isInitializing = False
        qconfig.themeChanged.connect(self._onThemeChanged)

    def _setupUi(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("关于", self)
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self._appInfoCard = self._createAppInfoCard()
        self._updateCard = self._createUpdateCard()
        self._authorCard = self._createAuthorCard()

        layout.addWidget(self._appInfoCard)
        layout.addWidget(self._updateCard)
        layout.addWidget(self._authorCard)

        layout.addStretch()

    def _createAppInfoCard(self):
        card = CardWidget(self)
        card.setMinimumHeight(120)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        logoLabel = QLabel(card)
        pixmap = QPixmap("Assets/AboutLogo.png")
        if not pixmap.isNull():
            logoLabel.setPixmap(pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            logoLabel.setText("Logo")
        logoLabel.setFixedSize(80, 80)
        logoLabel.setAlignment(Qt.AlignCenter)
        layout.addWidget(logoLabel)

        info = QWidget(card)
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(4)

        name_label = QLabel("AronaAI", info)
        name_label.setObjectName("app-name-label")
        
        version_label = QLabel(f"版本: dev.0.5.0", info)
        version_label.setObjectName("version-label")
        
        build_date = datetime.datetime.now().strftime("%Y%m%d")
        build_label = f"内部版本: dev.{build_date}.1"
        build_label = QLabel(build_label, info)
        build_label.setObjectName("build-label")
        
        info_layout.addWidget(name_label)
        info_layout.addWidget(version_label)
        info_layout.addWidget(build_label)
        
        layout.addWidget(info, 1)

        self.licenseBtn = PrimaryPushButton("查看开放源代码许可", card)
        self.licenseBtn.setFixedWidth(180)
        self.licenseBtn.setFixedHeight(36)
        self.licenseBtn.clicked.connect(self._onLicenseClicked)
        layout.addWidget(self.licenseBtn)

        return card

    def _createUpdateCard(self):
        card = CardWidget(self)
        card.setMinimumHeight(180)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        section_title = QLabel("检查更新", card)
        section_title.setObjectName("section-title")
        layout.addWidget(section_title)

        channel_row = QWidget(card)
        channel_layout = QHBoxLayout(channel_row)
        channel_layout.setContentsMargins(0, 0, 0, 0)
        channel_layout.setSpacing(12)
        
        channel_label = QLabel("更新频道", channel_row)
        channel_label.setObjectName("item-label")
        
        self.channelComboBox = ComboBox(card)
        self.channelComboBox.setFixedWidth(150)
        self.channelComboBox.addItem("正式版", "stable")
        self.channelComboBox.addItem("测试版", "beta")
        self.channelComboBox.currentIndexChanged.connect(self._onChannelChanged)
        
        channel_layout.addWidget(channel_label, 1)
        channel_layout.addWidget(self.channelComboBox)
        layout.addWidget(channel_row)

        auto_row = QWidget(card)
        auto_layout = QHBoxLayout(auto_row)
        auto_layout.setContentsMargins(0, 0, 0, 0)
        auto_layout.setSpacing(12)
        
        auto_label = QLabel("自动检查更新", auto_row)
        auto_label.setObjectName("item-label")
        
        self.autoCheckSwitch = SwitchButton(card)
        self.autoCheckSwitch.checkedChanged.connect(self._onAutoCheckToggled)
        
        auto_layout.addWidget(auto_label, 1)
        auto_layout.addWidget(self.autoCheckSwitch)
        layout.addWidget(auto_row)

        manual_row = QWidget(card)
        manual_layout = QHBoxLayout(manual_row)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_layout.setSpacing(12)
        
        manual_label = QLabel("手动检查更新", manual_row)
        manual_label.setObjectName("item-label")
        
        self.checkUpdateBtn = PrimaryPushButton("检查更新", card)
        self.checkUpdateBtn.setFixedWidth(120)
        self.checkUpdateBtn.setFixedHeight(36)
        self.checkUpdateBtn.clicked.connect(self._onCheckUpdateClicked)
        
        manual_layout.addWidget(manual_label, 1)
        manual_layout.addWidget(self.checkUpdateBtn)
        layout.addWidget(manual_row)

        self.updateStatusLabel = QLabel("", card)
        self.updateStatusLabel.setObjectName("status-label")
        self.updateStatusLabel.setVisible(False)
        layout.addWidget(self.updateStatusLabel)

        return card

    def _createAuthorCard(self):
        card = CardWidget(self)
        card.setMinimumHeight(180)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        section_title = QLabel("关于作者", card)
        section_title.setObjectName("section-title")
        layout.addWidget(section_title)

        author_info = QWidget(card)
        grid_layout = QGridLayout(author_info)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(8)
        grid_layout.setColumnMinimumWidth(0, 150)
        grid_layout.setColumnStretch(1, 1)

        row = 0
        
        label_author = QLabel("作者", author_info)
        label_author.setObjectName("item-label")
        self.authorValue = QLabel('<a href="https://github.com/33770046" style="color: #0078D4; text-decoration: none;">3377004_六</a>', author_info)
        self.authorValue.setObjectName("link-label")
        self.authorValue.setTextFormat(Qt.RichText)
        self.authorValue.setCursor(QCursor(Qt.PointingHandCursor))
        self.authorValue.linkActivated.connect(self._onLinkClicked)
        
        author_container = QWidget(author_info)
        author_layout = QHBoxLayout(author_container)
        author_layout.setContentsMargins(0, 0, 0, 0)
        author_layout.addStretch()
        author_layout.addWidget(self.authorValue)
        
        grid_layout.addWidget(label_author, row, 0)
        grid_layout.addWidget(author_container, row, 1)
        
        row += 1
        label_frontend = QLabel("前端框架", author_info)
        label_frontend.setObjectName("item-label")
        value_frontend = QLabel("PyQt5 + FluentWidgets", author_info)
        value_frontend.setObjectName("value-label")
        
        frontend_container = QWidget(author_info)
        frontend_layout = QHBoxLayout(frontend_container)
        frontend_layout.setContentsMargins(0, 0, 0, 0)
        frontend_layout.addStretch()
        frontend_layout.addWidget(value_frontend)
        
        grid_layout.addWidget(label_frontend, row, 0)
        grid_layout.addWidget(frontend_container, row, 1)
        
        row += 1
        label_backend = QLabel("后端框架", author_info)
        label_backend.setObjectName("item-label")
        value_backend = QLabel("PyQt5", author_info)
        value_backend.setObjectName("value-label")
        
        backend_container = QWidget(author_info)
        backend_layout = QHBoxLayout(backend_container)
        backend_layout.setContentsMargins(0, 0, 0, 0)
        backend_layout.addStretch()
        backend_layout.addWidget(value_backend)
        
        grid_layout.addWidget(label_backend, row, 0)
        grid_layout.addWidget(backend_container, row, 1)
        
        row += 1
        label_github = QLabel("Github", author_info)
        label_github.setObjectName("item-label")
        self.githubLink = QLabel('<a href="https://github.com/33770046/AronaAI" style="color: #0078D4; text-decoration: none;">https://github.com/33770046/AronaAI</a>', author_info)
        self.githubLink.setObjectName("link-label")
        self.githubLink.setTextFormat(Qt.RichText)
        self.githubLink.setCursor(QCursor(Qt.PointingHandCursor))
        self.githubLink.linkActivated.connect(self._onLinkClicked)
        
        github_container = QWidget(author_info)
        github_layout = QHBoxLayout(github_container)
        github_layout.setContentsMargins(0, 0, 0, 0)
        github_layout.addStretch()
        github_layout.addWidget(self.githubLink)
        
        grid_layout.addWidget(label_github, row, 0)
        grid_layout.addWidget(github_container, row, 1)

        layout.addWidget(author_info)

        return card

    def _applyStyles(self):
        isDark = qconfig.theme == Theme.DARK
        if qconfig.theme == Theme.AUTO:
            isDark = False
            
        if isDark:
            fg = "#ffffff"
            fg_secondary = "rgba(255,255,255,0.6)"
            accent = "#60CDFF"
        else:
            fg = "#000000"
            fg_secondary = "rgba(0,0,0,0.6)"
            accent = "#0078D4"

        self.findChild(QLabel, "pageTitle").setStyleSheet(f"font-size: 28px; font-weight: bold; color: {fg};")
        
        for label in self.findChildren(QLabel, "section-title"):
            label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {fg};")
            
        for label in self.findChildren(QLabel, "item-label"):
            label.setStyleSheet(f"font-size: 14px; color: {fg_secondary};")
            
        for label in self.findChildren(QLabel, "value-label"):
            label.setStyleSheet(f"font-size: 14px; color: {fg};")
            
        for label in self.findChildren(QLabel, "link-label"):
            label.setStyleSheet(f"font-size: 14px;")
            
        for label in self.findChildren(QLabel, "app-name-label"):
            label.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {fg};")
            
        for label in self.findChildren(QLabel, "version-label"):
            label.setStyleSheet(f"font-size: 14px; color: {fg};")
            
        for label in self.findChildren(QLabel, "build-label"):
            label.setStyleSheet(f"font-size: 12px; color: {fg_secondary};")
            
        for label in self.findChildren(QLabel, "status-label"):
            label.setStyleSheet(f"font-size: 14px; color: #107C10;")

    def _onThemeChanged(self):
        QTimer.singleShot(50, self._applyStyles)

    def _loadSettings(self):
        channel = self._settings.value("updateChannel", "beta")
        index = self.channelComboBox.findData(channel)
        if index >= 0:
            self.channelComboBox.setCurrentIndex(index)
        else:
            self.channelComboBox.setCurrentIndex(1)
            
        self.autoCheckSwitch.setChecked(self._settings.value("autoCheckUpdates", False, type=bool))
        self._applyStyles()

    def _onChannelChanged(self, index):
        if self._isInitializing:
            return
        channel = self.channelComboBox.currentData()
        self._settings.setValue("updateChannel", channel)

    def _onAutoCheckToggled(self, checked):
        if self._isInitializing:
            return
        self._settings.setValue("autoCheckUpdates", checked)

    def _onCheckUpdateClicked(self):
        self.checkUpdateBtn.setEnabled(False)
        self.updateStatusLabel.setText("正在检查更新...")
        self.updateStatusLabel.setVisible(True)
        QTimer.singleShot(2000, self._onUpdateCheckComplete)

    def _onUpdateCheckComplete(self):
        self.updateStatusLabel.setText("您当前已是最新版本！")
        self.checkUpdateBtn.setEnabled(True)

    def _onLinkClicked(self, url):
        QDesktopServices.openUrl(QUrl(url))

    def _onLicenseClicked(self):
        from Pages.license_dialog import showLicenseDialog
        showLicenseDialog(self)