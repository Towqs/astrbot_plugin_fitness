# -*- coding: utf-8 -*-
"""
定时提醒模块 - 基于 APScheduler 精确触发
- 配置了 lite_provider_id → 用低成本 AI 生成个性化提醒
- 未配置 → 纯模板拼接，零 AI 成本
"""
from datetime import date
from astrbot import logger
from . import database as db
from .rpg import get_title
from .prompts import REMINDER_TEMPLATES, REMINDER_AI_PROMPT

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
except ImportError:
    AsyncIOScheduler = None
    CronTrigger = None

try:
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import AiocqhttpAdapter
except ImportError:
    AiocqhttpAdapter = None


class ScheduledReminder:
    """
    基于 APScheduler 的精确提醒服务。
    按用户设定的提醒时间分组，每个时间点一个 cron job。
    """

    def __init__(self, context, lite_provider_id: str = ""):
        self.context = context
        self.lite_provider_id = lite_provider_id
        self._scheduler = None
        self._reminded_today: set = set()
        self._last_date: str = ""

    def start(self):
        if not AsyncIOScheduler or not CronTrigger:
            logger.warning("APScheduler 不可用，提醒服务未启动")
            return
        self._scheduler = AsyncIOScheduler()
        self._scheduler.start()
        self._scheduler.add_job(
            self._daily_refresh,
            trigger=CronTrigger(hour=0, minute=1),
            name="fitness_daily_refresh",
            misfire_grace_time=120,
        )
        self._rebuild_jobs()
        mode = "AI个性化" if self.lite_provider_id else "纯模板"
        logger.info(f"健身打卡提醒服务已启动 (APScheduler, {mode}模式)")

    def stop(self):
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("健身打卡提醒服务已停止")

    def refresh(self):
        """用户修改提醒时间后调用，重建所有 cron job"""
        if self._scheduler:
            self._rebuild_jobs()

    # ==================== 内部方法 ====================

    def _rebuild_jobs(self):
        """从数据库读取所有提醒时间，按时间点分组注册 cron job"""
        for job in self._scheduler.get_jobs():
            if job.name.startswith("fitness_remind_"):
                job.remove()

        profiles = db.get_all_active_profiles()
        time_groups = {}
        for p in profiles:
            rt = p.get("reminder_time", "")
            if not rt or ":" not in rt:
                continue
            time_groups.setdefault(rt, [])

        for time_str in time_groups:
            try:
                hour, minute = map(int, time_str.split(":"))
                self._scheduler.add_job(
                    self._on_remind_tick,
                    trigger=CronTrigger(hour=hour, minute=minute),
                    args=[time_str],
                    name=f"fitness_remind_{time_str}",
                    misfire_grace_time=120,
                )
            except Exception as e:
                logger.warning(f"注册提醒任务 {time_str} 失败: {e}")

        logger.info(f"已注册 {len(time_groups)} 个提醒时间点")

    async def _daily_refresh(self):
        self._reminded_today.clear()
        self._last_date = date.today().isoformat()
        self._rebuild_jobs()

    async def _on_remind_tick(self, time_str: str):
        """某个时间点触发，查找该时间的所有用户并发送提醒"""
        today = date.today().isoformat()
        if today != self._last_date:
            self._reminded_today.clear()
            self._last_date = today

        profiles = db.get_profiles_by_reminder_time(time_str)

        for p in profiles:
            user_id = p["user_id"]
            group_id = p["group_id"]
            reminder_key = f"{user_id}:{group_id}"

            if reminder_key in self._reminded_today:
                continue

            checkin = db.get_today_checkin(user_id, group_id)
            if checkin:
                self._reminded_today.add(reminder_key)
                continue

            if p.get("current_status", "normal") in ("sick", "injured", "rest"):
                self._reminded_today.add(reminder_key)
                continue

            # 生成提醒消息
            msg = await self._build_reminder_msg(p)
            await self._send_group_message(group_id, user_id, msg)
            self._reminded_today.add(reminder_key)
            logger.info(f"已发送打卡提醒给 {p.get('nickname', user_id)}({user_id})")

    async def _build_reminder_msg(self, p: dict) -> str:
        """构建提醒消息：有低成本模型走AI，否则纯模板"""
        nickname = p.get("nickname", p["user_id"])
        streak = db.get_checkin_streak(p["user_id"], p["group_id"])
        level = p.get("level", 1)
        quest_days = p.get("quest_days", 0)
        quest_progress = p.get("quest_progress", 0)
        title = get_title(level)

        # 尝试用低成本 AI 生成
        if self.lite_provider_id:
            try:
                ai_msg = await self._generate_ai_reminder(p, nickname, streak)
                if ai_msg:
                    # AI 生成的消息前面加上等级标识
                    return f"Lv.{level}【{title}】{nickname}\n{ai_msg}"
            except Exception as e:
                logger.debug(f"AI提醒生成失败，回退模板: {e}")

        # 纯模板模式
        quest_line = ""
        if quest_days > 0 and quest_progress < quest_days:
            remaining = quest_days - quest_progress
            quest_line = REMINDER_TEMPLATES["quest"].format(
                quest_progress=quest_progress, quest_days=quest_days, remaining=remaining
            )

        streak_line = ""
        if streak > 0:
            streak_line = REMINDER_TEMPLATES["streak_high"].format(streak=streak)
        else:
            streak_line = REMINDER_TEMPLATES["streak_zero"]

        return REMINDER_TEMPLATES["normal"].format(
            nickname=f"Lv.{level}【{title}】{nickname}",
            quest_line=quest_line, streak_line=streak_line,
        )

    async def _generate_ai_reminder(self, p: dict, nickname: str, streak: int) -> str:
        """用低成本模型生成个性化提醒"""
        extra_info = ""
        quest_days = p.get("quest_days", 0)
        quest_progress = p.get("quest_progress", 0)
        if quest_days > 0 and quest_progress < quest_days:
            extra_info = f"闯关进度: {quest_progress}/{quest_days}"

        prompt = REMINDER_AI_PROMPT.format(
            nickname=nickname,
            fitness_goal=p.get("fitness_goal", ""),
            streak=streak,
            current_status=p.get("current_status", "normal"),
            extra_info=extra_info,
        )

        # 通过 AstrBot 的 context.llm_generate 调用低成本模型
        resp = await self.context.llm_generate(
            chat_provider_id=self.lite_provider_id,
            prompt=prompt,
        )
        if resp and resp.completion_text:
            return resp.completion_text.strip()
        return ""

    def _get_bot_client(self):
        try:
            for inst in self.context.platform_manager.platform_insts:
                if AiocqhttpAdapter and isinstance(inst, AiocqhttpAdapter):
                    client = inst.get_client()
                    if client is not None:
                        return client
        except Exception as e:
            logger.debug(f"获取 bot 客户端失败: {e}")
        return None

    async def _send_group_message(self, group_id: str, user_id: str, text: str):
        parts = group_id.split(":")
        qq_group_id = parts[-1] if len(parts) >= 3 else group_id

        client = self._get_bot_client()
        if not client:
            logger.warning("无法获取 bot 客户端，跳过提醒发送")
            return False

        message = [
            {"type": "at", "data": {"qq": user_id}},
            {"type": "text", "data": {"text": f" {text}"}},
        ]

        try:
            gid = int(qq_group_id) if qq_group_id.isdigit() else qq_group_id
            await client.send_group_msg(group_id=gid, message=message)
            return True
        except Exception as e:
            logger.error(f"发送群消息失败: {e}")
        return False
