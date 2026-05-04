import datetime
import re
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QGridLayout, QScrollArea
from PyQt5.QtCore import Qt, QSettings, pyqtSignal, QTimer, QUrl
from PyQt5.QtGui import QFont, QPixmap, QDesktopServices, QCursor
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from qfluentwidgets import CardWidget, ComboBox, SwitchButton, PrimaryPushButton, TransparentPushButton
from qfluentwidgets import qconfig, Theme, InfoBar, InfoBarPosition

CURRENT_VERSION = "dev.0.6.0"
GITHUB_REPO = "33770046/AronaAI"


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
        
        version_label = QLabel(f"版本: dev.0.6.0", info)
        version_label.setObjectName("version-label")
        build_label = f"内部版本: dev.20260504.1500"
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
        self.checkUpdateBtn.setFixedWidth(100)
        self.checkUpdateBtn.setFixedHeight(36)
        self.checkUpdateBtn.clicked.connect(self._onCheckUpdateClicked)
        
        manual_layout.addWidget(manual_label, 1)
        manual_layout.addWidget(self.checkUpdateBtn)
        layout.addWidget(manual_row)
        layout.addSpacing(0)
        
        download_row = QWidget(card)
        download_layout = QHBoxLayout(download_row)
        download_layout.setContentsMargins(0, 0, 0, 0)
        download_layout.setSpacing(12)
        
        download_label = QLabel("下载更新", download_row)
        download_label.setObjectName("item-label")
        
        self.downloadYesBtn = PrimaryPushButton("是", download_row)
        self.downloadYesBtn.setFixedWidth(60)
        self.downloadYesBtn.setFixedHeight(36)
        self.downloadYesBtn.setEnabled(False)
        
        self.downloadNoBtn = TransparentPushButton("否", download_row)
        self.downloadNoBtn.setFixedWidth(60)
        self.downloadNoBtn.setFixedHeight(36)
        self.downloadNoBtn.setEnabled(False)
        
        download_layout.addWidget(download_label, 1)
        download_layout.addWidget(self.downloadYesBtn)
        download_layout.addWidget(self.downloadNoBtn)
        layout.addWidget(download_row)
        layout.addSpacing(0)
        
        auto_download_row = QWidget(card)
        auto_download_layout = QHBoxLayout(auto_download_row)
        auto_download_layout.setContentsMargins(0, 0, 0, 0)
        auto_download_layout.setSpacing(12)
        
        auto_download_label = QLabel("检查后自动下载", auto_download_row)
        auto_download_label.setObjectName("item-label")
        
        self.autoDownloadSwitch = SwitchButton(card)
        self.autoDownloadSwitch.checkedChanged.connect(self._onAutoDownloadToggled)
        
        auto_download_layout.addWidget(auto_download_label, 1)
        auto_download_layout.addWidget(self.autoDownloadSwitch)
        layout.addWidget(auto_download_row)
        
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
        self.autoCheckSwitch.setChecked(self._settings.value("autoCheckUpdates", False, type=bool))
        self.autoDownloadSwitch.setChecked(self._settings.value("autoDownload", False, type=bool))
        self._applyStyles()
        
        if self._settings.value("autoCheckUpdates", False, type=bool):
            QTimer.singleShot(1000, self._onCheckUpdateClicked)

    def _onAutoCheckToggled(self, checked):
        if self._isInitializing:
            return
        self._settings.setValue("autoCheckUpdates", checked)
    
    def _onAutoDownloadToggled(self, checked):
        if self._isInitializing:
            return
        self._settings.setValue("autoDownload", checked)

    def _onCheckUpdateClicked(self):
        if not hasattr(self, '_updateCheckCount'):
            self._updateCheckCount = 0
        self._updateCheckCount += 1
        current_count = self._updateCheckCount
        
        self.checkUpdateBtn.setEnabled(False)
        
        self._network_manager = QNetworkAccessManager(self)
        url = QUrl(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest")
        request = QNetworkRequest(url)
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "AronaAI")
        self._reply = self._network_manager.get(request)
        self._reply.finished.connect(lambda: self._onUpdateReplyFinished(current_count))

    def _onUpdateReplyFinished(self, check_count):
        if check_count != getattr(self, '_updateCheckCount', 0):
            return
        
        self.checkUpdateBtn.setEnabled(True)
        
        if self._reply.error() != QNetworkReply.NetworkError.NoError:
            if "rate limit" in self._reply.errorString().lower():
                InfoBar.warning(
                    title="请求过于频繁",
                    content="请稍后再试",
                    duration=3000,
                    position=InfoBarPosition.BOTTOM_RIGHT,
                    parent=self.window()
                )
            else:
                print(f"Network error: {self._reply.errorString()}")
                InfoBar.error(
                    title="检查更新失败",
                    content=f"网络错误: {self._reply.errorString()[:40]}",
                    duration=3000,
                    position=InfoBarPosition.BOTTOM_RIGHT,
                    parent=self.window()
                )
            return
        
        import json
        try:
            data = json.loads(self._reply.readAll().data().decode('utf-8'))
            tag_name = data.get('tag_name', '')
            match = re.search(r'([vV]|dev)[._]?(\d+\.\d+\.\d+)', tag_name)
            prefix = "dev"
            if match:
                prefix = match.group(1).lower()
                version = match.group(2)
                latest_version = prefix + "." + version
            else:
                version = tag_name
                latest_version = tag_name
            download_url = data.get('html_url', '')
            
            latest_is_dev = prefix == 'dev'
            display_version = latest_version
            
            if self._compareVersions(CURRENT_VERSION, latest_version) < 0:
                autoDownload = self._settings.value("autoDownload", False, type=bool)
                if autoDownload:
                    QDesktopServices.openUrl(QUrl(download_url))
                    InfoBar.success(
                        title="正在下载",
                        content=f"正在下载版本 {display_version}...",
                        duration=3000,
                        position=InfoBarPosition.BOTTOM_RIGHT,
                        parent=self.window()
                    )
                else:
                    self._showUpdatePrompt(display_version, download_url, latest_is_dev)
            else:
                InfoBar.info(
                    title="已是最新版本",
                    content="当前版本已是最新",
                    duration=3000,
                    position=InfoBarPosition.BOTTOM_RIGHT,
                    parent=self.window()
                )
        except Exception as e:
            print(f"Update check error: {e}")
            import traceback
            traceback.print_exc()
            InfoBar.error(
                title="检查更新失败",
                content=f"请稍后重试: {str(e)[:30]}",
                duration=3000,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self.window()
            )

    def _showUpdatePrompt(self, version, url, is_dev):
        from PyQt5.QtCore import QTimer
        from qfluentwidgets import InfoBar, InfoBarPosition

        InfoBar.success(
            title="发现新版本",
            content=f"版本 {version} 可用",
            duration=3000,
            position=InfoBarPosition.BOTTOM_RIGHT,
            parent=self.window()
        )
        
        self._updateDownloadUrl = url
        self._updateTimer = None
        
        default_is_yes = not is_dev
        self._defaultIsYes = default_is_yes
        self._remaining = 10
        
        self.downloadYesBtn.setEnabled(True)
        self.downloadNoBtn.setEnabled(True)
        
        def update_buttons():
            self._remaining -= 1
            if self._remaining > 0:
                if default_is_yes:
                    self.downloadYesBtn.setText(f"是({self._remaining})")
                    self.downloadNoBtn.setText("否")
                else:
                    self.downloadYesBtn.setText("是")
                    self.downloadNoBtn.setText(f"否({self._remaining})")
            else:
                self._updateTimer.stop()
                self._onDownloadTimeout()
        
        def on_yes():
            if self._updateTimer:
                self._updateTimer.stop()
            self._resetDownloadButtons()
            QDesktopServices.openUrl(QUrl(url))
        
        def on_no():
            if self._updateTimer:
                self._updateTimer.stop()
            self._resetDownloadButtons()
        
        try:
            self.downloadYesBtn.clicked.disconnect()
            self.downloadNoBtn.clicked.disconnect()
        except TypeError:
            pass
        self.downloadYesBtn.clicked.connect(on_yes)
        self.downloadNoBtn.clicked.connect(on_no)
        
        if default_is_yes:
            self.downloadYesBtn.setText(f"是({self._remaining})")
            self.downloadNoBtn.setText("否")
        else:
            self.downloadYesBtn.setText("是")
            self.downloadNoBtn.setText(f"否({self._remaining})")
        
        self._updateTimer = QTimer()
        self._updateTimer.timeout.connect(update_buttons)
        self._updateTimer.start(1000)

    def _onDownloadTimeout(self):
        if self._defaultIsYes:
            QDesktopServices.openUrl(QUrl(self._updateDownloadUrl))
        self._resetDownloadButtons()

    def _resetDownloadButtons(self):
        self.downloadYesBtn.setEnabled(False)
        self.downloadNoBtn.setEnabled(False)
        self.downloadYesBtn.setText("是")
        self.downloadNoBtn.setText("否")

    def _compareVersions(self, current, latest):
        def normalize(v):
            v = re.sub(r'^(dev|v)', '', v)
            parts = re.split(r'[.\-_]', v)
            return [int(p) if p.isdigit() else 0 for p in parts[:4]] + [0] * (4 - len(parts))
        
        current_parts = normalize(current)
        latest_parts = normalize(latest)
        
        for c, l in zip(current_parts, latest_parts):
            if c < l:
                return -1
            elif c > l:
                return 1
        return 0
    
    def _onLinkClicked(self, url):
        QDesktopServices.openUrl(QUrl(url))

    def _onLicenseClicked(self):
        from Pages.license_dialog import showLicenseDialog
        showLicenseDialog(self)