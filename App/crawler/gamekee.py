import json
import ssl
import time
import urllib.request
from pathlib import Path
from typing import Optional

from .models import GameKeeArticle, GameKeeActivity, GameKeeGameInfo
from ..update_utils import get_base_dir

CACHE_DIR = get_base_dir() / "data" / "crawler_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

LIST_CACHE_TTL = 600
DETAIL_CACHE_TTL = 3600
GAME_INFO_CACHE_TTL = 3600

BA_GAME_ID = 829
BA_ALIAS = "ba"

API_BASE = "https://www.gamekee.com"
CONTENT_API_BASE = "https://api-cdn.gamekee.com/wiki2.0/pro"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "game-alias": BA_ALIAS,
    "device-num": "1",
}

REQUEST_INTERVAL = 1.5


class RateLimiter:
    def __init__(self, interval: float = REQUEST_INTERVAL):
        self.interval = interval
        self._last_time = 0.0

    def wait(self):
        now = time.time()
        elapsed = now - self._last_time
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self._last_time = time.time()


_rate_limiter = RateLimiter()


def _cache_path(key: str) -> Path:
    safe = key.replace("/", "_").replace("?", "_").replace("&", "_").replace("=", "_")
    return CACHE_DIR / f"{safe}.json"


def _load_cache(path: Path, ttl: int) -> Optional[dict]:
    if path.exists():
        mtime = path.stat().st_mtime
        if time.time() - mtime < ttl:
            try:
                return json.loads(path.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
    return None


def _save_cache(path: Path, data: dict):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _request(path: str, use_cache: bool = True, cache_ttl: int = LIST_CACHE_TTL) -> dict:
    url = f"{API_BASE}{path}"
    cache_key = path

    if use_cache:
        cached = _load_cache(_cache_path(cache_key), cache_ttl)
        if cached:
            return cached

    _rate_limiter.wait()

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {url}: {e}")

    data = json.loads(raw)
    if data.get("code") != 0:
        raise RuntimeError(f"API error for {url}: {data.get('msg', 'unknown')}")

    result = data["data"] if "data" in data else data
    if use_cache:
        _save_cache(_cache_path(cache_key), result)
    return result


class GameKeeClient:
    def __init__(self):
        self._game_info: Optional[GameKeeGameInfo] = None

    def get_game_info(self) -> GameKeeGameInfo:
        if self._game_info:
            return self._game_info
        cached = _load_cache(_cache_path("game_detail"), GAME_INFO_CACHE_TTL)
        if cached:
            self._game_info = GameKeeGameInfo(
                id=cached["id"], name=cached["name"], alias=cached["alias"],
                icon=cached["icon"], entry_count=cached["entry_count"],
                content_count=cached["content_count"], follow_count=cached["follow_count"],
            )
            return self._game_info
        data = _request("/v1/game/detail", use_cache=False)
        info = GameKeeGameInfo(
            id=data["id"],
            name=data["name"],
            alias=data["alias"],
            icon=data["icon"],
            entry_count=data["entry_count"],
            content_count=data["content_count"],
            follow_count=data["follow_count"],
        )
        _save_cache(_cache_path("game_detail"), {
            "id": data["id"], "name": data["name"], "alias": data["alias"],
            "icon": data["icon"], "entry_count": data["entry_count"],
            "content_count": data["content_count"], "follow_count": data["follow_count"],
        })
        self._game_info = info
        return info

    def get_articles(self, page: int = 1, page_size: int = 20, entry_id: Optional[int] = None, server_id: Optional[int] = None, content_type: Optional[str] = None) -> list[GameKeeArticle]:
        path = f"/v1/content/pageList?page={page}&pageSize={page_size}"
        if entry_id is not None:
            path += f"&entry_id={entry_id}"
        if server_id is not None:
            path += f"&server_id={server_id}"
        if content_type is not None:
            path += f"&type={content_type}"
        data = _request(path)
        items = data if isinstance(data, list) else data.get("list", data)
        return [self._parse_article(item) for item in items]

    def get_article_detail(self, content_id: int) -> Optional[str]:
        cpath = f"/v1/content/detail/{content_id}"
        try:
            resp = _request(cpath, cache_ttl=DETAIL_CACHE_TTL)
        except RuntimeError:
            return None
        if isinstance(resp, dict):
            return resp.get("content") or resp.get("content_detail")
        return None

    def get_rich_content(self, content_id: int) -> Optional[dict]:
        url = f"{CONTENT_API_BASE}/{BA_GAME_ID}/content/{content_id}.json"
        _rate_limiter.wait()
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={
            "User-Agent": DEFAULT_HEADERS["User-Agent"],
            "Referer": f"{API_BASE}/",
        })
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def get_activities(self, page: int = 1, page_size: int = 50, server_id: Optional[int] = None) -> list[GameKeeActivity]:
        path = f"/v1/activity/page-list?page={page}&pageSize={page_size}"
        if server_id is not None:
            path += f"&serverId={server_id}"
        data = _request(path)
        items = data if isinstance(data, list) else data.get("list", data)
        return [self._parse_activity(item) for item in items]

    def _parse_article(self, item: dict) -> GameKeeArticle:
        return GameKeeArticle(
            id=item["id"],
            title=item.get("title", ""),
            summary=item.get("summary", ""),
            created_at=item.get("created_at", 0),
            updated_at=item.get("updated_at", 0),
            view_count=item.get("view_count", 0),
            like_count=item.get("like_count", 0),
            comment_count=item.get("comment_count", 0),
            thumb=item.get("thumb", ""),
            entry_id=item.get("entry_id", 0),
            content_type=item.get("content_type", 0),
            is_top=item.get("is_top", 0),
            tags=item.get("tag", ""),
            server_id=item.get("server_id", 0),
            user_name=item.get("user", {}).get("nickname", "") if item.get("user") else "",
            content_detail=item.get("content_detail"),
        )

    def _parse_activity(self, item: dict) -> GameKeeActivity:
        return GameKeeActivity(
            id=item["id"],
            title=item.get("title", ""),
            description=item.get("description", ""),
            link_url=item.get("link_url", ""),
            picture=item.get("picture", ""),
            begin_at=item.get("begin_at", 0),
            end_at=item.get("end_at", 0),
            activity_kind_id=item.get("activity_kind_id", 0),
            activity_kind_name=item.get("activity_kind_name", ""),
            activity_state=item.get("activity_state", 0),
            pub_area=item.get("pub_area", ""),
            tag=item.get("tag", ""),
        )
