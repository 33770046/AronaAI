import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                              QPushButton, QFileDialog)
from PyQt5.QtCore import Qt, QSettings, QTimer
from PyQt5.QtCore import pyqtSignal
from qfluentwidgets import CardWidget, PrimaryPushButton, ComboBox, Slider, FluentIcon, setTheme, Theme, LineEdit
from qfluentwidgets import qconfig, InfoBar, InfoBarPosition
from resource_path import get_resource_path


class VoicePage(QWidget):
    hotkeyChanged = pyqtSignal(str)
    navigateToAbout = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('voice')
        self._isInitializing = True
        self._mainWindow = parent
        self._settings = QSettings("AronaAI", "Settings")
        self._windowThemes = []
        self._currentLanguage = "JP"
        self._popupWindow = None
        
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

        title = QLabel("声音与窗口", self)
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self._volumeCard = self._createVolumeCard()
        self._languageCard = self._createLanguageCard()
        self._themeCard = self._createThemeCard()
        self._testCard = self._createTestCard()

        layout.addWidget(self._volumeCard)
        layout.addWidget(self._languageCard)
        layout.addWidget(self._themeCard)
        layout.addWidget(self._testCard)

        layout.addStretch()

    def _createVolumeCard(self):
        card = CardWidget(self)
        card.setFixedHeight(100)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        title_label = QLabel("音量", self)
        title_label.setObjectName("title-label")
        
        slider_layout = QHBoxLayout()
        slider_layout.setSpacing(12)
        
        self.volumeSlider = Slider(Qt.Horizontal, self)
        self.volumeSlider.setMinimum(0)
        self.volumeSlider.setMaximum(100)
        self.volumeSlider.setValue(100)
        self.volumeSlider.setFixedHeight(32)
        self.volumeSlider.valueChanged.connect(self._onVolumeChanged)
        
        self.volumeText = QLabel("100%", self)
        self.volumeText.setObjectName("value-label")
        self.volumeText.setFixedWidth(50)
        
        slider_layout.addWidget(self.volumeSlider)
        slider_layout.addWidget(self.volumeText, 0, Qt.AlignRight)
        
        layout.addWidget(title_label)
        layout.addLayout(slider_layout)

        return card

    def _createLanguageCard(self):
        card = CardWidget(self)
        card.setFixedHeight(80)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        info = QWidget(card)
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(6)
        
        title_label = QLabel("选择配音语言", info)
        title_label.setObjectName("title-label")
        desc_label = QLabel("选择角色配音的语言", info)
        desc_label.setObjectName("desc-label")
        
        info_layout.addWidget(title_label)
        info_layout.addWidget(desc_label)
        
        layout.addWidget(info, 1)

        self.languageComboBox = ComboBox(self)
        self.languageComboBox.setFixedWidth(130)
        self.languageComboBox.setFixedHeight(36)
        self.languageComboBox.setStyleSheet("font-size: 14px;")
        self.languageComboBox.addItem("日配 (JP)", userData="JP")
        self.languageComboBox.addItem("中配 (CN)", userData="CN")
        self.languageComboBox.currentIndexChanged.connect(self._onLanguageChanged)
        
        layout.addWidget(self.languageComboBox)

        return card

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
        
        title_label = QLabel("窗口主题", info)
        title_label.setObjectName("title-label")
        desc_label = QLabel("选择角色窗口主题", info)
        desc_label.setObjectName("desc-label")
        
        info_layout.addWidget(title_label)
        info_layout.addWidget(desc_label)
        
        layout.addWidget(info, 1)

        self.themeComboBox = ComboBox(self)
        self.themeComboBox.setFixedWidth(130)
        self.themeComboBox.setFixedHeight(36)
        self.themeComboBox.setStyleSheet("font-size: 14px;")
        self.themeComboBox.currentIndexChanged.connect(self._onThemeChangedComboBox)
        
        layout.addWidget(self.themeComboBox)

        return card

    def _createTestCard(self):
        card = CardWidget(self)
        card.setMinimumHeight(120)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        title_label = QLabel("测试", self)
        title_label.setObjectName("title-label")
        
        self.showWindowButton = PrimaryPushButton("显示窗口", self)
        self.showWindowButton.setFixedWidth(120)
        self.showWindowButton.setFixedHeight(40)
        self.showWindowButton.clicked.connect(self._onShowWindowClicked)
        
        self.statusLabel = QLabel("", self)
        self.statusLabel.setObjectName("status-label")
        self.statusLabel.setVisible(False)
        
        layout.addWidget(title_label)
        
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        button_layout.addWidget(self.showWindowButton)
        
        self.hotkeyInput = LineEdit(self)
        self.hotkeyInput.setPlaceholderText("如: Ctrl+Alt+Z")
        self.hotkeyInput.setFixedWidth(150)
        self.hotkeyInput.setText(self._settings.value("popupHotkey", "Ctrl+Alt+Z"))
        self.hotkeyInput.textChanged.connect(self._onHotkeyChanged)
        
        button_layout.addWidget(self.hotkeyInput)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        layout.addWidget(self.statusLabel)

        return card

    def _applyStyles(self):
        isDark = qconfig.theme == Theme.DARK
        if qconfig.theme == Theme.AUTO:
            isDark = False
            
        if isDark:
            fg = "#ffffff"
            fg_secondary = "rgba(255,255,255,0.6)"
        else:
            fg = "#000000"
            fg_secondary = "rgba(0,0,0,0.6)"

        pageTitle = self.findChild(QLabel, "pageTitle")
        if pageTitle:
            pageTitle.setStyleSheet(f"font-size: 28px; font-weight: bold; color: {fg};")
        
        for label in self.findChildren(QLabel, "title-label"):
            label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {fg};")
        
        for label in self.findChildren(QLabel, "desc-label"):
            label.setStyleSheet(f"font-size: 14px; color: {fg_secondary};")
        
        for label in self.findChildren(QLabel, "value-label"):
            label.setStyleSheet(f"font-size: 14px; color: {fg_secondary};")
        
        status_label = self.findChild(QLabel, "status-label")
        if status_label:
            status_label.setStyleSheet(f"font-size: 14px; color: #4caf50; padding: 8px; background: rgba(76, 175, 80, 0.1); border-radius: 4px;")

    def _onThemeChanged(self):
        QTimer.singleShot(50, self._applyStyles)

    def _loadSettings(self):
        self._loadWindowThemes()
        
        volume = self._settings.value("volume", 100, type=int)
        self.volumeSlider.setValue(volume)
        self.volumeText.setText(f"{volume}%")
        
        self._currentLanguage = self._settings.value("windowLanguage", "JP")
        self.languageComboBox.blockSignals(True)
        for i in range(self.languageComboBox.count()):
            if self.languageComboBox.itemData(i) == self._currentLanguage:
                self.languageComboBox.setCurrentIndex(i)
                break
        self.languageComboBox.blockSignals(False)
        
        savedTheme = self._settings.value("windowTheme", "Aluona")
        if not savedTheme:
            savedTheme = "Aluona"
        print(f"Loading saved theme: {savedTheme}")
        
        self.themeComboBox.blockSignals(True)
        for i in range(self.themeComboBox.count()):
            data = self.themeComboBox.itemData(i)
            print(f"Combo item {i}: data={data}, text={self.themeComboBox.itemText(i)}")
            if data == savedTheme:
                self.themeComboBox.setCurrentIndex(i)
                print(f"Set to index {i}")
                break
        self.themeComboBox.blockSignals(False)
        
        self._applyStyles()

    def _loadWindowThemes(self):
        self._windowThemes = []
        self.themeComboBox.clear()
        
        appDir = get_resource_path("")
        iniPath = os.path.join(appDir, "Images", "images.ini")
        
        if os.path.exists(iniPath):
            try:
                with open(iniPath, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                currentName = None
                currentFolder = None
                
                for line in lines:
                    line = line.strip()
                    if line.startswith('[') and line.endswith(']'):
                        if currentName and currentFolder:
                            self.themeComboBox.addItem(currentName)
                            self.themeComboBox.setItemData(self.themeComboBox.count() - 1, currentFolder)
                            self._windowThemes.append((currentName, currentFolder))
                        currentName = None
                        currentFolder = None
                    elif '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        if key == "name":
                            currentName = value
                        elif key == "folder":
                            currentFolder = value
                
                if currentName and currentFolder:
                    self.themeComboBox.addItem(currentName)
                    self.themeComboBox.setItemData(self.themeComboBox.count() - 1, currentFolder)
                    self._windowThemes.append((currentName, currentFolder))
            except Exception as e:
                print(f"Error loading themes: {e}")
        
        if self.themeComboBox.count() == 0:
            self.themeComboBox.addItem("阿罗娜")
            self.themeComboBox.setItemData(0, "Aluona")
            self.themeComboBox.addItem("普拉纳")
            self.themeComboBox.setItemData(1, "Pulana")

    def _onVolumeChanged(self, value):
        if self._isInitializing:
            return
        self.volumeText.setText(f"{value}%")
        self._settings.setValue("volume", value)
        self._writeVolumeFile(value)

    def _onLanguageChanged(self, index):
        if self._isInitializing:
            return
        self._currentLanguage = self.languageComboBox.itemData(index)
        self._settings.setValue("windowLanguage", self._currentLanguage)

    def _onThemeChangedComboBox(self, index):
        if self._isInitializing:
            return
        themeFolder = self.themeComboBox.itemData(index)
        print(f"Theme changed to: {themeFolder}")
        self._settings.setValue("windowTheme", themeFolder)

    def _writeVolumeFile(self, volume):
        try:
            appDir = get_resource_path("")
            volumeFile = os.path.join(appDir, "volume.txt")
            with open(volumeFile, 'w') as f:
                f.write(str(volume))
        except Exception as e:
            print(f"Error writing volume file: {e}")

    def _onShowWindowClicked(self):
        self._showAronaWindow()
    
    def _onHotkeyChanged(self, text):
        if self._isInitializing:
            return
        self._settings.setValue("popupHotkey", text)
        self.hotkeyChanged.emit(text)
    
    def _showAronaWindow(self):
        try:
            from Pages.Popup import PopupWindow
            
            if self._popupWindow is None:
                self._popupWindow = PopupWindow()
            
            themeFolder = self._settings.value("windowTheme", "Aluona")
            volume = self._settings.value("volume", 100, type=int)
            language = self._settings.value("windowLanguage", "JP")
            
            audioFile = "2.wav"
            text = self._getAudioText(language, audioFile)
            if not text:
                text = "开发中"
            
            print(f"Theme: {themeFolder}, Language: {language}, Volume: {volume}")
            self._popupWindow.setWindowTheme(themeFolder)
            self._popupWindow.setWindowLanguage(language)
            self._popupWindow.setAudioVolume(volume)
            self._popupWindow.showAronaDialog(text=text, alwaysOnTop=True, audioId=audioFile)
            
            self._showStatus("已显示")
            
        except Exception as e:
            print(f"Error: {e}")
            self._showStatus(f"启动失败: {str(e)}")

    def _getAudioText(self, language, audioFileName):
        try:
            appDir = get_resource_path("")
            iniPath = os.path.join(appDir, "Audio", "audio.ini")
            if os.path.exists(iniPath):
                with open(iniPath, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                currentKey = None
                for line in lines:
                    line = line.strip()
                    if line.startswith('[') and line.endswith(']'):
                        currentKey = line[1:-1]
                    elif currentKey == audioFileName and line:
                        return line
        except Exception as e:
            print(f"Error reading audio ini: {e}")
        return ""

    def _showStatus(self, message):
        if "已显示" in message or "成功" in message:
            InfoBar.success(title="成功", content=message, duration=2000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self.window())
        elif "失败" in message or "错误" in message:
            InfoBar.error(title="失败", content=message, duration=3000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self.window())
        elif "测试" in message:
            InfoBar.info(title="测试", content=message, duration=2000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self.window())
        else:
            InfoBar.info(title="提示", content=message, duration=2000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self.window())

    def loadSettings(self):
        self._loadSettings()