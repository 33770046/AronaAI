import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFontDatabase

from main_window import MainWindow
from qfluentwidgets import setFontFamilies
from resource_path import get_resource_path

app = QApplication([])

font_path = get_resource_path("fonts/ResourceHanCN-Bold.ttf")
font_id = QFontDatabase.addApplicationFont(font_path)
font_families = QFontDatabase.applicationFontFamilies(font_id)
font_name = font_families[0] if font_families else "ResourceHanCN-Bold"

setFontFamilies([font_name], save=True)
app.setStyleSheet(f"*{{font-family: '{font_name}' !important;}}")

start_minimized = "--minimized" in sys.argv

w = MainWindow()
sys.exit(app.exec_())