"""主窗口."""

from qfluentwidgets import FluentWindow, FluentIcon

from app.ui.email_page import EmailPage
from app.ui.account_page import AccountPage
from app.ui.generate_page import GeneratePage
from app.ui.settings_page import SettingsPage


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Canva x Leonardo.ai")
        self.showMaximized()

        self.email_page = EmailPage(self)
        self.email_page.setObjectName("emailPage")
        self.account_page = AccountPage(self)
        self.account_page.setObjectName("accountPage")
        self.generate_page = GeneratePage(self)
        self.generate_page.setObjectName("generatePage")
        self.settings_page = SettingsPage(self)
        self.settings_page.setObjectName("settingsPage")

        self._init_navigation()

        self.generate_page.taskFinished.connect(self.account_page._refresh)

    def _init_navigation(self):
        self.addSubInterface(self.email_page, FluentIcon.MAIL, "邮箱管理")
        self.addSubInterface(self.account_page, FluentIcon.PEOPLE, "账号管理")
        self.addSubInterface(self.generate_page, FluentIcon.PLAY, "视频生成")
        self.addSubInterface(self.settings_page, FluentIcon.SETTING, "设置")
        self.navigationInterface.setCurrentItem(self.email_page.objectName())

    def closeEvent(self, event):
        """关闭前取消所有后台任务，避免 QThread 被销毁时报错."""
        self.account_page.shutdown()
        self.generate_page.shutdown()
        super().closeEvent(event)
