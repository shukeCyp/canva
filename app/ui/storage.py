"""数据存储层 - JSON 读写."""

import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
EMAILS_FILE = os.path.join(DATA_DIR, "emails.json")
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


#   

def load_emails():
    _ensure_dir()
    if not os.path.exists(EMAILS_FILE):
        return []
    with open(EMAILS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_emails(emails):
    _ensure_dir()
    with open(EMAILS_FILE, "w", encoding="utf-8") as f:
        json.dump(emails, f, indent=2, ensure_ascii=False)


#   

def load_accounts():
    _ensure_dir()
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_accounts(accounts):
    _ensure_dir()
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)


#   

def load_settings():
    _ensure_dir()
    if not os.path.exists(SETTINGS_FILE):
        return {}
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_settings(settings):
    _ensure_dir()
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
