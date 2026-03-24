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
from .prompts import (
    REMINDER_TEMPLATES, REMINDER_AI_PROMPT,
    MORNING_BRIEFING_AI_PROMPT, MORNING_BRIEFING_TEMPLATE,
    MORNING_REST_DAY_TEMPLATE,
    PRE_WORKOUT_AI_PROMPT, PRE_WORKOUT_TEMPLATE,
)
from .weekly_report import WeeklyReportGenerator
from .periodization import PeriodizationEngine

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

    def __init__(self, context, lite_provider_id: str = "",
                 saturday_feedback_time: str = "10:00",
                 weekly_report_time: str = "20:00",
                 morning_briefing_enabled: bool = True,
                 morning_briefing_time: str = "08:00",
                 pre_workout_reminder_enabled: bool = True):
        self.context = context
        self.lite_provider_id = lite_provider_id
        self.saturday_feedback_time = saturday_feedback_time
        self.weekly_report_time = weekly_report_time
        self.morning_briefing_enabled = morning_briefing_enabled
        self.morning_briefing_time = morning_briefing_time
        self.pre_workout_reminder_enabled = pre_workout_reminder_enabled
        self._scheduler = None
        self._reminded_today: set = set()
        self._briefed_today: set = set()  # 晨间推送去重
        self._pre_reminded_today: set = set()  # 训练前提醒去重
        self._last_date: str = ""
        self._weekly_report_gen = WeeklyReportGenerator()
        self._periodization_engine = PeriodizationEngine()
        self._remind_lock = False  # 防止并发重复发送

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

        # v2.0: 周六体重反馈
        try:
            sat_h, sat_m = map(int, self.saturday_feedback_time.split(":"))
            self._scheduler.add_job(
                self._on_saturday_feedback,
                trigger=CronTrigger(day_of_week="sat", hour=sat_h, minute=sat_m),
                name="fitness_saturday_feedback",
                misfire_grace_time=120,
            )
        except Exception as e:
            logger.warning(f"注册周六反馈任务失败: {e}")

        # v2.0: 群周报（周日）
        try:
            rep_h, rep_m = map(int, self.weekly_report_time.split(":"))
            self._scheduler.add_job(
                self._on_weekly_report,
                trigger=CronTrigger(day_of_week="sun", hour=rep_h, minute=rep_m),
                name="fitness_weekly_report",
                misfire_grace_time=120,
            )
        except Exception as e:
            logger.warning(f"注册周报任务失败: {e}")

        # v2.0: 去负荷检测（周一）
        self._scheduler.add_job(
            self._on_deload_check,
            trigger=CronTrigger(day_of_week="mon", hour=9, minute=0),
            name="fitness_deload_check",
            misfire_grace_time=120,
        )

        # v2.0.7: 晨间任务推送
        if self.morning_briefing_enabled:
            try:
                mb_h, mb_m = map(int, self.morning_briefing_time.split(":"))
                self._scheduler.add_job(
                    self._on_morning_briefing,
                    trigger=CronTrigger(hour=mb_h, minute=mb_m),
                    name="fitness_morning_briefing",
                    misfire_grace_time=120,
                    max_instances=1,
                )
                logger.info(f"晨间任务推送已注册: {self.morning_briefing_time}")
            except Exception as e:
                logger.warning(f"注册晨间任务推送失败: {e}")

        # v2.0.7: 训练前提醒（按用户偏好时间 -30min 分组）
        if self.pre_workout_reminder_enabled:
            self._rebuild_pre_workout_jobs()

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
        # 先移除所有旧的提醒 job
        jobs_to_remove = [job for job in self._scheduler.get_jobs()
                          if job.name.startswith("fitness_remind_")]
        for job in jobs_to_remove:
            job.remove()

        profiles = db.get_all_active_profiles()
        time_groups = set()
        for p in profiles:
            rt = p.get("reminder_time", "")
            if rt and ":" in rt:
                time_groups.add(rt)

        for time_str in time_groups:
            try:
                hour, minute = map(int, time_str.split(":"))
                self._scheduler.add_job(
                    self._on_remind_tick,
                    trigger=CronTrigger(hour=hour, minute=minute),
                    args=[time_str],
                    name=f"fitness_remind_{time_str}",
                    misfire_grace_time=120,
                    max_instances=1,  # 防止同一 job 并发执行
                )
            except Exception as e:
                logger.warning(f"注册提醒任务 {time_str} 失败: {e}")

        logger.info(f"已注册 {len(time_groups)} 个提醒时间点")

    async def _daily_refresh(self):
        self._reminded_today.clear()
        self._briefed_today.clear()
        self._pre_reminded_today.clear()
        self._last_date = date.today().isoformat()
        self._rebuild_jobs()
        if self.pre_workout_reminder_enabled:
            self._rebuild_pre_workout_jobs()
        # 自动推进训练周期的 current_week
        await self._advance_cycle_weeks()

    async def _on_remind_tick(self, time_str: str):
        """某个时间点触发，查找该时间的所有用户并发送提醒"""
        # 防止并发重复执行
        if self._remind_lock:
            return
        self._remind_lock = True
        try:
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

                # 先标记，防止重复发送
                self._reminded_today.add(reminder_key)

                checkin = db.get_today_checkin(user_id, group_id)
                if checkin:
                    continue

                if p.get("current_status", "normal") in ("sick", "injured", "rest"):
                    continue

                # 生成提醒消息
                msg = await self._build_reminder_msg(p)
                await self._send_group_message(group_id, user_id, msg)
                logger.info(f"已发送打卡提醒给 {p.get('nickname', user_id)}({user_id})")
        finally:
            self._remind_lock = False

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
        logger.debug(f"[模型路由] 打卡提醒 → {self.lite_provider_id}")
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

    # ==================== v2.0 定时任务 ====================

    async def _advance_cycle_weeks(self):
        """每日检查并推进所有活跃训练周期的 current_week"""
        profiles = db.get_all_active_profiles()
        seen_cycles = set()
        for p in profiles:
            user_id = p["user_id"]
            group_id = p["group_id"]
            try:
                cycle = db.get_active_cycle(user_id, group_id)
                if not cycle or cycle.id in seen_cycles:
                    continue
                seen_cycles.add(cycle.id)
                # 计算当前应该是第几周
                start = date.fromisoformat(cycle.start_date)
                today = date.today()
                elapsed_weeks = (today - start).days // 7 + 1
                elapsed_weeks = max(1, min(elapsed_weeks, cycle.total_weeks))
                if elapsed_weeks != cycle.current_week:
                    if elapsed_weeks > cycle.total_weeks:
                        db.complete_cycle(cycle.id)
                    else:
                        db.update_cycle_week(cycle.id, elapsed_weeks)
            except Exception as e:
                logger.debug(f"推进训练周期失败 {user_id}: {e}")

    async def _on_saturday_feedback(self):
        """周六体重反馈：向所有已建档用户发送体重询问"""
        profiles = db.get_all_active_profiles()
        # 按群分组
        groups = {}
        for p in profiles:
            gid = p["group_id"]
            groups.setdefault(gid, []).append(p)

        for group_id, members in groups.items():
            for p in members:
                nickname = p.get("nickname", p["user_id"])
                msg = (
                    f"📊 {nickname}，周六体重反馈时间到啦～\n"
                    f"请告诉我你现在的体重（kg），以及这周训练的感受和反馈。\n"
                    f"比如：'体重72.5，这周感觉还不错，但腿部训练有点吃力'"
                )
                await self._send_group_message(group_id, p["user_id"], msg)

        logger.info(f"周六体重反馈已发送给 {len(profiles)} 位用户")

    async def _on_weekly_report(self):
        """周日群周报：生成并发送群健身数据总结"""
        # 获取所有有活跃用户的群
        profiles = db.get_all_active_profiles()
        groups = set(p["group_id"] for p in profiles)

        for group_id in groups:
            try:
                report_data = self._weekly_report_gen.generate_report(group_id)
                text = report_data["text"]

                # 如果有低成本模型，生成教练评语
                if self.lite_provider_id and not report_data["stats"].get("empty"):
                    try:
                        stats = report_data["stats"]
                        prompt = (
                            f"你是一个专业健身教练，请根据以下群周报数据写一段简短的总结评语（80字以内）：\n"
                            f"打卡人数: {stats.get('checkin_users', 0)}/{stats.get('total_members', 0)}\n"
                            f"总打卡次数: {stats.get('total_checkins', 0)}\n"
                            f"打卡率: {stats.get('checkin_rate', 0)}%\n"
                            f"要求：鼓励为主，简洁有力，带1-2个emoji"
                        )
                        logger.debug(f"[模型路由] 周报评语 → {self.lite_provider_id}")
                        resp = await self.context.llm_generate(
                            chat_provider_id=self.lite_provider_id,
                            prompt=prompt,
                        )
                        if resp and resp.completion_text:
                            text = self._weekly_report_gen.format_report(
                                stats, resp.completion_text.strip()
                            )
                    except Exception as e:
                        logger.debug(f"周报AI评语生成失败: {e}")

                # 发送周报（不@特定用户，发给群）
                await self._send_group_text(group_id, text)
                logger.info(f"已发送周报到群 {group_id}")
            except Exception as e:
                logger.error(f"生成周报失败 {group_id}: {e}")

    async def _on_deload_check(self):
        """周一去负荷检测：检查所有活跃用户是否需要去负荷"""
        profiles = db.get_all_active_profiles()
        for p in profiles:
            user_id = p["user_id"]
            group_id = p["group_id"]
            try:
                if self._periodization_engine.check_deload_needed(user_id, group_id):
                    nickname = p.get("nickname", user_id)
                    msg = (
                        f"⚠️ {nickname}，你已经连续高强度训练好几周了！\n"
                        f"建议这周安排一个去负荷周，降低训练强度让身体恢复。\n"
                        f"告诉我「安排去负荷周」我来帮你调整计划～"
                    )
                    await self._send_group_message(group_id, user_id, msg)
                    logger.info(f"已发送去负荷建议给 {nickname}")
            except Exception as e:
                logger.debug(f"去负荷检测失败 {user_id}: {e}")

    async def _send_group_text(self, group_id: str, text: str):
        """发送纯文本群消息（不@任何人）"""
        parts = group_id.split(":")
        qq_group_id = parts[-1] if len(parts) >= 3 else group_id

        client = self._get_bot_client()
        if not client:
            logger.warning("无法获取 bot 客户端，跳过消息发送")
            return False

        message = [{"type": "text", "data": {"text": text}}]
        try:
            gid = int(qq_group_id) if qq_group_id.isdigit() else qq_group_id
            await client.send_group_msg(group_id=gid, message=message)
            return True
        except Exception as e:
            logger.error(f"发送群消息失败: {e}")
        return False

    # ==================== v2.0.7: 晨间任务推送 ====================

    async def _on_morning_briefing(self):
        """每天早上推送今日训练任务给所有活跃用户"""
        profiles = db.get_all_active_profiles()
        for p in profiles:
            user_id = p["user_id"]
            group_id = p["group_id"]
            key = f"{user_id}:{group_id}"

            if key in self._briefed_today:
                continue
            self._briefed_today.add(key)

            if p.get("current_status", "normal") in ("sick", "injured"):
                continue

            try:
                plan = db.get_today_plan(user_id, group_id)
                nickname = p.get("nickname", user_id)
                level = p.get("level", 1)
                title = get_title(level)
                display_name = f"Lv.{level}【{title}】{nickname}"

                if not plan or plan.is_rest_day:
                    msg = MORNING_REST_DAY_TEMPLATE.format(nickname=display_name)
                else:
                    msg = await self._build_morning_briefing_msg(
                        p, plan, display_name
                    )

                await self._send_group_message(group_id, user_id, msg)
                logger.info(f"已发送晨间任务推送给 {nickname}({user_id})")
            except Exception as e:
                logger.error(f"晨间推送失败 {user_id}: {e}")

    async def _build_morning_briefing_msg(self, p: dict, plan, display_name: str) -> str:
        """构建晨间任务推送消息"""
        nickname = p.get("nickname", p["user_id"])
        streak = db.get_checkin_streak(p["user_id"], p["group_id"])
        preferred_time = p.get("preferred_workout_time", "18:00")

        # 尝试 AI 生成
        if self.lite_provider_id:
            try:
                prompt = MORNING_BRIEFING_AI_PROMPT.format(
                    nickname=nickname,
                    fitness_goal=p.get("fitness_goal", ""),
                    streak=streak,
                    workout_type=plan.workout_type,
                    workout_detail=plan.workout_detail,
                    preferred_time=preferred_time,
                )
                logger.debug(f"[模型路由] 晨间推送 → {self.lite_provider_id}")
                resp = await self.context.llm_generate(
                    chat_provider_id=self.lite_provider_id,
                    prompt=prompt,
                )
                if resp and resp.completion_text:
                    return f"{display_name}\n{resp.completion_text.strip()}"
            except Exception as e:
                logger.debug(f"AI晨间推送生成失败，回退模板: {e}")

        # 纯模板
        streak_line = f"🔥 已连续打卡 {streak} 天！\n" if streak > 0 else ""
        return MORNING_BRIEFING_TEMPLATE.format(
            nickname=display_name,
            workout_type=plan.workout_type,
            workout_detail=plan.workout_detail,
            preferred_time=preferred_time,
            streak_line=streak_line,
        )

    # ==================== v2.0.7: 训练前提醒 ====================

    def _rebuild_pre_workout_jobs(self):
        """按用户偏好训练时间 -30min 分组注册 cron job"""
        # 移除旧的训练前提醒 job
        if not self._scheduler:
            return
        jobs_to_remove = [job for job in self._scheduler.get_jobs()
                          if job.name.startswith("fitness_preworkout_")]
        for job in jobs_to_remove:
            job.remove()

        profiles = db.get_all_active_profiles()
        time_groups = set()
        for p in profiles:
            wt = p.get("preferred_workout_time", "")
            if wt and ":" in wt:
                # 计算 -30 分钟
                try:
                    h, m = map(int, wt.split(":"))
                    total_min = h * 60 + m - 30
                    if total_min < 0:
                        total_min += 24 * 60
                    pre_h, pre_m = divmod(total_min, 60)
                    time_groups.add(f"{pre_h:02d}:{pre_m:02d}")
                except ValueError:
                    continue

        for time_str in time_groups:
            try:
                hour, minute = map(int, time_str.split(":"))
                self._scheduler.add_job(
                    self._on_pre_workout_tick,
                    trigger=CronTrigger(hour=hour, minute=minute),
                    args=[time_str],
                    name=f"fitness_preworkout_{time_str}",
                    misfire_grace_time=120,
                    max_instances=1,
                )
            except Exception as e:
                logger.warning(f"注册训练前提醒 {time_str} 失败: {e}")

        logger.info(f"已注册 {len(time_groups)} 个训练前提醒时间点")

    async def _on_pre_workout_tick(self, pre_time_str: str):
        """训练前30分钟提醒"""
        # 反推原始训练时间
        pre_h, pre_m = map(int, pre_time_str.split(":"))
        total_min = pre_h * 60 + pre_m + 30
        if total_min >= 24 * 60:
            total_min -= 24 * 60
        orig_h, orig_m = divmod(total_min, 60)
        workout_time_str = f"{orig_h:02d}:{orig_m:02d}"

        profiles = db.get_all_active_profiles()
        for p in profiles:
            if p.get("preferred_workout_time", "") != workout_time_str:
                continue

            user_id = p["user_id"]
            group_id = p["group_id"]
            key = f"{user_id}:{group_id}"

            if key in self._pre_reminded_today:
                continue
            self._pre_reminded_today.add(key)

            if p.get("current_status", "normal") in ("sick", "injured", "rest"):
                continue

            # 已打卡则跳过
            checkin = db.get_today_checkin(user_id, group_id)
            if checkin:
                continue

            try:
                plan = db.get_today_plan(user_id, group_id)
                if not plan or plan.is_rest_day:
                    continue

                nickname = p.get("nickname", user_id)
                level = p.get("level", 1)
                title = get_title(level)
                display_name = f"Lv.{level}【{title}】{nickname}"

                msg = await self._build_pre_workout_msg(p, plan, display_name)
                await self._send_group_message(group_id, user_id, msg)
                logger.info(f"已发送训练前提醒给 {nickname}({user_id})")
            except Exception as e:
                logger.error(f"训练前提醒失败 {user_id}: {e}")

    async def _build_pre_workout_msg(self, p: dict, plan, display_name: str) -> str:
        """构建训练前提醒消息"""
        nickname = p.get("nickname", p["user_id"])

        # 尝试 AI 生成
        if self.lite_provider_id:
            try:
                prompt = PRE_WORKOUT_AI_PROMPT.format(
                    nickname=nickname,
                    workout_type=plan.workout_type,
                    workout_detail=plan.workout_detail,
                )
                logger.debug(f"[模型路由] 训练前提醒 → {self.lite_provider_id}")
                resp = await self.context.llm_generate(
                    chat_provider_id=self.lite_provider_id,
                    prompt=prompt,
                )
                if resp and resp.completion_text:
                    return f"{display_name}\n{resp.completion_text.strip()}"
            except Exception as e:
                logger.debug(f"AI训练前提醒生成失败，回退模板: {e}")

        # 纯模板
        return PRE_WORKOUT_TEMPLATE.format(
            nickname=display_name,
            workout_type=plan.workout_type,
        )
