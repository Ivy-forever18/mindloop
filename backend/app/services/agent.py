import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import settings


@dataclass
class ParsedCapture:
    intent: str
    content: str
    remind_at: datetime | None = None
    clarification: str | None = None


class CognitiveAgent:
    """Deterministic offline agent. Replace methods with an LLM/ASR adapter in production."""

    def atomize(self, title: str, context: str | None = None) -> list[tuple[str, int]]:
        clean = title.strip().rstrip("。.!！")
        patterns = [
            (r"(周报|报告)", [("打开对应文档", 2), ("写下已完成的三件事", 8), ("补充结果或数据", 8), ("写下下一步计划", 5)]),
            (r"(汇报|PPT|演示)", [("打开已有的演示文稿或新建文件", 2), ("新建第一页并写下标题", 5), ("列出三个核心要点", 8), ("为每个要点补一条证据", 10)]),
            (r"(学习|复习|看书)", [("打开学习材料并定位到要学的章节", 3), ("读第一个小节并划出一个重点", 8), ("用一句话复述刚才的内容", 3)]),
        ]
        for pattern, steps in patterns:
            if re.search(pattern, clean, re.I):
                return steps
        return [(f"打开完成“{clean}”所需的材料", 3), ("写下最小可交付结果的一句话描述", 5), ("完成其中第一个可见动作", 8)]

    def shrink(self, step: str) -> tuple[str, int]:
        return (f"找到并打开：{step.replace('打开', '').strip()}", 2) if "打开" in step else (f"先写下与“{step}”有关的一个词", 2)

    def parse_capture(self, text: str, now: datetime | None = None) -> ParsedCapture:
        tz = ZoneInfo(settings.timezone)
        base = now or datetime.now(tz)
        if base.tzinfo is None:
            base = base.replace(tzinfo=tz)
        normalized = text.strip()
        wants_start = any(x in normalized for x in ("开始做", "不知道从哪", "帮我开始", "拆解"))
        has_reminder_word = "提醒" in normalized
        date = base.date()
        if "明天" in normalized:
            date = (base + timedelta(days=1)).date()
        elif "后天" in normalized:
            date = (base + timedelta(days=2)).date()
        time_match = re.search(r"(?:(早上|上午|中午|下午|晚上)\s*)?([0-2]?\d)(?:[:：点时]([0-5]?\d)?)?", normalized)
        remind_at = None
        if time_match:
            period, hour_raw, minute_raw = time_match.groups()
            hour, minute = int(hour_raw), int(minute_raw or 0)
            if period in ("下午", "晚上") and hour < 12:
                hour += 12
            if period == "中午" and hour < 11:
                hour += 12
            try:
                remind_at = datetime.combine(date, datetime.min.time(), tz) + timedelta(hours=hour, minutes=minute)
            except ValueError:
                remind_at = None
        content = re.sub(r"^(请|帮我)?", "", normalized)
        content = re.sub(r"(明天|后天|今天)?\s*(早上|上午|中午|下午|晚上)?\s*[0-2]?\d(?:[:：点时][0-5]?\d?)?\s*提醒我", "", content).strip(" ，,。")
        if wants_start:
            return ParsedCapture("task", normalized)
        if has_reminder_word and remind_at:
            return ParsedCapture("reminder", content or normalized, remind_at)
        if has_reminder_word:
            return ParsedCapture("reminder", content or normalized, clarification="你想在哪一天、几点提醒？")
        return ParsedCapture("todo", normalized)


agent = CognitiveAgent()
