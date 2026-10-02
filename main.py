#!/usr/bin/env python3
"""
Hermes Storage & Session Optimizer (CLI & Web Wizard)
Safe, standalone cleaner and analyzer for ~/.hermes directories.
Zero third-party dependencies.
"""

from __future__ import annotations

import argparse
import html
import http.server
import io
import json
import os
import shutil
import sqlite3
import sys
import threading
import time
import webbrowser
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_hermes_dir() -> Path:
    env_dir = os.getenv("HERMES_HOME")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    return Path.home() / ".hermes"



def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gm > 2:
        gy2 = gy
    else:
        gy2 = gy - 1
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def format_jalali_date(ts: float) -> str:
    lt = time.localtime(ts)
    jy, jm, jd = gregorian_to_jalali(lt.tm_year, lt.tm_mon, lt.tm_mday)
    return f"{jy:04d}/{jm:02d}/{jd:02d} {lt.tm_hour:02d}:{lt.tm_min:02d}"

def format_bytes(size: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size) < 1024.0:
            return f"{size:3.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def get_dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat().st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += get_dir_size(Path(entry.path))
            except (OSError, PermissionError):
                continue
    except (OSError, PermissionError):
        pass
    return total


@dataclass
class SessionItem:
    id: str
    filename: str
    path: str
    size_bytes: int
    size_human: str
    modified_time: float
    modified_iso: str
    modified_jalali: str
    message_count: int
    user_messages: int
    assistant_messages: int
    approx_tokens: int
    first_prompt: str


@dataclass
class StorageBreakdown:
    total_size: int
    total_human: str
    hermes_path: str
    sessions_size: int
    sessions_human: str
    attachments_size: int
    attachments_human: str
    orphaned_attachments_size: int
    orphaned_attachments_human: str
    logs_size: int
    logs_human: str
    cache_size: int
    cache_human: str
    state_db_size: int
    state_db_human: str
    venv_size: int
    venv_human: str
    skills_size: int
    skills_human: str


class HermesAnalyzer:
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or get_hermes_dir()
        self.webui_dir = self.base_dir / "webui"
        self.sessions_dir = self.webui_dir / "sessions"
        self.attachments_dir = self.webui_dir / "attachments"
        self.logs_dir = self.base_dir / "logs"
        self.cache_dir = self.base_dir / "cache"
        self.state_db = self.base_dir / "state.db"

    def scan_summary(self) -> StorageBreakdown:
        total = get_dir_size(self.base_dir)
        sess_size = get_dir_size(self.sessions_dir)
        att_size = get_dir_size(self.attachments_dir)
        orphaned_size = self.get_orphaned_attachments_size()

        webui_log = self.base_dir / "webui.log"
        logs_size = get_dir_size(self.logs_dir) + (webui_log.stat().st_size if webui_log.exists() else 0)
        cache_size = get_dir_size(self.cache_dir)
        db_size = self.state_db.stat().st_size if self.state_db.exists() else 0
        venv_size = get_dir_size(self.base_dir / "hermes-agent")
        skills_size = get_dir_size(self.base_dir / "skills")

        return StorageBreakdown(
            total_size=total,
            total_human=format_bytes(total),
            hermes_path=str(self.base_dir),
            sessions_size=sess_size,
            sessions_human=format_bytes(sess_size),
            attachments_size=att_size,
            attachments_human=format_bytes(att_size),
            orphaned_attachments_size=orphaned_size,
            orphaned_attachments_human=format_bytes(orphaned_size),
            logs_size=logs_size,
            logs_human=format_bytes(logs_size),
            cache_size=cache_size,
            cache_human=format_bytes(cache_size),
            state_db_size=db_size,
            state_db_human=format_bytes(db_size),
            venv_size=venv_size,
            venv_human=format_bytes(venv_size),
            skills_size=skills_size,
            skills_human=format_bytes(skills_size),
        )

    def scan_sessions(self, min_size_mb: float = 0.0) -> List[SessionItem]:
        results: List[SessionItem] = []
        if not self.sessions_dir.exists():
            return results

        min_bytes = int(min_size_mb * 1024 * 1024)

        for file in self.sessions_dir.glob("*.json"):
            try:
                st = file.stat()
                if st.st_size < min_bytes:
                    continue

                msg_count = 0
                user_msgs = 0
                asst_msgs = 0
                approx_tokens = 0
                snippet = "Empty or binary session"

                if st.st_size < 35 * 1024 * 1024:
                    try:
                        with open(file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            msgs = []
                            if isinstance(data, list):
                                msgs = data
                            elif isinstance(data, dict):
                                msgs = data.get("messages", [])
                                if "title" in data:
                                    snippet = str(data["title"])

                            msg_count = len(msgs)
                            total_chars = 0
                            for m in msgs:
                                if isinstance(m, dict):
                                    role = m.get("role", "")
                                    if role == "user":
                                        user_msgs += 1
                                        c = m.get("content", "")
                                        if isinstance(c, str) and c.strip() and snippet in ("Empty or binary session", "Session"):
                                            snippet = c.strip().split("\n")[0][:120]
                                    elif role == "assistant":
                                        asst_msgs += 1
                                    
                                    cnt = m.get("content", "")
                                    if isinstance(cnt, str):
                                        total_chars += len(cnt)

                            approx_tokens = total_chars // 4
                    except Exception:
                        snippet = "Unparsed JSON structure"
                else:
                    snippet = f"Large raw session log ({format_bytes(st.st_size)})"
                    approx_tokens = st.st_size // 4

                results.append(
                    SessionItem(
                        id=file.stem,
                        filename=file.name,
                        path=str(file),
                        size_bytes=st.st_size,
                        size_human=format_bytes(st.st_size),
                        modified_time=st.st_mtime,
                        modified_iso=time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                        modified_jalali=format_jalali_date(st.st_mtime),
                        message_count=msg_count,
                        user_messages=user_msgs,
                        assistant_messages=asst_msgs,
                        approx_tokens=approx_tokens,
                        first_prompt=snippet,
                    )
                )
            except (OSError, PermissionError):
                continue

        results.sort(key=lambda s: s.size_bytes, reverse=True)
        return results

    def get_orphaned_attachments_size(self) -> int:
        if not self.attachments_dir.exists():
            return 0
        existing_sessions = {f.stem for f in self.sessions_dir.glob("*.json")} if self.sessions_dir.exists() else set()
        orphaned_size = 0
        for entry in self.attachments_dir.iterdir():
            if entry.name not in existing_sessions:
                orphaned_size += get_dir_size(entry)
        return orphaned_size

    def clean_orphaned_attachments(self) -> int:
        if not self.attachments_dir.exists():
            return 0
        existing_sessions = {f.stem for f in self.sessions_dir.glob("*.json")} if self.sessions_dir.exists() else set()
        freed = 0
        for entry in self.attachments_dir.iterdir():
            if entry.name not in existing_sessions:
                size = get_dir_size(entry)
                try:
                    if entry.is_dir():
                        shutil.rmtree(entry, ignore_errors=True)
                    else:
                        entry.unlink()
                    freed += size
                except OSError:
                    pass
        return freed

    def export_session_zip(self, session_id: str) -> Optional[bytes]:
        session_file = self.sessions_dir / f"{session_id}.json"
        if not session_file.exists():
            return None

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(session_file, arcname=f"session_{session_id}.json")
            att_dir = self.attachments_dir / session_id
            if att_dir.exists() and att_dir.is_dir():
                for root, _, files in os.walk(att_dir):
                    for file in files:
                        full_path = Path(root) / file
                        rel_path = full_path.relative_to(self.attachments_dir)
                        zf.write(full_path, arcname=f"attachments/{rel_path}")

        buf.seek(0)
        return buf.getvalue()

    def delete_session(self, session_id: str) -> bool:
        target = self.sessions_dir / f"{session_id}.json"
        deleted = False
        if target.exists():
            target.unlink()
            deleted = True

        att_dir = self.attachments_dir / session_id
        if att_dir.exists() and att_dir.is_dir():
            shutil.rmtree(att_dir, ignore_errors=True)

        return deleted

    def clean_logs(self) -> int:
        freed = 0
        webui_log = self.base_dir / "webui.log"
        if webui_log.exists():
            try:
                freed += webui_log.stat().st_size
                webui_log.write_text("", encoding="utf-8")
            except OSError:
                pass

        if self.logs_dir.exists():
            for f in self.logs_dir.glob("*.log*"):
                try:
                    freed += f.stat().st_size
                    f.unlink()
                except OSError:
                    pass
        return freed

    def clean_cache(self) -> int:
        freed = 0
        if self.cache_dir.exists():
            for entry in self.cache_dir.iterdir():
                try:
                    size = get_dir_size(entry)
                    if entry.is_file():
                        entry.unlink()
                    elif entry.is_dir():
                        shutil.rmtree(entry, ignore_errors=True)
                    freed += size
                except OSError:
                    pass
        return freed

    def vacuum_db(self) -> int:
        if not self.state_db.exists():
            return 0
        before = self.state_db.stat().st_size
        try:
            conn = sqlite3.connect(str(self.state_db))
            conn.execute("VACUUM;")
            conn.close()
            after = self.state_db.stat().st_size
            return max(0, before - after)
        except Exception:
            return 0


HTML_PAGE = """<!DOCTYPE html>
<html lang="fa" dir="rtl" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Hermes Storage Optimizer | بهینه‌ساز حافظه هرمس</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;700;900&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Vazirmatn', system-ui, -apple-system, sans-serif; background-color: #080c14; }
    html[dir="ltr"] body { font-family: system-ui, -apple-system, sans-serif; }
  </style>
</head>
<body class="text-slate-100 min-h-screen p-4 md:p-8 flex flex-col items-center">
  <div class="max-w-6xl w-full space-y-6">
    
    <!-- Header -->
    <header class="bg-slate-900/80 border border-slate-800 rounded-2xl p-6 shadow-2xl backdrop-blur flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
      <div class="flex items-center gap-3">
        <div class="w-12 h-12 rounded-xl bg-sky-500/10 text-sky-400 border border-sky-500/20 flex items-center justify-center font-bold text-2xl">
          ⚡
        </div>
        <div>
          <h1 class="text-2xl font-black text-white flex items-center gap-2">
            <span>Hermes Storage Optimizer</span>
            <span class="text-xs px-2.5 py-0.5 rounded-full bg-sky-500/20 text-sky-300 border border-sky-500/30">v1.1.0</span>
          </h1>
          <p class="text-xs text-slate-400 mt-1">پاکسازی سشن‌های فوق سنگین، کش‌ها و بهینه‌سازی سرعت لوکال هرمس</p>
        </div>
      </div>
      <div class="flex items-center gap-2.5">
        <button onclick="toggleLang()" class="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs border border-slate-700 font-semibold transition-colors" id="btnLang">English</button>
        <button onclick="loadAll()" class="px-4 py-1.5 rounded-xl bg-sky-500 hover:bg-sky-400 text-slate-950 font-bold text-xs shadow-lg shadow-sky-500/10 transition-colors" id="btnRefresh">🔄 تازه‌سازی</button>
      </div>
    </header>

    <!-- Visual Storage Distribution Bar -->
    <section class="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-3">
      <div class="flex items-center justify-between">
        <h3 class="text-xs font-bold text-slate-300 flex items-center gap-2">
          <span>📊</span> <span id="titleDistribution">نمودار توزیع فضای ذخیره‌سازی هرمس</span>
        </h3>
        <span class="text-xs font-mono text-sky-400 font-bold" id="distTotalLabel">--</span>
      </div>
      <div class="w-full h-4 rounded-full bg-slate-950 overflow-hidden flex" id="distBar">
        <!-- Segments injected dynamically -->
      </div>
      <div class="flex flex-wrap items-center gap-4 text-[11px] pt-1" id="distLegend">
        <!-- Legend injected dynamically -->
      </div>
    </section>

    <!-- Storage Stats Grid -->
    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3" id="statsGrid">
      <div class="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-1">
        <div class="text-[11px] text-slate-400" id="lblTotal">کل فضای هرمس</div>
        <div class="text-lg font-black text-sky-400 font-mono" id="statTotal">--</div>
      </div>
      <div class="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-1">
        <div class="text-[11px] text-slate-400" id="lblSessions">سشن‌های گفتگو</div>
        <div class="text-lg font-black text-amber-400 font-mono" id="statSessions">--</div>
      </div>
      <div class="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-1">
        <div class="text-[11px] text-slate-400" id="lblVenv">محیط و کتابخانه‌ها</div>
        <div class="text-lg font-black text-slate-300 font-mono" id="statVenv">--</div>
      </div>
      <div class="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-1">
        <div class="text-[11px] text-slate-400" id="lblLogs">فایل‌های لاگ</div>
        <div class="text-lg font-black text-rose-400 font-mono" id="statLogs">--</div>
      </div>
      <div class="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-1">
        <div class="text-[11px] text-slate-400" id="lblCache">فایل‌های کش</div>
        <div class="text-lg font-black text-emerald-400 font-mono" id="statCache">--</div>
      </div>
      <div class="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-1">
        <div class="text-[11px] text-slate-400" id="lblDb">دیتابیس وضعیت</div>
        <div class="text-lg font-black text-indigo-400 font-mono" id="statDb">--</div>
      </div>
    </div>

    <!-- Quick Maintenance Bar -->
    <section class="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-3">
      <div class="flex items-center justify-between">
        <h2 class="text-sm font-bold text-white flex items-center gap-2">
          <span>🛠️</span> <span id="titleQuickActions">اقدامات نگهداری فوری (بدون از دست رفتن چت‌ها)</span>
        </h2>
        <span class="text-[11px] text-slate-400">کاملاً امن و بدون دست‌خوردن به پیام‌ها</span>
      </div>
      <div class="flex flex-wrap gap-2.5 pt-1">
        
        <!-- Clean Logs Button with Info Icon -->
        <div class="flex items-center rounded-xl bg-slate-800 border border-slate-700 p-0.5 shadow-sm">
          <button onclick="cleanLogs()" class="px-3 py-1.5 hover:bg-slate-700/80 rounded-lg text-xs text-slate-200 transition-colors flex items-center gap-1.5">
            <span>🧹</span> <span id="btnCleanLogs">تخلیه لاگ‌های حجیم</span>
            <span id="badgeLogsSize" class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/30">--</span>
          </button>
          <button onclick="showInfo('infoLogs')" class="px-2 py-1 text-slate-400 hover:text-sky-300 font-serif italic font-bold text-xs" title="توضیحات">
            ⓘ
          </button>
        </div>

        <!-- Clean Cache Button with Info Icon -->
        <div class="flex items-center rounded-xl bg-slate-800 border border-slate-700 p-0.5 shadow-sm">
          <button onclick="cleanCache()" class="px-3 py-1.5 hover:bg-slate-700/80 rounded-lg text-xs text-slate-200 transition-colors flex items-center gap-1.5">
            <span>🗑️</span> <span id="btnCleanCache">پاکسازی کش موقت</span>
            <span id="badgeCacheSize" class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">--</span>
          </button>
          <button onclick="showInfo('infoCache')" class="px-2 py-1 text-slate-400 hover:text-sky-300 font-serif italic font-bold text-xs" title="توضیحات">
            ⓘ
          </button>
        </div>

        <!-- Vacuum DB Button with Info Icon -->
        <div class="flex items-center rounded-xl bg-slate-800 border border-slate-700 p-0.5 shadow-sm">
          <button onclick="vacuumDb()" class="px-3 py-1.5 hover:bg-slate-700/80 rounded-lg text-xs text-slate-200 transition-colors flex items-center gap-1.5">
            <span>🗜️</span> <span id="btnVacuum">فشرده‌سازی دیتابیس (Vacuum)</span>
            <span id="badgeDbSize" class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">--</span>
          </button>
          <button onclick="showInfo('infoVacuum')" class="px-2 py-1 text-slate-400 hover:text-sky-300 font-serif italic font-bold text-xs" title="توضیحات">
            ⓘ
          </button>
        </div>

        <!-- Clean Orphaned Attachments Button with Info Icon -->
        <div class="flex items-center rounded-xl bg-slate-800 border border-slate-700 p-0.5 shadow-sm">
          <button onclick="cleanOrphaned()" class="px-3 py-1.5 hover:bg-slate-700/80 rounded-lg text-xs text-slate-200 transition-colors flex items-center gap-1.5">
            <span>📁</span> <span id="btnCleanOrphaned">حذف ضمیمه‌های یتیم</span>
            <span id="badgeOrphanedSize" class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30">--</span>
          </button>
          <button onclick="showInfo('infoOrphaned')" class="px-2 py-1 text-slate-400 hover:text-sky-300 font-serif italic font-bold text-xs" title="توضیحات">
            ⓘ
          </button>
        </div>

      </div>
    </section>

    <!-- Sessions Management -->
    <section class="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 class="text-base font-bold text-white flex items-center gap-2">
            <span>💬</span> <span id="titleSessions">مدیریت سشن‌های سنگین هرمس (Chat Sessions)</span>
          </h2>
          <p class="text-xs text-slate-400 mt-0.5" id="descSessions">چت‌های بسیار حجیم موجب افت سرعت لوکال WebUI و افزایش مصرف توکن می‌شوند.</p>
        </div>
        <div class="flex items-center gap-2">
          <select id="filterSize" onchange="loadSessions()" class="bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-300 focus:outline-none">
            <option value="0">همه سشن‌ها</option>
            <option value="5" selected>بزرگ‌تر از ۵ مگابایت</option>
            <option value="20">بزرگ‌تر از ۲۰ مگابایت</option>
            <option value="100">فوق سنگین (۱۰۰+ مگابایت)</option>
          </select>
          <span id="sessionsCountBadge" class="text-xs font-mono px-2.5 py-1 rounded bg-slate-800 text-sky-400 border border-slate-700">0 سشن</span>
        </div>
      </div>

      <!-- Sessions List -->
      <div class="overflow-x-auto">
        <table class="w-full text-right text-xs">
          <thead>
            <tr class="border-b border-slate-800 text-slate-400">
              <th class="py-2.5 px-3" id="thId">شناسه سشن</th>
              <th class="py-2.5 px-3" id="thPrompt">عنوان / پرامپت</th>
              <th class="py-2.5 px-3 text-center" id="thTokens">تخمین توکن</th>
              <th class="py-2.5 px-3 text-center" id="thSize">حجم فایل</th>
              <th class="py-2.5 px-3 text-center" id="thDate">آخرین تغییر</th>
              <th class="py-2.5 px-3 text-center" id="thAction">عملیات</th>
            </tr>
          </thead>
          <tbody id="sessionsTbody" class="divide-y divide-slate-800/60">
            <tr><td colspan="6" class="py-6 text-center text-slate-500">در حال بررسی سشن‌ها...</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- Footer -->
    <footer class="text-center text-xs text-slate-500 py-3">
      Hermes Storage Optimizer • Open-Source Maintenance Tool for Hermes Agent
    </footer>

  </div>

  <!-- Info Modal -->
  <div id="infoModal" class="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 hidden">
    <div class="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl relative text-right">
      <button onclick="closeInfoModal()" class="absolute top-4 left-4 text-slate-400 hover:text-white text-lg">✕</button>
      <div class="flex items-center gap-2">
        <span class="w-8 h-8 rounded-lg bg-sky-500/10 text-sky-400 border border-sky-500/20 flex items-center justify-center font-bold">ℹ</span>
        <h4 class="text-base font-bold text-white" id="infoModalTitle">راهنما</h4>
      </div>
      <p class="text-xs text-slate-300 leading-relaxed" id="infoModalBody"></p>
      <div class="flex justify-end pt-2">
        <button onclick="closeInfoModal()" class="px-4 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold">بستن</button>
      </div>
    </div>
  </div>

  <script>
    let currentLang = 'fa';
    let summaryData = null;

    const I18N = {
      fa: {
        langBtn: "English",
        lblTotal: "کل فضای هرمس",
        lblSessions: "سشن‌های گفتگو",
        lblVenv: "محیط و کتابخانه‌ها",
        lblLogs: "فایل‌های لاگ",
        lblCache: "فایل‌های کش",
        lblDb: "دیتابیس وضعیت",
        titleDistribution: "نمودار توزیع فضای ذخیره‌سازی هرمس",
        titleQuickActions: "اقدامات نگهداری فوری (بدون از دست رفتن چت‌ها)",
        btnCleanLogs: "تخلیه لاگ‌های حجیم",
        btnCleanCache: "پاکسازی کش موقت",
        btnVacuum: "فشرده‌سازی دیتابیس (Vacuum)",
        btnCleanOrphaned: "حذف ضمیمه‌های یتیم",
        titleSessions: "مدیریت سشن‌های سنگین هرمس (Chat Sessions)",
        descSessions: "چت‌های بسیار حجیم موجب افت سرعت لوکال WebUI و افزایش مصرف توکن می‌شوند.",
        thId: "شناسه سشن",
        thPrompt: "عنوان / پرامپت",
        thTokens: "تخمین توکن",
        thSize: "حجم فایل",
        thDate: "آخرین تغییر",
        thAction: "عملیات",
        btnDelete: "حذف",
        btnExport: "آرشیو (ZIP)",
        btnOpenChat: "مشاهده در WebUI",
        confirmDelete: "آیا از حذف این سشن مطمئن هستید؟ فایل‌های ضمیمه آن نیز پاک خواهند شد.",
        emptySessions: "هیچ سشنی با این فیلتر حجم یافت نشد.",
        infoLogsTitle: "تخلیه لاگ‌های حجیم",
        infoLogsBody: "هرمس تمام خطاهای کلاینت، درخواست‌های ترمینال و لاگ‌های وب‌پنل را در فایل‌هایی مثل webui.log ذخیره می‌کند که با گذشت زمان به صدها مگابایت می‌رسند. این عملیات بدون پاک کردن اصل فایل، حجم آن را صفر بایت می‌کند تا فضای هارد آزاد شود بدون اینکه در سرور اختلالی ایجاد شود.",
        infoCacheTitle: "پاکسازی کش موقت",
        infoCacheBody: "در پوشه cache فایل‌های موقت تولید صدا (Whisper)، پاسخ‌های واسط مدل‌ها و کش پیش‌نمایش‌ها نگهداری می‌شوند. پاکسازی این بخش ۱۰۰٪ امن است و هیچ چت یا تنظیمی را پاک نمی‌کند.",
        infoVacuumTitle: "فشرده‌سازی دیتابیس (Vacuum)",
        infoVacuumBody: "دیتابیس state.db هرمس بر پایه SQLite است. در SQLite وقتی رکوردی حذف می‌شود، فضای اشغال‌شده روی هارد آزاد نمی‌شود و صفحات خالی داخل فایل باقی می‌مانند. دستور VACUUM کل دیتابیس را بازسازی کرده و فضای خالی آزاد شده را به هارد برمی‌گرداند.",
        infoOrphanedTitle: "حذف ضمیمه‌های یتیم (Orphaned Attachments)",
        infoOrphanedBody: "گاهی اوقات تصاویری که در چت‌ها آپلود شده‌اند در پوشه attachments باقی می‌مانند در حالی که خود چت مدت‌ها پیش پاک شده است. این ابزار این پوشه‌های بی‌صاحب را پیدا کرده و با حذف آن‌ها فضای هارد را پس می‌گیرد.",
      },
      en: {
        langBtn: "فارسی",
        lblTotal: "Total Hermes Size",
        lblSessions: "Chat Sessions",
        lblVenv: "Virtualenv & Deps",
        lblLogs: "Log Files",
        lblCache: "Caches",
        lblDb: "State SQLite DB",
        titleDistribution: "Hermes Storage Distribution",
        titleQuickActions: "Safe Quick Maintenance (No Chat Loss)",
        btnCleanLogs: "Clear Log Files",
        btnCleanCache: "Purge Cache",
        btnVacuum: "Vacuum SQLite DB",
        btnCleanOrphaned: "Purge Orphaned Assets",
        titleSessions: "Heavy Sessions Manager (Chat Sessions)",
        descSessions: "Extremely heavy chat sessions slow down the local WebUI and inflate token overhead.",
        thId: "Session ID",
        thPrompt: "Snippet / Prompt",
        thTokens: "Tokens (est.)",
        thSize: "File Size",
        thDate: "Last Modified",
        thAction: "Action",
        btnDelete: "Delete",
        btnExport: "Archive (ZIP)",
        btnOpenChat: "Open in WebUI",
        confirmDelete: "Are you sure you want to delete this session? Attached assets will be deleted too.",
        emptySessions: "No sessions matched the current size filter.",
        infoLogsTitle: "Clear Large Log Files",
        infoLogsBody: "Hermes records client errors, terminal activities, and WebUI runtime logs in files such as webui.log. Over time, these files grow into hundreds of megabytes. This operation safely truncates log files to 0 bytes without disrupting running server processes.",
        infoCacheTitle: "Purge Temporary Cache",
        infoCacheBody: "The cache folder contains transient voice transcripts (Whisper), preview chunks, and temporary model buffers. Purging this folder is 100% safe and preserves all your actual chats and configurations.",
        infoVacuumTitle: "Defragment SQLite Database (VACUUM)",
        infoVacuumBody: "Hermes state.db runs on SQLite. Deleting records leaves free fragmented pages inside the file without reducing disk size. The VACUUM command rebuilds the database file and reclaims freed disk space.",
        infoOrphanedTitle: "Purge Orphaned Attachments",
        infoOrphanedBody: "Uploaded media and images sometimes linger in webui/attachments even after their corresponding chat session was deleted. This scanner detects and deletes these orphaned folders to reclaim wasted disk space.",
      }
    };

    function showInfo(topic) {
      const dict = I18N[currentLang];
      const modal = document.getElementById('infoModal');
      const title = document.getElementById('infoModalTitle');
      const body = document.getElementById('infoModalBody');

      if (topic === 'infoLogs') {
        title.textContent = dict.infoLogsTitle;
        body.textContent = dict.infoLogsBody;
      } else if (topic === 'infoCache') {
        title.textContent = dict.infoCacheTitle;
        body.textContent = dict.infoCacheBody;
      } else if (topic === 'infoVacuum') {
        title.textContent = dict.infoVacuumTitle;
        body.textContent = dict.infoVacuumBody;
      } else if (topic === 'infoOrphaned') {
        title.textContent = dict.infoOrphanedTitle;
        body.textContent = dict.infoOrphanedBody;
      }
      modal.classList.remove('hidden');
    }

    function closeInfoModal() {
      document.getElementById('infoModal').classList.add('hidden');
    }

    function toggleLang() {
      currentLang = currentLang === 'fa' ? 'en' : 'fa';
      const dict = I18N[currentLang];
      const html = document.documentElement;
      if (currentLang === 'fa') {
        html.setAttribute('dir', 'rtl');
        html.setAttribute('lang', 'fa');
      } else {
        html.setAttribute('dir', 'ltr');
        html.setAttribute('lang', 'en');
      }

      document.getElementById('btnLang').textContent = dict.langBtn;
      for (const [k, v] of Object.entries(dict)) {
        const el = document.getElementById(k);
        if (el) el.textContent = v;
      }
      if (summaryData) renderDistribution(summaryData);
      loadSessions();
    }

    function renderDistribution(data) {
      const bar = document.getElementById('distBar');
      const legend = document.getElementById('distLegend');
      const total = data.total_size || 1;
      document.getElementById('distTotalLabel').textContent = data.total_human;

      const items = [
        { label: currentLang === 'fa' ? 'سشن‌ها' : 'Sessions', size: data.sessions_size, human: data.sessions_human, color: 'bg-amber-500' },
        { label: currentLang === 'fa' ? 'محیط venv' : 'Virtualenv', size: data.venv_size, human: data.venv_human, color: 'bg-slate-500' },
        { label: currentLang === 'fa' ? 'دیتابیس' : 'Database', size: data.state_db_size, human: data.state_db_human, color: 'bg-indigo-500' },
        { label: currentLang === 'fa' ? 'لاگ‌ها' : 'Logs', size: data.logs_size, human: data.logs_human, color: 'bg-rose-500' },
        { label: currentLang === 'fa' ? 'کش‌ها' : 'Cache', size: data.cache_size, human: data.cache_human, color: 'bg-emerald-500' },
        { label: currentLang === 'fa' ? 'ضمیمه‌ها' : 'Attachments', size: data.attachments_size, human: data.attachments_human, color: 'bg-sky-500' },
      ];

      bar.innerHTML = items.map(it => {
        const pct = Math.max(1, ((it.size / total) * 100)).toFixed(1);
        return `<div class="${it.color} h-full" style="width: ${pct}%" title="${it.label}: ${it.human} (${pct}%)"></div>`;
      }).join('');

      legend.innerHTML = items.map(it => `
        <div class="flex items-center gap-1.5 text-slate-300">
          <span class="w-2.5 h-2.5 rounded-full ${it.color}"></span>
          <span>${it.label}:</span>
          <span class="font-mono text-slate-400 font-bold">${it.human}</span>
        </div>
      `).join('');
    }

    async function loadSummary() {
      try {
        const res = await fetch('/api/summary');
        const data = await res.json();
        summaryData = data;
        document.getElementById('statTotal').textContent = data.total_human;
        document.getElementById('statSessions').textContent = data.sessions_human;
        document.getElementById('statVenv').textContent = data.venv_human;
        document.getElementById('statLogs').textContent = data.logs_human;
        document.getElementById('statCache').textContent = data.cache_human;
        document.getElementById('statDb').textContent = data.state_db_human;

        document.getElementById('badgeLogsSize').textContent = '~' + data.logs_human;
        document.getElementById('badgeCacheSize').textContent = '~' + data.cache_human;
        document.getElementById('badgeDbSize').textContent = '~' + data.state_db_human;
        document.getElementById('badgeOrphanedSize').textContent = data.orphaned_attachments_human;

        renderDistribution(data);
      } catch (err) {
        console.error(err);
      }
    }

    async function loadSessions() {
      const minMb = document.getElementById('filterSize').value;
      const tbody = document.getElementById('sessionsTbody');
      const badge = document.getElementById('sessionsCountBadge');
      const dict = I18N[currentLang];

      try {
        const res = await fetch('/api/sessions?min_mb=' + minMb);
        const data = await res.json();
        badge.textContent = data.length + (currentLang === 'fa' ? ' سشن' : ' session(s)');

        if (!data.length) {
          tbody.innerHTML = `<tr><td colspan="6" class="py-6 text-center text-slate-500">${dict.emptySessions}</td></tr>`;
          return;
        }

        tbody.innerHTML = data.map(s => {
          const isGigantic = s.size_bytes > 50 * 1024 * 1024;
          const sizeColor = isGigantic ? 'text-rose-400 font-black' : (s.size_bytes > 10 * 1024 * 1024 ? 'text-amber-400 font-bold' : 'text-slate-300 font-mono');
          const tokenStr = s.approx_tokens > 1000 ? (s.approx_tokens / 1000).toFixed(1) + 'k' : s.approx_tokens;

          return `
            <tr class="hover:bg-slate-800/40 transition-colors">
              <td class="py-2.5 px-3 font-mono text-sky-400 font-semibold">${s.id}</td>
              <td class="py-2.5 px-3 max-w-sm truncate text-slate-300" title="${s.first_prompt}">
                <div class="truncate font-medium">${s.first_prompt}</div>
                <div class="text-[10px] text-slate-400 mt-0.5 flex items-center gap-1.5">
                  <span class="text-sky-400 font-bold">${s.user_messages} پیام شما</span>
                  <span>•</span>
                  <span class="text-slate-300">${s.assistant_messages} پاسخ هوش مصنوعی</span>
                </div>
              </td>
              <td class="py-2.5 px-3 text-center font-mono text-slate-300 font-semibold">~${tokenStr}</td>
              <td class="py-2.5 px-3 text-center ${sizeColor}">${s.size_human}</td>
              <td class="py-2.5 px-3 text-center text-slate-300 font-mono text-[11px]" dir="ltr">${currentLang === 'fa' ? s.modified_jalali : s.modified_iso}</td>
              <td class="py-2.5 px-3 text-center flex items-center justify-center gap-1.5 flex-wrap">
                <a href="http://127.0.0.1:8787/?session=${s.id}" target="_blank" class="px-2 py-1 rounded-lg bg-sky-500/10 hover:bg-sky-500/20 text-sky-300 border border-sky-500/30 text-[11px] transition-colors" title="نمایش در پنل وب هرمس">
                  ↗️ ${dict.btnOpenChat}
                </a>
                <a href="/api/export_session?session_id=${s.id}" download class="px-2 py-1 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-[11px] transition-colors" title="دانلود فایل زیپ بکاپ">
                  📦 ${dict.btnExport}
                </a>
                <button onclick="deleteSession('${s.id}')" class="px-2 py-1 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 text-[11px] transition-colors" title="حذف دائمی سشن">
                  🗑️ ${dict.btnDelete}
                </button>
              </td>
            </tr>
          `;
        }).join('');
      } catch (err) {
        tbody.innerHTML = `<tr><td colspan="6" class="py-6 text-center text-rose-400">Error: ${err}</td></tr>`;
      }
    }

    async function deleteSession(id) {
      const dict = I18N[currentLang];
      if (!confirm(`${dict.confirmDelete} (${id})`)) return;

      try {
        const res = await fetch('/api/delete_session', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ session_id: id })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          loadAll();
        } else {
          alert('Error: ' + data.message);
        }
      } catch (err) {
        alert(err);
      }
    }

    async function cleanLogs() {
      try {
        const res = await fetch('/api/clean_logs', { method: 'POST' });
        const data = await res.json();
        alert((currentLang === 'fa' ? 'فایل‌های لاگ با موفقیت پاک شدند. فضای آزاد شده: ' : 'Logs purged successfully. Freed: ') + data.freed_human);
        loadAll();
      } catch (err) { alert(err); }
    }

    async function cleanCache() {
      try {
        const res = await fetch('/api/clean_cache', { method: 'POST' });
        const data = await res.json();
        alert((currentLang === 'fa' ? 'کش‌های موقت با موفقیت پاک شدند. فضای آزاد شده: ' : 'Cache purged successfully. Freed: ') + data.freed_human);
        loadAll();
      } catch (err) { alert(err); }
    }

    async function vacuumDb() {
      try {
        const res = await fetch('/api/vacuum', { method: 'POST' });
        const data = await res.json();
        alert((currentLang === 'fa' ? 'دیتابیس فشرده‌سازی شد. فضای آزاد شده: ' : 'Database vacuumed successfully. Freed: ') + data.freed_human);
        loadAll();
      } catch (err) { alert(err); }
    }

    async function cleanOrphaned() {
      try {
        const res = await fetch('/api/clean_orphaned', { method: 'POST' });
        const data = await res.json();
        alert((currentLang === 'fa' ? 'ضمیمه‌های یتیم پاکسازی شدند. فضای آزاد شده: ' : 'Orphaned attachments purged. Freed: ') + data.freed_human);
        loadAll();
      } catch (err) { alert(err); }
    }

    function loadAll() {
      loadSummary();
      loadSessions();
    }

    loadAll();
  </script>
</body>
</html>
"""


class WizardRequestHandler(http.server.BaseHTTPRequestHandler):
    analyzer = HermesAnalyzer()

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif self.path == "/api/summary":
            summary = self.analyzer.scan_summary()
            self.send_json(asdict(summary))
        elif self.path.startswith("/api/sessions"):
            from urllib.parse import parse_qs, urlparse

            qs = parse_qs(urlparse(self.path).query)
            min_mb = float(qs.get("min_mb", [0])[0])
            sessions = self.analyzer.scan_sessions(min_size_mb=min_mb)
            self.send_json([asdict(s) for s in sessions])
        elif self.path.startswith("/api/export_session"):
            from urllib.parse import parse_qs, urlparse

            qs = parse_qs(urlparse(self.path).query)
            sid = str(qs.get("session_id", [""])[0]).strip()
            zip_bytes = self.analyzer.export_session_zip(sid)
            if zip_bytes is None:
                self.send_response(404)
                self.end_headers()
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="hermes_session_{sid}.zip"')
            self.end_headers()
            self.wfile.write(zip_bytes)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            data = json.loads(body)
        except Exception:
            data = {}

        if self.path == "/api/delete_session":
            sid = str(data.get("session_id", "")).strip()
            if not sid:
                self.send_json({"status": "error", "message": "Missing session_id"}, status_code=400)
                return
            ok = self.analyzer.delete_session(sid)
            self.send_json({"status": "ok" if ok else "not_found"})
        elif self.path == "/api/clean_logs":
            freed = self.analyzer.clean_logs()
            self.send_json({"status": "ok", "freed_bytes": freed, "freed_human": format_bytes(freed)})
        elif self.path == "/api/clean_cache":
            freed = self.analyzer.clean_cache()
            self.send_json({"status": "ok", "freed_bytes": freed, "freed_human": format_bytes(freed)})
        elif self.path == "/api/vacuum":
            freed = self.analyzer.vacuum_db()
            self.send_json({"status": "ok", "freed_bytes": freed, "freed_human": format_bytes(freed)})
        elif self.path == "/api/clean_orphaned":
            freed = self.analyzer.clean_orphaned_attachments()
            self.send_json({"status": "ok", "freed_bytes": freed, "freed_human": format_bytes(freed)})
        else:
            self.send_response(404)
            self.end_headers()

    def send_json(self, payload: Any, status_code: int = 200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        pass


def run_web_wizard(port: int = 9123):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), WizardRequestHandler)
    url = f"http://127.0.0.1:{port}"
    print(f"\n=======================================================")
    print(f"  ⚡ Hermes Storage & Session Optimizer")
    print(f"  🔗 Wizard Dashboard: {url}")
    print(f"  Press Ctrl+C to stop.")
    print(f"=======================================================\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down wizard.")


def run_cli_inspect():
    analyzer = HermesAnalyzer()
    s = analyzer.scan_summary()
    print("\n--- Hermes Storage Summary ---")
    print(f"Base Directory   : {s.hermes_path}")
    print(f"Total Size       : {s.total_human}")
    print(f"Sessions         : {s.sessions_human}")
    print(f"Virtualenv (venv): {s.venv_human}")
    print(f"Logs             : {s.logs_human}")
    print(f"Caches           : {s.cache_human}")
    print(f"State DB (sqlite): {s.state_db_human}")
    print(f"Attachments      : {s.attachments_human} (Orphaned: {s.orphaned_attachments_human})")

    heavy = analyzer.scan_sessions(min_size_mb=10.0)
    if heavy:
        print(f"\nTop Heavy Sessions (>10 MB):")
        for item in heavy[:5]:
            print(f" - [{item.id}] {item.size_human} (~{item.approx_tokens//1000}k tokens) -> {item.first_prompt[:60]}")
    print("")


def main():
    parser = argparse.ArgumentParser(description="Hermes Storage & Session Optimizer")
    parser.add_argument("--ui", action="store_true", help="Launch interactive web wizard")
    parser.add_argument("--port", type=int, default=9123, help="Port for the web wizard (default: 9123)")
    parser.add_argument("--clean-logs", action="store_true", help="Safely purge large log files")
    parser.add_argument("--clean-cache", action="store_true", help="Purge temporary cache files")
    parser.add_argument("--vacuum", action="store_true", help="Vacuum state.db SQLite database")
    parser.add_argument("--clean-orphaned", action="store_true", help="Purge orphaned attachments")
    args = parser.parse_args()

    if args.ui:
        run_web_wizard(port=args.port)
    elif args.clean_logs:
        freed = HermesAnalyzer().clean_logs()
        print(f"Cleared logs: freed {format_bytes(freed)}")
    elif args.clean_cache:
        freed = HermesAnalyzer().clean_cache()
        print(f"Cleared cache: freed {format_bytes(freed)}")
    elif args.vacuum:
        freed = HermesAnalyzer().vacuum_db()
        print(f"Vacuumed SQLite DB: freed {format_bytes(freed)}")
    elif args.clean_orphaned:
        freed = HermesAnalyzer().clean_orphaned_attachments()
        print(f"Cleared orphaned attachments: freed {format_bytes(freed)}")
    else:
        run_cli_inspect()
        print("Tip: Run with --ui to open the graphical Web Wizard: python main.py --ui")


if __name__ == "__main__":
    main()
