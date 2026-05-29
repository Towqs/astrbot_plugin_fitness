"""动作视频引导工具。"""
from __future__ import annotations

import re
from urllib.parse import quote


ACTION_ALIASES = {
    "杠铃卧推": "杠铃卧推动作教学",
    "上斜哑铃卧推": "上斜哑铃卧推动作教学",
    "哑铃卧推": "哑铃卧推动作教学",
    "俯卧撑": "俯卧撑标准动作教学",
    "标准俯卧撑": "俯卧撑标准动作教学",
    "引体向上": "引体向上动作教学",
    "反手引体向上": "反手引体向上动作教学",
    "杠铃划船": "杠铃划船动作教学",
    "坐姿划船": "坐姿划船动作教学",
    "坐姿下拉": "高位下拉动作教学",
    "哑铃划船": "哑铃划船动作教学",
    "杠铃深蹲": "杠铃深蹲动作教学",
    "哑铃深蹲": "哑铃深蹲动作教学",
    "深蹲": "深蹲标准动作教学",
    "罗马尼亚硬拉": "罗马尼亚硬拉动作教学",
    "杠铃硬拉": "硬拉动作教学",
    "哑铃硬拉": "哑铃硬拉动作教学",
    "腿举": "腿举动作教学",
    "箭步蹲": "箭步蹲动作教学",
    "保加利亚分腿蹲": "保加利亚分腿蹲动作教学",
    "臀桥": "臀桥动作教学",
    "哑铃推肩": "哑铃推肩动作教学",
    "侧平举": "侧平举动作教学",
    "哑铃侧平举": "侧平举动作教学",
    "俯身飞鸟": "俯身飞鸟动作教学",
    "绳索下压": "绳索下压动作教学",
    "杠铃弯举": "杠铃弯举动作教学",
    "哑铃弯举": "哑铃弯举动作教学",
    "锤式弯举": "锤式弯举动作教学",
    "平板支撑": "平板支撑动作教学",
    "卷腹": "卷腹动作教学",
    "死虫": "死虫动作教学",
    "登山跑": "登山跑动作教学",
    "波比跳": "波比跳动作教学",
    "开合跳": "开合跳动作教学",
    "高抬腿": "高抬腿动作教学",
    "跑步机快走": "跑步机快走教学",
    "跑步机慢跑": "跑步机跑步教学",
    "椭圆机": "椭圆机使用教学",
    "划船机": "划船机动作教学",
    "全身拉伸": "全身拉伸教程",
    "泡沫轴放松": "泡沫轴放松教程",
}


def _bilibili_search_url(keyword: str) -> str:
    return f"https://search.bilibili.com/all?keyword={quote(keyword)}"


def _extract_action_name(item: str) -> str:
    item = re.sub(r"^\s*\d+[.、]\s*", "", item).strip()
    item = re.sub(r"\([^)]*\)", "", item).strip()
    item = re.split(
        r"\s+\d+|\s+[0-9一二三四五六七八九十]+组|\s+\d+分钟",
        item,
        maxsplit=1,
    )[0]
    return item.strip(" ：:-")


def extract_actions(workout_detail: str) -> list[str]:
    """从计划详情中提取动作名，兼容“1.动作 组次 2.动作 组次”格式。"""
    if not workout_detail:
        return []
    parts = re.findall(r"(?:^|\s)(\d+[.、]\s*.*?)(?=\s+\d+[.、]\s*|$)", workout_detail)
    if not parts:
        parts = [p.strip() for p in re.split(r"[；;\n]", workout_detail) if p.strip()]
    actions = []
    seen = set()
    for part in parts:
        name = _extract_action_name(part)
        if name and name not in seen and "休息" not in name:
            actions.append(name)
            seen.add(name)
    return actions


def video_guides_for_detail(workout_detail: str, max_items: int = 5) -> list[dict[str, str]]:
    guides = []
    for action in extract_actions(workout_detail)[:max_items]:
        keyword = ACTION_ALIASES.get(action, f"{action} 动作教学")
        guides.append({
            "action": action,
            "title": f"{action} 动作教学",
            "content": "B站视频搜索参考，训练前先看动作要点",
            "url": _bilibili_search_url(keyword),
        })
    return guides


def format_video_guides(workout_detail: str, max_items: int = 5) -> str:
    guides = video_guides_for_detail(workout_detail, max_items=max_items)
    if not guides:
        return ""
    lines = ["\n🎬 动作视频参考（B站搜索）:"]
    for item in guides:
        lines.append(f"- {item['action']}: {item['url']}")
    return "\n".join(lines)
