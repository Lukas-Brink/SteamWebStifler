import os
import sys
import io
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageDraw

from paths import BANNERS_DIR, ICONS_DIR, CACHE_DIR


class ImageCache:
    """High-performance asset cache manager for SteamWebStifler.
    Fetches crystal-clear official 1920x620 hero banners and 64x64 square icons,
    storing them strictly in the portable data/cache directory.
    """
    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="GhostAssetWorker")

    def get_banner_url(self, app_id, steam_path=None):
        return f"/cache/banners/{app_id}.jpg"

    def get_icon_url(self, app_id, steam_path=None):
        return f"/cache/icons/{app_id}.png"

    def ensure_banner(self, app_id, steam_path=None):
        """Ensures a high-resolution hero banner exists on disk.
        Prioritizes official Steam CDN 1920x620 library_hero.jpg.
        """
        dest_path = os.path.join(BANNERS_DIR, f"{app_id}.jpg")
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
            return dest_path

        # 1. Check local Steam librarycache for high-res hero
        if steam_path:
            cand = os.path.join(steam_path, "appcache", "librarycache", str(app_id), "library_hero.jpg")
            if os.path.exists(cand):
                try:
                    with Image.open(cand) as im:
                        if im.size[0] >= 600:
                            im.convert("RGB").save(dest_path, "JPEG", quality=92)
                            return dest_path
                except Exception:
                    pass

        # 2. Online fetch from official Steam CDN (Full 1920x620 HD artwork)
        cdn_urls = [
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/library_hero.jpg",
            f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{app_id}/library_hero.jpg",
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/page_bg_raw.jpg",
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/page_bg_generated_v6b.jpg",
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/capsule_616x353.jpg",
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg"
        ]

        for url in cdn_urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    if resp.status == 200:
                        raw_data = resp.read()
                        if len(raw_data) > 1000:
                            im = Image.open(io.BytesIO(raw_data))
                            im.convert("RGB").save(dest_path, "JPEG", quality=92)
                            return dest_path
            except Exception:
                continue

        # Fallback: create sleek monochrome placeholder if offline
        try:
            placeholder = Image.new("RGB", (1920, 620), (19, 21, 27))
            placeholder.save(dest_path, "JPEG", quality=85)
            return dest_path
        except Exception:
            return None

    def ensure_icon(self, app_id, steam_path=None):
        """Ensures a crisp 64x64 square icon exists on disk."""
        dest_path = os.path.join(ICONS_DIR, f"{app_id}.png")
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 200:
            return dest_path

        # 1. Check local Steam librarycache for square icon
        if steam_path:
            lib_cache = os.path.join(steam_path, "appcache", "librarycache", str(app_id))
            if os.path.isdir(lib_cache):
                try:
                    for f in os.listdir(lib_cache):
                        if f.lower().endswith((".jpg", ".png")):
                            fp = os.path.join(lib_cache, f)
                            try:
                                with Image.open(fp) as im:
                                    w, h = im.size
                                    if h > 0 and 0.8 <= (w / h) <= 1.25 and w >= 28:
                                        sq = im.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
                                        sq.save(dest_path, "PNG")
                                        return dest_path
                            except Exception:
                                continue
                except Exception:
                    pass

        # 2. Online fetch from official Steam CDN
        icon_urls = [
            f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{app_id}/logo.png",
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/capsule_sm_120.jpg",
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg"
        ]

        for url in icon_urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        raw_data = resp.read()
                        raw_im = Image.open(io.BytesIO(raw_data)).convert("RGBA")
                        w, h = raw_im.size
                        min_dim = min(w, h)
                        left = (w - min_dim) // 2
                        top = (h - min_dim) // 2
                        cropped = raw_im.crop((left, top, left + min_dim, top + min_dim))
                        sq = cropped.resize((64, 64), Image.Resampling.LANCZOS)
                        sq.save(dest_path, "PNG")
                        return dest_path
            except Exception:
                continue

        # Fallback: create clean lettermark icon if offline
        try:
            im = Image.new("RGBA", (64, 64), (27, 29, 37, 255))
            draw = ImageDraw.Draw(im)
            draw.rectangle([0, 0, 63, 63], outline=(38, 41, 51, 255), width=2)
            im.save(dest_path, "PNG")
            return dest_path
        except Exception:
            return None

    def preload_assets(self, games, steam_path=None):
        """Asynchronously pre-caches banners and icons in background pool."""
        def worker(app_id):
            self.ensure_banner(app_id, steam_path)
            self.ensure_icon(app_id, steam_path)

        for g in games:
            aid = g.get("app_id")
            if aid:
                self._executor.submit(worker, aid)


from paths import BANNERS_DIR, ICONS_DIR, CACHE_DIR, APP_DIR

def create_tray_icon_image():
    """Generates the official 64x64 SteamWebStifler circular tray icon from logo.png."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        logo_path = os.path.join(sys._MEIPASS, "gui", "logo.png")
    else:
        logo_path = os.path.join(APP_DIR, "gui", "logo.png")

    if os.path.exists(logo_path):
        try:
            with Image.open(logo_path) as im:
                return im.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
        except Exception:
            pass

    # Fallback if file missing
    img = Image.new("RGBA", (64, 64), (18, 20, 26, 255))
    return img


image_cache = ImageCache()
