# Hermes Storage Optimizer ⚡

<p align="center">
  <img src="assets/banner.svg" alt="بنر بهینه‌ساز حافظه هرمس" width="100%" />
</p>

<div align="center">

[![DevSponsors Official](https://devsponsors.github.io/assets/badges/sponsor.svg)](https://devsponsors.github.io)
[![DevSponsors Member](https://devsponsors.github.io/assets/badges/member.svg)](https://devsponsors.github.io)
[![DevSponsors Cloud](https://devsponsors.github.io/assets/badges/cloud.svg)](https://devsponsors.github.io/mediakit.html)

<br>

[![DevSponsors Verified](https://img.shields.io/badge/DevSponsors-Verified_OSS-6366f1?style=for-the-badge&logo=github)](https://devsponsors.github.io)
[![DevSponsors Sponsor](https://img.shields.io/badge/Sponsor-DevSponsors_Hub-emerald?style=for-the-badge&logo=github-sponsors)](https://devsponsors.github.io)
[![DevSponsors Cloud](https://img.shields.io/badge/Infrastructure-DevSponsors_Cloud-ec4899?style=for-the-badge&logo=server)](https://devsponsors.github.io/mediakit.html)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge)](LICENSE)

<br>

**راهنمای فارسی** • [English Documentation](README.en.md)

</div>

> ⚡ **Hermes Storage Optimizer**: ابزار سبک، ماژولار و بدون وابستگی (Zero-Dependency) برای پاکسازی، مدیریت نشست‌ها و بهینه‌سازی دیسک ایجنت **Hermes Agent** همراه با رابط کاربری تحت وب (Web Wizard).

---

## 🌟 چرا به Hermes Storage Optimizer نیاز دارید؟

کار مداوم با ایجنت‌های هوش مصنوعی مستقل مانند Hermes Agent، حجم عظیمی از داده‌های متنی، لاگ‌ها و فایل‌های رسانه‌ای را در مسیر `~/.hermes` تولید و ذخیره می‌کند. در طول زمان، این اتفاق منجر به مشکلات زیر می‌شود:

1. **افت شدید سرعت بارگذاری WebUI:** خواندن ده‌ها فایل حجیم چند ده مگابایتی یا گیگابایتی سشن‌ها هنگام اجرای پنل وب لوکال باعث کندی شدید می‌شود.
2. **اتلاف توکن و افزایش زمان پردازش (Context Bloat):** سشن‌های بیش از حد طولانی کانتکست عظیمی را به مدل‌های زبانی ارسال می‌کنند که هزینه توکن را بالا برده و پاسخ‌دهی را کند می‌کند.
3. **اشغال بیهوده دیسک:** فایل‌های سرریز لاگ (`webui.log`)، فایل‌های صوتی موقت ویسپر در کش و دیتابیس بدون دیفرگمنت SQLite تا چندین گیگابایت حافظه سیستم را پر می‌کنند.

**Hermes Storage Optimizer** یک راه‌حل مستقل، کاملاً محلی و بدون نیاز به نصب حتی یک پکیج خارجی است که وضعیت حافظه را شفاف کرده و امکان بهینه‌سازی امن و سریع را فراهم می‌سازد.

---

## 📸 نمای داشبورد وب (Web Wizard)

<div align="center">
  <img src="assets/dashboard-fa.png" alt="داشبورد وب مدیریت حافظه هرمس" width="100%" style="border-radius: 14px; border: 1px solid #1e293b; box-shadow: 0 20px 25px -5px rgb(0 0 0 / 0.5);" />
</div>

---

## 🛡️ قابلیت‌های کلیدی

### ۱. 📊 نمودار بصری توزیع فضای دیسک
نمایش زنده و تفکیک‌شده سهم هر بخش شامل سشن‌های گفتگو، محیط مجازی پایتون (`hermes-agent`)، دیتابیس وضعیت (`state.db`)، فایل‌های لاگ، کش و فایل‌های ضمیمه.

### ۲. 🛠️ بسته اقدامات نگهداری امن (بدون از دست رفتن چت‌ها)
روی هر یک از دکمه‌ها حجم دقیق قابل آزادسازی به همراه یک آیکون راهنما (**ⓘ**) قرار گرفته است:
* **🧹 تخلیه لاگ‌های حجیم:** سبک کردن فایل‌های `webui.log` و `logs/*.log` و رساندن حجم آن‌ها به صفر بایت بدون اختلال در عملکرد سرور.
* **🗑️ پاکسازی کش موقت:** خالی کردن فایل‌های موقت صوتی (Whisper) و بافرهای موقت بدون دست‌زدن به تنظیمات یا سشن‌ها.
* **🗜️ فشرده‌سازی دیتابیس (Vacuum):** اجرای دستور استاندارد SQLite VACUUM روی `state.db` جهت بازگرداندن صفحات خالی دیتابیس به فایل‌سیستم سیستم‌عامل.
* **📁 حذف ضمیمه‌های یتیم (Orphaned Assets):** شناسایی و پاکسازی پوشه‌های مدیا در `webui/attachments` که سشن مربوطه‌شان قبلاً حذف شده است.

### ۳. 💬 مدیریت سشن‌های سنگین و تحلیل توکن
* **فیلتر سشن‌ها:** فیلتر فوری سشن‌ها بر اساس حجم (۵ مگابایت، ۲۰ مگابایت و ۱۰۰+ مگابایت).
* **شمارشگر پیام‌ها:** تفکیک دقیق تعداد پیام‌های کاربر و پاسخ‌های هوش مصنوعی.
* **تخمین توکن:** برآورد هوشمند میزان کانتکست اشغال‌شده توسط هر چت (`~k tokens`).
* **تاریخ‌های شمسی:** نمایش تاریخ و زمان آخرین ویرایش سشن‌ها با تقویم هجری خورشیدی در محیط فارسی.
* **مشاهده مستقیم در WebUI:** دکمه `↗️` جهت باز کردن مستقیم همان چت در پنل وب هرمس قبل از حذف.
* **پشتیبان‌گیری زیپ (ZIP):** امکان دانلود سشن به همراه تمام تصاویر و فایل‌های ضمیمه‌اش در یک فایل زیپ قبل از حذف نهایی.

---

## ⚡ نحوه اجرا و استفاده

### روش اول: اجرای ویزارد وب (پیشنهادی)
بدون نیاز به نصب هیچ‌گونه پیش‌نیازی، دستور زیر را در ترمینال اجرا کنید:
```bash
python3 main.py --ui
```
صفحه ویزارد به طور خودکار در مرورگر شما در آدرس `http://127.0.0.1:9123` باز می‌شود.

### روش دوم: بررسی سریع در خط فرمان (CLI)
```bash
python3 main.py
```

### روش سوم: پاکسازی مستقیم و خودکار
```bash
# تخلیه لاگ‌های حجیم
python3 main.py --clean-logs

# پاکسازی کش‌های موقت
python3 main.py --clean-cache

# فشرده‌سازی دیتابیس SQLite
python3 main.py --vacuum

# حذف ضمیمه‌های یتیم
python3 main.py --clean-orphaned
```

---

## 🔒 امنیت و حریم خصوصی
* **۱۰۰٪ آفلاین و محلی:** ابزار هیچ‌گونه اطلاعاتی به سرورهای خارجی ارسال نمی‌کند.
* **عدم نشت کلیدها و اسرار:** کلیدهای API، فایل‌های کانفیگ و توکن‌های ورود هرگز خوانده یا پردازش نمی‌شوند.

---

## لایسنس
توسعه‌یافته تحت لایسنس متن‌باز **MIT License**.
