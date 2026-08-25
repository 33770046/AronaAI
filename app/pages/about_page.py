from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QFont
from qfluentwidgets import (
    MessageBoxBase, TransparentPushButton, TextEdit,
    BodyLabel, ImageLabel,
)

from ..config import get_accent_color
from ..update_utils import get_bundle_dir, get_assets_dir
from qfluentwidgets.common.font import getFont


CURRENT_VERSION = "dev.0.9.3"
GITHUB_REPO = "33770046/AronaAI"


class LicenseDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        license_path = get_bundle_dir() / "LICENSE"
        try:
            text = license_path.read_text("utf-8")
        except Exception:
            text = "未找到 LICENSE 文件"

        self.titleLabel = BodyLabel("开源许可")
        self.titleLabel.setFont(getFont(16))
        self.viewLayout.addWidget(self.titleLabel)

        self._edit = TextEdit()
        self._edit.setReadOnly(True)
        self._edit.setPlainText(text)
        self._edit.setFont(QFont("Microsoft YaHei", 9))
        self._edit.setFixedSize(520, 360)
        self.viewLayout.addWidget(self._edit)

        self.yesButton.setText("确定")
        self.cancelButton.hide()


class CopyrightNoticeDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.titleLabel = BodyLabel("版权声明")
        self.titleLabel.setFont(getFont(16))
        self.viewLayout.addWidget(self.titleLabel)

        notices = [
            "1. 源代码：本程序（指逻辑代码、脚本、配置文件）遵循 GNU General Public License v3.0 开源协议。",
            "2. 美术资源：本程序所使用的所有立绘、CG、音频、模型、图片、MomoTalk主题等美术素材，其知识产权及所有权均归 Nexon / Yostar 及其关联公司所有。",
            "3. 免责声明：本应用为粉丝制作的非商业性同人作品，仅供学习与交流使用，请勿用于任何商业用途或非法分发。",
            "4. 许可证隔离：本项目中的美术资源不适用 GPLv3 协议。使用、修改或分发这些资源时，需遵守《著作权法》及版权方（Nexon/Yostar）的相关规定，因滥用美术资源引发的法律责任由行为人自行承担。",
        ]

        text_block = QWidget(self.widget)
        text_layout = QVBoxLayout(text_block)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(8)
        for text in notices:
            lbl = BodyLabel(text)
            lbl.setFont(getFont(12))
            lbl.setWordWrap(True)
            text_layout.addWidget(lbl)
        text_layout.addStretch()

        self.viewLayout.addWidget(text_block)

        self.yesButton.setText("确定")
        self.cancelButton.hide()
        self.widget.setMinimumWidth(520)


class AboutDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        assets = get_assets_dir()

        row = QWidget(self.widget)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(16)

        logo_label = ImageLabel()
        pixmap = QPixmap(str(assets / "Logo" / "Logo.png"))
        if not pixmap.isNull():
            logo_label.setPixmap(
                pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            logo_label.setText("Logo")
        logo_label.setAlignment(Qt.AlignCenter)
        logo_label.setFixedSize(80, 80)
        row_layout.addWidget(logo_label)

        text_col = QWidget(row)
        text_layout = QVBoxLayout(text_col)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)

        name_label = BodyLabel("AronaAI")
        name_label.setFont(getFont(24))
        text_layout.addWidget(name_label)

        version_label = BodyLabel(f"版本: {CURRENT_VERSION}")
        version_label.setFont(getFont(14))
        text_layout.addWidget(version_label)

        text_layout.addStretch()
        row_layout.addWidget(text_col)

        self.viewLayout.addWidget(row)

        license_label = BodyLabel("本程序遵循 GNU General Public License v3.0 开源许可")
        license_label.setAlignment(Qt.AlignLeft)
        license_label.setFont(getFont(12))
        self.viewLayout.addWidget(license_label)

        copyright_label = BodyLabel("Copyright © 2026 AronaAI.")
        copyright_label.setAlignment(Qt.AlignLeft)
        copyright_label.setFont(getFont(12))
        self.viewLayout.addWidget(copyright_label)

        link_color = get_accent_color()

        link_row = QWidget()
        link_row_layout = QHBoxLayout(link_row)
        link_row_layout.setContentsMargins(0, 0, 0, 0)
        link_row_layout.setSpacing(24)
        link_row_layout.addStretch()

        self._license_link = BodyLabel(
            f'<a href="license" style="color:{link_color}; text-decoration:none;">开源许可</a>'
        )
        self._license_link.setFont(getFont(12))
        self._license_link.setOpenExternalLinks(False)
        self._license_link.linkActivated.connect(self._show_license)
        link_row_layout.addWidget(self._license_link)

        self._notice_link = BodyLabel(
            f'<a href="notice" style="color:{link_color}; text-decoration:none;">版权声明</a>'
        )
        self._notice_link.setFont(getFont(12))
        self._notice_link.setOpenExternalLinks(False)
        self._notice_link.linkActivated.connect(self._show_notice)
        link_row_layout.addWidget(self._notice_link)

        self._github_link = BodyLabel(
            f'<a href="https://github.com/{GITHUB_REPO}" style="color:{link_color}; text-decoration:none;">GitHub</a>'
        )
        self._github_link.setFont(getFont(12))
        self._github_link.setOpenExternalLinks(True)
        link_row_layout.addWidget(self._github_link)

        link_row_layout.addStretch()
        self.viewLayout.addWidget(link_row)

        self.yesButton.setText("确定")
        self.cancelButton.hide()
        self.widget.setMinimumWidth(280)

    def _show_license(self, url):
        dlg = LicenseDialog(self)
        dlg.exec()

    def _show_notice(self, url):
        dlg = CopyrightNoticeDialog(self)
        dlg.exec()
