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
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# نام فونت‌ها همان نام‌های PDF است؛ حتی اگر فونت نصب نباشد نگه داشته می‌شود تا
# رابط بتواند «پیشنهاد» را نشان دهد و در مرحلهٔ بعد با فونت‌های موجود جایگزین شود.
BUBBLE_TYPES: dict[str, dict] = {
    "speech": {
        "label": "صحبت عادی",
        "description": "بالن ساده و دایره‌ای با دنباله از یک گوشه؛ گفت‌وگوی معمول شخصیت‌ها.",
        "fonts": ["Koodak Bold", "Roya Bold"],
        "style": {"bold": True, "italic": False, "stroke": "none", "shadow": False},
    },
    "solar": {
        "label": "تفکر خورشیدی (درخشان)",
        "description": "بالن دندانه‌دار و درخشان برای تفکر؛ با استروک سیاه و سایه.",
        "fonts": ["Koodak Bold Italic", "Homa", "Mehr"],
        "style": {"bold": True, "italic": True, "stroke": "black", "shadow": True},
    },
    "thought_bubble": {
        "label": "تفکر معمولی (حباب‌دار)",
        "description": "بالن عادی که چند حباب کوچک پیش از آن آمده است.",
        "fonts": ["B Morvarid"],
        "style": {"bold": False, "italic": False, "stroke": "none", "shadow": False},
    },
    "square": {
        "label": "بالن مستطیلی و مربعی",
        "description": "بالن با گوشه‌های تیز برای توضیح و شرح در مانهوا.",
        "fonts": ["Elham", "B Esfehan", "Farnaz", "Yekan"],
        "style": {"bold": False, "italic": False, "stroke": "none", "shadow": False},
    },
    "hexagon": {
        "label": "بالن شش‌ضلعی",
        "description": "صدا از رادیو، تلویزیون، بلندگو یا مکالمهٔ تلفنی.",
        "fonts": ["Farnaz"],
        "style": {"bold": False, "italic": False, "stroke": "none", "shadow": False},
    },
    "shout": {
        "label": "بالن فریاد",
        "description": "گوشه‌های تیز؛ فریاد شدید با فونت افسانه و فریاد ملایم‌تر با کوروش.",
        "fonts": ["Afsaneh", "Kourush"],
        "style": {"bold": True, "italic": False, "stroke": "none", "shadow": False},
    },
    "fear": {
        "label": "بالن ترس و لرزش",
        "description": "لبهٔ لرزان و ناهموار؛ ترس یا خجالت شخصیت.",
        "fonts": ["B Siavash", "B Moj", "Haleh", "Setareh", "Gam Azad"],
        "style": {"bold": False, "italic": False, "stroke": "none", "shadow": False},
    },
    "monster": {
        "label": "ترسناک یا حرف زدن هیولا",
        "description": "بالن بی‌قاعده و نامنظم برای صداهای هیولاگونه و ترسناک.",
        "fonts": ["A Kordi", "A Zangar", "Aref Graffiti"],
        "style": {"bold": True, "italic": False, "stroke": "none", "shadow": True},
    },
    "cloud": {
        "label": "بالن ابری (ناز و عشوه)",
        "description": "بالن کنگره‌ای مانند ابر؛ لحن ناز و عشوه یا صورت سرخ‌شده.",
        "fonts": ["Mj_Ramollah", "Mj_Parand"],
        "style": {"bold": False, "italic": False, "stroke": "none", "shadow": False},
    },
    "outside": {
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
    "unknown": {
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
    "unknown": (120, 120, 120),
}

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
            for item in defects[:, 0, :]:
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


def _grow_from(seed, bright, page_height: int, page_width: int, limit: int):
    """ناحیهٔ روشنِ پیرامون یک نقطه را در پنجره‌ای روبه‌بزرگ‌شدن پر می‌کند.

    خروجی: (ماسک ناحیه، مبدأ پنجره، محصور بودن). اگر ناحیه به لبهٔ پنجره بچسبد،
    پنجره بزرگ‌تر می‌شود؛ اگر تا سقف هم محصور نشد، یعنی به پس‌زمینه راه دارد.
    """
    import cv2
    import numpy as np

    seed_x, seed_y = seed
    size = 48
    while True:
        x0 = max(0, seed_x - size)
        y0 = max(0, seed_y - size)
        x1 = min(page_width, seed_x + size + 1)
        y1 = min(page_height, seed_y + size + 1)
        window = bright[y0:y1, x0:x1]
        if window[seed_y - y0, seed_x - x0] == 0:
            return None, (x0, y0), False
        mask = np.zeros((window.shape[0] + 2, window.shape[1] + 2), np.uint8)
        cv2.floodFill(window.copy(), mask, (seed_x - x0, seed_y - y0), 1,
                      flags=4 | (1 << 8) | cv2.FLOODFILL_MASK_ONLY)
        blob = mask[1:-1, 1:-1]
        touches = bool(blob[0, :].any() or blob[-1, :].any() or blob[:, 0].any() or blob[:, -1].any())
        grown_to_page = (x1 - x0) >= page_width or (y1 - y0) >= page_height
        if not touches:
            return _fill_holes(blob), (x0, y0), True
        if grown_to_page or size >= limit:
            return _fill_holes(blob), (x0, y0), False
        size = min(limit, size * 2)


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
    """نزدیک‌ترین پیکسل روشن به مرکز کادر متن، در حلقهٔ اطراف آن."""
    import numpy as np

    height, width = bright.shape[:2]
    x0 = max(0, bbox[0] - padding)
    y0 = max(0, bbox[1] - padding)
    x1 = min(width, bbox[2] + padding + 1)
    y1 = min(height, bbox[3] + padding + 1)
    window = bright[y0:y1, x0:x1]
    ys, xs = np.nonzero(window)
    if not len(xs):
        return None
    center_x = (bbox[2] - bbox[0]) / 2
    center_y = (bbox[3] - bbox[1]) / 2
    index = int(np.argmin((xs - center_x) ** 2 + (ys - center_y) ** 2))
    return int(xs[index] + x0), int(ys[index] + y0)


def _has_companions(bright, bubble: dict, height: int, width: int) -> bool:
    """آیا ناحیه‌های روشن کوچک و محصوری کنار این بالن هست (حباب‌های تفکر)؟"""
    import cv2
    import numpy as np

    bx, by, bw, bh = bubble["bbox"]
    area = float(bubble["features"].get("area", bw * bh))
    pad = max(24, int(0.5 * max(bw, bh)))
    x0, y0 = max(0, bx - pad), max(0, by - pad)
    x1, y1 = min(width, bx + bw + pad), min(height, by + bh + pad)
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
        if min(w, h) / max(w, h) < 0.6:
            continue  # حباب تفکر تقریباً گرد است
        if region_area / float(w * h) < 0.45:
            continue
        # خودِ بالن (یا بخشی از آن) نباید حباب همراه شمرده شود.
        overlaps = not (x + x0 >= bx + bw or x + x0 + w <= bx or y + y0 >= by + bh or y + y0 + h <= by)
        if overlaps:
            continue
        companions += 1
    # بالن تفکر معمولاً ۲ تا ۳ حباب کوچک دارد؛ یکی احتمالاً لکه یا نور است.
    return companions >= 2


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
    limit = int(min(height, width) * 0.6)

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
        blob, origin, enclosed = _grow_from(seed, bright, height, width, limit)
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
        try:
            features = _contour_features(union, total)
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
            "lines": sorted(found[member]["line"] for member in members),
            "features": {key: value for key, value in features.items() if key != "contour"},
        })

    # حباب‌های کوچک بی‌متن نزدیک یک بالن = نشانهٔ تفکر حباب‌دار.
    for bubble in bubbles:
        if bubble["kind"] not in {"speech", "unknown"}:
            continue
        if _has_companions(bright, bubble, height, width):
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
