from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel


class ActivityPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('activity')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("\u6d3b\u52a8", self)
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        layout.addStretch()