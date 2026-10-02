#!/usr/bin/env python3
"""
Hermes Storage & Session Optimizer (CLI & Web Wizard)
Safe, standalone cleaner and analyzer for ~/.hermes directories.
"""

from __future__ import annotations

import argparse
import html
import http.server
import json
import os
import shutil
import sqlite3
import sys
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_hermes_dir() -> Path:
    env_dir = os.getenv("HERMES_HOME")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    return Path.home() / ".hermes"


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
    message_count: int
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
        logs_size = get_dir_size(self.logs_dir) + (self.base_dir / "webui.log").stat().st_size if (self.base_dir / "webui.log").exists() else 0
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
                snippet = "Empty or binary session"

                if st.st_size < 30 * 1024 * 1024:
                    try:
                        with open(file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            if isinstance(data, list):
                                msg_count = len(data)
                                for m in data:
                                    if isinstance(m, dict) and m.get("role") == "user":
                                        c = m.get("content", "")
                                        if isinstance(c, str) and c.strip():
                                            snippet = c.strip().split("\n")[0][:120]
                                            break
                            elif isinstance(data, dict):
                                msgs = data.get("messages", [])
                                msg_count = len(msgs)
                                snippet = str(data.get("title", data.get("name", "Session")))
                    except Exception:
                        snippet = "Unparsed JSON structure"
                else:
                    snippet = f"Large raw session log ({format_bytes(st.st_size)})"

                results.append(
                    SessionItem(
                        id=file.stem,
                        filename=file.name,
                        path=str(file),
                        size_bytes=st.st_size,
                        size_human=format_bytes(st.st_size),
                        modified_time=st.st_mtime,
                        modified_iso=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
                        message_count=msg_count,
                        first_prompt=snippet,
                    )
                )
            except (OSError, PermissionError):
                continue

        results.sort(key=lambda s: s.size_bytes, reverse=True)
        return results

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


# Interactive Web Wizard UI
HTML_PAGE = """<!DOCTYPE html>
<html lang="fa" dir="rtl" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Hermes Storage Manager | بهینه‌ساز حافظه هرمس</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;700;900&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Vazirmatn', system-ui, -apple-system, sans-serif; background-color: #080c14; }
    html[dir="ltr"] body { font-family: system-ui, -apple-system, sans-serif; }
  </style>
</head>
<body class="text-slate-100 min-h-screen p-4 md:p-8 flex flex-col items-center">
  <div class="max-w-5xl w-full space-y-6">
    
    <!-- Header -->
    <header class="bg-slate-900/80 border border-slate-800 rounded-2xl p-6 shadow-2xl backdrop-blur flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
      <div class="flex items-center gap-3">
        <div class="w-12 h-12 rounded-xl bg-sky-500/10 text-sky-400 border border-sky-500/20 flex items-center justify-center font-bold text-2xl">
          ⚡
        </div>
        <div>
          <h1 class="text-2xl font-black text-white flex items-center gap-2">
            <span>Hermes Storage Optimizer</span>
            <span class="text-xs px-2.5 py-0.5 rounded-full bg-sky-500/20 text-sky-300 border border-sky-500/30">v1.0.0</span>
          </h1>
          <p class="text-xs text-slate-400 mt-1">پاکسازی سشن‌های فوق سنگین، کش‌ها و بهینه‌سازی سرعت لوکال هرمس</p>
        </div>
      </div>
      <div class="flex items-center gap-2.5">
        <button onclick="toggleLang()" class="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs border border-slate-700 font-semibold transition-colors" id="btnLang">English</button>
        <button onclick="loadAll()" class="px-4 py-1.5 rounded-xl bg-sky-500 hover:bg-sky-400 text-slate-950 font-bold text-xs shadow-lg shadow-sky-500/10 transition-colors" id="btnRefresh">🔄 تازه‌سازی</button>
      </div>
    </header>

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
        <span class="text-[11px] text-slate-400">کاملاً امن و تست‌شده</span>
      </div>
      <div class="flex flex-wrap gap-2.5 pt-1">
        <button onclick="cleanLogs()" class="px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs border border-slate-700 text-slate-200 transition-colors flex items-center gap-1.5">
          <span>🧹</span> <span id="btnCleanLogs">تخلیه لاگ‌های حجیم</span>
        </button>
        <button onclick="cleanCache()" class="px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs border border-slate-700 text-slate-200 transition-colors flex items-center gap-1.5">
          <span>🗑️</span> <span id="btnCleanCache">پاکسازی کش موقت</span>
        </button>
        <button onclick="vacuumDb()" class="px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs border border-slate-700 text-slate-200 transition-colors flex items-center gap-1.5">
          <span>🗜️</span> <span id="btnVacuum">فشرده‌سازی دیتابیس (Vacuum)</span>
        </button>
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
              <th class="py-2.5 px-3 text-center" id="thSize">حجم فایل</th>
              <th class="py-2.5 px-3 text-center" id="thDate">آخرین تغییر</th>
              <th class="py-2.5 px-3 text-center" id="thAction">عملیات</th>
            </tr>
          </thead>
          <tbody id="sessionsTbody" class="divide-y divide-slate-800/60">
            <tr><td colspan="5" class="py-6 text-center text-slate-500">در حال بررسی سشن‌ها...</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- Footer -->
    <footer class="text-center text-xs text-slate-500 py-3">
      Hermes Storage Optimizer • Open-Source Maintenance Tool for Hermes Agent
    </footer>

  </div>

  <script>
    let currentLang = 'fa';

    const I18N = {
      fa: {
        langBtn: "English",
        lblTotal: "کل فضای هرمس",
        lblSessions: "سشن‌های گفتگو",
        lblVenv: "محیط و کتابخانه‌ها",
        lblLogs: "فایل‌های لاگ",
        lblCache: "فایل‌های کش",
        lblDb: "دیتابیس وضعیت",
        titleQuickActions: "اقدامات نگهداری فوری (بدون از دست رفتن چت‌ها)",
        btnCleanLogs: "تخلیه لاگ‌های حجیم",
        btnCleanCache: "پاکسازی کش موقت",
        btnVacuum: "فشرده‌سازی دیتابیس (Vacuum)",
        titleSessions: "مدیریت سشن‌های سنگین هرمس (Chat Sessions)",
        descSessions: "چت‌های بسیار حجیم موجب افت سرعت لوکال WebUI و افزایش مصرف توکن می‌شوند.",
        thId: "شناسه سشن",
        thPrompt: "عنوان / پرامپت",
        thSize: "حجم فایل",
        thDate: "آخرین تغییر",
        thAction: "عملیات",
        btnDelete: "حذف سشن",
        btnOpenChat: "مشاهده در WebUI",
        confirmDelete: "آیا از حذف این سشن مطمئن هستید؟ فایل‌های ضمیمه آن نیز پاک خواهند شد.",
        emptySessions: "هیچ سشنی با این فیلتر حجم یافت نشد.",
      },
      en: {
        langBtn: "فارسی",
        lblTotal: "Total Hermes Size",
        lblSessions: "Chat Sessions",
        lblVenv: "Virtualenv & Deps",
        lblLogs: "Log Files",
        lblCache: "Caches",
        lblDb: "State SQLite DB",
        titleQuickActions: "Safe Quick Maintenance (No Chat Loss)",
        btnCleanLogs: "Clear Log Files",
        btnCleanCache: "Purge Cache",
        btnVacuum: "Vacuum SQLite DB",
        titleSessions: "Heavy Sessions Manager (Chat Sessions)",
        descSessions: "Extremely heavy chat sessions slow down the local WebUI and inflate token overhead.",
        thId: "Session ID",
        thPrompt: "Snippet / Prompt",
        thSize: "File Size",
        thDate: "Last Modified",
        thAction: "Action",
        btnDelete: "Delete",
        btnOpenChat: "Open in WebUI",
        confirmDelete: "Are you sure you want to delete this session? Attached assets will be deleted too.",
        emptySessions: "No sessions matched the current size filter.",
      }
    };

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
      loadSessions();
    }

    async function loadSummary() {
      try {
        const res = await fetch('/api/summary');
        const data = await res.json();
        document.getElementById('statTotal').textContent = data.total_human;
        document.getElementById('statSessions').textContent = data.sessions_human;
        document.getElementById('statVenv').textContent = data.venv_human;
        document.getElementById('statLogs').textContent = data.logs_human;
        document.getElementById('statCache').textContent = data.cache_human;
        document.getElementById('statDb').textContent = data.state_db_human;
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
          tbody.innerHTML = `<tr><td colspan="5" class="py-6 text-center text-slate-500">${dict.emptySessions}</td></tr>`;
          return;
        }

        tbody.innerHTML = data.map(s => {
          const isGigantic = s.size_bytes > 50 * 1024 * 1024;
          const sizeColor = isGigantic ? 'text-rose-400 font-black' : (s.size_bytes > 10 * 1024 * 1024 ? 'text-amber-400 font-bold' : 'text-slate-300 font-mono');
          
          return `
            <tr class="hover:bg-slate-800/40 transition-colors">
              <td class="py-2.5 px-3 font-mono text-sky-400 font-semibold">${s.id}</td>
              <td class="py-2.5 px-3 max-w-md truncate text-slate-300" title="${s.first_prompt}">${s.first_prompt}</td>
              <td class="py-2.5 px-3 text-center ${sizeColor}">${s.size_human}</td>
              <td class="py-2.5 px-3 text-center text-slate-400 font-mono text-[11px]">${s.modified_iso}</td>
              <td class="py-2.5 px-3 text-center flex items-center justify-center gap-1.5">
                <a href="http://127.0.0.1:8787/?session=${s.id}" target="_blank" class="px-2.5 py-1 rounded-lg bg-sky-500/10 hover:bg-sky-500/20 text-sky-300 border border-sky-500/30 text-[11px] transition-colors flex items-center gap-1">
                  ↗️ <span>${dict.btnOpenChat || 'باز کردن'}</span>
                </a>
                <button onclick="deleteSession('${s.id}')" class="px-2.5 py-1 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 text-[11px] transition-colors">
                  🗑️ ${dict.btnDelete}
                </button>
              </td>
            </tr>
          `;
        }).join('');
      } catch (err) {
        tbody.innerHTML = `<tr><td colspan="5" class="py-6 text-center text-rose-400">Error: ${err}</td></tr>`;
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
        else:
            self.send_response(404)
            self.end_headers()

    def send_json(self, payload: Any, status_code: int = 200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        # Mute normal request logs to keep terminal quiet
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

    heavy = analyzer.scan_sessions(min_size_mb=10.0)
    if heavy:
        print(f"\nTop Heavy Sessions (>10 MB):")
        for item in heavy[:5]:
            print(f" - [{item.id}] {item.size_human} (Modified: {item.modified_iso}) -> {item.first_prompt[:60]}")
    print("")


def main():
    parser = argparse.ArgumentParser(description="Hermes Storage & Session Optimizer")
    parser.add_argument("--ui", action="store_true", help="Launch interactive web wizard")
    parser.add_argument("--port", type=int, default=9123, help="Port for the web wizard (default: 9123)")
    parser.add_argument("--clean-logs", action="store_true", help="Safely purge large log files")
    parser.add_argument("--clean-cache", action="store_true", help="Purge temporary cache files")
    parser.add_argument("--vacuum", action="store_true", help="Vacuum state.db SQLite database")
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
    else:
        run_cli_inspect()
        print("Tip: Run with --ui to open the graphical Web Wizard: python main.py --ui")


if __name__ == "__main__":
    main()
