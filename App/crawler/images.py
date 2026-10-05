import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from .models import GameKeeActivity
from ..update_utils import get_base_dir

IMAGE_DIR = get_base_dir() / "data" / "activity_images"

IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Referer": "https://www.gamekee.com/",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "zh-CN",
}


def _full_url(url: str) -> Optional[str]:
    if not url:
        return None
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return None


def image_path(activity: GameKeeActivity) -> Optional[Path]:
    url = _full_url(activity.picture)
    if not url:
        return None
    ext = Path(url).suffix or ".webp"
    if len(ext) > 8:
        ext = ".webp"
    return IMAGE_DIR / f"{activity.id}{ext}"


def ensure_activity_image(activity: GameKeeActivity) -> Optional[Path]:
    path = image_path(activity)
    if path is None:
        return None
    if path.exists():
        return path
    url = _full_url(activity.picture)
    req = urllib.request.Request(url, headers=IMAGE_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        if not data:
            return None
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path
    except Exception:
        return None


def download_all_images(activities: list[GameKeeActivity]) -> None:
    missing = [a for a in activities if _needs_download(a)]
    if not missing:
        return
    with ThreadPoolExecutor(max_workers=min(len(missing), 4)) as pool:
        list(pool.map(ensure_activity_image, missing))


def _needs_download(activity: GameKeeActivity) -> bool:
    path = image_path(activity)
    return path is not None and not path.exists()
