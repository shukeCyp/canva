"""任务列表页面."""

import os
import uuid
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QHeaderView, QAbstractItemView,
    QWidget, QDialog, QFileDialog, QLabel, QApplication,
)
from qfluentwidgets import (
    TableWidget, PushButton, PrimaryPushButton, LineEdit, TextEdit,
    InfoBar, InfoBarPosition, SubtitleLabel, BodyLabel, StrongBodyLabel,
    FluentIcon,
)

from app.ui.workers import ExecuteTaskWorker, DownloadVideoWorker, ScanAndAssignWorker
from app.ui.storage import load_settings

THUMB_SIZE = 80


class AddTaskDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加生成任务")
        self.resize(500, 300)
        self.setStyleSheet("QDialog { background-color: #1e1e1e; }")
        self.image_paths = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        layout.addWidget(StrongBodyLabel("选择图片"))
        img_row = QHBoxLayout()
        self.img_label = BodyLabel("未选择图片")
        self.img_label.setStyleSheet("color: gray;")
        img_row.addWidget(self.img_label)
        img_row.addStretch()

        single_btn = PushButton(FluentIcon.PHOTO, "选择图片")
        single_btn.clicked.connect(self._pick_images)
        img_row.addWidget(single_btn)
        folder_btn = PushButton(FluentIcon.FOLDER, "选择文件夹")
        folder_btn.clicked.connect(self._pick_folder)
        img_row.addWidget(folder_btn)
        layout.addLayout(img_row)

        layout.addWidget(StrongBodyLabel("Prompt"))
        self.prompt_edit = TextEdit()
        self.prompt_edit.setPlaceholderText("输入生成提示词...")
        self.prompt_edit.setMaximumHeight(100)
        layout.addWidget(self.prompt_edit)

        info = BodyLabel("seedance-2.0 | 496x864 | 15s | 2109积分/次")
        info.setStyleSheet("color: gray; font-size: 12px;")
        layout.addWidget(info)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = PushButton("取消")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        confirm = PrimaryPushButton(FluentIcon.ADD, "添加任务")
        confirm.clicked.connect(self._confirm)
        btn_row.addWidget(confirm)
        layout.addLayout(btn_row)

    def _pick_images(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "",
            "Images (*.png *.jpg *.jpeg *.webp);;All Files (*)"
        )
        if paths:
            self.image_paths = paths
            self.img_label.setText(f"已选择 {len(paths)} 张")

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if folder:
            exts = {".png", ".jpg", ".jpeg", ".webp"}
            self.image_paths = []
            for f in os.listdir(folder):
                if os.path.splitext(f)[1].lower() in exts:
                    self.image_paths.append(os.path.join(folder, f))
            self.img_label.setText(f"已选择 {len(self.image_paths)} 张 (来自文件夹)")

    def _confirm(self):
        if not self.image_paths:
            InfoBar.warning("提示", "请选择图片", position=InfoBarPosition.TOP, parent=self)
            return
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            InfoBar.warning("提示", "请输入 Prompt", position=InfoBarPosition.TOP, parent=self)
            return
        self.accept()


class GeneratePage(QWidget):
    taskFinished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tasks = []
        self._workers = {}
        self._thumb_cache = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("任务列表"))
        header.addStretch()
        refresh_btn = PushButton(FluentIcon.SYNC, "刷新")
        refresh_btn.clicked.connect(self._refresh_table)
        header.addWidget(refresh_btn)
        add_btn = PrimaryPushButton(FluentIcon.ADD, "添加任务")
        add_btn.clicked.connect(self._show_add_dialog)
        header.addWidget(add_btn)
        layout.addLayout(header)

        self.running_label = BodyLabel("运行中: 0")
        layout.addWidget(self.running_label)

        self.log_edit = TextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumHeight(150)
        self.log_edit.setPlaceholderText("暂无日志")
        layout.addWidget(self.log_edit)

        self.table = TableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["图片", "Prompt", "状态", "账号", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 100)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 80)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 200)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(4, 220)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        layout.addWidget(self.table)

    def _show_add_dialog(self):
        dlg = AddTaskDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        prompt = dlg.prompt_edit.toPlainText().strip()
        for img in dlg.image_paths:
            task_id = uuid.uuid4().hex[:12]
            self.tasks.append({
                "id": task_id,
                "image_path": img,
                "prompt": prompt,
                "status": "pending",
                "account_email": "",
                "videoUrl": "",
                "gifUrl": "",
                "error": "",
            })
        self._refresh_table()
        self._prepare_and_dispatch()
        InfoBar.success("已添加", f"共 {len(dlg.image_paths)} 个任务", position=InfoBarPosition.TOP, parent=self)

    # --- dispatch (两阶段: 扫描分配 → 顺序执行) ---

    def _prepare_and_dispatch(self):
        """Phase 1: 扫描所有账号 → 给待处理任务分配账号."""
        pending = [t for t in self.tasks if t["status"] == "pending"]
        if not pending:
            return
        self.running_label.setText(f"正在扫描账号并分配 {len(pending)} 个任务...")

        self._assign_worker = ScanAndAssignWorker(pending)
        self._assign_worker.progress.connect(self._on_assign_progress)
        self._assign_worker.finished.connect(self._on_assignment_done)
        self._assign_worker.error.connect(
            lambda msg: InfoBar.warning("分配失败", msg, position=InfoBarPosition.TOP, parent=self)
        )
        self._assign_worker.start()

    def _on_assign_progress(self, msg):
        """记录账号扫描和任务分配日志."""
        self.running_label.setText(msg)
        self._append_log(f"[账号分配] {msg}")

    def _on_assignment_done(self, assignments):
        """Phase 2: 分配完成 → 顺序执行，每个间隔 5 秒."""
        if not assignments:
            InfoBar.warning("提示", "没有任务被分配，请检查账号积分", position=InfoBarPosition.TOP, parent=self)
            return

        for index, (task, account) in enumerate(assignments, start=1):
            task["account_email"] = account.get("email", "")
            task["error"] = f"已分配账号，等待第 {index} 个启动"
            self._append_log(
                f"[账号分配] 任务 {task['id'][:8]} 使用 {account.get('email', '')}，第 {index} 个启动"
            )
        self._refresh_table()

        InfoBar.success("分配完成", f"共 {len(assignments)} 个任务已分配账号，开始顺序执行", position=InfoBarPosition.TOP, parent=self)
        self._assignment_queue = assignments
        self._assignment_idx = 0
        self._dispatch_next()

    def _dispatch_next(self):
        """从分配队列中取下一个任务执行（间隔 5 秒）."""
        if self._assignment_idx >= len(self._assignment_queue):
            self.running_label.setText(f"全部任务已启动  |  活跃: {len(self._workers)}")
            return

        task, account = self._assignment_queue[self._assignment_idx]
        self._assignment_idx += 1
        self._append_log(
            f"[任务启动] 第 {self._assignment_idx}/{len(self._assignment_queue)} 个任务 {task['id'][:8]}，账号 {account.get('email', '')}"
        )
        self._start_task(task, account)

        if self._assignment_idx < len(self._assignment_queue):
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(5000, self._dispatch_next)

    def _start_task(self, task, account):
        task["status"] = "running"
        task["account_email"] = account["email"]
        self._refresh_table()

        worker = ExecuteTaskWorker(task["id"], task["image_path"], task["prompt"], account)
        worker.progress.connect(self._on_progress)
        worker.account_used.connect(self._on_account_used)
        worker.finished.connect(self._on_finished)
        worker.error.connect(self._on_error)
        self._workers[task["id"]] = worker
        worker.finished.connect(lambda tid, r: self._cleanup_worker(tid))
        worker.error.connect(lambda tid, m: self._cleanup_worker(tid))
        worker.start()

    def _cleanup_worker(self, task_id):
        """任务结束，清理引用."""
        self._workers.pop(task_id, None)
        self.running_label.setText(f"活跃: {len(self._workers)}  |  任务: {len(self.tasks)}")

    # --- callbacks ---

    def _on_progress(self, task_id, msg):
        for t in self.tasks:
            if t["id"] == task_id:
                t["error"] = msg
                break
        self._refresh_table()

    def _append_log(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_edit.append(f"[{timestamp}] {msg}")
        self.log_edit.verticalScrollBar().setValue(self.log_edit.verticalScrollBar().maximum())

    def _on_account_used(self, task_id, email):
        for t in self.tasks:
            if t["id"] == task_id:
                t["account_email"] = email
                break
        self._refresh_table()

    def _on_finished(self, task_id, result):
        for t in self.tasks:
            if t["id"] == task_id:
                t["status"] = "done"
                t["videoUrl"] = result.get("videoUrl", "")
                t["gifUrl"] = result.get("gifUrl", "")
                t["error"] = ""
                break
        self._refresh_table()
        self.taskFinished.emit()

        settings = load_settings()
        video_url = result.get("videoUrl")
        if settings.get("auto_download"):
            dl_path = settings.get("download_path", "").strip()
            if not video_url:
                self._append_log(f"[下载] 任务 {task_id[:8]} 未返回视频链接，跳过自动下载")
                return
            if dl_path:
                self._append_log(f"[下载] 任务 {task_id[:8]} 自动下载已触发")
                self._download_video(video_url)
            else:
                self._append_log(f"[下载] 任务 {task_id[:8]} 自动下载未执行：未配置下载路径")
                InfoBar.warning("下载失败", "请先在设置中配置下载路径", position=InfoBarPosition.TOP, parent=self)

    def _download_video(self, url):
        """后台下载视频到设置中指定的目录."""
        settings = load_settings()
        dl_path = settings.get("download_path", "").strip()
        if not dl_path:
            self._append_log("[下载] 下载未开始：未配置下载路径")
            InfoBar.warning("提示", "请先在设置中配置下载路径", position=InfoBarPosition.TOP, parent=self)
            return
        os.makedirs(dl_path, exist_ok=True)
        fname = os.path.join(dl_path, f"video_{uuid.uuid4().hex[:8]}.mp4")

        self._append_log(f"[下载] 开始下载到 {fname}")
        worker = DownloadVideoWorker(url, fname)
        worker.progress.connect(self._on_download_progress)
        worker.finished.connect(self._on_download_finished)
        worker.error.connect(self._on_download_error)
        # 保持引用防止被回收
        self._dl_workers = getattr(self, "_dl_workers", {})
        self._dl_workers[fname] = worker
        worker.finished.connect(lambda u, p: self._cleanup_download_worker(p))
        worker.error.connect(lambda u, m, p=fname: self._cleanup_download_worker(p))
        worker.start()

    def _on_error(self, task_id, msg):
        for t in self.tasks:
            if t["id"] == task_id:
                t["status"] = "error"
                t["error"] = msg
                break
        self._refresh_table()
        self.taskFinished.emit()

    # --- download callbacks ---

    def _on_download_progress(self, msg):
        self._append_log(f"[下载] {msg}")

    def _on_download_finished(self, url, filepath):
        self._append_log(f"[下载] 下载完成: {filepath}")
        InfoBar.success("下载完成", f"{os.path.basename(filepath)}", position=InfoBarPosition.TOP, parent=self)

    def _on_download_error(self, url, err_msg):
        self._append_log(f"[下载] 下载失败: {err_msg}")
        InfoBar.warning("下载失败", err_msg[:80], position=InfoBarPosition.TOP, parent=self)

    def _cleanup_download_worker(self, filepath):
        self._dl_workers = getattr(self, "_dl_workers", {})
        self._dl_workers.pop(filepath, None)

    def _copy_video_url(self, url):
        QApplication.clipboard().setText(url)
        self._append_log("[下载] 已复制下载链接")
        InfoBar.success("已复制", "下载链接已复制", position=InfoBarPosition.TOP, parent=self)

    # --- UI ---

    def _refresh_table(self):
        from PyQt6.QtWidgets import QTableWidgetItem
        self.table.setRowCount(len(self.tasks))
        row_height = THUMB_SIZE + 8
        for i, t in enumerate(self.tasks):
            self.table.setRowHeight(i, row_height)

            img_path = t["image_path"]
            if img_path not in self._thumb_cache:
                pm = QPixmap(img_path)
                if not pm.isNull():
                    pm = pm.scaled(
                        THUMB_SIZE, THUMB_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                self._thumb_cache[img_path] = pm
            thumb_label = QLabel()
            thumb_label.setPixmap(self._thumb_cache[img_path])
            thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setCellWidget(i, 0, thumb_label)

            self.table.setItem(i, 1, self._item(t["prompt"][:30]))
            status_map = {"pending": "等待", "running": "运行中", "done": "完成", "error": "失败"}
            self.table.setItem(i, 2, self._item(status_map.get(t["status"], t["status"])))
            self.table.setItem(i, 3, self._item(t.get("account_email", "") or "-"))

            op_widget = QWidget()
            op_layout = QHBoxLayout(op_widget)
            op_layout.setContentsMargins(2, 2, 2, 2)
            op_layout.setSpacing(4)

            video_url = t.get("videoUrl", "")
            if video_url:
                dl_btn = PushButton("下载")
                dl_btn.clicked.connect(lambda checked, v=video_url: self._download_video(v))
                op_layout.addWidget(dl_btn)

                copy_btn = PushButton("复制")
                copy_btn.clicked.connect(lambda checked, v=video_url: self._copy_video_url(v))
                op_layout.addWidget(copy_btn)

            if t["status"] in ("done", "error"):
                rm_btn = PushButton("删除")
                rm_btn.clicked.connect(lambda checked, idx=i: self._delete_task(idx))
                op_layout.addWidget(rm_btn)

            op_layout.addStretch()
            self.table.setCellWidget(i, 4, op_widget)

    def _item(self, text):
        from PyQt6.QtWidgets import QTableWidgetItem
        item = QTableWidgetItem()
        item.setText(str(text))
        return item

    def _delete_task(self, idx):
        self.tasks.pop(idx)
        self._refresh_table()

    def shutdown(self):
        """关闭时取消所有运行中的任务，等待线程结束."""
        for worker in list(self._workers.values()):
            worker.cancel()
        for worker in list(self._workers.values()):
            worker.wait(5000)
        self._workers.clear()

        for worker in list(getattr(self, "_dl_workers", {}).values()):
            worker.quit()
            worker.wait(3000)
        if hasattr(self, "_dl_workers"):
            self._dl_workers.clear()
