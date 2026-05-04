from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore import Qt, QSize, QSettings
from PyQt5.QtGui import QPixmap, QLinearGradient, QColor
from qfluentwidgets import qconfig, Theme, setTheme


class HomePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('home')
        self._setupUi()
        
        settings = QSettings("AronaAI", "Settings")
        themeIndex = settings.value("theme", 0, type=int)
        setTheme([Theme.AUTO, Theme.LIGHT, Theme.DARK][themeIndex])
        
        qconfig.themeChanged.connect(self._onThemeChanged)

    def _setupUi(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self._image_label = QLabel(self)
        self._image_label.setObjectName("homeImage")
        self._image_label.setAlignment(Qt.AlignTop)
        self._image_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._image_label.setScaledContents(True)
        
        self._gradient_label = QLabel(self)
        self._gradient_label.setObjectName("gradientOverlay")
        self._gradient_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        
        self._pixmap_path = "Assets/homepage/45ce9da5-c75f-4ea3-a055-186951132875.png"
        self._original_pixmap = QPixmap(self._pixmap_path)
        
        layout.addWidget(self._image_label)
        layout.addWidget(self._gradient_label)
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._updateImage()
    
    def _updateImage(self):
        w = self.width()
        if w > 0 and not self._original_pixmap.isNull():
            ratio = w / self._original_pixmap.width()
            new_height = int(self._original_pixmap.height() * ratio)
            scaled = self._original_pixmap.scaled(w, new_height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self._image_label.setPixmap(scaled)
            self._image_label.setFixedHeight(new_height)
            
            gradient_height = min(100, new_height // 3)
            self._gradient_label.setFixedSize(w, gradient_height)
            
            is_dark = self._isDarkTheme()
            if is_dark:
                bottom_color = "39,39,39"
            else:
                bottom_color = "249,249,249"
            
            self._gradient_label.setStyleSheet(f"background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(0,0,0,0), stop:1 rgba({bottom_color},255));")
            
            self.setFixedHeight(new_height)
    
    def _onThemeChanged(self):
        self._updateImage()
    
    def _isDarkTheme(self):
        theme = qconfig.theme
        if theme == Theme.DARK:
            return True
        elif theme == Theme.LIGHT:
            return False
        else:
            from PyQt5.QtWidgets import QApplication
            palette = QApplication.palette()
            return palette.window().color().lightness() < 128