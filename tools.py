# -*- coding: utf-8 -*-
"""辅助函数 - 随机事件、QQ群头衔设置等"""
import random
from astrbot import logger


async def set_qq_group_title(event, user_id: str, title: str) -> bool:
    """通过 event.bot 调用 OneBot API 设置群专属头衔（使用 AstrBot 已配置的连接）"""
    try:
        group_id = event.get_group_id()
        await event.bot.set_group_special_title(
            group_id=int(group_id),
            user_id=int(user_id),
            special_title=title,
            duration=-1,
        )
        return True
    except Exception as e:
        logger.warning(f"设置群头衔失败: {e}")
    return False


# 随机事件表
RANDOM_EVENTS = [
    {"name": "暴击训练", "prob": 0.08, "type": "exp_mult", "value": 2,
     "msg": "💥 暴击训练！经验值翻倍！"},
    {"name": "宝箱掉落", "prob": 0.06, "type": "exp_add", "value": 80,
     "msg": "🎁 发现宝箱！额外获得 80 经验！"},
    {"name": "连击加成", "prob": 0.10, "type": "exp_add", "value": 30,
     "msg": "⚡ 连击加成！额外获得 30 经验！"},
    {"name": "蛋白质增幅", "prob": 0.07, "type": "exp_add", "value": 40,
     "msg": "🥩 蛋白质增幅！额外获得 40 经验！"},
    {"name": "BOSS遭遇战", "prob": 0.03, "type": "exp_add", "value": 150,
     "msg": "🐉 BOSS遭遇战！击败BOSS获得 150 经验！"},
]


def roll_random_event():
    """掷骰子触发随机事件，返回事件 dict 或 None"""
    for evt in RANDOM_EVENTS:
        if random.random() < evt["prob"]:
            return evt
    return None
