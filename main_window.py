import os
import re
import ctypes
from ctypes import wintypes
from PyQt5.QtCore import Qt, QSettings, QTimer, QUrl
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PyQt5.QtGui import QIcon, QKeySequence
from PyQt5.QtWidgets import QSystemTrayIcon, QMenu, QAction, QShortcut
from qfluentwidgets import FluentWindow, setTheme, Theme, MSFluentTitleBar, qconfig, InfoBar, InfoBarPosition
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
        self.voicePage.hotkeyChanged.connect(self._onHotkeyChangedFromPage)
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
        
        self._registerGlobalHotkey()

    def _registerGlobalHotkey(self):
        self._hotkeyTimer = QTimer(self)
        self._hotkeyTimer.timeout.connect(self._pollHotkey)
        self._hotkeyTimer.start(50)
        self._hotkeyPressed = False
        print("Hotkey polling started")
    
    def _pollHotkey(self):
        try:
            user32 = ctypes.windll.user32
            
            VK_CONTROL = 0x11
            VK_MENU = 0x12
            
            key_map = {'Z': 0x5A, 'X': 0x58, 'C': 0x43, 'V': 0x56, 'A': 0x41, 'S': 0x53, 'D': 0x44, 
                      '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34, '5': 0x35, 
                      '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39}
            
            settings = QSettings("AronaAI", "Settings")
            hotkey = settings.value("popupHotkey", "Ctrl+Alt+Z")
            
            key = hotkey.split("+")[-1].strip().upper()
            vk = key_map.get(key, 0x5A)
            
            ctrl = user32.GetAsyncKeyState(VK_CONTROL)
            alt = user32.GetAsyncKeyState(VK_MENU)
            key_pressed = user32.GetAsyncKeyState(vk)
            
            pressed = (ctrl & 0x8000) and (alt & 0x8000) and (key_pressed & 0x8000)
            
            if pressed and not self._hotkeyPressed:
                self._hotkeyPressed = True
                print("Hotkey detected!")
                self._showPopupByHotkey()
            elif not pressed:
                self._hotkeyPressed = False
        except Exception as e:
            pass
    
    def _registerHotkey(self):
        try:
            settings = QSettings("AronaAI", "Settings")
            hotkey_str = settings.value("popupHotkey", "Ctrl+Alt+Z")
            
            self._hotkeyShortcut = QShortcut(QKeySequence(hotkey_str), self)
            self._hotkeyShortcut.activated.connect(self._showPopupByHotkey)
        except Exception as e:
            print(f"Hotkey registration failed: {e}")
    
    def _registerHotkey(self):
        try:
            settings = QSettings("AronaAI", "Settings")
            hotkey_str = settings.value("popupHotkey", "Ctrl+Alt+Z")
            
            self._hotkeyShortcut = QShortcut(QKeySequence(hotkey_str), self)
            self._hotkeyShortcut.activated.connect(self._showPopupByHotkey)
        except Exception as e:
            print(f"Hotkey registration failed: {e}")
    
    def _onHotkeyChangedFromPage(self, hotkey):
        if hasattr(self, '_hotkeyShortcut'):
            self._hotkeyShortcut.setKey(QKeySequence(hotkey))
    
    def _showPopupByHotkey(self):
        try:
            from Pages.Popup import PopupWindow
            settings = QSettings("AronaAI", "Settings")
            themeFolder = settings.value("windowTheme", "Aluona")
            language = settings.value("windowLanguage", "JP")
            volume = settings.value("volume", 100, type=int)
            
            iniPath = os.path.join(get_resource_path(""), "Audio", "audio.ini")
            audioFile = "2.wav"
            text = self._getAudioText(language, audioFile)
            if not text:
                text = "开发中"
            
            popup = PopupWindow()
            popup.setWindowTheme(themeFolder)
            popup.setWindowLanguage(language)
            popup.setAudioVolume(volume)
            popup.showAronaDialog(text=text, alwaysOnTop=True, audioId=audioFile)
        except Exception as e:
            print(f"Hotkey popup error: {e}")

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
            from Pages.Popup import PopupWindow
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
            
            self._autoCheckUpdate()
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
    
    def _autoCheckUpdate(self):
        settings = QSettings("AronaAI", "Settings")
        autoCheck = settings.value("autoCheckUpdates", False, type=bool)
        if not autoCheck:
            return
        
        from Pages.about_page import CURRENT_VERSION, GITHUB_REPO
        self._update_channel = settings.value("updateChannel", "stable")
        
        self._update_network_manager = QNetworkAccessManager(self)
        url = QUrl(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest")
        request = QNetworkRequest(url)
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "AronaAI")
        self._update_reply = self._update_network_manager.get(request)
        self._update_reply.finished.connect(self._onAutoUpdateReplyFinished)
    
    def _onAutoUpdateReplyFinished(self):
        if self._update_reply.error() != QNetworkReply.NetworkError.NoError:
            if "rate limit" in self._update_reply.errorString().lower():
                pass
            return
        
        import json
        from Pages.about_page import CURRENT_VERSION
        try:
            data = json.loads(self._update_reply.readAll().data().decode('utf-8'))
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
            
            channel = self._update_channel
            latest_is_dev = prefix == 'dev'
            
            should_check = True
            if channel == "stable" and latest_is_dev:
                should_check = False
                display_version = None
            else:
                display_version = latest_version
            
            if should_check:
                def normalize(v):
                    v = re.sub(r'^(dev|v)', '', v)
                    parts = re.split(r'[.\-_]', v)
                    return [int(p) if p.isdigit() else 0 for p in parts[:4]] + [0] * (4 - len(parts))
                
                current_parts = normalize(CURRENT_VERSION)
                latest_parts = normalize(latest_version)
                
                if current_parts < latest_parts:
                    self._showUpdateNotification(display_version, data.get('html_url', ''))
        except:
            pass
    
    def _showUpdateNotification(self, version, url):
        settings = QSettings("AronaAI", "Settings")
        autoDownload = settings.value("autoDownload", False, type=bool)
        
        if autoDownload:
            QDesktopServices.openUrl(QUrl(url))
            InfoBar.success(
                title="正在下载",
                content=f"正在下载版本 {version}...",
                duration=3000,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self
            )
        else:
            InfoBar.success(
                title="发现新版本",
                content=f"版本 {version} 可用",
                duration=0,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self
            ).clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))