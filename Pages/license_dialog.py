import os
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QDialog, QHBoxLayout, QVBoxLayout, QWidget, QTextEdit, QScrollArea
from PyQt5.QtWidgets import QGraphicsDropShadowEffect
from PyQt5.QtGui import QFont, QFontDatabase
from qfluentwidgets import PrimaryPushButton, qconfig, Theme, isDarkTheme


class LicenseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(900, 700)
        
        font_id = QFontDatabase.addApplicationFont("fonts/汉仪正圆-75S.ttf")
        if font_id != -1:
            self.custom_font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
        else:
            self.custom_font_family = "Microsoft YaHei"
        
        self._setupUi()
        self._applyTheme()
        
        qconfig.themeChanged.connect(self._onThemeChanged)

    def _onThemeChanged(self):
        self._applyTheme()

    def _applyTheme(self):
        isDark = isDarkTheme()
        
        if isDark:
            container_bg = "#2d2d2d"
            text_bg = "#1e1e1e"
            text_fg = "#ffffff"
        else:
            container_bg = "#ffffff"
            text_bg = "#f5f5f5"
            text_fg = "#000000"
        
        self.setStyleSheet(f"""
            QDialog {{ background: transparent; }}
            #container {{
                background-color: {container_bg};
                border-radius: 12px;
            }}
            QLabel {{
                color: {text_fg};
            }}
        """)
        
        self._text_edit.setStyleSheet(f"""
            QTextEdit {{
                color: {text_fg};
                background-color: {text_bg};
                border: none;
                padding: 12px;
                font-family: '{self.custom_font_family}', 'Microsoft YaHei', sans-serif;
                font-size: 16px;
            }}
        """)
        
        container = self.findChild(QWidget, "container")
        if container and container.graphicsEffect():
            container.graphicsEffect().setColor(Qt.gray if not isDarkTheme() else Qt.black)

    def _setupUi(self):
        container = QWidget(self)
        container.setObjectName("container")
        
        shadow = QGraphicsDropShadowEffect(container)
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 4)
        shadow.setColor(Qt.gray if not isDarkTheme() else Qt.black)
        container.setGraphicsEffect(shadow)
        
        layout = QVBoxLayout(container)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)
        
        title = QLabel("开放源代码许可")
        title.setStyleSheet(f"font-size: 28px; font-weight: bold; font-family: '{self.custom_font_family}', 'Microsoft YaHei', sans-serif;")
        layout.addWidget(title)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        
        self._text_edit = QTextEdit()
        self._text_edit.setReadOnly(True)
        
        license_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "LICENSE")
        try:
            with open(license_path, "r", encoding="utf-8") as f:
                self._text_edit.setPlainText(f.read())
        except:
            self._text_edit.setPlainText("无法读取 LICENSE 文件")
        
        scroll.setWidget(self._text_edit)
        layout.addWidget(scroll, 1)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self._btn_close = PrimaryPushButton("关闭", self)
        self._btn_close.setFixedWidth(100)
        self._btn_close.setFixedHeight(32)
        self._btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(self._btn_close)
        
        layout.addLayout(btn_layout)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.addWidget(container)


def showLicenseDialog(parent=None):
    dialog = LicenseDialog(parent)
    dialog.exec_()


if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication
    from qfluentwidgets import setTheme, Theme
    app = QApplication(sys.argv)
    setTheme(Theme.AUTO)
    dialog = LicenseDialog()
    dialog.show()
    sys.exit(app.exec_())