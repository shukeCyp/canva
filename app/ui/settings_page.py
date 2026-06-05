"""设置页面."""

import os

from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QFileDialog
from qfluentwidgets import (
    LineEdit, SwitchButton, PushButton,
    InfoBar, InfoBarPosition, SubtitleLabel, BodyLabel, StrongBodyLabel,
    CardWidget, FluentIcon,
)

from app.ui.storage import load_settings, save_settings


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = load_settings()
        self._setup_ui()
        self._load()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(SubtitleLabel("设置"))

        # 1. 注册链接
        url_card = CardWidget()
        url_layout = QVBoxLayout(url_card)
        url_layout.setContentsMargins(16, 12, 16, 12)
        url_layout.setSpacing(8)
        url_layout.addWidget(StrongBodyLabel("Canva 注册链接"))
        url_layout.addWidget(BodyLabel("品牌邀请链接，自动注册时使用"))
        self.url_edit = LineEdit()
        self.url_edit.setPlaceholderText("https://www.canva.com/brand/join?token=...")
        url_layout.addWidget(self.url_edit)
        layout.addWidget(url_card)

        # 2. 无头模式
        headless_card = CardWidget()
        headless_layout = QHBoxLayout(headless_card)
        headless_layout.setContentsMargins(16, 12, 16, 12)
        headless_left = QVBoxLayout()
        headless_left.addWidget(StrongBodyLabel("无头模式"))
        headless_left.addWidget(BodyLabel("开启后浏览器在后台运行，不显示窗口"))
        headless_layout.addLayout(headless_left)
        headless_layout.addStretch()
        self.headless_switch = SwitchButton()
        headless_layout.addWidget(self.headless_switch)
        layout.addWidget(headless_card)

        # 3. 下载路径
        dl_card = CardWidget()
        dl_layout = QVBoxLayout(dl_card)
        dl_layout.setContentsMargins(16, 12, 16, 12)
        dl_layout.setSpacing(8)
        dl_layout.addWidget(StrongBodyLabel("视频下载路径"))
        dl_row = QHBoxLayout()
        self.dl_path_edit = LineEdit()
        self.dl_path_edit.setPlaceholderText("选择下载目录...")
        self.dl_path_edit.setReadOnly(True)
        dl_row.addWidget(self.dl_path_edit)
        browse_btn = PushButton(FluentIcon.FOLDER, "浏览")
        browse_btn.clicked.connect(self._browse_dl_path)
        dl_row.addWidget(browse_btn)
        dl_layout.addLayout(dl_row)
        layout.addWidget(dl_card)

        # 4. 自动下载
        auto_card = CardWidget()
        auto_layout = QHBoxLayout(auto_card)
        auto_layout.setContentsMargins(16, 12, 16, 12)
        auto_left = QVBoxLayout()
        auto_left.addWidget(StrongBodyLabel("自动下载视频"))
        auto_left.addWidget(BodyLabel("视频生成完成后自动下载到本地"))
        auto_layout.addLayout(auto_left)
        auto_layout.addStretch()
        self.auto_dl_switch = SwitchButton()
        auto_layout.addWidget(self.auto_dl_switch)
        layout.addWidget(auto_card)

        # 保存
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = PushButton("保存设置")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        layout.addStretch()

    def _load(self):
        self.url_edit.setText(self.settings.get("join_url", ""))
        self.headless_switch.setChecked(self.settings.get("headless", False))
        self.dl_path_edit.setText(self.settings.get("download_path", ""))
        self.auto_dl_switch.setChecked(self.settings.get("auto_download", False))

    def _browse_dl_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择下载目录")
        if path:
            self.dl_path_edit.setText(path)

    def _save(self):
        url = self.url_edit.text().strip()
        self.settings["join_url"] = url
        self.settings["headless"] = self.headless_switch.isChecked()
        self.settings["download_path"] = self.dl_path_edit.text().strip()
        self.settings["auto_download"] = self.auto_dl_switch.isChecked()
        save_settings(self.settings)
        InfoBar.success("已保存", "设置已保存", position=InfoBarPosition.TOP, parent=self)
