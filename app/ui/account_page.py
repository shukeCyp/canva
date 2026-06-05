"""账号列表页面."""

import json
import os
import subprocess
import sys
import tempfile

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QHeaderView, QAbstractItemView, QWidget,
    QDialog, QSpinBox,
)
from qfluentwidgets import (
    TableWidget, PushButton, PrimaryPushButton,
    InfoBar, InfoBarPosition, SubtitleLabel, StrongBodyLabel, BodyLabel,
    FluentIcon, TransparentPushButton, MessageBox,
)

from app.ui.storage import load_accounts, save_accounts, load_emails
from app.ui.workers import FetchCreditsWorker, RegisterAccountsWorker


class RegisterDialog(QDialog):
    """注册账号对话框."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("注册账号")
        self.setFixedSize(420, 280)
        self.setStyleSheet("QDialog { background-color: #1e1e1e; }")
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        layout.addWidget(StrongBodyLabel("注册账号数量"))
        layout.addWidget(BodyLabel("从邮箱列表取未使用的邮箱，逐个注册直到成功指定数量"))

        # 可用邮箱数提示
        emails = load_emails()
        available = sum(1 for e in emails if e.get("status") != "used")
        hint = BodyLabel(f"当前可用邮箱: {available} 个")
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)

        self.spin = QSpinBox()
        self.spin.setMinimum(1)
        self.spin.setMaximum(max(1, available))
        self.spin.setValue(min(10, available))
        self.spin.setStyleSheet("""
            QSpinBox {
                background: #2d2d2d; color: white; border: 1px solid #555;
                border-radius: 4px; padding: 10px 8px; font-size: 15px;
                min-height: 20px;
            }
        """)
        layout.addWidget(self.spin)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = PushButton("取消")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        confirm = PrimaryPushButton(FluentIcon.ADD, "开始注册")
        confirm.clicked.connect(self.accept)
        btn_row.addWidget(confirm)
        layout.addLayout(btn_row)


class AccountPage(QWidget):
    accountsChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.accounts = load_accounts()
        self._credit_workers = []
        self._reg_worker = None
        self._refreshing_credits = False
        self._setup_ui()
        self._refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("账号列表"))
        header.addStretch()

        reg_btn = PrimaryPushButton(FluentIcon.ADD, "注册账号")
        reg_btn.clicked.connect(self._show_register_dialog)
        header.addWidget(reg_btn)

        self.refresh_btn = PushButton(FluentIcon.SYNC, "刷新全部积分")
        self.refresh_btn.clicked.connect(self._refresh_all_credits)
        header.addWidget(self.refresh_btn)

        batch_delete_btn = PushButton(FluentIcon.DELETE, "批量删除")
        batch_delete_btn.clicked.connect(self._batch_delete)
        header.addWidget(batch_delete_btn)
        layout.addLayout(header)

        self.table = TableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "邮箱", "用户名", "Plan", "积分", "到期日", "操作"
        ])
        for i in range(3):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        for i in range(3, 5):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(i, 120)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(5, 150)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        layout.addWidget(self.table)

    # --- 注册 ---

    def _show_register_dialog(self):
        dlg = RegisterDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        target = dlg.spin.value()
        self._reg_worker = RegisterAccountsWorker(target)
        self._reg_worker.progress.connect(
            lambda msg: InfoBar.info("注册进度", msg, position=InfoBarPosition.TOP, parent=self)
        )
        self._reg_worker.finished.connect(self._on_register_done)
        self._reg_worker.start()
        InfoBar.info("提示", f"开始注册 {target} 个账号，请查看进度...", position=InfoBarPosition.TOP, parent=self)

    def _on_register_done(self, count):
        if count > 0:
            InfoBar.success("注册完成", f"成功注册 {count} 个账号", position=InfoBarPosition.TOP, parent=self)
            self._refresh()
            self.accountsChanged.emit()
        else:
            InfoBar.warning("注册失败", "没有成功注册任何账号", position=InfoBarPosition.TOP, parent=self)

    # --- 刷新积分 ---

    def _refresh_all_credits(self):
        if self._refreshing_credits:
            InfoBar.info("提示", "正在刷新积分，请稍候", position=InfoBarPosition.TOP, parent=self)
            return

        self.accounts = load_accounts()
        pending = [a for a in self.accounts if a.get("access_token") and a.get("cognito_sub")]
        if not pending:
            InfoBar.info("提示", "没有可刷新积分的账号", position=InfoBarPosition.TOP, parent=self)
            return
        self._refreshing_credits = True
        self.refresh_btn.setEnabled(False)
        self._refresh_next(0, pending)

    def _refresh_next(self, idx, accounts):
        if idx >= len(accounts):
            save_accounts(self.accounts)
            self._refresh()
            self.accountsChanged.emit()
            self._refreshing_credits = False
            self.refresh_btn.setEnabled(True)
            InfoBar.success("完成", f"已刷新 {len(accounts)} 个账号", position=InfoBarPosition.TOP, parent=self)
            return
        a = accounts[idx]
        worker = FetchCreditsWorker(a["access_token"], a["cognito_sub"])
        self._credit_workers.append(worker)
        worker.finished.connect(
            lambda credits, acc=a: self._on_one_credit(acc, credits)
        )
        worker.finished.connect(lambda _: self._refresh_next(idx + 1, accounts))
        worker.error.connect(lambda e: self._refresh_next(idx + 1, accounts))
        worker.finished.connect(lambda _: self._cleanup_credit_worker(worker))
        worker.error.connect(lambda _: self._cleanup_credit_worker(worker))
        worker.start()

    def _cleanup_credit_worker(self, worker):
        if worker in self._credit_workers:
            self._credit_workers.remove(worker)
        worker.deleteLater()

    def _on_one_credit(self, account, credits):
        for a in self.accounts:
            if a.get("email") == account.get("email"):
                a["tokens"] = credits.get("tokens", 0)
                a["plan"] = credits.get("plan", "BASIC")
                a["paidTokens"] = credits.get("paidTokens", 0)
                a["tokenRenewalDate"] = credits.get("tokenRenewalDate", "")
                break

    def _refresh(self):
        self.accounts = load_accounts()
        from PyQt6.QtWidgets import QTableWidgetItem
        self.table.setRowCount(len(self.accounts))
        for i, a in enumerate(self.accounts):
            self.table.setItem(i, 0, QTableWidgetItem(a.get("email", "")))
            self.table.setItem(i, 1, QTableWidgetItem(a.get("username", "")))
            self.table.setItem(i, 2, QTableWidgetItem(a.get("plan", "")))
            self.table.setItem(i, 3, QTableWidgetItem(str(a.get("tokens", 0))))
            self.table.setItem(i, 4, QTableWidgetItem(str(a.get("tokenRenewalDate", ""))[:10]))

            op_widget = QWidget()
            op_layout = QHBoxLayout(op_widget)
            op_layout.setContentsMargins(2, 2, 2, 2)
            op_layout.setSpacing(4)

            open_btn = PushButton("打开")
            open_btn.clicked.connect(lambda checked, idx=i: self._open_account(idx))
            op_layout.addWidget(open_btn)

            del_btn = TransparentPushButton(FluentIcon.DELETE, "")
            del_btn.clicked.connect(lambda checked, idx=i: self._delete(idx))
            op_layout.addWidget(del_btn)
            op_layout.addStretch()
            self.table.setCellWidget(i, 5, op_widget)

    def _delete(self, idx):
        email = self.accounts[idx]["email"]
        box = MessageBox("确认删除", f"删除账号 {email}?", self)
        if box.exec():
            self.accounts.pop(idx)
            save_accounts(self.accounts)
            self._refresh()
            self.accountsChanged.emit()

    def _open_account(self, idx):
        if not 0 <= idx < len(self.accounts):
            return

        account = self.accounts[idx]
        if not account.get("access_token"):
            InfoBar.warning("打开失败", "账号缺少 access_token", position=InfoBarPosition.TOP, parent=self)
            return

        script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "tools",
            "open_leonardo_account.py",
        )
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        with tmp:
            json.dump(account, tmp, ensure_ascii=False)

        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--open-account", tmp.name]
            else:
                cmd = [sys.executable, script, "--account", tmp.name]
            subprocess.Popen(
                cmd,
                cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            InfoBar.success("已打开", "正在打开 Leonardo.ai", position=InfoBarPosition.TOP, parent=self)
        except Exception as e:
            InfoBar.warning("打开失败", str(e), position=InfoBarPosition.TOP, parent=self)

    def _batch_delete(self):
        selected_rows = sorted(
            {index.row() for index in self.table.selectionModel().selectedRows()},
            reverse=True,
        )
        if not selected_rows:
            InfoBar.info("提示", "请先选择要删除的账号", position=InfoBarPosition.TOP, parent=self)
            return

        box = MessageBox("确认批量删除", f"确定删除选中的 {len(selected_rows)} 个账号?", self)
        if not box.exec():
            return

        for row in selected_rows:
            if 0 <= row < len(self.accounts):
                self.accounts.pop(row)
        save_accounts(self.accounts)
        self._refresh()
        self.accountsChanged.emit()

    def shutdown(self):
        """关闭时等待账号页后台线程结束，避免 QThread 被销毁时报错."""
        for worker in list(self._credit_workers):
            worker.quit()
            worker.wait(5000)
        self._credit_workers.clear()

        if self._reg_worker and self._reg_worker.isRunning():
            self._reg_worker.quit()
            self._reg_worker.wait(5000)
