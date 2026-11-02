# فونت‌های فارسی — Persian Font Pack

این فولدر حاوی **۸۴ فونت فارسی** استخراج‌شده از فایل `Fonts.rar` روی Google Drive است.

- **منبع:** Google Drive → `Fonts.rar` (ID: `14C9Sk3efMA79WMaFaX5zBCIs11dEqs7d`) - 3.2 MB - آخرین تغییر: 2026-05-12
- **تاریخ استخراج:** 2026-11-02
- **ابزار:** `unrar` 7.30 (کامپایل از سورس pmachapman/unrar)
- **حجم پس از اکسترکت:** ~7.3 MB (۸۴ فایل)

## محتوا

| دسته | نمونه‌ها |
|------|----------|
| سری B | B Helal, B Homa, B Elham, B Koodak, B Mitra, B Roya, B Elm, B Yekan, B Lotus, B Sina, B Aseman, B Moj, B Siavash ... |
| سری 0 | 0 Yekan, 0 Koodak, 0 Lotus, 0 Mahsa, 0 Mashhad, 0 Mehr, 0 Roya, 0 Soroosh, 0 Tannaz, 0 Tehran, 0 Titr, 0 Traffic, 0 Farnaz, 0 Narm ... |
| سری Mj | Mj_Parand, Mj_Liner (Light/Print/Screen/XL/XXL), Mj_Ramollah ... |
| سری IR | IRFarnaz, IRKamran, IRDastNevis, IRDavat, IRElham, IranNastaliq ... |
| متفرقه | A KORDi, AFSANEH, Vazir-Code, Lalezar-Regular, DecoType Naskh Variants, zangar, Hayat, Far_*, Kaghaz Alef, DimaBlue, Persian-Jadid ... |

لیست کامل در `manifest.json` موجود است (۸۴ ورودی با مسیر URL برای فرانت‌اند).

## مسیرها

- **کانونیکال بک‌اند/ذخیره:** `assets/fonts/` — تمام ۸۴ فایل `.ttf/.otf`
- **فرانت‌اند (سرو از Vite):** `frontend/public/fonts/persian-pack/` — کپی یکسان برای دسترسی از مرورگر
- **آرشیو اصلی:** `assets/archives/Fonts.rar` — فایل رار اصلی برای بازتولید
- **کش موقت Drive:** `google_drive/Fonts.rar` — دانلود اولیه (قابل حذف پس از تایید)

## استفاده در فرانت‌اند

تمام فونت‌ها به صورت خودکار در `frontend/src/persian-fonts.css` به شکل `@font-face` تعریف شده‌اند:

```css
@import './persian-fonts.css';
```

هر فونت با نام خانواده برابر نام فایل (بدون پسوند) قابل استفاده است:

```css
.title {
  font-family: 'B Yekan', 'Vazirmatn', Tahoma, sans-serif;
}
.nastaliq {
  font-family: 'IranNastaliq', serif;
}
```

`manifest.json` لیست URLهای سرو شده (`/fonts/persian-pack/<encoded>`) را دارد — می‌تواند برای انتخاب فونت پویا در UI استفاده شود:

```ts
import manifest from '/fonts/persian-pack/manifest.json'
// manifest[0] = { family: "0 Farnaz", file: "0 Farnaz.TTF", url: "/fonts/persian-pack/0%20Farnaz.TTF", ... }
```

## استفاده در بک‌اند (آینده)

برای رندر متن فارسی روی تصویر (مرحلهٔ جایگزینی ترجمه)، فونت‌های `assets/fonts/` مستقیماً توسط Pillow/OpenCV قابل بارگذاری هستند:

```python
from pathlib import Path
font_path = Path("assets/fonts/B Yekan.ttf")
```

`assets/fonts/manifest.json` می‌تواند برای اعتبارسنجی انتخاب فونت توسط API استفاده شود.

## مجوز

مجوز هر فونت جداگانه باید بررسی شود (بسیاری از فونت‌های سری B / سری 0 رایگان برای استفاده شخصی هستند اما برای توزیع تجاری نیاز به مجوز دارند). قبل از انتشار عمومی، مجوزها را تایید کنید. این ریپازیتوری صرفاً فونت‌ها را برای توسعهٔ داخلی نگه می‌دارد.

## بازتولید

```bash
# از رار اصلی
/tmp/unrar x assets/archives/Fonts.rar assets/fonts/
cp assets/fonts/* frontend/public/fonts/persian-pack/
```

یا از Google Drive:

```bash
# با google_drive connector: ID 14C9Sk3efMA79WMaFaX5zBCIs11dEqs7d
```
