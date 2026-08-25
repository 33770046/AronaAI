import os


def init_scale():
    from PySide6.QtCore import QSettings
    percent = int(QSettings("AronaAI", "AronaAI").value("scale", 100))
    os.environ["QT_SCALE_FACTOR"] = str(percent / 100)
