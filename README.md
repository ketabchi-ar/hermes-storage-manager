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
- **Zero Third-Party Dependencies:** Uses standard Python 3 libraries (`http.server`, `json`, `sqlite3`, `pathlib`).
- **Interactive Web Wizard (`--ui`):** Beautiful dark-mode dashboard (Bilingual: English / Persian with Vazirmatn font).
- **Heavy Session Detector:** Lists chat sessions by disk size, surfaces bloated sessions (>10MB / 1GB) with prompt previews.
- **Safe Maintenance:**
  - One-click log file cleanup (`webui.log`, `logs/*.log`).
  - Cache directory purge (`cache/`).
  - SQLite database defragmentation (`state.db` VACUUM).
  - Selective session deletion without breaking other active chats.

---

## Quick Start

### 1. Web Wizard (Recommended)
```bash
python3 main.py --ui
```
Opens an interactive dashboard in your default browser at `http://127.0.0.1:9123`.

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
```

---

## راهنمای فارسی

یک ابزار سبک، ماژولار و بدون وابستگی جانبی برای مدیریت و بهینه‌سازی حافظه **Hermes Agent**.

### چرا این ابزار ساخته شد؟
کار مداوم با ایجنت‌های هوش مصنوعی باعث ذخیره‌سازی صدها مگابایت یا گیگابایت لاگ‌های حجیم، کش‌ها و سشن‌های فوق سنگین در مسیر `~/.hermes` می‌شود. سشن‌های حجیم علاوه بر اشغال هارد، سرعت بارگذاری پنل وب لوکال و فرآیند تولید پاسخ را به شدت کاهش می‌دهند.

### امکانات کلیدی:
1. **داشبورد گرافیکی تحت وب (`--ui`):** رابط کاربری تاریک، ریسپانسیو و دو زبانه (فارسی/انگلیسی).
2. **شناسایی سشن‌های غول‌پیکر:** رصد نشست‌های بزرگ‌تر از ۵، ۲۰ و ۱۰۰ مگابایت با امکان حذف انتخابی.
3. **نگهداری امن و سریع:** پاکسازی لاگ‌ها، کش‌ها و فشرده‌سازی SQLite دیتابیس بدون دست‌خوردن به فایل‌های حساس و کلیدها.

### اجرا:
```bash
python3 main.py --ui
```

---

## License
MIT License
