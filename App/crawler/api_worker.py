"""HTTP API-based GameKee activity fetcher (no browser fallback)."""

import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from .models import GameKeeActivity
from ..update_utils import get_base_dir

API_URL = "https://wiki.ldmnq.com/v1/activity/page-list"

API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "game-alias": "ba",
    "lang": "zh-cn",
    "x-requested-with": "XMLHttpRequest",
    "accept": "application/json, text/plain, */*",
    "accept-language": "zh-CN",
}

CACHE_DIR = get_base_dir() / "data" / "crawler_cache"
CACHE_TTL = 900
MAX_WORKERS = 4


def _get_cache_path(server_id: int) -> Path:
    return CACHE_DIR / f"browser_activities_{server_id}.json"


def _load_cache_stale(server_id: int) -> Optional[list]:
    """Load cache ignoring TTL; used as fallback when a refresh fails."""
    path = _get_cache_path(server_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return None


def _load_cache(server_id: int) -> Optional[list]:
    path = _get_cache_path(server_id)
    if path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL:
        try:
            return json.loads(path.read_text("utf-8"))
        except Exception:
            pass
    return None


def _save_cache(server_id: int, items: list):
    active = [i for i in items if i.get("activity_state", 0) in (1, 2)]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _get_cache_path(server_id).write_text(
        json.dumps(active, ensure_ascii=False, indent=2), "utf-8"
    )


def _activities_from_cache(cached) -> list:
    """Hydrate cached rows into activities, skipping malformed entries."""
    items = []
    for row in cached:
        try:
            items.append(GameKeeActivity(**row))
        except Exception:
            continue
    return items


def _row_to_activity(row: dict) -> GameKeeActivity:
    return GameKeeActivity(
        id=int(row.get("id") or 0),
        title=row.get("title") or "",
        description=row.get("description") or "",
        link_url=row.get("link_url") or "",
        picture=row.get("picture") or "",
        begin_at=int(row.get("begin_at") or 0),
        end_at=int(row.get("end_at") or 0),
        activity_kind_id=int(row.get("activity_kind_id") or 0),
        activity_kind_name=row.get("activity_kind_name") or "",
        activity_state=int(row.get("activity_state") or 0),
        pub_area=row.get("pub_area") or "",
        tag=row.get("tag") or "",
    )


def _fetch_server(server_id: int) -> tuple[int, list[GameKeeActivity]]:
    url = f"{API_URL}?importance=0&sort=-1&keyword=&limit=999&page_no=1&serverId={server_id}&status=0"
    headers = dict(API_HEADERS)
    headers["referer"] = f"https://wiki.ldmnq.com/ba/huodong/{server_id}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if body.get("code") != 0:
        raise RuntimeError(body.get("msg") or "api error")
    rows = body.get("data") or []
    items: list[GameKeeActivity] = []
    for row in rows:
        try:
            items.append(_row_to_activity(row))
        except Exception:
            continue
    return server_id, items


def fetch_all_activities(server_ids: list[int], force: bool = False) -> dict[int, list[GameKeeActivity]]:
    """Fetch activities via HTTP API in parallel.

    Parameters
    ----------
    force: bool
        if True, bypass the local cache and always hit the network
    """
    results: dict[int, list[GameKeeActivity]] = {}
    pending: list[int] = []
    for sid in server_ids:
        if force:
            pending.append(sid)
            continue
        cached = _load_cache(sid)
        if cached is not None:
            results[sid] = _activities_from_cache(cached)
        else:
            pending.append(sid)

    if not pending:
        return results

    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=min(len(pending), MAX_WORKERS)) as pool:
        futures = {pool.submit(_fetch_server, sid): sid for sid in pending}
        for future in futures:
            sid = futures[future]
            try:
                got_sid, items = future.result()
                results[got_sid] = items
                _save_cache(got_sid, [vars(a) for a in items])
            except Exception as e:
                stale = _load_cache_stale(sid)
                if stale is not None:
                    results[sid] = _activities_from_cache(stale)
                else:
                    errors.append(f"server {sid}: {e}")

    if errors:
        raise RuntimeError("获取活动失败: " + "; ".join(errors))

    return results