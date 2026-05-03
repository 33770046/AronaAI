import sys
import os
from PyQt5.QtWidgets import (QDialog, QLabel, QTextEdit, QPushButton, 
                             QVBoxLayout, QHBoxLayout, QWidget)
from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, QPoint, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.Qt import QUrl
from resource_path import get_resource_path


class AronaDialog(QDialog):
    def __init__(self, imagePath, text, alwaysOnTop=True, audioFilePath="", volume=100, parent=None):
        super().__init__(parent)
        self._imagePath = imagePath
        self._text = text
        self._audioFilePath = audioFilePath
        self._volume = volume / 100.0
        self._exiting = False
        self._player = None
        self._animation = None
        self._textWindow = None
        self._finalPos = QPoint()
        self._lastVolume = volume
        
        self._setupUi(alwaysOnTop)
        self._startVolumeMonitor()
        
    def _setupUi(self, alwaysOnTop):
        flags = Qt.FramelessWindowHint | Qt.Tool
        if alwaysOnTop:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        imageLabel = QLabel(self)
        pixmap = QPixmap(self._imagePath)
        if not pixmap.isNull():
            newWidth = int(pixmap.width() * 0.37)
            newHeight = int(pixmap.height() * 0.37)
            scaledPixmap = pixmap.scaled(newWidth, newHeight, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            imageLabel.setPixmap(scaledPixmap)
            imageLabel.setFixedSize(newWidth, newHeight)
            imageLabel.setStyleSheet("background: transparent;")
        else:
            imageLabel.setText("图片加载失败")
            imageLabel.setFixedSize(200, 200)
            imageLabel.setStyleSheet("background: rgba(255,255,255,200); color: black;")
        
        mainLayout = QVBoxLayout(self)
        mainLayout.setContentsMargins(0, 0, 0, 0)
        mainLayout.addWidget(imageLabel, 0, Qt.AlignCenter)
        self.setFixedSize(imageLabel.size())
        
        self._textWindow = QWidget(self, Qt.Window | Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self._textWindow.setAttribute(Qt.WA_TranslucentBackground)
        
        textLayout = QVBoxLayout(self._textWindow)
        textLayout.setContentsMargins(5, 5, 5, 5)
        textLayout.setSpacing(5)
        
        self._closeBtn = QPushButton("关闭")
        self._closeBtn.setStyleSheet(
            "background-color: rgba(200, 200, 200, 200);"
            "border: none;"
            "border-radius: 5px;"
            "padding: 2px 8px;"
            "color: black;"
        )
        self._closeBtn.clicked.connect(self._onCloseClicked)
        
        self._textEdit = QTextEdit()
        self._textEdit.setPlainText(self._text)
        self._textEdit.setReadOnly(True)
        self._textEdit.setMaximumHeight(60)
        self._textEdit.setStyleSheet(
            "background-color: rgba(255, 255, 255, 200);"
            "border: none;"
            "border-radius: 10px;"
            "padding: 4px;"
            "color: black;"
        )
        try:
            self._textEdit.setFrameStyle(QTextEdit.NoFrame)
        except:
            pass
        
        topLayout = QHBoxLayout()
        topLayout.setContentsMargins(0, 0, 0, 0)
        topLayout.setSpacing(0)
        topLayout.addStretch()
        topLayout.addWidget(self._closeBtn)
        
        textLayout.addLayout(topLayout)
        textLayout.addWidget(self._textEdit)
        
        self._textWindow.adjustSize()
    
    def _startVolumeMonitor(self):
        self._volumeTimer = QTimer(self)
        self._volumeTimer.timeout.connect(self._checkVolumeChange)
        self._volumeTimer.start(200)
    
    def _checkVolumeChange(self):
        try:
            appDir = get_resource_path("")
            volumeFile = os.path.join(appDir, "volume.txt")
            if os.path.exists(volumeFile):
                with open(volumeFile, 'r') as f:
                    newVolume = int(f.read().strip())
                if newVolume != self._lastVolume and 0 <= newVolume <= 100:
                    self._lastVolume = newVolume
                    self.setVolume(newVolume)
        except:
            pass
    
    def setVolume(self, volume):
        if 0 <= volume <= 100:
            self._volume = volume / 100.0
            if self._player:
                self._player.setVolume(int(self._volume * 100))
    
    def showWithAnimation(self):
        self._adjustPosition()
        
        from PyQt5.QtWidgets import QApplication
        desktop = QApplication.desktop()
        screenGeo = desktop.availableGeometry()
        
        textX = screenGeo.right() - self._textWindow.width() - 5
        textY = screenGeo.bottom() - self._textWindow.height() - 5
        self._textWindow.move(textX, textY)
        
        self._textWindow.raise_()
        self._textWindow.show()
        self.show()
        
        screenRect = desktop.availableGeometry()
        startX = screenRect.width()
        self.move(startX, self._finalPos.y())
        
        self._animation = QPropertyAnimation(self, b"pos")
        self._animation.setDuration(500)
        self._animation.setStartValue(self.pos())
        self._animation.setEndValue(self._finalPos)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.start()
        
        if self._audioFilePath and os.path.exists(self._audioFilePath):
            self._player = QMediaPlayer()
            self._player.setVolume(int(self._volume * 100))
            self._player.setMedia(QMediaContent(QUrl.fromLocalFile(self._audioFilePath)))
            
            self._player.stateChanged.connect(self._onPlaybackStateChanged)
            self._player.play()
        else:
            QTimer.singleShot(5000, self.startExitAnimation)
    
    def _onPlaybackStateChanged(self, state):
        if state == QMediaPlayer.StoppedState or state == QMediaPlayer.PausedState:
            QTimer.singleShot(100, self.startExitAnimation)
    
    def closeEvent(self, event):
        if self._textWindow:
            self._textWindow.close()
        if hasattr(self, '_volumeTimer'):
            self._volumeTimer.stop()
        event.accept()
    
    def _onCloseClicked(self):
        if not self._exiting:
            self.startExitAnimation()
    
    def startExitAnimation(self):
        if self._exiting:
            return
        self._exiting = True
        
        if hasattr(self, '_volumeTimer'):
            self._volumeTimer.stop()
        
        if self._textWindow:
            self._textWindow.close()
        
        if self._animation:
            self._animation.stop()
        
        from PyQt5.QtWidgets import QApplication
        desktop = QApplication.desktop()
        screenRect = desktop.availableGeometry()
        endX = screenRect.width()
        
        self._exitAnimation = QPropertyAnimation(self, b"pos")
        self._exitAnimation.setDuration(500)
        self._exitAnimation.setStartValue(self.pos())
        self._exitAnimation.setEndValue(QPoint(endX, self.pos().y()))
        self._exitAnimation.setEasingCurve(QEasingCurve.InCubic)
        self._exitAnimation.finished.connect(self.close)
        self._exitAnimation.start()
    
    def _adjustPosition(self):
        from PyQt5.QtWidgets import QApplication
        desktop = QApplication.desktop()
        screenGeometry = desktop.availableGeometry()
        
        x = screenGeometry.right() - self.width()
        y = screenGeometry.bottom() - self.height()
        y += 280
        
        if x < screenGeometry.left():
            x = screenGeometry.left()
        
        self._finalPos = QPoint(x, y)
    
    def updateText(self, newText):
        self._textEdit.setPlainText(newText)


class PopupWindow:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._windowTheme = "Aluona"
        self._windowLanguage = "JP"
        self._audioVolume = 100
        self._aronaDialog = None
        self._shouldQuit = False
        self._themeNameMap = {}
        self._app = None
    
    def setWindowTheme(self, theme):
        if theme:
            self._windowTheme = theme
    
    def setWindowLanguage(self, lang):
        if lang:
            self._windowLanguage = lang
    
    def setAudioVolume(self, volume):
        if 0 <= volume <= 100:
            self._audioVolume = volume
    
    def setDialogVolume(self, volume):
        if self._aronaDialog:
            self._aronaDialog.setVolume(volume)
    
    def getCurrentAronaDialog(self):
        return self._aronaDialog
    
    def _loadThemeFromIni(self):
        appDir = get_resource_path("")
        iniPath = os.path.join(appDir, "Images", "images.ini")
        
        self._themeNameMap = {}
        
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
                            self._themeNameMap[currentFolder] = currentName
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
                    self._themeNameMap[currentFolder] = currentName
            except Exception as e:
                print(f"Error loading theme ini: {e}")
    
    def _getAudioTextFromIni(self, audioId):
        appDir = get_resource_path("")
        iniPath = os.path.join(appDir, "Audio", "audio.ini")
        
        if os.path.exists(iniPath):
            try:
                with open(iniPath, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                currentKey = None
                for line in lines:
                    line = line.strip()
                    if line.startswith('[') and line.endswith(']'):
                        currentKey = line[1:-1]
                    elif currentKey == audioId and line:
                        return line
            except Exception as e:
                print(f"Error reading audio ini: {e}")
        return None
    
    def showAronaDialog(self, text="Sensei，欢迎回来！今天也请多多指教了！", 
                        alwaysOnTop=True, audioId=""):
        if self._aronaDialog:
            old_dialog = self._aronaDialog
            
            old_dialog._exiting = True
            
            if old_dialog._textWindow:
                old_dialog._textWindow.close()
            
            if old_dialog._volumeTimer:
                old_dialog._volumeTimer.stop()
            
            if old_dialog._animation:
                old_dialog._animation.stop()
            
            if old_dialog._player:
                old_dialog._player.stop()
            
            old_dialog.hide()
            old_dialog.deleteLater()
            
            self._aronaDialog = None
        
        self._loadThemeFromIni()
        
        appDir = get_resource_path("")
        
        themeFolder = self._windowTheme if self._windowTheme else "Aluona"
        imagePath = os.path.join(appDir, "Images", themeFolder, "Normal.png")
        
        print(f"Popup themeFolder: {themeFolder}, imagePath: {imagePath}, exists: {os.path.exists(imagePath)}")
        
        if not os.path.exists(imagePath):
            imagePath = os.path.join(appDir, "Images", "Aluona", "Normal.png")
            print(f"Fallback to: {imagePath}")
        
        audioFilePath = ""
        if audioId:
            langFolder = self._windowLanguage if self._windowLanguage else "JP"
            audioFilePath = os.path.join(appDir, "Audio", themeFolder, langFolder, audioId)
            if not os.path.exists(audioFilePath):
                audioFilePath = ""
            
            if not audioFilePath or not os.path.exists(audioFilePath):
                audioText = self._getAudioTextFromIni(audioId)
                if audioText:
                    text = audioText
        
        if os.path.exists(imagePath):
            self._aronaDialog = AronaDialog(
                imagePath, text, alwaysOnTop, audioFilePath, self._audioVolume
            )
            self._aronaDialog.setAttribute(Qt.WA_DeleteOnClose)
            self._aronaDialog.destroyed.connect(self._onDialogDestroyed)
            self._aronaDialog.showWithAnimation()
    
    def _onDialogDestroyed(self):
        self._aronaDialog = None


if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    app = QApplication([])
    popup = PopupWindow()
    popup.showAronaDialog()
    sys.exit(app.exec_())