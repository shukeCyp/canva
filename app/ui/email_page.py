"""邮箱管理页面."""

from datetime import datetime

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QHeaderView, QAbstractItemView,
    QWidget, QDialog,
)
from qfluentwidgets import (
    TableWidget, PushButton, PrimaryPushButton,
    InfoBar, InfoBarPosition, MessageBox, SubtitleLabel, BodyLabel,
    StrongBodyLabel, FluentIcon, TransparentPushButton, TextEdit,
)

from app.ui.storage import load_emails, save_emails


class ImportDialog(QDialog):
    """批量导入邮箱对话框."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量导入邮箱")
        self.resize(500, 380)
        self.setStyleSheet("QDialog { background-color: #1e1e1e; }")
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        layout.addWidget(StrongBodyLabel("批量导入邮箱"))
        layout.addWidget(BodyLabel("每行一个，格式: 账号----密码"))

        self.text_edit = TextEdit()
        self.text_edit.setPlaceholderText(
            "user1@example.com----password1\n"
            "user2@example.com----password2\n"
            "user3@example.com----password3"
        )
        layout.addWidget(self.text_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = PushButton("取消")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        confirm = PrimaryPushButton(FluentIcon.ADD, "导入")
        confirm.clicked.connect(self.accept)
        btn_row.addWidget(confirm)
        layout.addLayout(btn_row)

    def get_emails(self):
        """解析输入，返回 [(email, password), ...]."""
        result = []
        raw = self.text_edit.toPlainText().strip()
        if not raw:
            return result
        for line in raw.split("\n"):
            line = line.strip()
            if not line or "----" not in line:
                continue
            email, password = line.split("----", 1)
            email, password = email.strip(), password.strip()
            if email and password:
                result.append((email, password))
        return result


class EmailPage(QWidget):
    emailsChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.emails = load_emails()
        self._setup_ui()
        self._refresh_table()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("邮箱管理"))
        header.addStretch()
        refresh_btn = PushButton(FluentIcon.SYNC, "刷新")
        refresh_btn.clicked.connect(self._refresh)
        header.addWidget(refresh_btn)
        import_btn = PrimaryPushButton(FluentIcon.ADD, "批量导入")
        import_btn.clicked.connect(self._import_emails)
        header.addWidget(import_btn)
        layout.addLayout(header)

        self.table = TableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["邮箱", "密码", "状态", "创建时间", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 80)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 150)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(4, 80)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        layout.addWidget(self.table)

        bottom = QHBoxLayout()
        self.count_label = BodyLabel()
        bottom.addWidget(self.count_label)
        bottom.addStretch()
        layout.addLayout(bottom)

    def _refresh_table(self):
        self.table.setRowCount(len(self.emails))
        for i, e in enumerate(self.emails):
            self.table.setItem(i, 0, self._item(e.get("email", "")))
            self.table.setItem(i, 1, self._item("........"))
            self.table.setItem(i, 2, self._item(e.get("status", "pending")))
            self.table.setItem(i, 3, self._item(e.get("created_at", "")[:19]))
            del_btn = TransparentPushButton(FluentIcon.DELETE, "")
            del_btn.clicked.connect(lambda checked, idx=i: self._delete_email(idx))
            self.table.setCellWidget(i, 4, del_btn)

        available = sum(1 for e in self.emails if e.get("status") != "used")
        self.count_label.setText(
            f"共 {len(self.emails)} 个  |  可用: {available}  |  已用: {len(self.emails) - available}"
        )

    def _item(self, text):
        from PyQt6.QtWidgets import QTableWidgetItem
        item = QTableWidgetItem()
        item.setText(str(text))
        return item

    def _import_emails(self):
        dlg = ImportDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        entries = dlg.get_emails()
        if not entries:
            InfoBar.warning("提示", "未识别到有效邮箱", position=InfoBarPosition.TOP, parent=self)
            return

        count = 0
        for email, password in entries:
            if any(e["email"] == email for e in self.emails):
                continue
            self.emails.append({
                "email": email, "password": password,
                "status": "pending", "created_at": datetime.now().isoformat(),
            })
            count += 1

        if count:
            save_emails(self.emails)
            self._refresh_table()
            self.emailsChanged.emit()
        InfoBar.success("导入完成", f"共导入 {count} 个邮箱", position=InfoBarPosition.TOP, parent=self)

    def _refresh(self):
        self.emails = load_emails()
        self._refresh_table()

    def _delete_email(self, idx):
        email = self.emails[idx]["email"]
        box = MessageBox("确认删除", f"确定删除 {email} ?", self)
        if box.exec():
            self.emails.pop(idx)
            save_emails(self.emails)
            self._refresh_table()
            self.emailsChanged.emit()
