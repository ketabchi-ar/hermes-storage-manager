# Hermes Storage Optimizer ⚡

A lightweight, zero-dependency storage manager and web wizard for **Hermes Agent**.  
Inspects disk usage, identifies bloated chat sessions, purges heavy logs/caches safely, and vacuums SQLite databases.

<div align="center">

[![DevSponsors](https://img.shields.io/badge/DevSponsors-Verified_OSS-6366f1?style=for-the-badge&logo=github)](https://devsponsors.github.io)
[![Sponsor](https://img.shields.io/badge/Sponsor-DevSponsors_Hub-emerald?style=for-the-badge&logo=github-sponsors)](https://devsponsors.github.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[English](#features) • [راهنمای فارسی](#راهنمای-فارسی)

</div>

---

## Features
- **Zero Third-Party Dependencies:** Written in standard Python 3 (`http.server`, `sqlite3`, `zipfile`, `json`, `pathlib`).
- **Interactive Web Wizard (`--ui`):** Beautiful dark-mode dashboard (Bilingual: English / Persian with Vazirmatn font).
- **Interactive Tooltips (ℹ):** Helpful info modals next to every maintenance action explaining why and how it runs.
- **Storage Distribution Bar:** Visual color-coded breakdown of disk consumption (Sessions, Venv, DB, Logs, Cache, Attachments).
- **Token & Message Analytics:** Estimates total message counts (user vs assistant) and context token overhead.
- **1-Click WebUI Deep-Link:** Quick jump to view the actual chat in Hermes WebUI before taking action.
- **1-Click Backup Export:** Download bloated sessions as a standalone `.zip` archive (session JSON + attachments) before deletion.
- **Orphaned Attachments Cleaner:** Scans and removes leftover image/media folders whose parent chat was previously deleted.

---

## Quick Start

### 1. Web Wizard (Recommended)
```bash
python3 main.py --ui
```
Opens the interactive dashboard in your default browser at `http://127.0.0.1:9123`.

### 2. CLI Mode (Quick Inspection)
```bash
python3 main.py
```

### 3. Automated Safe Cleaning
```bash
# Purge log files
python3 main.py --clean-logs

# Purge cache
python3 main.py --clean-cache

# Defragment state.db
python3 main.py --vacuum

# Clean orphaned attachments
python3 main.py --clean-orphaned
```

---

## راهنمای فارسی

یک ابزار سبک، ماژولار و بدون وابستگی جانبی برای مدیریت، آنالیز و بهینه‌سازی حافظه **Hermes Agent**.

### چرا این ابزار ساخته شد؟
کار مداوم با ایجنت‌های هوش مصنوعی باعث ذخیره‌سازی صدها مگابایت یا گیگابایت لاگ‌های حجیم، کش‌ها و سشن‌های فوق سنگین در مسیر `~/.hermes` می‌شود. سشن‌های حجیم علاوه بر اشغال هارد، سرعت بارگذاری پنل وب لوکال و فرآیند تولید پاسخ را به شدت کاهش می‌دهند.

### امکانات کلیدی:
1. **داشبورد گرافیکی تحت وب (`--ui`):** رابط کاربری تاریک، ریسپانسیو و دو زبانه (فارسی/انگلیسی).
2. **پاپ‌آپ توضیحات و راهنما (آیکون ⓘ):** توضیح دقیق کارکرد هر دکمه پاکسازی بدون ایجاد ابهام.
3. **نمودار بصری توزیع فضا:** نمایش رنگی سهم سشن‌ها، کتابخانه‌ها، لاگ‌ها و کش از هارد دیسک.
4. **تحلیل تعداد پیام‌ها و تخمین توکن:** برآورد بار کانتکست هر چت به صورت تفکیک‌شده.
5. **مشاهده در WebUI با ۱ کلیک:** باز کردن مستقیم چت در پنل وب برای بررسی قبل از تصمیم‌گیری.
6. **خروجی زیپ و بکاپ (Export ZIP):** دانلود و آرشیو سشن به همراه کلیه فایل‌های ضمیمه قبل از حذف.
7. **پاکسازی ضمیمه‌های یتیم (Orphaned Attachments):** شناسایی و حذف فایل‌های مدیا که چت مادر آن‌ها قبلاً پاک شده است.

### اجرا:
```bash
python3 main.py --ui
```

---

## License
MIT License
