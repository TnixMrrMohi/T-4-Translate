"""تشخیص و دسته‌بندی بالن گفت‌وگو بر پایهٔ «لیست فونت‌های مخصوص تایپ».

ایدهٔ کار: داخل بالن تقریباً همیشه روشن است و با خط دور تیره از پس‌زمینه جدا می‌شود.
پس ناحیه‌های روشنی که به لبهٔ صفحه *وصل نیستند* داخل بالن هستند، هر خط OCR به
ناحیهٔ دربرگیرنده‌اش نسبت داده می‌شود و شکل همان ناحیه ویژگی‌های هندسی زیر را
می‌دهد:

* تعداد ضلع پس از ساده‌سازی کانتور (۴ = مستطیل، ۶ = شش‌ضلعی)
* تحدب (نسبت مساحت به چندضلعی محدب): دندانه‌های فریاد و هیولا آن را کم می‌کند
* عمق و تعداد فرورفتگی‌ها: دندانه‌های تیز و بلند در برابر لبه‌های کاسه‌ای ابر
* زبری محیط نسبت به نسخهٔ هموارشده: لرزش بالن ترس
* حباب‌های کوچک همراه: بالن تفکر حباب‌دار
* خطی که داخل هیچ ناحیهٔ محصور نیست: متن بیرون بالن (نریشن/زمزمه/سیستم/تکنیک)

دستهٔ «بیرون بالن» را شکل نمی‌تواند از هم جدا کند (توضیحی، زمزمه، سیستم و تکنیک
همه شکل بالن ندارند)؛ برای همین حدس با اطمینان پایین برگردانده می‌شود تا کاربر
در رابط انتخاب کند.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# نام فونت‌ها همان نام‌های PDF است؛ حتی اگر فونت نصب نباشد نگه داشته می‌شود تا
# رابط بتواند «پیشنهاد» را نشان دهد و در مرحلهٔ بعد با فونت‌های موجود جایگزین شود.
BUBBLE_TYPES: dict[str, dict] = {
    "speech": {
        "tone": "گفت‌وگوی معمولی",
        "label": "صحبت عادی",
        "description": "بالن ساده و دایره‌ای با دنباله از یک گوشه؛ گفت‌وگوی معمول شخصیت‌ها.",
        "fonts": ["Koodak Bold", "Roya Bold"],
        "style": {"bold": True, "italic": False, "stroke": "none", "shadow": False},
    },
    "solar": {
        "tone": "تفکر درخشان و هیجانی",
        "label": "تفکر خورشیدی (درخشان)",
        "description": "بالن دندانه‌دار و درخشان برای تفکر؛ با استروک سیاه و سایه.",
        "fonts": ["Koodak Bold Italic", "Homa", "Mehr"],
        "style": {"bold": True, "italic": True, "stroke": "black", "shadow": True},
    },
    "thought_bubble": {
        "tone": "فکر کردن، بی‌صدا",
        "label": "تفکر معمولی (حباب‌دار)",
        "description": "بالن عادی که چند حباب کوچک پیش از آن آمده است.",
        "fonts": ["B Morvarid"],
        "style": {"bold": False, "italic": False, "stroke": "none", "shadow": False},
    },
    "square": {
        "tone": "توضیح و شرح",
        "label": "بالن مستطیلی و مربعی",
        "description": "بالن با گوشه‌های تیز برای توضیح و شرح در مانهوا.",
        "fonts": ["Elham", "B Esfehan", "Farnaz", "Yekan"],
        "style": {"bold": False, "italic": False, "stroke": "none", "shadow": False},
    },
    "hexagon": {
        "tone": "صدای رادیو، بلندگو یا تلفن",
        "label": "بالن شش‌ضلعی",
        "description": "صدا از رادیو، تلویزیون، بلندگو یا مکالمهٔ تلفنی.",
        "fonts": ["Farnaz"],
        "style": {"bold": False, "italic": False, "stroke": "none", "shadow": False},
    },
    "shout": {
        "tone": "فریاد و عصبانیت",
        "label": "بالن فریاد",
        "description": "گوشه‌های تیز؛ فریاد شدید با فونت افسانه و فریاد ملایم‌تر با کوروش.",
        "fonts": ["Afsaneh", "Kourush"],
        "style": {"bold": True, "italic": False, "stroke": "none", "shadow": False},
    },
    "fear": {
        "tone": "ترس و لرزش",
        "label": "بالن ترس و لرزش",
        "description": "لبهٔ لرزان و ناهموار؛ ترس یا خجالت شخصیت.",
        "fonts": ["B Siavash", "B Moj", "Haleh", "Setareh", "Gam Azad"],
        "style": {"bold": False, "italic": False, "stroke": "none", "shadow": False},
    },
    "monster": {
        "tone": "صدای هیولا، ترسناک",
        "label": "ترسناک یا حرف زدن هیولا",
        "description": "بالن بی‌قاعده و نامنظم برای صداهای هیولاگونه و ترسناک.",
        "fonts": ["A Kordi", "A Zangar", "Aref Graffiti"],
        "style": {"bold": True, "italic": False, "stroke": "none", "shadow": True},
    },
    "cloud": {
        "tone": "ناز و عشوه",
        "label": "بالن ابری (ناز و عشوه)",
        "description": "بالن کنگره‌ای مانند ابر؛ لحن ناز و عشوه یا صورت سرخ‌شده.",
        "fonts": ["Mj_Ramollah", "Mj_Parand"],
        "style": {"bold": False, "italic": False, "stroke": "none", "shadow": False},
    },
    "outside": {
        "tone": "متن توضیحی، زمزمه یا سیستم",
        "label": "متن بیرون بالن",
        "description": "توضیحی، زمزمه، متن سیستم یا متن تکنیک — بالنی ندارد و روی تصویر یا فضای سفید می‌نشیند.",
        "fonts": ["Beirut", "Farnaz", "Narm", "Liner", "Jadid", "Mehr", "Dast Nevis", "Kamran",
                  "Amin", "Esfehan", "Kaghaz", "Sina", "Yekan", "Dima Abdi", "Mj_Moshfegh"],
        "style": {"bold": False, "italic": False, "stroke": "white", "shadow": False},
        "variants": {
            "outside_narration": {"label": "توضیحی", "fonts": ["Beirut", "Farnaz", "Narm", "Liner", "Jadid", "Mehr"]},
            "outside_whisper": {"label": "زمزمه", "fonts": ["Dast Nevis", "Mehr", "Kamran", "Mj_Parand"],
                                "style": {"stroke": "white", "shadow": True}},
            "system": {"label": "متن سیستم", "fonts": ["Amin", "Esfehan", "Farnaz", "Beirut", "Liner", "Kaghaz", "Sina", "Yekan"]},
            "technique": {"label": "متن تکنیک", "fonts": ["Kaghaz", "Farnaz", "Dima Abdi", "Mj_Moshfegh", "Sina", "Afsaneh"]},
        },
    },
    "promo": {
        "tone": "متن تبلیغاتی (واترمارک/آدرس سایت)",
        "label": "متن تبلیغاتی",
        "description": "واترمارک، آدرس سایت، نام مترجم/اسکنر یا تبلیغ کانال؛ ترجمه نمی‌شود و حذف یا با moonb.ir جایگزین می‌شود.",
        "fonts": [],
        "style": {"bold": False, "italic": False, "stroke": "none", "shadow": False},
    },
    "unknown": {
        "tone": "نامشخص",
        "label": "نامشخص",
        "description": "شکل ناحیه به یک دستهٔ مشخص نزدیک نشد؛ کاربر انتخاب می‌کند.",
        "fonts": [],
        "style": {"bold": False, "italic": False, "stroke": "none", "shadow": False},
    },
}

# رنگ‌های پیش‌نمایش؛ هر دسته یک رنگ تا بررسی چشمی ساده باشد.
KIND_COLORS = {
    "speech": (0, 220, 255),
    "solar": (255, 200, 0),
    "thought_bubble": (120, 200, 255),
    "square": (0, 220, 120),
    "hexagon": (170, 120, 255),
    "shout": (255, 90, 90),
    "fear": (255, 140, 0),
    "monster": (200, 0, 120),
    "cloud": (255, 160, 220),
    "outside": (150, 150, 150),
    "promo": (255, 195, 90),
    "unknown": (120, 120, 120),
}

# نشانه‌های متن تبلیغاتی: آدرس سایت، آی‌دی شبکه‌های اجتماعی، نام اسکنر/مترجم و
# دعوت به کانال. الگوها محافظه‌کارانه‌اند تا دیالوگ عادی به‌اشتباه تبلیغ شمرده نشود.
PROMO_PATTERNS = (
    r"https?://", r"www\.", r"\b[a-z0-9-]+\.(com|net|org|ir|me|xyz|tv|co|io|info|site|online|link)\b",
    r"\bt\.me/", r"\bdiscord\.gg/", r"@[a-z0-9_]{4,}\b",
    r"instagram", r"telegram", r"facebook", r"twitter", r"patreon", r"ko-?fi",
    r"translated by", r"translation (by|group)", r"scanlat", r"scans? by", r"scan team",
    r"read (more|online|at)", r"follow us", r"join (us|our)", r"subscribe",
    r"free webtoon", r"raw provider", r"proofreader",
    r"تبلیغ", r"کانال", r"تلگرام", r"اینستاگرام", r"تخفیف", r"خرید", r"فروش",
    r"مترجم", r"اسکن", r"دانلود",
)
PROMO_RE = re.compile("|".join(PROMO_PATTERNS), re.IGNORECASE)
# در حالت «جایگزینی»، متن تبلیغاتی با همین رشته عوض می‌شود.
PROMO_REPLACEMENT = "moonb.ir"


def is_promotional(text: str) -> bool:
    """آیا این متن، تبلیغ/واترمارک است (نه دیالوگ داستان)؟"""
    clean = " ".join(str(text or "").split())
    if len(clean) < 2:
        return False
    return bool(PROMO_RE.search(clean))


MIN_AREA_RATIO = 0.00015       # ناحیه‌های کوچک‌تر از این نسبت، نویز شمرده می‌شوند
COMPANION_MAX_RATIO = 0.06     # حباب همراه کوچک‌تر از این نسبت از بالن اصلی است
BRIGHT_THRESHOLD = 185         # آستانهٔ روشنایی داخل بالن


class BubbleError(Exception):
    pass


def _contour_features(mask, area_total: float, bright_ratio: float = 1.0) -> dict:
    """ویژگی‌های هندسی یک ناحیهٔ محصور (ماسک دودویی همان ناحیه)."""
    import cv2
    import numpy as np

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise BubbleError("ناحیهٔ بالن پیدا نشد.")
    contour = max(contours, key=cv2.contourArea)
    area = float(cv2.contourArea(contour))
    perimeter = float(cv2.arcLength(contour, True))
    if area <= 1 or perimeter <= 0:
        raise BubbleError("ناحیهٔ بالن معتبر نیست.")

    hull = cv2.convexHull(contour)
    hull_area = float(cv2.contourArea(hull))
    solidity = area / hull_area if hull_area > 0 else 0.0
    circularity = 4 * math.pi * area / (perimeter ** 2)
    approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
    x, y, w, h = cv2.boundingRect(contour)
    extent = area / float(max(1, w * h))

    # «راستیِ» لبه: میانگین فاصلهٔ نقاط کانتور از چندضلعی ساده‌شده.
    # برای مستطیل/شش‌ضلعی تقریباً صفر است و برای بیضی محسوس.
    samples = contour[::max(1, len(contour) // 400)]
    distances = [abs(cv2.pointPolygonTest(approx, (float(point[0][0]), float(point[0][1])), True))
                 for point in samples]
    deviation = (sum(distances) / len(distances)) / max(1.0, math.sqrt(area)) if distances else 0.0

    # فرورفتگی‌های کانتور: عمق نسبی به اندازهٔ بالن سنجیده می‌شود.
    scale = max(1.0, math.sqrt(area))
    deep, mid, max_depth = 0, 0, 0.0
    hull_indices = cv2.convexHull(contour, returnPoints=False)
    if hull_indices is not None and len(hull_indices) >= 3:
        try:
            defects = cv2.convexityDefects(contour, hull_indices)
        except Exception:  # کانتور معیوب (کمتر از سه نقطه) در OpenCV
            defects = None
        if defects is not None:
            # OpenCV 4 آرایهٔ (N,1,4) می‌دهد و OpenCV 5 آرایهٔ (N,4)؛ هر دو پشتیبانی می‌شوند.
            rows = defects.reshape(-1, 4) if getattr(defects, "ndim", 0) != 2 else defects
            for item in rows:
                depth = float(item[3]) / 256.0 / scale
                max_depth = max(max_depth, depth)
                if depth > 0.06:
                    deep += 1
                elif depth > 0.012:
                    mid += 1

    # زبری: محیط اصلی تقسیم بر محیط نسخهٔ هموار؛ لبهٔ لرزان این نسبت را بالا می‌برد.
    sigma = max(1.0, scale * 0.02)
    smooth = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), sigmaX=sigma)
    smooth_bin = (smooth > 0.5).astype(np.uint8)
    smooth_contours, _ = cv2.findContours(smooth_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    smooth_perimeter = cv2.arcLength(max(smooth_contours, key=cv2.contourArea), True) if smooth_contours else 0.0
    roughness = perimeter / smooth_perimeter if smooth_perimeter > 0 else 1.0

    return {
        "area": round(area, 1),
        "areaRatio": round(area / area_total, 6) if area_total else 0.0,
        "bbox": [int(x), int(y), int(w), int(h)],
        "vertices": int(len(approx)),
        "solidity": round(solidity, 4),
        "circularity": round(circularity, 4),
        "extent": round(extent, 4),
        "deviation": round(deviation, 4),
        "brightRatio": round(bright_ratio, 3),
        "deepDefects": deep,
        "midDefects": mid,
        "maxDefectDepth": round(max_depth, 4),
        "roughness": round(roughness, 4),
        "contour": contour,
        "hasCompanion": False,
    }


def _classify(features: dict) -> tuple[str, float, str]:
    """دستهٔ بالن از روی ویژگی‌های هندسی؛ خروجی: (نوع، اطمینان، دلیل)."""
    vertices = features["vertices"]
    deviation = features["deviation"]
    solidity = features["solidity"]
    circularity = features["circularity"]
    extent = features["extent"]
    deep = features["deepDefects"]
    mid = features["midDefects"]
    roughness = features["roughness"]

    if features["hasCompanion"]:
        return "thought_bubble", 0.72, "حباب کوچک همراه پیدا شد."

    # دندانه‌های زیاد و ریز = تفکر خورشیدی؛ دندانه‌های کم و بزرگ = فریاد.
    if solidity < 0.86 and deep >= 4:
        if deep >= 14 and solidity >= 0.78:
            return "solar", 0.62, "دندانه‌های ریز و یکنواخت دور بالن."
        return "shout", 0.66, "برآمدگی‌های تیز و عمیق روی لبه."

    if roughness >= 1.12 and circularity >= 0.35 and solidity >= 0.86:
        return "fear", 0.58, "لبهٔ لرزان نسبت به نسخهٔ هموار."

    if mid >= 6 and solidity >= 0.90:
        return "cloud", 0.60, "لبهٔ کاسه‌ای/کنگره‌ای مانند ابر."

    # شش‌ضلعی و مربع لبهٔ راست دارند؛ بیضی با همین تعداد ضلع، لبهٔ خمیده دارد.
    if 5 <= vertices <= 8 and solidity >= 0.90 and deviation <= 0.012 and extent <= 0.88:
        return "hexagon", 0.64, f"چندضلعی {vertices} ضلعی با لبه‌های راست."

    if 4 <= vertices <= 5 and solidity >= 0.90 and extent >= 0.86 and deviation <= 0.02:
        return "square", 0.70, "چهار ضلع با گوشه‌های تیز."

    if solidity < 0.80:
        return "monster", 0.50, "شکل بی‌قاعده و نامنظم."

    if circularity >= 0.55 or (vertices <= 10 and solidity >= 0.90):
        return "speech", 0.68, "ناحیهٔ بیضی‌شکل و یکدست."

    if solidity >= 0.80 and 5 <= vertices <= 14:
        return "speech", 0.52, "ناحیهٔ گرد با لبهٔ دست‌کشیده."

    return "unknown", 0.30, "ویژگی هندسی به دستهٔ مشخصی نخورد."


def _fill_holes(blob):
    """سوراخ‌های داخل ناحیه (حروف تیره) را پر می‌کند."""
    import cv2
    import numpy as np

    height, width = blob.shape[:2]
    inverse = (blob == 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(inverse, connectivity=4)
    holes = np.zeros_like(inverse)
    for index in range(1, count):
        x, y, w, h, _area = stats[index]
        if x <= 0 or y <= 0 or x + w >= width or y + h >= height:
            continue  # به لبهٔ پنجره چسبیده؛ سوراخ نیست
        holes[labels == index] = 1
    return ((blob == 1) | (holes == 1)).astype(np.uint8)


def _crop_blob(blob, origin: tuple[int, int]):
    """ماسک را به کادر خودش می‌برد تا مقایسهٔ هم‌پوشانی سبک بماند."""
    import numpy as np

    rows = np.flatnonzero(blob.any(axis=1))
    columns = np.flatnonzero(blob.any(axis=0))
    if not len(rows) or not len(columns):
        return None, origin
    top, bottom = int(rows[0]), int(rows[-1]) + 1
    left, right = int(columns[0]), int(columns[-1]) + 1
    return blob[top:bottom, left:right], (origin[0] + left, origin[1] + top)


def _grow_from(seed, bright, page_height: int, page_width: int):
    """ناحیهٔ روشنِ پیرامون یک نقطه را پر می‌کند و می‌گوید آیا محصور است.

    پنجرهٔ جست‌وجو **نامتقارن** بزرگ می‌شود: فقط سمتی که ناحیه به آن چسبیده تا لبهٔ
    صفحه باز می‌شود. پنجرهٔ متقارنِ قبلی وقتی متن در سمت راست بالنِ پهن بود، لبهٔ چپ
    ناحیه را می‌برید و آن را تا آخر «محصور نشده» می‌دید؛ نتیجه این بود که خطوط یک
    بالن «بیرون بالن» شمرده می‌شدند و ترجمه‌شان روی لبهٔ بالن می‌افتاد.

    محصور بودن فقط با چسبیدن به لبهٔ *صفحه* سنجیده می‌شود، نه لبهٔ پنجره: ناحیه‌ای
    که به پس‌زمینه راه دارد به لبهٔ صفحه می‌رسد، ولی ناحیهٔ محصور هرگز.
    """
    import cv2
    import numpy as np

    seed_x, seed_y = seed
    left = right = up = down = 48
    while True:
        x0 = max(0, seed_x - left)
        x1 = min(page_width, seed_x + right + 1)
        y0 = max(0, seed_y - up)
        y1 = min(page_height, seed_y + down + 1)
        window = bright[y0:y1, x0:x1]
        if window[seed_y - y0, seed_x - x0] == 0:
            return None, (x0, y0), False
        mask = np.zeros((window.shape[0] + 2, window.shape[1] + 2), np.uint8)
        cv2.floodFill(window.copy(), mask, (seed_x - x0, seed_y - y0), 1,
                      flags=4 | (1 << 8) | cv2.FLOODFILL_MASK_ONLY)
        blob = mask[1:-1, 1:-1]
        touch_left = bool(blob[:, 0].any())
        touch_right = bool(blob[:, -1].any())
        touch_up = bool(blob[0, :].any())
        touch_down = bool(blob[-1, :].any())
        reaches_page = ((touch_left and x0 == 0) or (touch_right and x1 == page_width)
                        or (touch_up and y0 == 0) or (touch_down and y1 == page_height))
        if reaches_page or not (touch_left or touch_right or touch_up or touch_down):
            cropped, origin = _crop_blob(_fill_holes(blob), (x0, y0))
            return cropped, origin, not reaches_page
        if touch_left:
            left = seed_x
        if touch_right:
            right = page_width - seed_x
        if touch_up:
            up = seed_y
        if touch_down:
            down = page_height - seed_y


def _line_bbox(quad, width: int, height: int):
    try:
        points = [[float(p[0]), float(p[1])] for p in quad if len(p) == 2]
        if len(points) != 4 or not all(math.isfinite(v) for point in points for v in point):
            return None
    except (TypeError, ValueError):
        return None
    xs = [max(0, min(width - 1, point[0])) for point in points]
    ys = [max(0, min(height - 1, point[1])) for point in points]
    return [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]


def _seed_point(bright, bbox, padding: int = 8):
    """پیکسل روشنی در فضای خالیِ کنار متن، نه یک لکهٔ ریزِ تصادفی.

    قبلاً نزدیک‌ترین پیکسل روشن به مرکز کادر انتخاب می‌شد؛ اگر مرکز روی تیرگیِ حرف
    می‌افتاد، آن پیکسل ممکن بود یک نقطهٔ نوری چندپیکسلی داخل حرف باشد و رشد ناحیه
    همان لکهٔ ۱۶ پیکسلی شود؛ آن‌گاه خط «بیرون بالن» شمرده می‌شد. اینجا با تبدیل فاصله
    پیکسلی انتخاب می‌شود که در دلِ یک ناحیهٔ روشنِ به‌قدر کافی بزرگ است و در عین حال
    به مرکز متن نزدیک است.
    """
    import cv2
    import numpy as np

    height, width = bright.shape[:2]
    x0 = max(0, bbox[0] - padding)
    y0 = max(0, bbox[1] - padding)
    x1 = min(width, bbox[2] + padding + 1)
    y1 = min(height, bbox[3] + padding + 1)
    window = bright[y0:y1, x0:x1]
    if not window.any():
        return None
    distance = cv2.distanceTransform(window, cv2.DIST_L2, 5)
    far = float(distance.max())
    if far <= 0:
        return None
    ys, xs = np.nonzero(distance >= max(1.5, far * 0.6))
    if not len(xs):
        return None
    center_x = (bbox[2] - bbox[0]) / 2
    center_y = (bbox[3] - bbox[1]) / 2
    index = int(np.argmin((xs - center_x) ** 2 + (ys - center_y) ** 2))
    return int(xs[index] + x0), int(ys[index] + y0)


def _has_companions(gray, bright, bubble: dict, height: int, width: int, forbidden: list) -> bool:
    """آیا ناحیه‌های روشن کوچک و محصوری کنار این بالن هست (حباب‌های تفکر)؟"""
    import cv2
    import numpy as np

    bx, by, bw, bh = bubble["bbox"]
    area = float(bubble["features"].get("area", bw * bh))
    pad = max(24, int(0.5 * max(bw, bh)))
    x0, y0 = max(0, bx - pad), max(0, by - pad)
    x1, y1 = min(width, bx + bw + pad), min(height, by + bh + pad)
    light = gray[y0:y1, x0:x1]
    window = bright[y0:y1, x0:x1].copy()
    window[0, :] = window[-1, :] = window[:, 0] = window[:, -1] = 1
    mask = np.zeros((window.shape[0] + 2, window.shape[1] + 2), np.uint8)
    cv2.floodFill(window, mask, (0, 0), 2)
    enclosed = (window != 2).astype(np.uint8)
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(enclosed, connectivity=8)
    window_height, window_width = enclosed.shape[:2]
    companions = 0
    for index in range(1, count):
        x, y, w, h, region_area = stats[index]
        if region_area < 24 or region_area > area * COMPANION_MAX_RATIO:
            continue
        # ناحیه‌ای که به لبهٔ پنجره می‌خورد بریده شده است، نه حباب کامل.
        if x <= 3 or y <= 3 or x + w >= window_width - 3 or y + h >= window_height - 3:
            continue
        if max(w, h) > 0.3 * min(bw, bh) or max(w, h) < 6:
            continue
        box = (x + x0, y + y0, x + x0 + w, y + y0 + h)
        if any(not (box[2] <= area_box[0] or box[0] >= area_box[2]
                    or box[3] <= area_box[1] or box[1] >= area_box[3]) for area_box in forbidden):
            continue  # داخل متن یا بالن دیگر است، نه حباب تفکر
        if min(w, h) / max(w, h) < 0.6:
            continue  # حباب تفکر تقریباً گرد است
        if region_area / float(w * h) < 0.45:
            continue
        # حباب تفکر روشن است؛ حروف تیرهٔ داخل بالن‌های همسایه «حباب» نیستند.
        region = labels == index
        if int(region.sum()) and light[region].mean() < 110:
            continue
        # خودِ بالن (یا بخشی از آن) نباید حباب همراه شمرده شود.
        overlaps = not (x + x0 >= bx + bw or x + x0 + w <= bx or y + y0 >= by + bh or y + y0 + h <= by)
        if overlaps:
            continue
        companions += 1
    # بالن تفکر معمولاً ۲ تا ۳ حباب کوچک دارد؛ یکی احتمالاً لکه یا نور است.
    return companions >= 2


def _split_bubbles(mask, line_boxes: dict, origin: tuple[int, int] = (0, 0)):
    """بالن‌های چسبیده را از هم جدا می‌کند.

    اگر دو بالن هم را لمس کنند، ناحیهٔ روشن یکپارچه می‌شود و متن هر دو در یک بلوک
    می‌افتد. اینجا از تبدیل فاصله استفاده می‌شود: هر لوب یک قلهٔ فاصله دارد، پس با
    بریدن قله‌ها و رشد دادنشان، ناحیه به لوب‌های جدا شکسته می‌شود. فقط وقتی جدا
    می‌کنیم که دست‌کم دو لوب هرکدام حداقل یک خط OCR داشته باشند؛ وگرنه یک بالن است.

    `mask` محلی است؛ `line_boxes` مختصات صفحه است و با `origin` به محلی تبدیل می‌شود.
    (بدون این تبدیل، کادر هر خط در جای غلطی از ماسک خوانده می‌شد و هیچ لوبی خط
    نمی‌گرفت؛ نتیجه: دو بالنِ چسبیده هرگز جدا نمی‌شدند.)
    """
    import cv2
    import numpy as np

    numbers = [number for number, box in line_boxes.items() if box is not None]
    if len(numbers) < 2 or not mask.any():
        return [(mask, numbers)]

    distance = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    peak = float(distance.max())
    if peak <= 1.0:
        return [(mask, numbers)]

    labels = None
    for ratio in (0.72, 0.62, 0.52, 0.44, 0.36):
        seeds = (distance >= peak * ratio).astype(np.uint8)
        count, seed_labels, stats, _ = cv2.connectedComponentsWithStats(seeds, connectivity=8)
        kept = [index for index in range(1, count)
                if stats[index][4] >= mask.sum() * 0.02]
        if len(kept) < 2:
            continue
        labels = np.zeros(mask.shape, np.int32)
        for new_index, old_index in enumerate(kept, 1):
            labels[seed_labels == old_index] = new_index
        # رشد دانه‌ها تا پر شدن ناحیه؛ مرزها با نزدیک‌ترین دانه پر می‌شوند.
        refined = labels.copy()
        cv2.watershed(np.dstack([distance] * 3).astype(np.uint8), refined)
        grown = np.where(mask > 0, refined, 0)
        if len({value for value in np.unique(grown) if value > 0}) >= 2:
            labels = grown
            break
        labels = None
    if labels is None:
        return [(mask, numbers)]

    counts = {value: int((labels == value).sum()) for value in np.unique(labels) if value > 0}
    parts = []
    assigned: dict[int, list[int]] = {}
    for value, area in counts.items():
        if area < mask.sum() * 0.12:
            continue
        part = (labels == value).astype(np.uint8)
        part_numbers = []
        for number in numbers:
            top, bottom, left, right = line_boxes[number]
            local_top = int(max(0, top - origin[1]))
            local_left = int(max(0, left - origin[0]))
            local_bottom = int(min(part.shape[0], bottom - origin[1] + 1))
            local_right = int(min(part.shape[1], right - origin[0] + 1))
            window = part[local_top:local_bottom, local_left:local_right]
            if window.size and window.sum() >= 0.3 * window.size:
                part_numbers.append(number)
        if not part_numbers:
            continue
        parts.append((part, part_numbers))
        assigned[value] = part_numbers
    # هر خط باید فقط در یک لوب باشد؛ در هم‌پوشانی، لوبی که خط بیشتر در آن است برنده است.
    seen: dict[int, int] = {}
    for value, part_numbers in assigned.items():
        for number in part_numbers:
            seen[number] = seen.get(number, 0) + 1
    if any(count > 1 for count in seen.values()):
        return [(mask, numbers)]
    if len(parts) < 2:
        return [(mask, numbers)]
    return parts


def analyze(path: Path, lines: list) -> dict:
    """بالن هر خط OCR را پیدا و دسته‌بندی می‌کند.

    برای هر خط، ناحیهٔ روشنِ پیرامونش رشد داده می‌شود؛ اگر این ناحیه در پنجرهٔ
    جست‌وجو محصور بماند یعنی داخل بالن است و اگر تا سقف رشد به پس‌زمینه برسد یعنی
    متن بیرون بالن است. ناحیه‌های هم‌پوشان یک بالن شمرده می‌شوند.
    """
    try:
        import cv2
        import numpy as np
    except (ImportError, OSError) as exc:
        raise BubbleError("ابزار پردازش تصویر برای تشخیص بالن نصب نشده است.") from exc

    try:
        with Image.open(path) as source:
            if source.width * source.height > 40_000_000:
                raise BubbleError("تصویر برای تشخیص بالن بیش از حد بزرگ است.")
            if source.getexif().get(274, 1) != 1:
                raise BubbleError("تصاویر دارای چرخش EXIF در تشخیص بالن پشتیبانی نمی‌شوند.")
            gray = np.array(source.convert("L"))
    except (OSError, ValueError) as exc:
        raise BubbleError("خواندن تصویر منبع ناموفق بود.") from exc

    height, width = gray.shape[:2]
    total = float(height * width)
    bright = (gray >= BRIGHT_THRESHOLD).astype(np.uint8)

    found = []          # (شمارهٔ خط، ماسک، مبدأ پنجره)
    outside_lines = []
    for number, line in enumerate(lines, 1):
        quad = line.get("quad") if isinstance(line, dict) else None
        bbox = _line_bbox(quad, width, height)
        if bbox is None:
            outside_lines.append(number)
            continue
        seed = _seed_point(bright, bbox)
        if seed is None:
            outside_lines.append(number)
            continue
        blob, origin, enclosed = _grow_from(seed, bright, height, width)
        area = int(blob.sum()) if blob is not None else 0
        if not enclosed or area < total * MIN_AREA_RATIO or area > total * 0.35:
            outside_lines.append(number)
            continue
        found.append({"line": number, "mask": blob, "origin": origin})

    # ناحیه‌های هم‌پوشان = یک بالن.
    parent = list(range(len(found)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for first in range(len(found)):
        ax, ay = found[first]["origin"]
        ah, aw = found[first]["mask"].shape[:2]
        for second in range(first + 1, len(found)):
            bx2, by2 = found[second]["origin"]
            bh, bw = found[second]["mask"].shape[:2]
            if ax + aw <= bx2 or bx2 + bw <= ax or ay + ah <= by2 or by2 + bh <= ay:
                continue
            x0 = max(ax, bx2)
            y0 = max(ay, by2)
            x1 = min(ax + aw, bx2 + bw)
            y1 = min(ay + ah, by2 + bh)
            left = found[first]["mask"][y0 - ay:y1 - ay, x0 - ax:x1 - ax]
            right = found[second]["mask"][y0 - by2:y1 - by2, x0 - bx2:x1 - bx2]
            shared = int((left & right).sum())
            smaller = min(int(left.sum()), int(right.sum()))
            if smaller and shared / smaller >= 0.5:
                parent[find(second)] = find(first)

    groups: dict[int, list[int]] = {}
    for index in range(len(found)):
        groups.setdefault(find(index), []).append(index)

    bubbles = []
    for members in groups.values():
        masks = []
        for member in members:
            item = found[member]
            masks.append((item["origin"], item["mask"]))
        x0 = min(origin[0] for origin, _ in masks)
        y0 = min(origin[1] for origin, _ in masks)
        x1 = max(origin[0] + mask.shape[1] for origin, mask in masks)
        y1 = max(origin[1] + mask.shape[0] for origin, mask in masks)
        union = np.zeros((y1 - y0, x1 - x0), np.uint8)
        for origin, mask in masks:
            union[origin[1] - y0:origin[1] - y0 + mask.shape[0],
                  origin[0] - x0:origin[0] - x0 + mask.shape[1]] |= mask
        line_boxes = {found[member]["line"]: _line_box(lines[found[member]["line"] - 1])
                      for member in members}
        for part_mask, part_lines in _split_bubbles(union, line_boxes, (x0, y0)):
            try:
                features = _contour_features(part_mask, total)
            except BubbleError:
                continue
            features["bbox"] = [features["bbox"][0] + x0, features["bbox"][1] + y0,
                                features["bbox"][2], features["bbox"][3]]
            kind, confidence, reason = _classify(features)
            bubbles.append({
                "id": len(bubbles) + 1,
                "kind": kind,
                "confidence": round(confidence, 2),
                "reason": reason,
                "bbox": features["bbox"],
                "lines": sorted(part_lines),
                "features": {key: value for key, value in features.items() if key != "contour"},
            })

    # حباب‌های کوچک بی‌متن نزدیک یک بالن = نشانهٔ تفکر حباب‌دار.
    line_boxes_all = [box for box in (_line_box(line) for line in lines if isinstance(line, dict)) if box]
    line_bounds = [(left - 2, top - 2, right + 2, bottom + 2) for top, bottom, left, right in line_boxes_all]
    for bubble in bubbles:
        if bubble["kind"] not in {"speech", "unknown"}:
            continue
        others = [item["bbox"] for item in bubbles if item is not bubble and item.get("bbox")]
        forbidden = line_bounds + [(bx, by, bx + bw, by + bh) for bx, by, bw, bh in others]
        if _has_companions(gray, bright, bubble, height, width, forbidden):
            bubble["features"]["hasCompanion"] = True
            bubble["kind"] = "thought_bubble"
            bubble["confidence"] = max(bubble["confidence"], 0.72)
            bubble["reason"] = "حباب کوچک بی‌متن در کنار بالن دیده شد."

    for bubble in bubbles:
        meta = BUBBLE_TYPES.get(bubble["kind"], BUBBLE_TYPES["unknown"])
        bubble["kindLabel"] = meta["label"]
        bubble["description"] = meta["description"]
        bubble["fonts"] = meta["fonts"]
        bubble["style"] = meta["style"]

    bubbles.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    for index, bubble in enumerate(bubbles, 1):
        bubble["id"] = index

    # خط‌هایی که با رشد ناحیهٔ روشن در حباب نیفتادند، اگر مدل تشخیص حباب نصب باشد
    # با ماسک خودِ مدل جای‌گذاری می‌شوند (بالن‌های تیره، رنگی و پرنقش).
    outside_lines = _detector_place(lines, bubbles, outside_lines, path, np, cv2)

    if outside_lines:
        meta = BUBBLE_TYPES["outside"]
        bubbles.append({
            "id": len(bubbles) + 1,
            "kind": "outside",
            "kindLabel": meta["label"],
            "description": meta["description"],
            "confidence": 0.35,
            "reason": "این خطوط داخل ناحیهٔ محصوری نیستند؛ بالن ندارد یا به پس‌زمینه راه دارد.",
            "bbox": [],
            "lines": sorted(outside_lines),
            "fonts": meta["fonts"],
            "style": meta["style"],
            "variants": [{"id": key, "label": value["label"], "fonts": value["fonts"]}
                         for key, value in meta["variants"].items()],
            "features": {},
        })

    document = {"jobId": None, "provider": "region-growth-experimental", "bubbles": bubbles}
    document["revision"] = hashlib.sha256(
        json.dumps(bubbles, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return document


def _detector_place(lines: list, bubbles: list, outside_lines: list, path: Path,
                    np, cv2) -> list:
    """خط‌های بیرون‌مانده را با ماسک حبابِ مدل به حباب خودشان برمی‌گرداند.

    فقط خط‌هایی جابه‌جا می‌شوند که مرکزشان داخل یک ناحیهٔ حبابِ خودِ مدل باشد؛ بقیه
    مثل قبل «بیرون حباب» می‌مانند. اگر مدل نصب نباشد هیچ تغییری رخ نمی‌دهد.
    """
    if not outside_lines:
        return outside_lines
    try:
        from . import textdet

        if not textdet.available():
            return outside_lines
        with Image.open(path) as source:
            array = np.array(source.convert("RGB"))
        found = textdet.masks(array)
    except Exception:  # noqa: BLE001 - مدل نباید تشخیص حباب را بشکند
        return outside_lines
    bubble_mask = (found or {}).get("bubble")
    if bubble_mask is None or not bool(np.asarray(bubble_mask).any()):
        return outside_lines
    height, width = bubble_mask.shape[:2]
    total = float(height * width)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(
        np.asarray(bubble_mask, dtype=np.uint8), 8)
    grouped: dict[int, list[int]] = {}
    remaining: list[int] = []
    for number in outside_lines:
        box = _line_box(lines[number - 1]) if 0 < number <= len(lines) else None
        if box is None:
            remaining.append(number)
            continue
        top, bottom, left, right = box
        cx = max(0, min(width - 1, int((left + right) / 2)))
        cy = max(0, min(height - 1, int((top + bottom) / 2)))
        label = int(labels[cy, cx])
        if label == 0:
            # مرکز خط ممکن است روی خودِ حرف بیفتد؛ همان کادر را می‌گردیم.
            patch = labels[max(0, int(top)):max(1, int(bottom)),
                           max(0, int(left)):max(1, int(right))]
            values = patch[patch > 0]
            if values.size == 0:
                remaining.append(number)
                continue
            label = int(np.bincount(values).argmax())
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < total * 0.0002 or area > total * 0.6:
            remaining.append(number)   # لکهٔ ریز یا کل صفحه، نه حباب
            continue
        grouped.setdefault(label, []).append(number)
    for label, numbers in grouped.items():
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        w = int(stats[label, cv2.CC_STAT_WIDTH])
        h = int(stats[label, cv2.CC_STAT_HEIGHT])
        meta = BUBBLE_TYPES["speech"]
        bubbles.append({
            "id": 0,
            "kind": "speech",
            "kindLabel": meta["label"],
            "description": meta["description"],
            "confidence": 0.66,
            "reason": "حباب با مدل تشخیص حباب پیدا شد (بالن تیره/رنگی/پرنقش).",
            "bbox": [x, y, w, h],
            "lines": sorted(numbers),
            "fonts": meta["fonts"],
            "style": meta["style"],
            "features": {"detector": "comic-text-detector"},
        })
    return remaining


def _label_font(size: int):
    from app import rendering

    try:
        return ImageFont.truetype(str(rendering.font_path()), size)
    except Exception:
        return ImageFont.load_default()


def overlay(path: Path, document: dict, max_side: int = 1800) -> Image.Image:
    """پیش‌نمایشی که کانتور و دستهٔ هر بالن را روی تصویر منبع می‌کشد."""
    from app import rendering

    try:
        with Image.open(path) as source:
            image = source.convert("RGB")
    except (OSError, ValueError) as exc:
        raise BubbleError("خواندن تصویر منبع ناموفق بود.") from exc

    scale = min(1.0, max_side / max(image.size))
    if scale != 1.0:
        image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                             Image.LANCZOS)
    draw = ImageDraw.Draw(image)
    line_width = max(2, round(min(image.size) / 320))
    font = _label_font(max(14, min(34, round(min(image.size) / 26))))
    for bubble in document.get("bubbles", []):
        if not bubble.get("bbox"):
            continue
        x, y, w, h = [value * scale for value in bubble["bbox"]]
        color = KIND_COLORS.get(bubble["kind"], KIND_COLORS["unknown"])
        draw.rectangle([x, y, x + w, y + h], outline=color, width=line_width)
        label = f'{bubble["id"]}: {bubble["kindLabel"]} {round(bubble["confidence"] * 100)}%'
        try:
            text = rendering.shape_text(label)
        except Exception:
            text = label
        box = draw.textbbox((0, 0), text, font=font)
        pad = max(3, line_width)
        width_needed = box[2] - box[0] + pad * 2
        top = max(0, y - (box[3] - box[1]) - pad * 2)
        draw.rectangle([x, top, min(image.width, x + width_needed), top + (box[3] - box[1]) + pad * 2],
                       fill=(10, 14, 18))
        draw.text((x + pad - box[0], top + pad - box[1]), text, fill=color, font=font)
    return image


# ---------------------------------------------------------------- بلوک‌ها
AREA_SLACK = 2.0        # تحمل چند پیکسلی وقتی کادر شکل باید کادر متن را در بر بگیرد
AREA_MAX_WIDTH_RATIO = 8.0    # کادر شکل نباید بی‌اندازه پهن‌تر از کادر متن باشد
AREA_MAX_HEIGHT_RATIO = 10.0  # و نه بی‌اندازه بلندتر (نشانهٔ تشخیص نادرست)
AREA_MAX_RATIO = 40.0         # و نه بی‌اندازه بزرگ‌تر از نظر مساحت
OUTSIDE_GROUP_GAP = 1.8  # فاصلهٔ عمودی مجاز (برابر ارتفاع خط) برای یک بلوک بیرون بالن


def _line_box(line) -> tuple[float, float, float, float] | None:
    """کادر یک خط OCR به شکل (بالا، پایین، چپ، راست) یا None اگر معتبر نباشد."""
    quad = line.get("quad") if isinstance(line, dict) else None
    try:
        points = [[float(point[0]), float(point[1])] for point in quad]
    except (TypeError, ValueError):
        return None
    if len(points) != 4 or not all(math.isfinite(value) for point in points for value in point):
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(ys), max(ys), min(xs), max(xs)


def _cluster(numbers: list[int], by_number: dict) -> list[list[int]]:
    """خطوط بیرون بالن را به بلوک‌های نزدیک به هم می‌شکند (هر افکت جدا)."""
    ordered = sorted(numbers, key=lambda number: (_line_box(by_number[number]) or (0, 0, 0, 0))[0])
    clusters: list[list[int]] = []
    for number in ordered:
        box = _line_box(by_number[number])
        if box is None or not clusters:
            clusters.append([number])
            continue
        previous_box = _line_box(by_number[clusters[-1][-1]])
        if previous_box is None:
            clusters.append([number])
            continue
        line_height = max(1.0, previous_box[1] - previous_box[0])
        if box[0] - previous_box[1] <= line_height * OUTSIDE_GROUP_GAP:
            clusters[-1].append(number)
        else:
            clusters.append([number])
    return clusters


def _block(numbers: list[int], by_number: dict, kind: str, bbox: list, fill: float = 1.0) -> dict:
    """یک بلوک ترجمه؛ کادر خروجی همیشه به شکل [چپ، بالا، راست، پایین] است.

    کادر تشخیص بالن [x, y, w, h] است و کادر خطوط [چپ، بالا، راست، پایین]؛ اگر این
    دو مستقیم با هم ترکیب شوند، عرض/ارتفاع متن غلط می‌شود و ترجمه جای خودش نمی‌نشیند.

    `bbox` جای *متن* است (برای ترتیب و مرجع)، و `area` کل فضای *شکلِ* بالن داخل
    همان کادر. اندازهٔ قلم بر اساس `area` انتخاب می‌شود؛ وگرنه قلم به ارتفاع
    متن اصلی (که معمولاً یک یا دو خط نازک است) محدود می‌شد و ناگهان خیلی ریز
    درمی‌آمد.
    """
    meta = BUBBLE_TYPES.get(kind, BUBBLE_TYPES["unknown"])
    ordered = sorted(numbers, key=lambda number: (
        (_line_box(by_number[number]) or (0, 0, 0, 0))[0],
        (_line_box(by_number[number]) or (0, 0, 0, 0))[2]))
    boxes = [box for box in (_line_box(by_number[number]) for number in ordered) if box]
    box = []
    shape_box = []
    if len(bbox) == 4 and all(isinstance(value, (int, float)) for value in bbox):
        left, top, width, height = [float(value) for value in bbox]
        box = [left, top, left + width, top + height]
        shape_box = list(box)
    if boxes:
        union = [min(b[2] for b in boxes), min(b[0] for b in boxes),
                 max(b[3] for b in boxes), max(b[1] for b in boxes)]
        if not box:
            box = union
        else:
            # کادر شکلِ تشخیص‌داده‌شده گاهی حاشیهٔ اضافه یا برش دارد؛ کادر متن باید
            # در محدودهٔ خطوط خودِ متن بماند تا ترجمه جای اصلی‌اش بنشیند.
            box = [max(box[0], union[0]), max(box[1], union[1]),
                   min(box[2], union[2]), min(box[3], union[3])]
            if box[2] - box[0] < 24 or box[3] - box[1] < 24:
                box = union
    box = [round(value) for value in box]
    # فضای شکلِ بالن برای اندازهٔ قلم؛ اگر کادر متن را در بر نگیرد یا بی‌اندازه
    # بزرگ‌تر باشد (تشخیص نادرست)، نادیده گرفته می‌شود.
    area = None
    if box and len(shape_box) == 4:
        shape_width = shape_box[2] - shape_box[0]
        shape_height = shape_box[3] - shape_box[1]
        text_width = max(1.0, box[2] - box[0])
        text_height = max(1.0, box[3] - box[1])
        text_area = text_width * text_height
        contains_text = (shape_box[0] <= box[0] + AREA_SLACK and shape_box[1] <= box[1] + AREA_SLACK
                         and shape_box[2] >= box[2] - AREA_SLACK and shape_box[3] >= box[3] - AREA_SLACK)
        if (shape_width > 8 and shape_height > 8 and contains_text
                and shape_width / text_width <= AREA_MAX_WIDTH_RATIO
                and shape_height / text_height <= AREA_MAX_HEIGHT_RATIO
                and (shape_width * shape_height) / text_area <= AREA_MAX_RATIO):
            area = [round(value) for value in shape_box]
    text = " ".join(str(by_number[number].get("text", "")).strip() for number in ordered).strip()
    return {
        "lines": ordered,
        "text": text,
        "kind": kind,
        "kindLabel": meta["label"],
        "tone": meta.get("tone", ""),
        "fonts": meta["fonts"],
        "bbox": box,
        # کادر شکل (بالن) برای اندازهٔ قلم؛ None یعنی فقط کادر متن در دست است.
        "area": area,
        # نسبت مساحت شکل به کادرش؛ برای شکل‌های دندانه‌دار متن باید جمع‌تر بنشیند.
        "fill": fill,
    }


def blocks(document: dict, lines: list) -> list[dict]:
    """هر بالن را یک بلوک متنی می‌کند؛ متن خطوط همان بالن با هم می‌آید.

    ترجمه و رندر بر پایهٔ همین بلوک‌ها انجام می‌شود تا هر بالن یک متن فارسی بگیرد،
    نه یک ترجمه برای هر خط. اگر تشخیص بالن انجام نشده باشد یا خطی در هیچ بالنی
    نباشد، همان خط یک بلوک مستقل می‌شود.
    """
    by_number = {}
    for index, line in enumerate(lines, 1):
        if isinstance(line, dict):
            by_number[index] = line
    result: list[dict] = []
    seen: set[int] = set()
    for bubble in (document or {}).get("bubbles", []):
        numbers = [number for number in bubble.get("lines", []) if number in by_number]
        numbers = [number for number in numbers if number not in seen]
        if not numbers:
            continue
        seen.update(numbers)
        if bubble.get("kind") == "outside":
            for cluster in _cluster(numbers, by_number):
                result.append(_block(cluster, by_number, "outside", []))
        else:
            features = bubble.get("features") or {}
            result.append(_block(numbers, by_number, bubble.get("kind", "unknown"),
                                 bubble.get("bbox") or [], float(features.get("solidity") or 1.0)))
    for number in sorted(set(by_number) - seen):
        result.append(_block([number], by_number, "unknown", []))

    def order(item: dict):
        box = item["bbox"]
        if len(box) == 4:
            return (box[1], box[0])
        first = _line_box(by_number[item["lines"][0]]) if item["lines"] else None
        return (first[0], first[2]) if first else (0.0, 0.0)

    result.sort(key=order)
    for index, item in enumerate(result, 1):
        item["number"] = index
    return result
