import ctypes
import sys

from PySide6.QtCore import (
    QProcess, Qt,
)
from PySide6.QtGui import QIcon, QColor, QCursor
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QDialog, QWidget
from qfluentwidgets import (
    MSFluentWindow, NavigationItemPosition, FluentIcon as FIF,
    qconfig, FluentStyleSheet, MessageBoxBase, BodyLabel,
    RadioButton, CheckBox, isDarkTheme, Action, RoundMenu, PrimaryPushButton
)
from qfluentwidgets.common.style_sheet import setThemeColor
from qfluentwidgets.common.font import getFont, fontStyleSheet
from qfluentwidgets.components.navigation.navigation_bar import NavigationBarPushButton
import qfluentwidgets.components.navigation.navigation_bar as _nav_bar_module
import qfluentwidgets.components.navigation.navigation_widget as _nav_widget_module
from qfluentwidgets.components.navigation.navigation_widget import NavigationWidget
from qfluentwidgets.common.icon import FluentIconBase
from qfluentwidgets import Theme

from App.config import (
    get_close_behavior, set_close_behavior, get_last_choice, set_last_choice,
    MOMOTALK, MOMO_TITLEBAR_COLOR, MOMO_NAV_COLOR, MOMO_CONTENT_COLOR,
    get_accent_color,
)
from App.update_utils import get_assets_dir, supports_backdrop
from App.pages.home_page import HomePage
from App.pages.chat_page import ChatPage
from App.pages.schedule_page import SchedulePage
from App.pages.settings_page import SettingsPage
from App.pages.about_page import AboutDialog
from App.pages.spine_window import SpineWindow


_ORIG_NAV_BAR_IS_DARK = _nav_bar_module.isDarkTheme
_ORIG_NAV_WIDGET_IS_DARK = _nav_widget_module.isDarkTheme


def _force_dark_nav():
    return True


class CloseDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.titleLabel = BodyLabel("关闭主窗口", self.widget)
        self.titleLabel.setFont(getFont(20))
        self.exitRadio = RadioButton("退出程序", self.widget)
        self.trayRadio = RadioButton("最小化到系统托盘", self.widget)
        self.dontAskCheck = CheckBox("不再询问", self.widget)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.trayRadio)
        self.viewLayout.addWidget(self.exitRadio)
        self.viewLayout.addSpacing(8)
        self.viewLayout.addWidget(self.dontAskCheck)

        self.yesButton.setText("确认")
        self.cancelButton.setText("取消")

        self.widget.setMinimumWidth(320)
        self._restore_default()

    def _restore_default(self):
        last = get_last_choice()
        if last == "exit":
            self.exitRadio.setChecked(True)
        else:
            self.trayRadio.setChecked(True)

    def getResult(self):
        if self.exitRadio.isChecked():
            return "exit"
        return "tray"


class MainWindow(MSFluentWindow):
    def __init__(self):
        super().__init__()
        self.home = HomePage()
        self.chat = ChatPage()
        self.schedule = SchedulePage()
        self.settings = SettingsPage()

        self._setup_update_ready_button()
        self._add_pages()
        self.setWindowTitle("AronaAI")
        self.resize(960, 640)
        self._default_size = self.size()
        self._size_applied = False

        qconfig.themeChanged.connect(self._on_theme_changed)
        try:
            qconfig.themeChangedFinished.disconnect(self._onThemeChangedFinished)
        except (TypeError, RuntimeError):
            pass
        qconfig.backgroundEffect.valueChanged.connect(self._apply_background_effect)
        self._setup_tray()
        QApplication.instance().aboutToQuit.connect(self._remove_tray)
        self._adjust_nav_font()
        self.titleBar.titleLabel.setStyleSheet(fontStyleSheet(getFont(14)))
        self._apply_theme_chrome()
        setThemeColor(get_accent_color(), save=False)
        self._apply_background_effect()
        self._setup_spine_window()

    def _setup_spine_window(self):
        self.spineWindow = SpineWindow()
        self.spineWindow.hide()
        self.spineWindow.visibilityChangedSignal.connect(self._on_spine_visibility)
        self._connect_tts_progress()

    def _connect_tts_progress(self):
        """把两个 TTS 引擎的下载进度都接到设置页的进度条上。

        对话页和桌面模型各有一个引擎，但下载是全局的一次性事件，
        所以共用设置页里的同一根进度条。
        """
        slot = self.settings.on_tts_download_progress
        for owner in (self.chat, self.spineWindow):
            engine = getattr(owner, "_tts_engine", None)
            if engine is None:
                continue
            try:
                engine.downloadProgress.connect(slot)
            except (AttributeError, RuntimeError, TypeError):
                pass

    def _setup_update_ready_button(self):
        self._updateReadyBtn = PrimaryPushButton("更新", self)
        self._updateReadyBtn.setFixedSize(84, 30)
        self._updateReadyBtn.setFont(getFont(14))
        self._updateReadyBtn.setToolTip("下载完成，点击以安装更新并重启")
        self._updateReadyBtn.hide()

        layout = self.titleBar.hBoxLayout
        idx = layout.indexOf(self.titleBar.vBoxLayout)
        layout.insertWidget(idx, self._updateReadyBtn, 0, Qt.AlignRight | Qt.AlignVCenter)

        self.settings._updateCard.updateReady.connect(self._on_update_ready)
        self._updateReadyBtn.clicked.connect(self._on_update_ready_clicked)

    def _on_update_ready(self, version):
        self._updateReadyBtn.setToolTip(f"版本 {version} 已就绪，点击以安装更新并重启")
        self._updateReadyBtn.show()
        self._updateReadyBtn.raise_()

    def _on_update_ready_clicked(self):
        self.settings._updateCard.apply_update()

    def _on_spine_visibility(self, visible):
        self.spineToggleAction.setText("隐藏模型" if visible else "显示模型")
        qconfig.set(qconfig.spineVisible, visible, save=False)

    def _toggle_spine_window(self):
        if self.spineWindow.isVisible():
            self.spineWindow.hide()
        else:
            self.spineWindow.show()

    def _apply_background_effect(self, value=None):
        mode = qconfig.get(qconfig.backgroundEffect)
        hwnd = int(self.winId())
        if sys.platform != "win32":
            return

        is_momo = qconfig.get(qconfig.themeMode) == MOMOTALK

        if not supports_backdrop():
            self._isMicaEnabled = False
            self.windowEffect.removeBackgroundEffect(hwnd)
            self._set_nav_transparent(False)
            self._set_content_transparent(False)
            return

        self.setBackgroundColor(QColor(0, 0, 0, 0))
        self._set_content_transparent(True)
        self._isMicaEnabled = True
        self.windowEffect.removeBackgroundEffect(hwnd)
        self._set_system_backdrop(
            hwnd, {"mica": 2, "mica_alt": 4, "acrylic": 3}[mode])
        self._set_nav_transparent(not is_momo)

    def _set_content_transparent(self, transparent):
        """切换内容区（stackedWidget）的背景是否透明。

        qfluentwidgets 的默认 QSS 给 StackedWidget 铺了
        rgba(255,255,255,0.5) 的半透明白，只有 isTransparent=true 时才换成
        transparent。窗口整体透明后，这层白会糊在背景之上，看起来就是
        「整个界面发白」。改完属性必须 unpolish/polish，否则属性选择器
        不会重新求值。
        """
        w = self.stackedWidget
        if w.property("isTransparent") == transparent:
            return
        w.setProperty("isTransparent", transparent)
        w.style().unpolish(w)
        w.style().polish(w)
        w.update()

    def _set_system_backdrop(self, hwnd, kind):
        try:
            dwmapi = ctypes.WinDLL("dwmapi")
            dark = ctypes.c_int(1 if isDarkTheme() else 0)
            dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), 4)
            kind = ctypes.c_int(kind)
            dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(kind), 4)
        except Exception:
            pass

    def _set_nav_transparent(self, transparent):
        nav = self.navigationInterface
        rule = "\nNavigationBar { background: transparent; }"
        if transparent:
            if rule not in nav.styleSheet():
                nav.setStyleSheet(nav.styleSheet() + rule)
        else:
            ss = nav.styleSheet().replace(rule, "")
            if ss != nav.styleSheet():
                nav.setStyleSheet(ss)

    def showEvent(self, e):
        super().showEvent(e)
        if not self._size_applied:
            self._size_applied = True
            if self.size() != self._default_size:
                self.resize(self._default_size)
        self._apply_theme_chrome()
        self._apply_background_effect()

    def _apply_theme_chrome(self):
        is_momo = qconfig.get(qconfig.themeMode) == MOMOTALK
        if is_momo:
            _nav_bar_module.isDarkTheme = _force_dark_nav
            _nav_widget_module.isDarkTheme = _force_dark_nav
            if "#FA94A6" not in self.titleBar.styleSheet():
                self.titleBar.setStyleSheet(
                    self.titleBar.styleSheet()
                    + f"\nMSFluentTitleBar {{ background-color: {MOMO_TITLEBAR_COLOR}; "
                    f"border-top-left-radius: 8px; border-top-right-radius: 8px; }}"
                    "\nFluentTitleBar>QLabel#titleLabel { color: #FFFFFF; }"
                )
            self.titleBar.titleLabel.setStyleSheet(fontStyleSheet(getFont(14)))
            self._momo_btn_sheet = """
MinimizeButton, MaximizeButton {
    qproperty-normalColor: white;
    qproperty-hoverColor: white;
    qproperty-pressedColor: white;
    qproperty-normalBackgroundColor: transparent;
    qproperty-hoverBackgroundColor: rgba(0, 0, 0, 26);
    qproperty-pressedBackgroundColor: rgba(0, 0, 0, 51);
}
CloseButton {
    qproperty-normalColor: white;
    qproperty-hoverColor: white;
    qproperty-pressedColor: white;
    qproperty-normalBackgroundColor: transparent;
    qproperty-hoverBackgroundColor: rgb(232, 17, 35);
    qproperty-pressedBackgroundColor: rgb(241, 112, 122);
}
"""
            for btn in (self.titleBar.minBtn, self.titleBar.maxBtn, self.titleBar.closeBtn):
                btn.setStyleSheet(self._momo_btn_sheet)
            self._updateReadyBtn.setStyleSheet(self._momo_update_btn_qss())
            if not hasattr(self, "_momo_orig_icons"):
                self._momo_orig_icons = {}
            for item in self.navigationInterface.findChildren(NavigationWidget):
                icon = getattr(item, "_icon", None)
                if icon is None:
                    continue
                if item not in self._momo_orig_icons:
                    self._momo_orig_icons[item] = icon
                if isinstance(icon, FluentIconBase):
                    item._icon = icon.icon(Theme.DARK)
                item.lightSelectedColor = QColor(255, 255, 255)
                item.darkSelectedColor = QColor(255, 255, 255)
                item.lightIndicatorColor = QColor(255, 255, 255)
                item.darkIndicatorColor = QColor(255, 255, 255)
                item.update()
            self.navigationInterface.setSelectedColor(QColor(255, 255, 255), QColor(255, 255, 255))
            self.navigationInterface.indicator.setIndicatorColor(QColor(255, 255, 255), QColor(255, 255, 255))
            if "#4A5A70" not in self.navigationInterface.styleSheet():
                self.navigationInterface.setStyleSheet(
                    self.navigationInterface.styleSheet()
                    + f"\nNavigationBar {{ background-color: {MOMO_NAV_COLOR}; }}"
                )
            if "background-color: #FFFFFF" not in self.stackedWidget.styleSheet():
                self.stackedWidget.setStyleSheet(
                    self.stackedWidget.styleSheet()
                    + f"\nQStackedWidget {{ background-color: {MOMO_CONTENT_COLOR}; }}"
                )
        else:
            _nav_bar_module.isDarkTheme = _ORIG_NAV_BAR_IS_DARK
            _nav_widget_module.isDarkTheme = _ORIG_NAV_WIDGET_IS_DARK
            self.titleBar.titleLabel.setStyleSheet(fontStyleSheet(getFont(14)))
            for btn in (self.titleBar.minBtn, self.titleBar.maxBtn, self.titleBar.closeBtn):
                btn.setStyleSheet("")
            FluentStyleSheet.BUTTON.apply(self._updateReadyBtn)
            for item, icon in getattr(self, "_momo_orig_icons", {}).items():
                item._icon = icon
                item.lightSelectedColor = QColor()
                item.darkSelectedColor = QColor()
                item.lightIndicatorColor = QColor()
                item.darkIndicatorColor = QColor()
                item.update()
            self._momo_orig_icons = {}
            self.navigationInterface.setSelectedColor(QColor(), QColor())
            self.navigationInterface.indicator.setIndicatorColor(QColor(), QColor())
            self._updateStackedBackground()

        for widget in self.navigationInterface.findChildren(QWidget):
            widget.update()
        self.navigationInterface.update()
        self.titleBar.update()
        self.stackedWidget.update()

    def _adjust_nav_font(self):
        for btn in self.findChildren(NavigationBarPushButton):
            btn.setStyleSheet(fontStyleSheet(getFont(12)))

    def _momo_update_btn_qss(self):
        from qfluentwidgets.common.style_sheet import QssTemplate, ThemeColor
        base = FluentStyleSheet.BUTTON.content(
            Theme.LIGHT if not isDarkTheme() else Theme.DARK
        )
        color = QColor("#4A5A70")
        mapping = {
            ThemeColor.PRIMARY.value: color.name(),
            ThemeColor.LIGHT_1.value: color.lighter(120).name(),
            ThemeColor.LIGHT_2.value: color.lighter(140).name(),
            ThemeColor.LIGHT_3.value: color.lighter(160).name(),
            ThemeColor.DARK_1.value: color.darker(120).name(),
            ThemeColor.DARK_2.value: color.darker(140).name(),
            ThemeColor.DARK_3.value: color.darker(160).name(),
            "FontFamilies": ",".join([f"'{i}'" for i in qconfig.get(qconfig.fontFamilies)]),
        }
        return QssTemplate(base).safe_substitute(mapping)

    def _add_pages(self):
        self.addSubInterface(self.home, FIF.HOME, "主页", FIF.HOME_FILL)
        self.addSubInterface(self.chat, FIF.CHAT, "对话")
        self.addSubInterface(self.schedule, FIF.DATE_TIME, "日程")
        self.addSubInterface(self.settings, FIF.SETTING, "设置",
                             position=NavigationItemPosition.BOTTOM)
        self.navigationInterface.addItem(
            "about", FIF.INFO, "关于",
            onClick=self._show_about,
            selectable=False,
            position=NavigationItemPosition.BOTTOM,
        )

    def _on_theme_changed(self, theme):
        setThemeColor(get_accent_color(), save=False, lazy=True)
        qconfig.themeChangedFinished.emit()
        self._adjust_nav_font()
        self.titleBar.titleLabel.setStyleSheet(fontStyleSheet(getFont(14)))
        self._apply_theme_chrome()
        self._apply_background_effect()

    def _setup_tray(self):
        self.trayIcon = QSystemTrayIcon(
            QIcon(str(get_assets_dir() / "Logo" / "Logo.png")), self)
        self.trayIcon.setToolTip("AronaAI")

        self.trayMenu = RoundMenu(parent=self)
        showAction = Action(FIF.HOME, "显示窗口", self)
        showAction.triggered.connect(self._show_window)
        self.trayMenu.addAction(showAction)

        self.spineToggleAction = Action(FIF.HOME, "显示模型", self)
        self.spineToggleAction.triggered.connect(self._toggle_spine_window)
        self.trayMenu.addAction(self.spineToggleAction)

        self.trayMenu.addSeparator()
        restartAction = Action(FIF.SYNC, "重启", self)
        restartAction.triggered.connect(self._restart_app)
        self.trayMenu.addAction(restartAction)

        quitAction = Action(FIF.POWER_BUTTON, "退出", self)
        quitAction.triggered.connect(self._quit_app)
        self.trayMenu.addAction(quitAction)

        self.trayIcon.activated.connect(self._on_tray_activated)

    def _restart_app(self):
        """重启：拉起新进程，然后退出当前实例。

        命令行复用更新器那套：打包版重启 exe，源码运行重启 main.py，
        并保留 --autostart 这类启动参数。`_restarting` 标志让 closeEvent
        直接放行关闭，而不是被"最小化到托盘"的逻辑拦下。
        """
        try:
            from App.update_utils import build_relaunch_command
            cmd = build_relaunch_command()
        except Exception:
            return
        app = QApplication.instance()
        if app is None:
            return
        self.trayIcon.hide()
        # 先启动新进程，确认起来了才退出；启动失败就恢复托盘图标，
        # 免得用户落到"没窗口也没托盘、进程还活着"的境地
        if not QProcess.startDetached(cmd[0], cmd[1:]):
            self.trayIcon.show()
            return
        app._restarting = True
        app.exit(0)

    def _quit_app(self):
        self.trayIcon.hide()
        app = QApplication.instance()
        if app:
            app.exit(0)

    def _remove_tray(self):
        try:
            self.trayIcon.hide()
        except RuntimeError:
            pass

    def _show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _show_about(self):
        dlg = AboutDialog(self)
        dlg.exec()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_window()
        elif reason == QSystemTrayIcon.ActivationReason.Context:
            self.trayMenu.exec(QCursor.pos())

    def closeEvent(self, event):
        app = QApplication.instance()
        if app and getattr(app, '_restarting', False):
            event.accept()
            return

        behavior = get_close_behavior()

        if behavior == "exit":
            event.accept()
            return
        elif behavior == "tray":
            event.ignore()
            self.hide()
            self.trayIcon.show()
            self.trayIcon.showMessage("AronaAI", "已最小化到系统托盘",
                                      QSystemTrayIcon.MessageIcon.Information, 2000)
            return

        dialog = CloseDialog(self)
        ret = dialog.exec()

        if ret == QDialog.DialogCode.Accepted:
            choice = dialog.getResult()
            set_last_choice(choice)

            if dialog.dontAskCheck.isChecked():
                set_close_behavior(choice)

            if choice == "exit":
                event.accept()
            else:
                event.ignore()
                self.hide()
                self.trayIcon.show()
                self.trayIcon.showMessage("AronaAI", "已最小化到系统托盘",
                                          QSystemTrayIcon.MessageIcon.Information, 2000)
        else:
            event.ignore()
