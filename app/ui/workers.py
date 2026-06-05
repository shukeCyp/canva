"""后台任务线程."""

import asyncio
import os
import sys
import threading

from PyQt6.QtCore import QThread, pyqtSignal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.tools.leo_api import (
    get_user_details_sync, upload_image_sync,
    submit_generation_sync, poll_generation_sync,
)
from app.tools.canva_join import login_flow
from app.ui.storage import load_emails, save_emails, load_accounts, save_accounts, load_settings

MODEL = "seedance-2.0"
WIDTH = 496
HEIGHT = 864
DURATION = 15
COST_PER_GEN = 2109

_account_lock = threading.Lock()


class ExecuteTaskWorker(QThread):
    """使用预分配的账号执行任务：上传 → 提交 → 轮询 → 扣积分释放."""

    progress = pyqtSignal(str, str)
    account_used = pyqtSignal(str, str)
    finished = pyqtSignal(str, dict)
    error = pyqtSignal(str, str)

    def __init__(self, task_id, image_path, prompt, account):
        super().__init__()
        self.task_id = task_id
        self.image_path = image_path
        self.prompt = prompt
        self.account = account  # 预分配的账号（已锁）
        self._cancel_event = threading.Event()

    def run(self):
        import time
        email = self.account["email"]
        token = self.account["access_token"]
        hasura_id = self.account["hasura_user_id"]
        t_start = time.time()
        try:
            self._log(f"═══ 开始执行任务 ═══")
            self._log(f"账号: {email}  积分余额: {self.account.get('tokens', '?')}")
            self._log(f"Prompt: {self.prompt[:50]}{'...' if len(self.prompt) > 50 else ''}")
            self.account_used.emit(self.task_id, email)

            # 1. 上传图片
            self._log("▶ [1/3] 上传图片到 Leonardo...")
            upload_result = upload_image_sync(self.image_path, token, hasura_id)
            image_id = upload_result.get("initImageId")
            if not image_id:
                raise RuntimeError("上传失败: 未获取到 initImageId")
            self._log(f"✓ [1/3] 上传成功 initImageId={image_id}")

            # 2. 提交生成任务
            self._log("▶ [2/3] 提交视频生成任务...")
            submit_result = submit_generation_sync(
                token, hasura_id, self.prompt, image_id,
                width=WIDTH, height=HEIGHT, duration=DURATION, model=MODEL,
            )
            generation_id = submit_result.get("generationId")
            cost = submit_result.get("apiCreditCost", COST_PER_GEN)
            self._log(f"✓ [2/3] 提交成功 generationId={generation_id} 消耗={cost}积分")

            # 3. 轮询结果
            self._log(f"▶ [3/3] 等待视频生成完成 (最多等待20分钟)...")
            poll_result = poll_generation_sync(
                token, hasura_id, generation_id,
                cancel_event=self._cancel_event,
            )
            video_url = poll_result.get("videoUrl", "")
            if video_url:
                self._log(f"✓ [3/3] 视频生成完成，获取到下载链接")

            # 4. 成功 → 扣积分 + 释放锁
            self._deduct_tokens(email)

            elapsed = time.time() - t_start
            self._log(f"═══ 任务完成 总耗时={elapsed:.0f}秒 ═══")

            result = {
                **upload_result, **poll_result,
                "account_email": email,
            }
            self.finished.emit(self.task_id, result)

        except Exception as e:
            elapsed = time.time() - t_start
            self._log(f"✗ 任务失败 (耗时{elapsed:.0f}秒): {e}")
            # 失败 → 释放锁
            self._release_account(email)
            self.error.emit(self.task_id, str(e))

    def _log(self, msg):
        self.progress.emit(self.task_id, msg)

    def _release_account(self, email):
        """仅释放 in_use 锁, 不扣积分."""
        with _account_lock:
            accounts = load_accounts()
            for a in accounts:
                if a.get("email") == email:
                    a["in_use"] = False
                    self._log(f"🔓 释放账号锁: {email}")
                    break
            save_accounts(accounts)

    def _deduct_tokens(self, email):
        """扣减积分, 释放 in_use, 不够则删除账号."""
        with _account_lock:
            accounts = load_accounts()
            for a in accounts:
                if a.get("email") == email:
                    a["in_use"] = False
                    before = a.get("tokens", 0)
                    remaining = before - COST_PER_GEN
                    a["tokens"] = remaining
                    self._log(f"💰 扣减积分: {email} {before} → {remaining} (-{COST_PER_GEN})")
                    if remaining < COST_PER_GEN:
                        self._log(f"⚠ 积分不足({remaining} < {COST_PER_GEN})，删除账号: {email}")
                        accounts.remove(a)
                    break
            save_accounts(accounts)

    def cancel(self):
        self._cancel_event.set()


class ScanAndAssignWorker(QThread):
    """扫描全部账号积分 → 按积分高低给任务分配账号 → 返回 (task, account) 列表."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(list)  # [(task_dict, account_dict), ...]
    error = pyqtSignal(str)

    def __init__(self, tasks):
        super().__init__()
        self.tasks = tasks  # 待分配的任务列表

    def run(self):
        try:
            # Step 1: 扫描全部账号积分
            self.progress.emit("═══ 开始扫描所有账号积分 ═══")
            with _account_lock:
                accounts = load_accounts()
            if not accounts:
                self.error.emit('❌ 没有任何账号！请先在「账号管理」页面注册账号。')
                return

            self.progress.emit(f"共 {len(accounts)} 个账号，开始逐个查询积分...")
            total_tokens = 0
            available_count = 0
            expired_accounts = []
            for a in accounts:
                token = a.get("access_token", "")
                sub = a.get("cognito_sub", "")
                email = a.get("email", "?")
                if not token or not sub:
                    self.progress.emit(f"  ⊘ {email} 缺少token，跳过")
                    continue
                try:
                    user = get_user_details_sync(token, sub)
                    details = user.get("user_details", [{}])[0] if user.get("user_details") else {}
                    plan = details.get("plan", "")
                    if plan == "EXPIRED":
                        # token 过期 → 标记待删除，释放邮箱
                        self.progress.emit(f"  ⏰ {email} Token已过期，释放邮箱")
                        expired_accounts.append(a)
                        self._release_email(email)
                        continue
                    a["tokens"] = details.get("subscriptionTokens", 0)
                    a["plan"] = plan
                    a["paidTokens"] = details.get("paidTokens", 0)
                    a["tokenRenewalDate"] = details.get("tokenRenewalDate", "")
                    total_tokens += a["tokens"]
                    status = "✓" if (not a.get("in_use") and a["tokens"] >= COST_PER_GEN) else ""
                    self.progress.emit(f"  {status} {email} plan={a['plan']} 积分={a['tokens']}{' (已占用)' if a.get('in_use') else ''}")
                    if not a.get("in_use") and a["tokens"] >= COST_PER_GEN:
                        available_count += 1
                except Exception as e:
                    self.progress.emit(f"  ✗ {email} 查询失败: {e}")
                    # 查询异常也可能是 token 过期 → 同样处理
                    if "Token" in str(e) or "过期" in str(e) or "expired" in str(e).lower():
                        self.progress.emit(f"  ⏰ {email} 疑似Token过期，释放邮箱")
                        expired_accounts.append(a)
                        self._release_email(email)

            # 删除过期账号
            if expired_accounts:
                expired_emails = {a.get("email") for a in expired_accounts}
                accounts = [a for a in accounts if a.get("email") not in expired_emails]
                with _account_lock:
                    save_accounts(accounts)
                self.progress.emit(f"🗑 已清除 {len(expired_accounts)} 个过期账号")

            with _account_lock:
                save_accounts(accounts)

            self.progress.emit(f"扫描完成: 总积分={total_tokens} 可用账号={available_count} 个")
            if available_count == 0 and len(accounts) > 0:
                self.progress.emit("⚠ 所有账号token已过期！请重新注册账号。")

            # Step 2: 按积分从高到低排序账号
            available = [a for a in accounts if not a.get("in_use") and a.get("tokens", 0) >= COST_PER_GEN]
            available.sort(key=lambda a: a.get("tokens", 0), reverse=True)
            self.progress.emit(f"待分配任务: {len(self.tasks)} 个  可用账号: {len(available)} 个  单次消耗: {COST_PER_GEN}积分")

            # Step 3: 分配 —— 按账号积分容量分配，积分越高越优先
            assignments = []
            account_slots = []
            for account in available:
                slots = max(0, account.get("tokens", 0) // COST_PER_GEN)
                account_slots.extend([account] * slots)
                self.progress.emit(
                    f"账号容量: {account.get('email', '')} 积分={account.get('tokens', 0)} 可分配={slots} 个任务"
                )
            self.progress.emit(f"可分配任务名额: {len(account_slots)} 个")

            for task in self.tasks:
                if len(assignments) >= len(account_slots):
                    shortage = len(self.tasks) - len(assignments)
                    self.progress.emit(f"⚠ 积分不够！已分配 {len(assignments)} 个，剩余 {shortage} 个任务未分配（请注册更多账号）")
                    break
                acct = account_slots[len(assignments)]
                assignments.append((task, acct.copy()))
                self.progress.emit(f"  #{len(assignments)} {task['id'][:8]} → {acct['email']} (积分={acct['tokens']})")

            if assignments:
                assigned_emails = {acct.get("email") for _, acct in assignments}
                self.progress.emit(f"锁定已分配账号: {len(assigned_emails)} 个")
                # 锁定已分配账号，避免下一轮调度重复分配
                with _account_lock:
                    accs = load_accounts()
                    for a2 in accs:
                        if a2.get("email") in assigned_emails:
                            a2["in_use"] = True
                    save_accounts(accs)

            self.progress.emit(f"═══ 分配完成: {len(assignments)}/{len(self.tasks)} 个任务已获配账号 ═══")
            self.finished.emit(assignments)

        except Exception as e:
            self.error.emit(f"扫描分配异常: {e}")

    def _release_email(self, email):
        """将邮箱状态重置为可用."""
        try:
            emails = load_emails()
            for e in emails:
                if e.get("email") == email:
                    e["status"] = "available"
                    save_emails(emails)
                    return
        except Exception:
            pass


class PrepareAccountsWorker(QThread):
    """准备账号: 先刷新全部积分, 不够则逐个注册, 直到账号数 >= needed."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(int)  # 返回可用账号数

    def __init__(self, needed):
        super().__init__()
        self.needed = needed

    def run(self):
        try:
            # Step 1: 刷新全部现有账号积分
            self._refresh_all_credits()

            # Step 2: 检查可用数, 不够就注册
            available = self._count_available()
            self.progress.emit(f"刷新后可用账号: {available}, 需要: {self.needed}")

            while available < self.needed:
                self.progress.emit(f"账号不足 ({available}/{self.needed}), 开始注册...")
                ok = self._register_one()
                if not ok:
                    self.progress.emit("没有更多可用邮箱, 注册停止")
                    break
                available = self._count_available()
                self.progress.emit(f"注册后可用账号: {available}/{self.needed}")

            self.finished.emit(available)
        except Exception as e:
            self.progress.emit(f"准备账号异常: {e}")
            self.finished.emit(0)

    def _refresh_all_credits(self):
        """刷新所有账号的积分, 过期账号自动清除并释放邮箱."""
        with _account_lock:
            accounts = load_accounts()
        if not accounts:
            self.progress.emit("没有现有账号, 跳过刷新")
            return

        self.progress.emit(f"刷新 {len(accounts)} 个账号积分...")
        expired_accounts = []
        for a in accounts:
            token = a.get("access_token", "")
            sub = a.get("cognito_sub", "")
            email = a.get("email", "")
            if not token or not sub:
                continue
            try:
                user = get_user_details_sync(token, sub)
                details = user.get("user_details", [{}])[0] if user.get("user_details") else {}
                plan = details.get("plan", "")
                if plan == "EXPIRED":
                    self.progress.emit(f"  ⏰ {email} Token已过期，释放邮箱")
                    expired_accounts.append(a)
                    self._release_one_email(email)
                    continue
                a["tokens"] = details.get("subscriptionTokens", 0)
                a["plan"] = plan
                a["paidTokens"] = details.get("paidTokens", 0)
                a["tokenRenewalDate"] = details.get("tokenRenewalDate", "")
                self.progress.emit(f"  {email} 积分={a['tokens']}")
            except Exception as e:
                self.progress.emit(f"  {email} 查询失败: {e}")
                if "Token" in str(e) or "过期" in str(e) or "expired" in str(e).lower():
                    self.progress.emit(f"  ⏰ {email} 疑似过期，释放邮箱")
                    expired_accounts.append(a)
                    self._release_one_email(email)

        if expired_accounts:
            with _account_lock:
                accounts = load_accounts()
                for ea in expired_accounts:
                    accounts = [a for a in accounts if a.get("email") != ea.get("email")]
                save_accounts(accounts)
            self.progress.emit(f"🗑 已清除 {len(expired_accounts)} 个过期账号")

        with _account_lock:
            save_accounts(accounts)

    def _release_one_email(self, email):
        """将邮箱状态重置."""
        try:
            emails = load_emails()
            for e in emails:
                if e.get("email") == email:
                    e["status"] = "available"
                    save_emails(emails)
                    return
        except Exception:
            pass

    def _count_available(self):
        """统计当前可用账号数 (积分>=2109 且未占用)."""
        with _account_lock:
            accounts = load_accounts()
        return sum(1 for a in accounts if not a.get("in_use") and a.get("tokens", 0) >= COST_PER_GEN)

    def _register_one(self):
        """注册一个账号, 返回是否成功."""
        emails = load_emails()
        available = [e for e in emails if e.get("status") != "used"]
        if not available:
            return False

        email_entry = available[0]
        email = email_entry["email"]
        password = email_entry["password"]
        self.progress.emit(f"注册: {email}")

        settings = load_settings()
        join_url = settings.get("join_url", "")
        headless = settings.get("headless", False)

        try:
            session_data = asyncio.run(login_flow(email, password, join_url=join_url, headless=headless))
        except Exception as e:
            self.progress.emit(f"  注册失败: {e}, 本轮跳过")
            return False

        session_info = session_data.get("session", {})
        user_info = session_data.get("user", {})

        if not session_info.get("accessToken"):
            self.progress.emit("  未获取到 token, 本轮跳过")
            return False

        email_entry["status"] = "used"
        save_emails(emails)

        # 注册后立刻查积分
        access_token = session_info.get("accessToken", "")
        cognito_sub = session_info.get("cognitoSub", "")
        tokens = 0
        try:
            user = get_user_details_sync(access_token, cognito_sub)
            details = user.get("user_details", [{}])[0] if user.get("user_details") else {}
            tokens = details.get("subscriptionTokens", 0)
        except Exception:
            pass

        account = {
            "email": user_info.get("email", email),
            "username": user_info.get("name", ""),
            "hasura_user_id": session_info.get("hasuraUserId", ""),
            "cognito_sub": cognito_sub,
            "access_token": access_token,
            "session_id": session_info.get("id", ""),
            "session_token": session_info.get("token", ""),
            "session_expires_at": session_info.get("expiresAt", ""),
            "cookies": session_data.get("cookies", []),
            "plan": "BASIC",
            "tokens": tokens,
            "paidTokens": 0,
            "tokenRenewalDate": "",
            "in_use": False,
        }
        with _account_lock:
            accounts = load_accounts()
            existing = [a for a in accounts if a.get("email") == account["email"]]
            if not existing:
                accounts.append(account)
            save_accounts(accounts)

        self.progress.emit(f"  注册成功: {account['email']} 积分={tokens}")
        return True


class RegisterAccountsWorker(QThread):
    """后台注册账号，直到成功 target_count 个."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(int)  # 实际注册成功的数量

    def __init__(self, target_count):
        super().__init__()
        self.target_count = target_count

    def run(self):
        success_count = 0
        failed_emails = []
        try:
            self.progress.emit(f"目标: 注册 {self.target_count} 个账号")

            while success_count < self.target_count:
                emails = load_emails()
                available = [e for e in emails if e.get("status") != "used"]
                if not available:
                    self.progress.emit("没有更多可用邮箱，注册停止")
                    break

                email_entry = available[0]
                email = email_entry["email"]
                password = email_entry["password"]
                self.progress.emit(f"({success_count + 1}/{self.target_count}) 注册: {email}")

                settings = load_settings()
                join_url = settings.get("join_url", "")
                headless = settings.get("headless", False)

                try:
                    session_data = asyncio.run(
                        login_flow(email, password, join_url=join_url, headless=headless)
                    )
                except Exception as e:
                    self.progress.emit(f"  ✗ {email} 注册失败: {e}")
                    failed_emails.append(email)
                    continue

                session_info = session_data.get("session", {})
                user_info = session_data.get("user", {})

                if not session_info.get("accessToken"):
                    self.progress.emit(f"  ✗ {email} 未获取到 token")
                    failed_emails.append(email)
                    continue

                email_entry["status"] = "used"
                save_emails(emails)

                # 注册后立刻查积分
                access_token = session_info.get("accessToken", "")
                cognito_sub = session_info.get("cognitoSub", "")
                tokens = 0
                try:
                    user = get_user_details_sync(access_token, cognito_sub)
                    details = user.get("user_details", [{}])[0] if user.get("user_details") else {}
                    tokens = details.get("subscriptionTokens", 0)
                except Exception:
                    pass

                account = {
                    "email": user_info.get("email", email),
                    "username": user_info.get("name", ""),
                    "hasura_user_id": session_info.get("hasuraUserId", ""),
                    "cognito_sub": cognito_sub,
                    "access_token": access_token,
                    "session_id": session_info.get("id", ""),
                    "session_token": session_info.get("token", ""),
                    "session_expires_at": session_info.get("expiresAt", ""),
                    "cookies": session_data.get("cookies", []),
                    "plan": "BASIC",
                    "tokens": tokens,
                    "paidTokens": 0,
                    "tokenRenewalDate": "",
                    "in_use": False,
                }
                with _account_lock:
                    accounts = load_accounts()
                    existing = [a for a in accounts if a.get("email") == account["email"]]
                    if not existing:
                        accounts.append(account)
                    save_accounts(accounts)

                success_count += 1
                self.progress.emit(f"  ✓ 注册成功: {account['email']} 积分={tokens}")

            if success_count > 0:
                self.progress.emit(f"注册完成: 成功 {success_count} 个")
            else:
                self.progress.emit("注册完成: 0 个成功")
            self.finished.emit(success_count)
        except Exception as e:
            self.progress.emit(f"注册异常: {e}")
            self.finished.emit(success_count)


class FetchCreditsWorker(QThread):
    """查询单个账号积分."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, access_token, user_sub):
        super().__init__()
        self.access_token = access_token
        self.user_sub = user_sub

    def run(self):
        try:
            self.progress.emit("查询积分...")
            user = get_user_details_sync(self.access_token, self.user_sub)
            details = user.get("user_details", [{}])[0] if user.get("user_details") else {}
            result = {
                "tokens": details.get("subscriptionTokens", 0),
                "plan": details.get("plan", ""),
                "paidTokens": details.get("paidTokens", 0),
                "tokenRenewalDate": details.get("tokenRenewalDate", ""),
            }
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class DownloadVideoWorker(QThread):
    """后台下载视频，不阻塞 UI."""
    progress = pyqtSignal(str)       # 进度消息
    finished = pyqtSignal(str, str)  # (url, filepath)
    error = pyqtSignal(str, str)     # (url, error_message)

    def __init__(self, url, filepath):
        super().__init__()
        self.url = url
        self.filepath = filepath

    def run(self):
        import urllib.request
        import urllib.parse
        import os
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            self.progress.emit(f"开始下载: {os.path.basename(self.filepath)}")
            # URL 编码中文等非 ASCII 字符
            url = self.url
            scheme, netloc, path, query, fragment = urllib.parse.urlsplit(url)
            path = urllib.parse.quote(path, safe='/-_.%')
            url = urllib.parse.urlunsplit((scheme, netloc, path, query, fragment))
            req = urllib.request.Request(url, headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/147.0.0.0 Safari/537.36"
                ),
                "Accept": "*/*",
            })
            with urllib.request.urlopen(req, timeout=300) as resp:
                total = resp.headers.get("Content-Length")
                total_str = f" ({int(total) / 1024 / 1024:.1f} MB)" if total else ""
                downloaded = 0
                last_reported_pct = -10
                with open(self.filepath, "wb") as f:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded * 100 // int(total)
                            if pct >= last_reported_pct + 10 or pct == 100:
                                last_reported_pct = pct
                                self.progress.emit(
                                    f"下载中: {pct}%{total_str}"
                                )
                if not total:
                    self.progress.emit(f"已下载: {downloaded / 1024 / 1024:.1f} MB")
                self.progress.emit(f"下载完成{total_str}")
            self.finished.emit(self.url, self.filepath)
        except Exception as e:
            self.error.emit(self.url, str(e))
