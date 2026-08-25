import sys, re, json
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QApplication, QLabel, QFrame, QHBoxLayout,
    QFormLayout,
)
from PySide6.QtCore import Qt, QSettings, QProcess, QTimer, QUrl, Signal, QThread
from PySide6.QtGui import QColor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from qfluentwidgets import (
    SettingCardGroup, OptionsSettingCard, ExpandSettingCard, SettingCard, ComboBox,
    FluentIcon as FIF, qconfig, Theme, MessageBox, RadioButton, ScrollArea,
    SwitchButton, PushButton, SpinBox, IndicatorPosition,
    InfoBar, InfoBarPosition, SwitchSettingCard,
    MessageBoxBase, BodyLabel, TextEdit, LineEdit, TransparentToolButton,
)
from app.config import get_close_behavior, set_close_behavior, MOMOTALK
from app.config import is_autostart_enabled, set_autostart_enabled
from app.config import get_ai_settings, set_ai_settings
from app.pages.about_page import CURRENT_VERSION, GITHUB_REPO
from app.scroll_utils import enable_touch_scroll
from app.update_utils import (
    get_base_dir, get_exe_name, validate_zip, stage_zip,
    write_updater_script, build_relaunch_command, list_spine_models,
    spine_model_display_names,
)
from qfluentwidgets.common.font import getFont, fontStyleSheet


SCALES = [100, 125, 150, 200]


def _show_tip(parent, title, content, level="info"):
    factory = {
        "success": InfoBar.success,
        "warning": InfoBar.warning,
        "error": InfoBar.error,
    }.get(level, InfoBar.info)
    bar = factory(
        title=title, content=content,
        duration=2500, position=InfoBarPosition.TOP_RIGHT,
        parent=parent.window(),
    )
    bar.titleLabel.setStyleSheet(fontStyleSheet(getFont(14)))
    bar.contentLabel.setStyleSheet(fontStyleSheet(getFont(14)))


class ScaleCard(SettingCard):
    def __init__(self, parent=None):
        super().__init__(FIF.ZOOM, "缩放比例",
                        "调整界面元素的缩放大小", parent)
        self.combo = ComboBox(self)
        self.combo.addItems([f"{s}%" for s in SCALES])
        settings = QSettings("AronaAI", "AronaAI")
        saved = int(settings.value("scale", 100))
        if saved not in SCALES:
            saved = 100
        self.combo.setCurrentIndex(SCALES.index(saved))
        self.combo.currentIndexChanged.connect(self._on_changed)
        self.hBoxLayout.addWidget(self.combo, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def _on_changed(self, index):
        percent = SCALES[index]
        QSettings("AronaAI", "AronaAI").setValue("scale", percent)
        w = MessageBox("重启应用", "缩放比例将在应用重启后生效，是否立即重启？", self.window())
        w.yesButton.setText("立即重启")
        w.cancelButton.setText("稍后")
        if w.exec():
            if getattr(sys, "frozen", False):
                args = sys.argv[1:]
            else:
                args = sys.argv
            QProcess.startDetached(sys.executable, args)
            QApplication.instance()._restarting = True
            QTimer.singleShot(500, QApplication.instance().exit)


OPTIONS = [("ask", "每次询问"), ("exit", "退出程序"), ("tray", "最小化到系统托盘")]


class SpineZoomCard(SettingCard):
    """SpinBox for the model zoom percentage."""

    def __init__(self, configItem, icon, title, content=None, parent=None):
        super().__init__(icon, title, content, parent)
        self.configItem = configItem
        self.spin = SpinBox(self)
        self.spin.setRange(1, 10000)
        self.spin.setSuffix("%")
        self.spin.setValue(configItem.value)
        self.spin.valueChanged.connect(self._on_changed)
        self.hBoxLayout.addStretch(1)
        self.hBoxLayout.addWidget(self.spin, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        configItem.valueChanged.connect(self._on_config_changed)

    def _on_changed(self, value):
        qconfig.set(self.configItem, value)

    def _on_config_changed(self, value):
        if self.spin.value() != int(value):
            self.spin.blockSignals(True)
            self.spin.setValue(int(value))
            self.spin.blockSignals(False)


class CloseBehaviorCard(ExpandSettingCard):
    def __init__(self, parent=None):
        super().__init__(FIF.CANCEL, "关闭按钮行为",
                        "点击关闭按钮时", parent)
        self.choiceLabel = BodyLabel(self)
        self.choiceLabel.setObjectName("titleLabel")
        self.addWidget(self.choiceLabel)

        self.viewLayout.setSpacing(19)
        self.viewLayout.setContentsMargins(48, 18, 0, 18)
        for value, text in OPTIONS:
            btn = RadioButton(text, self.view)
            btn.setProperty("value", value)
            self.viewLayout.addWidget(btn)
            btn.clicked.connect(self._on_clicked)

        self._adjustViewSize()
        self._update_label()

    def _on_clicked(self):
        btn = self.sender()
        if btn.text() == self.choiceLabel.text():
            return
        set_close_behavior(btn.property("value"))
        self.choiceLabel.setText(btn.text())
        self.choiceLabel.adjustSize()

    def _update_label(self):
        value = get_close_behavior()
        for btn in self.findChildren(RadioButton):
            if btn.property("value") == value:
                self.choiceLabel.setText(btn.text())
                self.choiceLabel.adjustSize()
                btn.setChecked(True)
                break


class _SwitchRow(QWidget):
    """A labeled switch row used inside expandable cards."""

    def __init__(self, title, configItem, parent=None):
        super().__init__(parent)
        self.configItem = configItem
        self.setObjectName("switchRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 16, 0)
        layout.setSpacing(12)
        self.label = BodyLabel(title, self)
        self.label.setObjectName("modeSwitchLabel")
        layout.addWidget(self.label, 1)
        self.switch = SwitchButton(self, IndicatorPosition.RIGHT)
        self.switch.setOnText("开")
        self.switch.setOffText("关")
        self.switch.setChecked(qconfig.get(configItem))
        self.switch.checkedChanged.connect(self._onChanged)
        layout.addWidget(self.switch)
        configItem.valueChanged.connect(self._onConfigChanged)

    def _onChanged(self, checked):
        qconfig.set(self.configItem, checked)

    def _onConfigChanged(self, value):
        if self.switch.isChecked() != bool(value):
            self.switch.blockSignals(True)
            self.switch.setChecked(bool(value))
            self.switch.blockSignals(False)


class SwitchExpandSettingCard(ExpandSettingCard):
    """Expandable card with a master switch in the header and sub-switches inside."""

    def __init__(self, icon, title, content, configItem, subRows, parent=None):
        super().__init__(icon, title, content, parent)
        self.configItem = configItem
        self.switchButton = SwitchButton(self, IndicatorPosition.RIGHT)
        self.switchButton.setOnText("开")
        self.switchButton.setOffText("关")
        self.switchButton.setChecked(qconfig.get(configItem))
        self.switchButton.checkedChanged.connect(self._onSwitchChanged)
        self.addWidget(self.switchButton)

        self.viewLayout.setContentsMargins(48, 18, 0, 18)
        self.viewLayout.setSpacing(19)
        self.rows = []
        for label, item in subRows:
            row = _SwitchRow(label, item, self.view)
            self.viewLayout.addWidget(row)
            self.rows.append(row)
        self._updateRowsEnabled()
        self._adjustViewSize()

    def _onSwitchChanged(self, checked):
        qconfig.set(self.configItem, checked)
        self._updateRowsEnabled()

    def _updateRowsEnabled(self):
        enabled = qconfig.get(self.configItem)
        for row in self.rows:
            row.setEnabled(enabled)


class LocalizedSwitchSettingCard(SwitchSettingCard):
    """SwitchSettingCard that keeps the localized on/off text.

    Upstream SwitchSettingCard.setValue resets the switch label to tr('On')/
    tr('Off') on every toggle, wiping our setOnText/setOffText. Override it so
    the Chinese text stays.
    """

    def setValue(self, isChecked: bool):
        if self.configItem:
            qconfig.set(self.configItem, isChecked)
        self.switchButton.setChecked(isChecked)


class ModelFetchWorker(QThread):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, base_url, api_key, parent=None):
        super().__init__(parent)
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    def run(self):
        import urllib.request
        import urllib.error
        try:
            url = f"{self._base_url}/models"
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            models = [m["id"] for m in data.get("data", [])]
            models.sort()
            self.finished.emit(models)
        except urllib.error.HTTPError as e:
            self.error.emit(f"HTTP {e.code}")
        except Exception as e:
            self.error.emit(str(e))


class AISettingsCard(ExpandSettingCard):
    def __init__(self, parent=None):
        super().__init__(FIF.ROBOT, "API Key 设置",
                         "配置 API 地址、密钥和模型", parent)
        self.viewLayout.setContentsMargins(48, 18, 20, 18)
        self.viewLayout.setSpacing(12)

        self._base_url_input = LineEdit()
        self._base_url_input.setPlaceholderText("https://api.openai.com/v1")
        self._base_url_input.setMinimumWidth(300)

        self._api_key_input = LineEdit()
        self._api_key_input.setPlaceholderText("sk-...")
        self._api_key_input.setEchoMode(LineEdit.EchoMode.Password)
        self._api_key_input.setMinimumWidth(300)

        self._eye_btn = TransparentToolButton(FIF.VIEW)
        self._eye_btn.setCheckable(True)
        self._eye_btn.setFixedSize(29, 25)
        self._eye_btn.toggled.connect(self._toggle_api_key_visibility)
        self._api_key_input.hBoxLayout.addWidget(self._eye_btn, 0, Qt.AlignmentFlag.AlignRight)
        self._api_key_input.setTextMargins(0, 0, 30, 0)

        self._model_input = ComboBox()
        self._model_input.setMinimumWidth(300)
        self._model_input.setPlaceholderText("点击右侧按钮加载模型列表")

        self._refresh_btn = TransparentToolButton(FIF.SYNC)
        self._refresh_btn.setFixedSize(29, 25)
        self._refresh_btn.clicked.connect(self._fetch_models)

        model_row = QWidget()
        model_row_layout = QHBoxLayout(model_row)
        model_row_layout.setContentsMargins(0, 0, 0, 0)
        model_row_layout.setSpacing(4)
        model_row_layout.addWidget(self._model_input, 1)
        model_row_layout.addWidget(self._refresh_btn)

        self._save_btn = PushButton("保存", self)
        self._save_btn.clicked.connect(self._on_save)

        self._label_base_url = BodyLabel("Base URL:")
        self._label_api_key = BodyLabel("API Key:")
        self._label_model = BodyLabel("模型:")
        self._field_labels = [self._label_base_url, self._label_api_key, self._label_model]

        form = QFormLayout()
        form.setSpacing(10)
        form.addRow(self._label_base_url, self._base_url_input)
        form.addRow(self._label_api_key, self._api_key_input)
        form.addRow(self._label_model, model_row)
        form.addRow("", self._save_btn)
        self.viewLayout.addLayout(form)

        self._load()
        self._adjustViewSize()

    def _load(self):
        cfg = get_ai_settings()
        self._api_key_input.setText(cfg["api_key"])
        self._base_url_input.setText(cfg["base_url"])
        saved_model = cfg["model"]
        if saved_model:
            self._model_input.addItem(saved_model)
            self._model_input.setCurrentText(saved_model)

    def _on_save(self):
        set_ai_settings(
            self._api_key_input.text().strip(),
            self._base_url_input.text().strip() or "https://api.openai.com/v1",
            self._model_input.currentText().strip() or "gpt-4o-mini",
        )
        _show_tip(self, "API Key 设置", "保存成功", level="success")

    def _toggle_api_key_visibility(self, checked):
        if checked:
            self._api_key_input.setEchoMode(LineEdit.EchoMode.Normal)
            self._eye_btn.setIcon(FIF.VIEW)
        else:
            self._api_key_input.setEchoMode(LineEdit.EchoMode.Password)
            self._eye_btn.setIcon(FIF.VIEW)

    def _fetch_models(self):
        base_url = self._base_url_input.text().strip()
        api_key = self._api_key_input.text().strip()
        if not base_url or not api_key:
            _show_tip(self, "刷新模型", "请先填写 Base URL 和 API Key", level="warning")
            return
        self._refresh_btn.setEnabled(False)
        self._worker = ModelFetchWorker(base_url, api_key)
        self._worker.finished.connect(self._on_fetch_done)
        self._worker.error.connect(self._on_fetch_error)
        self._worker.start()

    def _on_fetch_done(self, models):
        self._refresh_btn.setEnabled(True)
        if not models:
            _show_tip(self, "刷新模型", "未找到可用模型", level="warning")
            return
        saved = self._model_input.currentText().strip()
        self._model_input.clear()
        self._model_input.addItems(models)
        if saved and saved not in models:
            self._model_input.addItem(saved)
        if saved:
            self._model_input.setCurrentText(saved)
        _show_tip(self, "刷新模型", f"已加载 {len(models)} 个模型", level="success")

    def _on_fetch_error(self, msg):
        self._refresh_btn.setEnabled(True)
        _show_tip(self, "刷新模型", f"获取模型列表失败: {msg}", level="error")


class ListEditDialog(MessageBoxBase):
    """Small editor dialog with one name per line."""

    def __init__(self, title, hint, entries, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)

        title_label = BodyLabel(title, self)
        title_label.setFont(getFont(16))
        self.viewLayout.addWidget(title_label)

        tip = BodyLabel(hint, self)
        tip.setWordWrap(True)
        self.viewLayout.addWidget(tip)

        self._edit = TextEdit()
        self._edit.setPlainText("\n".join(entries))
        self._edit.setFixedSize(460, 260)
        self.viewLayout.addWidget(self._edit)

        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")

    def resultEntries(self):
        lines = self._edit.toPlainText().splitlines()
        return [line.strip() for line in lines if line.strip()]


class ListSettingCard(SettingCard):
    """Card that edits a list config item through a dialog."""

    def __init__(self, icon, title, content, configItem, dialogTitle, hint, parent=None):
        super().__init__(icon, title, content, parent)
        self._configItem = configItem
        self._dialogTitle = dialogTitle
        self._hint = hint
        self._editBtn = PushButton("", self)
        self._editBtn.clicked.connect(self._onEdit)
        self.hBoxLayout.addWidget(self._editBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self._updateBtn()
        configItem.valueChanged.connect(self._onConfigChanged)

    def _onConfigChanged(self, value):
        self._updateBtn()

    def _updateBtn(self):
        self._editBtn.setText("编辑")

    def _onEdit(self):
        dlg = ListEditDialog(
            self._dialogTitle, self._hint,
            qconfig.get(self._configItem), self.window())
        if dlg.exec():
            qconfig.set(self._configItem, dlg.resultEntries())


class UpdateCheckCard(ExpandSettingCard):
    updateReady = Signal(str)

    def __init__(self, parent=None):
        super().__init__(FIF.UPDATE, "更新", "检查并安装最新版本", parent)
        self._settings = QSettings("AronaAI", "Settings")
        self._isInitializing = True
        self._isManualCheck = True
        self._latestVersion = ""
        self._downloadUrl = ""
        self._downloadAssetUrl = ""

        self._autoCheckTimer = QTimer(self)
        self._autoCheckTimer.setInterval(7200000)
        self._autoCheckTimer.timeout.connect(self._onAutoCheckTimer)

        self._setupUi()
        self._loadSettings()
        self._isInitializing = False

    def _setupUi(self):
        self.viewLayout.setContentsMargins(48, 18, 20, 18)
        self.viewLayout.setSpacing(12)

        self._updateBtn = PushButton("检查更新", self)
        self._updateBtn.setFixedWidth(130)
        self._updateBtn.clicked.connect(lambda: self._onCheckUpdateClicked(manual=True))
        self.addWidget(self._updateBtn)

        prerelease_row = QWidget(self.view)
        prerelease_layout = QHBoxLayout(prerelease_row)
        prerelease_layout.setContentsMargins(0, 0, 0, 0)
        prerelease_layout.setSpacing(12)
        prerelease_label = BodyLabel("检查更新包含非正式版", prerelease_row)
        prerelease_label.setObjectName("update-item-label")
        self.includePrereleaseSwitch = SwitchButton(self.view)
        self.includePrereleaseSwitch.setOnText("开")
        self.includePrereleaseSwitch.setOffText("关")
        self.includePrereleaseSwitch.checkedChanged.connect(self._onIncludePrereleaseToggled)
        prerelease_layout.addWidget(prerelease_label, 1)
        prerelease_layout.addWidget(self.includePrereleaseSwitch)
        self.viewLayout.addWidget(prerelease_row)

        self._adjustViewSize()

    def _loadSettings(self):
        self.includePrereleaseSwitch.setChecked(self._settings.value("includePrerelease", False, type=bool))
        self._autoCheckTimer.start()
        QTimer.singleShot(1000, self._onAutoCheckTimer)

    def _onAutoCheckTimer(self):
        self._onCheckUpdateClicked(manual=False)

    def _onIncludePrereleaseToggled(self, checked):
        if self._isInitializing:
            return
        self._settings.setValue("includePrerelease", checked)

    def _onCheckUpdateClicked(self, manual=True):
        self._isManualCheck = manual

        self._updateBtn.setEnabled(False)
        if self._isManualCheck:
            _show_tip(self, "检查更新", "正在检查更新…")

        self._nam = QNetworkAccessManager(self)
        url = QUrl(f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=50")
        req = QNetworkRequest(url)
        req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "AronaAI")
        self._reply = self._nam.get(req)
        self._reply.finished.connect(self._onUpdateReplyFinished)

    def _parseVersion(self, tag):
        match = re.search(r'([vV]|dev)[._]?(\d+\.\d+\.\d+(?:\.\d+)?)', tag)
        if match:
            prefix = match.group(1).lower()
            version = match.group(2)
            return prefix + "." + version
        return tag

    def _onUpdateReplyFinished(self):
        self._updateBtn.setEnabled(True)
        self._updateBtn.setText("检查更新")

        if self._reply.error() != QNetworkReply.NetworkError.NoError:
            if self._isManualCheck:
                _show_tip(self, "检查更新", "检查失败，请检查网络连接后重试", level="error")
            return

        try:
            data = json.loads(self._reply.readAll().data().decode('utf-8'))
            if isinstance(data, dict):
                data = [data]

            include_prerelease = self.includePrereleaseSwitch.isChecked()
            latest_version = ""
            download_url = ""
            download_asset_url = ""
            for rel in data:
                version = self._parseVersion(rel.get('tag_name', ''))
                if version.startswith('dev.') and not include_prerelease:
                    continue
                latest_version = version
                download_url = rel.get('html_url', '')
                if rel.get('assets'):
                    download_asset_url = rel['assets'][0].get('browser_download_url', '')
                break

            if not latest_version:
                if self._isManualCheck:
                    _show_tip(self, "检查更新", "未找到发布版本", level="warning")
                return

            if self._compareVersions(CURRENT_VERSION, latest_version) >= 0:
                if self._isManualCheck:
                    _show_tip(self, "检查更新", "当前已是最新版本", level="success")
                return

            self._latestVersion = latest_version
            self._downloadUrl = download_url
            self._downloadAssetUrl = download_asset_url
            self._onDownloadClicked()
        except Exception:
            if self._isManualCheck:
                _show_tip(self, "检查更新", "检查更新时出错", level="error")
            return

    def _onDownloadClicked(self):
        url = self._downloadAssetUrl or self._downloadUrl
        if not url:
            if self._isManualCheck:
                _show_tip(self, "检查更新", "未找到下载链接", level="error")
            return

        if self._isManualCheck:
            _show_tip(self, "检查更新", f"发现新版本: {self._latestVersion} 正在下载…")

        self._dl_nam = QNetworkAccessManager(self)
        req = QNetworkRequest(QUrl(url))
        req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        self._dl_reply = self._dl_nam.get(req)
        self._dl_reply.finished.connect(self._onDownloadFinished)

        ext = ".zip" if self._downloadAssetUrl else ".html"
        update_dir = get_base_dir() / "Update"
        update_dir.mkdir(parents=True, exist_ok=True)
        self._dl_path = update_dir / f"AronaAI_update_{self._latestVersion}{ext}"
        self._dl_file = open(self._dl_path, 'wb')

        self._dl_reply.readyRead.connect(self._onDownloadReadyRead)

    def _onDownloadReadyRead(self):
        if hasattr(self, '_dl_file') and self._dl_file and self._dl_reply:
            self._dl_file.write(self._dl_reply.readAll().data())

    def _onDownloadFinished(self):
        if hasattr(self, '_dl_file') and self._dl_file:
            self._dl_file.close()
            self._dl_file = None

        if self._dl_reply.error() != QNetworkReply.NetworkError.NoError:
            return

        if self._isManualCheck:
            _show_tip(self, "检查更新", f"下载完成: {Path(self._dl_path).name}", level="success")

        if Path(self._dl_path).suffix.lower() == ".zip":
            self.updateReady.emit(self._latestVersion)

    def apply_update(self):
        """Stage the downloaded update and restart the app on demand."""
        self._isManualCheck = True
        self._applyUpdate()

    def _applyUpdate(self):
        """Validate, stage, spawn the external updater, then quit the app."""
        zip_path = Path(self._dl_path)
        version = self._latestVersion

        ok, _ = validate_zip(zip_path)
        if not ok:
            if self._isManualCheck:
                _show_tip(self, "检查更新", f"更新包无效: {zip_path.name}", level="error")
            return

        try:
            staging = stage_zip(zip_path, version)
        except Exception:
            if self._isManualCheck:
                _show_tip(self, "检查更新", "解压升级包失败", level="error")
            return

        try:
            script = write_updater_script(
                staging=staging,
                install_dir=get_base_dir(),
                exe_name=get_exe_name(),
                relaunch_cmd=build_relaunch_command(),
                main_pid=QApplication.instance().applicationPid(),
            )
        except Exception:
            if self._isManualCheck:
                _show_tip(self, "检查更新", "生成更新脚本失败", level="error")
            return

        args = ["-NoProfile", "-ExecutionPolicy", "Bypass",
                "-WindowStyle", "Hidden", "-File", str(script)]
        if not QProcess.startDetached("powershell.exe", args):
            if self._isManualCheck:
                _show_tip(self, "检查更新", "启动更新器失败", level="error")
            return

        if self._isManualCheck:
            _show_tip(self, "检查更新", "更新完成，正在重启…", level="success")
        app = QApplication.instance()
        if app:
            app._restarting = True
            QTimer.singleShot(500, app.exit)

    def _compareVersions(self, current, latest):
        def normalize(v):
            v = re.sub(r'^(dev|v)', '', v)
            parts = re.split(r'[.\-_]', v)
            return [int(p) if p.isdigit() else 0 for p in parts[:4]] + [0] * (4 - len(parts))

        current_parts = normalize(current)
        latest_parts = normalize(latest)

        for c, l in zip(current_parts, latest_parts):
            if c < l:
                return -1
            elif c > l:
                return 1
        return 0


class SettingsPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("settingsPage")
        self._setupUi()
        qconfig.themeChanged.connect(self._onThemeChanged)
        self._updateBgCardEnabled()

    def _updateBgCardEnabled(self):
        self._bg_card.setEnabled(qconfig.get(qconfig.themeMode) != MOMOTALK)

    def _on_autostart_toggled(self, checked):
        set_autostart_enabled(checked)
        if checked:
            _show_tip(self, "开机自启", "已开启开机自启，重启电脑后生效", level="success")
        else:
            _show_tip(self, "开机自启", "已关闭开机自启")

    def _onThemeChanged(self):
        self._updateBgCardEnabled()
        is_dark = qconfig.theme == Theme.DARK
        fg = "#ffffff" if is_dark else "#000000"
        sec = "rgba(255,255,255,0.6)" if is_dark else "rgba(0,0,0,0.6)"
        status_green = "#6fbf73" if is_dark else "#107C10"
        self._updateTitle.setFont(getFont(18))
        self._updateTitle.setTextColor(QColor(fg), QColor(fg))
        for card in (self._theme_card.card, self._scale_card, self._close_card.card,
                     self._bg_card.card, self._autostart_card, self._tray_card.card,
                     self._spine_visible_card.card, self._spine_model_card.card,
                     self._voice_card.card, self._spine_zoom_card,
                     self._top_rule_card.card, self._top_white_card, self._top_black_card,
                     self._ai_card.card, self._updateCard.card):
            card.titleLabel.setStyleSheet(fontStyleSheet(getFont(16)) + f"; color: {fg};")
            card.contentLabel.setStyleSheet(fontStyleSheet(getFont(14)) + f"; color: {sec};")
        for btn in self._theme_card.buttonGroup.buttons():
            btn.setStyleSheet(fontStyleSheet(getFont(14)) + f"; color: {fg};")
        for btn in self._close_card.findChildren(RadioButton):
            btn.setStyleSheet(fontStyleSheet(getFont(14)) + f"; color: {fg};")
        for label in self.findChildren(QLabel, "modeSwitchLabel"):
            label.setStyleSheet(fontStyleSheet(getFont(14)) + f"; color: {fg};")
        for group in self.findChildren(SettingCardGroup):
            group.titleLabel.setStyleSheet(fontStyleSheet(getFont(18)) + f"; color: {fg};")
        for label in self._updateCard.findChildren(QLabel, "update-item-label"):
            label.setStyleSheet(fontStyleSheet(getFont(14)) + f"; color: {sec};")
        for label in self._updateCard.findChildren(QLabel, "update-status-label"):
            label.setStyleSheet(fontStyleSheet(getFont(14)) + f"; color: {status_green};")
        if hasattr(self, '_ai_card'):
            for lbl in self._ai_card._field_labels:
                lbl.setStyleSheet(fontStyleSheet(getFont(14)) + f"; color: {fg};")

    def _setupUi(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("ScrollArea { background: transparent; border: none; }")

        content = QWidget()
        content.setStyleSheet("QWidget { background: transparent; }")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        self._theme_card = OptionsSettingCard(
            qconfig.themeMode,
            FIF.BRIGHTNESS,
            "主题模式",
            "切换浅色、深色或 MomoTalk 主题",
            texts=["浅色", "深色", "跟随系统", "MomoTalk"],
        )
        self._scale_card = ScaleCard()
        self._close_card = CloseBehaviorCard()
        self._bg_card = OptionsSettingCard(
            qconfig.backgroundEffect,
            FIF.ALBUM,
            "窗口背景效果",
            "选择窗口的背景模糊效果",
            texts=["云母", "云母增强", "亚克力"],
        )
        self._autostart_card = LocalizedSwitchSettingCard(
            FIF.POWER_BUTTON,
            "开机自启",
            "开机后自动启动并收纳入系统托盘",
        )
        self._autostart_card.switchButton.setOnText("开")
        self._autostart_card.switchButton.setOffText("关")
        self._autostart_card.blockSignals(True)
        self._autostart_card.setChecked(is_autostart_enabled())
        self._autostart_card.blockSignals(False)
        self._autostart_card.checkedChanged.connect(self._on_autostart_toggled)
        self._tray_card = ExpandSettingCard(
            FIF.EMBED,
            "启动后收进系统托盘",
            "自定义不同启动方式收进系统托盘的行为",
        )
        self._tray_card.viewLayout.setContentsMargins(48, 18, 0, 18)
        self._tray_card.viewLayout.setSpacing(19)
        self._tray_rows = [
            _SwitchRow("开机自启时", qconfig.startToTray, self._tray_card.view),
            _SwitchRow("手动启动时", qconfig.manualStartToTray, self._tray_card.view),
        ]
        for row in self._tray_rows:
            self._tray_card.viewLayout.addWidget(row)
        self._tray_card._adjustViewSize()

        self._spine_visible_card = SwitchExpandSettingCard(
            FIF.EMBED,
            "显示桌面模型",
            "在桌面显示 Spine 模型",
            qconfig.spineVisible,
            [
                ("开机自启时", qconfig.spineVisibleAutostart),
                ("手动启动时", qconfig.spineVisibleManual),
            ],
        )
        models = list_spine_models()
        display_names = spine_model_display_names()
        self._spine_model_card = OptionsSettingCard(
            qconfig.spineModel,
            FIF.ROBOT,
            "桌面模型",
            "选择显示哪个模型",
            texts=[display_names.get(m, m.capitalize()) for m in models],
        )
        self._spine_zoom_card = SpineZoomCard(
            qconfig.spineZoom,
            FIF.ZOOM,
            "模型缩放",
            "输入数值调整模型显示大小，35% 为原始大小",
        )
        self._voice_card = OptionsSettingCard(
            qconfig.voiceLang,
            FIF.VOLUME,
            "配音",
            "选择桌面模型的配音语言",
            texts=["中配", "日配"],
        )
        self._top_rule_card = OptionsSettingCard(
            qconfig.spineTopRule,
            FIF.ROBOT,
            "置顶规则",
            "选择桌面模型在窗口全屏或最大化时的置顶行为",
            texts=["始终置顶", "全屏时不置顶", "最大化时不置顶", "始终置底"],
        )
        self._top_white_card = ListSettingCard(
            FIF.PIN,
            "置顶白名单",
            "白名单中的窗口为前台窗口时，模型始终置顶并盖过该窗口",
            qconfig.spineTopWhiteList,
            "置顶白名单",
            "请填写进程名",
        )
        self._top_black_card = ListSettingCard(
            FIF.UNPIN,
            "置顶黑名单",
            "黑名单中的窗口为前台窗口时，模型始终沉到该窗口之下",
            qconfig.spineTopBlackList,
            "置顶黑名单",
            "请填写进程名",
        )
        appearance_group = SettingCardGroup("外观", content)
        appearance_group.addSettingCard(self._theme_card)
        appearance_group.addSettingCard(self._bg_card)
        appearance_group.addSettingCard(self._scale_card)
        layout.addWidget(appearance_group)

        spine_group = SettingCardGroup("桌面模型", content)
        spine_group.addSettingCard(self._spine_visible_card)
        spine_group.addSettingCard(self._spine_model_card)
        spine_group.addSettingCard(self._voice_card)
        spine_group.addSettingCard(self._spine_zoom_card)
        layout.addWidget(spine_group)

        top_group = SettingCardGroup("置顶规则", content)
        top_group.addSettingCard(self._top_rule_card)
        top_group.addSettingCard(self._top_white_card)
        top_group.addSettingCard(self._top_black_card)
        layout.addWidget(top_group)

        launch_group = SettingCardGroup("启动与关闭", content)
        launch_group.addSettingCard(self._autostart_card)
        launch_group.addSettingCard(self._tray_card)
        launch_group.addSettingCard(self._close_card)
        layout.addWidget(launch_group)

        ai_group = SettingCardGroup("API Key 设置", content)
        self._ai_card = AISettingsCard(content)
        ai_group.addSettingCard(self._ai_card)
        layout.addWidget(ai_group)

        self._updateTitle = BodyLabel("更新", content)
        layout.addWidget(self._updateTitle)

        self._updateCard = UpdateCheckCard(content)
        layout.addWidget(self._updateCard)

        layout.addStretch()

        scroll.setWidget(content)
        enable_touch_scroll(scroll)
        outer.addWidget(scroll, 1)

        self._onThemeChanged()
