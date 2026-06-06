import json
import time
import datetime
import urllib.request
import os


class SchaleDBCrawler:
    BASE_URL = "https://schaledb.com/data"
    USER_AGENT = "AronaAI/1.0 (Blue Archive fan tool; +https://github.com/33770046/AronaAI)"
    CACHE_DURATION = 600  # 10 minutes

    def __init__(self, cache_dir=None):
        self._cache = {}
        if cache_dir is None:
            cache_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")
        self._cache_dir = cache_dir
        os.makedirs(self._cache_dir, exist_ok=True)

    def _fetch_json(self, path):
        cache_key = path
        cached = self._cache.get(cache_key)
        if cached and time.time() - cached["time"] < self.CACHE_DURATION:
            return cached["data"]

        cache_file = os.path.join(self._cache_dir, path.replace("/", "_") + ".json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._cache[cache_key] = {"data": data, "time": time.time()}
                return data
            except Exception:
                pass

        url = f"{self.BASE_URL}/{path}"
        req = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            self._cache[cache_key] = {"data": data, "time": time.time()}
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
            except Exception:
                pass
            return data
        except Exception as e:
            cached = self._cache.get(cache_key)
            if cached:
                return cached["data"]
            raise

    def get_config(self):
        return self._fetch_json("config.min.json")

    def get_events(self):
        return self._fetch_json("en/events.json")

    def _fetch_students_cn(self):
        return self._fetch_json("cn/students.json")

    def _get_character_name(self, cid):
        students = self._fetch_students_cn()
        return students.get(str(cid), {}).get("Name", str(cid))

    def _fetch_localization_cn(self):
        return self._fetch_json("cn/localization.json")

    def _fetch_raids_cn(self):
        return self._fetch_json("cn/raids.json")

    def _get_raid_name(self, rtype, raid_id):
        raids = self._fetch_raids_cn()
        key_map = {"Raid": "Raid", "EliminateRaid": "Raid", "MultiFloorRaid": "MultiFloorRaid", "TimeAttack": "TimeAttack"}
        arr = raids.get(key_map.get(rtype, "Raid"), [])
        for r in arr:
            if r["Id"] == raid_id:
                return r.get("Name", "")
        return ""

    @staticmethod
    def ts_to_local(ts):
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def ts_to_relative(ts):
        now = time.time()
        diff = ts - now
        if diff < 0:
            return "已结束"
        days = int(diff // 86400)
        hours = int((diff % 86400) // 3600)
        if days > 0:
            return f"剩余 {days} 天 {hours} 小时"
        return f"剩余 {hours} 小时"

    @staticmethod
    def raid_type_cn(rtype):
        mapping = {
            "Raid": "总力战",
            "EliminateRaid": "大决战",
            "MultiFloorRaid": "无限制决战",
            "TimeAttack": "综合战术测试",
        }
        return mapping.get(rtype, rtype)

    def get_current_activities(self, region_name="Global"):
        config = self.get_config()
        region = None
        for r in config["Regions"]:
            if r["Name"] == region_name:
                region = r
                break
        if not region:
            return None

        events_data = self.get_events()
        event_list = events_data.get("Events", [])

        activities = {
            "events": [],
            "raids": [],
            "gacha": [],
            "region": region_name,
        }

        event_map = {e["Id"]: e for e in event_list}

        for ev in region.get("CurrentEvents", []):
            eid = ev["event"]
            meta = event_map.get(eid, {})
            name = self._get_event_name(eid, meta)
            activities["events"].append({
                "id": eid,
                "name": name,
                "start": ev["start"],
                "end": ev["end"],
                "start_str": self.ts_to_local(ev["start"]),
                "end_str": self.ts_to_local(ev["end"]),
                "remaining": self.ts_to_relative(ev["end"]),
            })

        for rd in region.get("CurrentRaid", []):
            raid_name = self._get_raid_name(rd["type"], rd["raid"])
            season_str = f"第{rd.get('season', '')}期 " if rd.get('season') else ""
            terrain = rd.get("terrain", "")
            terrain_cn = {"Street": "市街", "Outdoor": "室外", "Indoor": "室内"}.get(terrain, terrain)
            terrain_part = f" [{terrain_cn}]" if terrain_cn else ""
            subtitle = f"{season_str}{raid_name}{terrain_part}" if raid_name else f"{season_str}{terrain_part}"
            activities["raids"].append({
                "type": rd["type"],
                "type_cn": self.raid_type_cn(rd["type"]),
                "name": subtitle,
                "terrain": terrain_cn,
                "season": rd.get("season", ""),
                "start": rd["start"],
                "end": rd["end"],
                "start_str": self.ts_to_local(rd["start"]),
                "end_str": self.ts_to_local(rd["end"]),
                "remaining": self.ts_to_relative(rd["end"]),
            })

        for gb in region.get("CurrentGacha", []):
            char_names = [self._get_character_name(c) for c in gb["characters"]]
            activities["gacha"].append({
                "characters": gb["characters"],
                "char_names": char_names,
                "start": gb["start"],
                "end": gb["end"],
                "start_str": self.ts_to_local(gb["start"]),
                "end_str": self.ts_to_local(gb["end"]),
                "remaining": self.ts_to_relative(gb["end"]),
            })

        activities["birthdays"] = self._get_upcoming_birthdays()

        return activities

    def _get_upcoming_birthdays(self, days=14):
        students = self._fetch_students_cn()
        now = datetime.datetime.now()
        upcoming = []
        for sid, s in students.items():
            bd = s.get("BirthDay", "")
            if not bd:
                continue
            parts = bd.split("/")
            if len(parts) != 2:
                continue
            try:
                m, d = int(parts[0]), int(parts[1])
            except ValueError:
                continue
            bd_this_year = datetime.datetime(now.year, m, d)
            bd_next_year = datetime.datetime(now.year + 1, m, d)
            diff = (bd_this_year - now).total_seconds()
            if diff < -86400:
                diff = (bd_next_year - now).total_seconds()
            today = (m == now.month and d == now.day)
            if today:
                diff = 0
            if 0 <= diff <= days * 86400:
                name = s.get("Name", str(sid))
                school = s.get("School", "")
                remaining = "今天" if today else self.ts_to_relative(now.timestamp() + diff)
                upcoming.append({
                    "id": int(sid),
                    "name": name,
                    "school": school,
                    "month": m,
                    "day": d,
                    "today": today,
                    "remaining": remaining,
                })
        upcoming.sort(key=lambda x: (x["month"], x["day"]))
        return upcoming

    def _get_event_name(self, eid, meta):
        loc = self._fetch_localization_cn()
        names = loc.get("EventName", {})
        return names.get(str(eid), f"#{eid}")

    def clear_cache(self):
        self._cache.clear()
        if os.path.exists(self._cache_dir):
            for f in os.listdir(self._cache_dir):
                if f.endswith(".json"):
                    try:
                        os.remove(os.path.join(self._cache_dir, f))
                    except Exception:
                        pass
