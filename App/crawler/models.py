import time
from dataclasses import dataclass


@dataclass
class GameKeeActivity:
    id: int
    title: str
    description: str
    link_url: str
    picture: str
    begin_at: int
    end_at: int
    activity_kind_id: int
    activity_kind_name: str
    activity_state: int
    pub_area: str
    tag: str

    def remaining_text(self) -> str:
        now = int(time.time())
        if self.activity_state == 1 and self.end_at:
            remain = self.end_at - now
            if remain > 0:
                return _format_duration(remain, "剩")
            return "已结束"
        if self.activity_state == 2 and self.begin_at:
            wait = self.begin_at - now
            if wait > 0:
                return _format_duration(wait, "开始倒计时")
            return "即将开始"
        return self.tag or ""


def _format_duration(seconds: int, prefix: str) -> str:
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    if days > 0:
        return f"{prefix}{days}天{hours}小时"
    if hours > 0:
        return f"{prefix}{hours}小时{minutes}分"
    return f"{prefix}{minutes}分钟"
