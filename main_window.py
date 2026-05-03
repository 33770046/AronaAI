import os
from PyQt5.QtCore import Qt, QSettings, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QSystemTrayIcon, QMenu, QAction
from qfluentwidgets import FluentWindow, setTheme, Theme, MSFluentTitleBar, qconfig
from qfluentwidgets import FluentIcon, NavigationItemPosition
from resource_path import get_resource_path

from Pages.home_page import HomePage
from Pages.general_page import GeneralPage
from Pages.voice_page import VoicePage
from Pages.activity_page import ActivityPage
from Pages.about_page import AboutPage


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()

        settings = QSettings("AronaAI", "Settings")
        themeIndex = settings.value("theme", 0, type=int)
        setTheme([Theme.AUTO, Theme.LIGHT, Theme.DARK][themeIndex])

        self.homePage = HomePage(self)
        self.homePage.setObjectName('home')
        self.generalPage = GeneralPage(self)
        self.generalPage.setObjectName('general')
        self.voicePage = VoicePage(self)
        self.voicePage.setObjectName('voice')
        self.activityPage = ActivityPage(self)
        self.activityPage.setObjectName('activity')
        self.aboutPage = AboutPage(self)
        self.aboutPage.setObjectName('about')

        self.addSubInterface(self.homePage, FluentIcon.HOME, '\u9996\u9875')
        self.addSubInterface(self.generalPage, FluentIcon.SETTING, '\u901a\u7528')
        self.addSubInterface(self.voicePage, FluentIcon.VOLUME, '\u58f0\u97f3')
        self.addSubInterface(self.activityPage, FluentIcon.CALENDAR, '\u6d3b\u52a8')
        self.addSubInterface(self.aboutPage, FluentIcon.INFO, '\u5173\u4e8e', position=NavigationItemPosition.BOTTOM)

        self.navigationInterface.setCurrentItem('home')

        self.setTitleBar(MSFluentTitleBar(self))
        self.setWindowIcon(QIcon(get_resource_path("Assets/WindowLogo.png")))
        self.setWindowTitle("AronaAI 设置")
        self.resize(1200, 800)
        self.setMinimumWidth(800)
        self.setMaximumWidth(1920)

        self.generalPage.navigateToAbout.connect(self.switchToAbout)

        qconfig.themeChanged.connect(self._onThemeChanged)

        self._setupTray()
        
        settings = QSettings("AronaAI", "Settings")
        startMinimized = settings.value("startMinimized", "false")
        autoStartEnabled = str(settings.value("autoStart", "false")).lower() == "true"
        
        if str(startMinimized).lower() == "true" and autoStartEnabled:
            self.hide()
        else:
            self.show()
        
        QTimer.singleShot(1500, self._showWelcomeDialog)

    def _setupTray(self):
        self.trayIcon = QSystemTrayIcon(self)
        self.trayIcon.setIcon(QIcon(get_resource_path("Assets/WindowLogo.png")))
        
        trayMenu = QMenu(self)
        showAction = QAction("显示主窗口", self)
        showAction.triggered.connect(self.show)
        quitAction = QAction("退出", self)
        quitAction.triggered.connect(self.quitApp)
        
        trayMenu.addAction(showAction)
        trayMenu.addSeparator()
        trayMenu.addAction(quitAction)
        
        self.trayIcon.setContextMenu(trayMenu)
        self.trayIcon.show()

    def _checkStartMinimized(self):
        pass
    
    def _showWelcomeDialog(self):
        try:
            from Popup import PopupWindow
            from resource_path import get_resource_path
            
            settings = QSettings("AronaAI", "Settings")
            themeFolder = settings.value("windowTheme", "Aluona")
            language = settings.value("windowLanguage", "JP")
            volume = settings.value("volume", 100, type=int)
            
            appDir = get_resource_path("")
            iniPath = os.path.join(appDir, "Audio", "audio.ini")
            text = self._getAudioText(iniPath, "1.wav")
            if not text:
                text = "Sensei，欢迎回来！今天也请多多指教了！"
            
            popup = PopupWindow()
            popup.setWindowTheme(themeFolder)
            popup.setWindowLanguage(language)
            popup.setAudioVolume(volume)
            popup.showAronaDialog(text=text, alwaysOnTop=True, audioId="1.wav")
        except Exception as e:
            print(f"Show welcome dialog error: {e}")
    
    def _getAudioText(self, iniPath, audioFileName):
        try:
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

    def closeEvent(self, event):
        settings = QSettings("AronaAI", "Settings")
        minimizeToTray = settings.value("minimizeToTray", "false")
        if str(minimizeToTray).lower() == "true":
            event.ignore()
            self.hide()
        else:
            event.accept()
            self.quitApp()

    def quitApp(self):
        self.trayIcon.hide()
        self.close()
        import sys
        sys.exit(0)

    def _onThemeChanged(self):
        QTimer.singleShot(50, lambda: self.generalPage._applyStyles())
        QTimer.singleShot(50, lambda: self.aboutPage._applyStyles())
        QTimer.singleShot(50, lambda: self.voicePage._applyStyles())

    def switchToAbout(self):
        self.navigationInterface.setCurrentItem('about')