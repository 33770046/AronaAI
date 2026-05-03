import sys
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSignal, QSettings, QTimer
from qfluentwidgets import CardWidget, SwitchButton, PrimaryPushButton, ComboBox, FluentIcon, setTheme, Theme
from qfluentwidgets import qconfig


class GeneralPage(QWidget):
    navigateToAbout = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('general')
        self._isInitializing = True
        self._mainWindow = parent
        self._settings = QSettings("AronaAI", "Settings")
        self._setupUi()
        self._loadSettings()
        
        self._isInitializing = False
        
        settings = QSettings("AronaAI", "Settings")
        themeIndex = settings.value("theme", 0, type=int)
        setTheme([Theme.AUTO, Theme.LIGHT, Theme.DARK][themeIndex])
        
        qconfig.themeChanged.connect(self._onThemeChanged)

    def _setupUi(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("通用设置", self)
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self._themeCard = self._createThemeCard()
        self._startupCard = self._createStartupCard()
        self._trayCard = self._createTrayCard()
        self._minimizeCard = self._createMinimizeCard()

        layout.addWidget(self._themeCard)
        layout.addWidget(self._startupCard)
        layout.addWidget(self._trayCard)
        layout.addWidget(self._minimizeCard)

        layout.addStretch()

    def _createThemeCard(self):
        card = CardWidget(self)
        card.setFixedHeight(80)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        info = QWidget(card)
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(6)
        title_label = QLabel("\u5916\u89c2", info)
        title_label.setObjectName("title-label")
        desc_label = QLabel("\u9009\u62e9\u5e94\u7528\u4e3b\u9898", info)
        desc_label.setObjectName("desc-label")
        info_layout.addWidget(title_label)
        info_layout.addWidget(desc_label)
        layout.addWidget(info, 1)

        self.themeComboBox = ComboBox(self)
        self.themeComboBox.setFixedWidth(130)
        self.themeComboBox.setFixedHeight(36)
        self.themeComboBox.addItem("跟随系统", userData=0)
        self.themeComboBox.addItem("浅色", userData=1)
        self.themeComboBox.addItem("深色", userData=2)
        self.themeComboBox.currentIndexChanged.connect(self._onThemeChangedComboBox)

        layout.addWidget(self.themeComboBox)

        return card

    def _createStartupCard(self):
        card = CardWidget(self)
        card.setFixedHeight(80)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        info = QWidget(card)
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(6)
        title_label = QLabel("\u5f00\u673a\u81ea\u542f", info)
        title_label.setObjectName("title-label")
        desc_label = QLabel("\u7cfb\u7edf\u542f\u52a8\u65f6\u81ea\u52a8\u8fd0\u884c", info)
        desc_label.setObjectName("desc-label")
        info_layout.addWidget(title_label)
        info_layout.addWidget(desc_label)
        layout.addWidget(info, 1)

        self.startupSwitch = SwitchButton(card)
        self.startupSwitch.checkedChanged.connect(self._onStartupToggled)
        layout.addWidget(self.startupSwitch)

        return card

    def _createTrayCard(self):
        card = CardWidget(self)
        card.setFixedHeight(80)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        info = QWidget(card)
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(6)
        title_label = QLabel("最小化到托盘", info)
        title_label.setObjectName("title-label")
        desc_label = QLabel("关闭窗口时最小化到系统托盘", info)
        desc_label.setObjectName("desc-label")
        info_layout.addWidget(title_label)
        info_layout.addWidget(desc_label)
        layout.addWidget(info, 1)

        self.traySwitch = SwitchButton(card)
        self.traySwitch.checkedChanged.connect(self._onTrayToggled)
        layout.addWidget(self.traySwitch)

        return card

    def _createMinimizeCard(self):
        card = CardWidget(self)
        card.setFixedHeight(80)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        info = QWidget(card)
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(6)
        title_label = QLabel("启动时最小化", info)
        title_label.setObjectName("title-label")
        desc_label = QLabel("启动时最小化到系统托盘", info)
        desc_label.setObjectName("desc-label")
        info_layout.addWidget(title_label)
        info_layout.addWidget(desc_label)
        layout.addWidget(info, 1)

        self.minimizeSwitch = SwitchButton(card)
        self.minimizeSwitch.checkedChanged.connect(self._onMinimizeToggled)
        layout.addWidget(self.minimizeSwitch)

        return card

    def _applyStyles(self):
        isDark = qconfig.theme == Theme.DARK
        if qconfig.theme == Theme.AUTO:
            isDark = False
            
        if isDark:
            fg = "#ffffff"
            fg_secondary = "rgba(255,255,255,0.6)"
            bg = "#1e1e1e"
            hover_bg = "#2d2d2d"
        else:
            fg = "#000000"
            fg_secondary = "rgba(0,0,0,0.6)"
            bg = "#f0f0f0"
            hover_bg = "#e0e0e0"

        self.findChild(QLabel, "pageTitle").setStyleSheet(f"font-size: 28px; font-weight: bold; color: {fg};")

        for label in self.findChildren(QLabel, "title-label"):
            label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {fg};")
        for label in self.findChildren(QLabel, "desc-label"):
            label.setStyleSheet(f"font-size: 14px; color: {fg_secondary};")

    def _onThemeChanged(self):
        QTimer.singleShot(50, self._applyStyles)

    def _loadSettings(self):
        themeIndex = self._settings.value("theme", 0, type=int)
        self.themeComboBox.setCurrentIndex(themeIndex)
        self._applyStyles()
        
        # Apply initial theme without triggering signal
        theme = [Theme.AUTO, Theme.LIGHT, Theme.DARK][themeIndex]
        setTheme(theme)

        if hasattr(self, 'startupSwitch'):
            self.startupSwitch.blockSignals(True)
            startup_val = self._settings.value("autoStart", "false")
            self.startupSwitch.setChecked(str(startup_val).lower() == "true")
            self.startupSwitch.blockSignals(False)

        if hasattr(self, 'traySwitch'):
            tray_val = self._settings.value("minimizeToTray", "false")
            self.traySwitch.setChecked(str(tray_val).lower() == "true")
        if hasattr(self, 'minimizeSwitch'):
            min_val = self._settings.value("startMinimized", "false")
            self.minimizeSwitch.setChecked(str(min_val).lower() == "true")
            self._updateMinimizeState()
    
    def _updateMinimizeState(self):
        startup_val = self._settings.value("autoStart", "false")
        auto_start = str(startup_val).lower() == "true"
        self.minimizeSwitch.setEnabled(auto_start)
        if not auto_start:
            self.minimizeSwitch.setChecked(False)
            self._settings.setValue("startMinimized", "false")

    

    def _onThemeChangedComboBox(self, index):
        if self._isInitializing:
            return
        theme = [Theme.AUTO, Theme.LIGHT, Theme.DARK][index]
        setTheme(theme)
        self._settings.setValue("theme", index)

    def _onStartupToggled(self, checked):
        if self._isInitializing:
            return
        self._settings.setValue("autoStart", checked)
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", True)
            if checked:
                exePath = sys.executable
                winreg.SetValueEx(key, "AronaAI", 0, winreg.REG_SZ, f'"{exePath}" --minimized')
            else:
                try:
                    winreg.DeleteValue(key, "AronaAI")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except:
            pass
        self._updateMinimizeState()

    def _onTrayToggled(self, checked):
        if self._isInitializing:
            return
        self._settings.setValue("minimizeToTray", checked)

    def _onMinimizeToggled(self, checked):
        if self._isInitializing:
            return
        self._settings.setValue("startMinimized", checked)
    
    def _isAutoStartEnabled(self):
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", False)
            try:
                value, _ = winreg.QueryValueEx(key, "AronaAI")
                winreg.CloseKey(key)
                return value is not None
            except FileNotFoundError:
                winreg.CloseKey(key)
                return False
        except:
            return False

    def loadSettings(self):
        self._loadSettings()