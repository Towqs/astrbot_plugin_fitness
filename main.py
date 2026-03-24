# -*- coding: utf-8 -*-
"""
智能健身教练 AstrBot 插件
- 自然对话建档，AI 自动调用工具
- 个性化训练计划生成
- 每日打卡提醒与动态调整
- RPG 游戏化 + 随机事件
- QQ群头衔同步
"""
import json
import random
from datetime import date, timedelta

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.event.filter import EventMessageType
from astrbot.api.star import Context, Star, register
from astrbot.api.provider import ProviderRequest
from astrbot.core import AstrBotConfig
from astrbot import logger

from . import database as db
from .models import UserProfile, CheckinRecord, TrainingPlan, WeightRecord
from .tools import set_qq_group_title, roll_random_event
from .prompts import SYSTEM_PROMPT_FULL, PERSONA_PROMPTS, PROACTIVE_REPLY_PROMPT
from .reminder import ScheduledReminder
from .rpg import calc_level, exp_for_next_level, get_title
from .fatigue import FatigueAssessor
from .portrait import UserPortraitManager
from .diet import DietLogger
from .achievement import AchievementSystem, ACHIEVEMENTS
from .progress import ProgressDetector
from .periodization import PeriodizationEngine

# 群白名单辅助
def _parse_enabled_groups(raw) -> set:
    if isinstance(raw, list):
        return {str(g).strip() for g in raw if str(g).strip()}
    if isinstance(raw, str) and raw.strip():
        return {g.strip() for g in raw.split(",") if g.strip()}
    return set()


@register(
    "astrbot_plugin_fitness",
    "FitnessCoach",
    "智能健身教练 v2.0 - 档案/计划/打卡/画像/周期化/成就/饮食/周报/主动回复",
    "2.0.3",
    "https://github.com/Towqs/astrbot_plugin_fitness",
)
class FitnessCoachPlugin(Star):

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        db.init_db()

        # 读取配置
        self._enabled_groups = _parse_enabled_groups(config.get("enabled_groups", ""))
        self.title_sync_enabled = config.get("title_sync_enabled", True)
        self.random_event_enabled = config.get("random_event_enabled", True)
        self.reminder_enabled = config.get("reminder_enabled", True)
        self.extra_training_suggest = config.get("extra_training_suggest", True)
        self.default_reminder_time = config.get("default_reminder_time", "17:30")
        self.chat_provider_id = config.get("chat_provider_id", "")
        self.lite_provider_id = config.get("lite_provider_id", "")
        self.achievement_enabled = config.get("achievement_enabled", True)
        self.diet_log_enabled = config.get("diet_log_enabled", True)
        self.proactive_reply_enabled = config.get("proactive_reply_enabled", False)
        self.proactive_reply_probability = max(0, min(100, int(config.get("proactive_reply_probability", 5))))

        # AI 人格
        persona_choice = config.get("coach_persona", "热血教练 - 充满激情，像动漫里的热血导师")
        persona_key = persona_choice.split(" - ")[0] if " - " in persona_choice else persona_choice
        if persona_key == "自定义":
            self.persona_prompt = config.get("custom_persona", "")
        else:
            self.persona_prompt = PERSONA_PROMPTS.get(persona_key, "")

        # 定时提醒
        self.reminder = None
        if self.reminder_enabled:
            saturday_time = config.get("saturday_feedback_time", "10:00")
            report_time = config.get("weekly_report_time", "20:00")
            self.reminder = ScheduledReminder(
                context, self.lite_provider_id,
                saturday_feedback_time=saturday_time,
                weekly_report_time=report_time,
            )
            self.reminder.start()

        # v2.0 模块初始化
        self.fatigue_assessor = FatigueAssessor()
        self.portrait_manager = UserPortraitManager()
        self.diet_logger = DietLogger()
        self.achievement_system = AchievementSystem()
        self.progress_detector = ProgressDetector()
        self.periodization_engine = PeriodizationEngine()

        # 私聊建档会话状态: {user_id: {"step": str, "data": dict, "group_id": str, "group_origin": str}}
        self._onboarding_sessions: dict[str, dict] = {}

        logger.info(f"智能健身教练插件已加载 | 群白名单: {self._enabled_groups or '全部'}")

    def _is_group_enabled(self, event: AstrMessageEvent) -> bool:
        """检查当前群是否在白名单中"""
        if not self._enabled_groups:
            return True
        group_id = str(event.unified_msg_origin)
        parts = group_id.split(":")
        qq_group_id = parts[-1] if len(parts) >= 3 else group_id
        return qq_group_id in self._enabled_groups

    # ==================== LLM 系统提示注入 ====================

    @filter.on_llm_request()
    async def inject_fitness_context(self, event: AstrMessageEvent, req: ProviderRequest):
        """在 LLM 请求前注入健身教练的系统提示和用户档案"""
        if not self._is_group_enabled(event):
            return

        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        profile = db.get_profile(user_id, group_id)

        fitness_prompt = SYSTEM_PROMPT_FULL

        # 注入人格
        if self.persona_prompt:
            fitness_prompt += f"\n\n## 你的人格风格：\n{self.persona_prompt}\n"

        # 注入配置开关信息
        if not self.random_event_enabled:
            fitness_prompt += "\n注意：随机事件功能已关闭，打卡时不会触发随机事件。\n"
        if not self.extra_training_suggest:
            fitness_prompt += "\n注意：加练建议功能已关闭，打卡后不要建议加练。\n"

        if profile:
            fitness_prompt += f"\n\n## 当前用户档案：\n"
            fitness_prompt += f"- 昵称: {profile.nickname}\n"
            fitness_prompt += f"- 身高: {profile.height_cm}cm, 体重: {profile.weight_kg}kg\n"
            fitness_prompt += f"- 年龄: {profile.age}, 性别: {profile.gender}\n"
            fitness_prompt += f"- 健身目标: {profile.fitness_goal}\n"
            fitness_prompt += f"- 体质: {profile.body_condition}\n"
            fitness_prompt += f"- 健康备注: {profile.health_notes}\n"
            fitness_prompt += f"- 器材: {profile.equipment}\n"
            fitness_prompt += f"- 补剂: {'有 - ' + profile.supplement_details if profile.has_supplements else '无'}\n"
            if profile.training_experience:
                fitness_prompt += f"- 训练经验: {profile.training_experience}\n"
            if profile.training_frequency:
                fitness_prompt += f"- 训练频率: {profile.training_frequency}\n"
            if profile.weak_parts:
                fitness_prompt += f"- 薄弱部位: {profile.weak_parts}\n"
            if profile.focus_parts:
                fitness_prompt += f"- 重点部位: {profile.focus_parts}\n"
            if profile.diet_habit:
                fitness_prompt += f"- 饮食习惯: {profile.diet_habit}\n"
            if profile.meals_per_day:
                fitness_prompt += f"- 每日餐数: {profile.meals_per_day}\n"
            if profile.protein_intake:
                fitness_prompt += f"- 蛋白质摄入: {profile.protein_intake}\n"
            if profile.daily_activity:
                fitness_prompt += f"- 日常活动量: {profile.daily_activity}\n"
            fitness_prompt += f"- 作息: {profile.wake_time}起床, {profile.sleep_time}睡觉\n"
            fitness_prompt += f"- 锻炼时间: {profile.preferred_workout_time}\n"
            fitness_prompt += f"- 当前状态: {profile.current_status} {profile.status_note}\n"
            fitness_prompt += f"- 建档进度: {profile.onboarding_step}\n"
            if profile.ai_analysis:
                fitness_prompt += f"- AI综合分析: {profile.ai_analysis}\n"
            fitness_prompt += f"- 等级: Lv.{profile.level} | 经验值: {profile.exp}\n"
            if profile.quest_days > 0:
                fitness_prompt += f"- 闯关任务: {profile.quest_days}天 | 进度: {profile.quest_progress}/{profile.quest_days}\n"
            streak = db.get_checkin_streak(user_id, group_id)
            fitness_prompt += f"- 连续打卡: {streak}天\n"
            today_plan = db.get_today_plan(user_id, group_id)
            if today_plan:
                fitness_prompt += f"- 今日计划: {today_plan.workout_type} - {today_plan.workout_detail}\n"
            today_checkin = db.get_today_checkin(user_id, group_id)
            fitness_prompt += f"- 今日已打卡: {'是' if today_checkin else '否'}\n"

            # v2.0: 注入画像数据
            portrait = db.get_portrait(user_id, group_id)
            if portrait:
                fitness_prompt += f"\n## 用户画像数据：\n"
                fitness_prompt += f"- 恢复能力评分: {portrait.recovery_score}/100\n"
                fitness_prompt += f"- 进步速度: {portrait.progress_speed}\n"
                fitness_prompt += f"- 疲劳度: {portrait.fatigue_score}/100\n"
                if portrait.weight_trend:
                    fitness_prompt += f"- 体重趋势: {portrait.weight_trend}\n"
                if portrait.training_preference:
                    fitness_prompt += f"- 训练偏好: {portrait.training_preference}\n"
                if portrait.weekly_feedback:
                    fitness_prompt += f"- 最近反馈: {portrait.weekly_feedback}\n"
        else:
            fitness_prompt += "\n\n## 当前用户还没有建立健身档案，请引导用户建档。\n"

        req.system_prompt = fitness_prompt + "\n\n" + (req.system_prompt or "")

        # 如果配置了指定模型，覆盖 provider
        if self.chat_provider_id:
            req.provider_id = self.chat_provider_id

    # ==================== LLM Tools (装饰器模式) ====================

    @filter.llm_tool(name="create_profile")
    async def tool_create_profile(
        self, event: AstrMessageEvent,
        nickname: str,
        height_cm: float = 0, weight_kg: float = 0,
        age: int = 0, gender: str = "",
        fitness_goal: str = "", body_condition: str = "",
        health_notes: str = "", equipment: str = "",
        has_supplements: bool = False, supplement_details: str = "",
        wake_time: str = "", sleep_time: str = "",
        preferred_workout_time: str = "",
        reminder_time: str = "", quest_days: int = 0,
    ):
        '''为用户创建健身档案。在用户提供基本信息后调用，必须提供nickname，其他可选。

        Args:
            nickname(string): 用户昵称
            height_cm(number): 身高cm
            weight_kg(number): 体重kg
            age(number): 年龄
            gender(string): 性别 male/female
            fitness_goal(string): 健身目标 增肌/减脂/塑形/维持健康
            body_condition(string): 体质 偏瘦/正常/偏胖/肥胖
            health_notes(string): 健康备注
            equipment(string): 拥有的器材
            has_supplements(boolean): 是否使用补剂
            supplement_details(string): 补剂详情
            wake_time(string): 起床时间HH:MM，仅在用户明确告知时传入
            sleep_time(string): 睡觉时间HH:MM，仅在用户明确告知时传入
            preferred_workout_time(string): 偏好锻炼时间HH:MM，仅在用户明确告知时传入
            reminder_time(string): 提醒时间HH:MM，根据用户作息智能建议后由用户确认再传入
            quest_days(number): 闯关天数 3/7/30
        '''
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)

        existing = db.get_profile(user_id, group_id)
        if existing and existing.onboarding_step == "complete":
            yield event.plain_result("该用户已有完整档案，如需更新请直接告诉我要改什么。")
            return

        p = existing or UserProfile(user_id=user_id, group_id=group_id)
        fields = {
            "nickname": nickname, "height_cm": height_cm, "weight_kg": weight_kg,
            "age": age, "gender": gender, "fitness_goal": fitness_goal,
            "body_condition": body_condition, "health_notes": health_notes,
            "equipment": equipment, "supplement_details": supplement_details,
            "wake_time": wake_time, "sleep_time": sleep_time,
            "preferred_workout_time": preferred_workout_time,
            "reminder_time": reminder_time, "quest_days": quest_days,
        }
        for key, val in fields.items():
            if val:
                setattr(p, key, val)
        # 布尔字段：仅在同时提供了 supplement_details 时才更新，避免分步建档覆盖
        if supplement_details or has_supplements:
            p.has_supplements = has_supplements

        if p.height_cm and p.weight_kg and p.age and p.gender and p.fitness_goal:
            p.onboarding_step = "complete"

        db.save_profile(p)

        title_msg = ""
        if p.onboarding_step == "complete":
            title = get_title(p.level)
            if self.title_sync_enabled:
                ok = await set_qq_group_title(event, user_id, f"Lv.{p.level} {title}")
                title_msg = f"\n已设置群头衔: Lv.{p.level} {title}" if ok else ""

        status = "建档完成" if p.onboarding_step == "complete" else "信息已保存，继续补充中"
        # 建档完成后刷新提醒调度（新用户加入）
        if p.onboarding_step == "complete" and self.reminder:
            self.reminder.refresh()

        if p.onboarding_step == "complete":
            # 自动生成首个训练周期
            try:
                plans = self.periodization_engine.generate_cycle(user_id, group_id, 4)
                cycle_msg = f"\n已自动生成4周训练周期（共{len(plans)}天计划）。"
            except Exception as e:
                logger.warning(f"自动生成训练周期失败: {e}")
                cycle_msg = "\n请接下来帮用户生成训练周期，调用 generate_training_cycle 工具。"
            yield event.plain_result(f"档案已保存。状态: {status}{title_msg}{cycle_msg}")
        else:
            yield event.plain_result(f"档案已保存。状态: {status}{title_msg}")

    @filter.llm_tool(name="get_profile")
    async def tool_get_profile(self, event: AstrMessageEvent):
        '''查询当前用户的健身档案信息，包括基本信息、RPG等级、闯关进度等。'''
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        p = db.get_profile(user_id, group_id)
        if not p:
            yield event.plain_result("该用户尚未建立健身档案。")
            return
        streak = db.get_checkin_streak(user_id, group_id)
        title = get_title(p.level)
        result = json.dumps({
            "nickname": p.nickname, "height_cm": p.height_cm, "weight_kg": p.weight_kg,
            "age": p.age, "gender": p.gender, "fitness_goal": p.fitness_goal,
            "body_condition": p.body_condition, "health_notes": p.health_notes,
            "equipment": p.equipment, "has_supplements": p.has_supplements,
            "supplement_details": p.supplement_details,
            "training_experience": p.training_experience,
            "training_frequency": p.training_frequency,
            "weak_parts": p.weak_parts, "focus_parts": p.focus_parts,
            "diet_habit": p.diet_habit, "meals_per_day": p.meals_per_day,
            "protein_intake": p.protein_intake, "daily_activity": p.daily_activity,
            "wake_time": p.wake_time, "sleep_time": p.sleep_time,
            "preferred_workout_time": p.preferred_workout_time,
            "reminder_time": p.reminder_time,
            "level": p.level, "exp": p.exp, "title": title,
            "quest_days": p.quest_days, "quest_progress": p.quest_progress,
            "current_status": p.current_status, "status_note": p.status_note,
            "streak": streak, "onboarding_step": p.onboarding_step,
            "ai_analysis": p.ai_analysis,
        }, ensure_ascii=False)
        yield event.plain_result(result)

    @filter.llm_tool(name="update_status")
    async def tool_update_status(
        self, event: AstrMessageEvent,
        current_status: str = "", status_note: str = "",
        weight_kg: float = 0, fitness_goal: str = "",
        equipment: str = "", has_supplements: bool = False,
        supplement_details: str = "", reminder_time: str = "",
        quest_days: int = 0, preferred_workout_time: str = "",
        health_notes: str = "",
        training_experience: str = "", training_frequency: str = "",
        weak_parts: str = "", focus_parts: str = "",
        diet_habit: str = "", meals_per_day: int = 0,
        protein_intake: str = "", daily_activity: str = "",
        ai_analysis: str = "",
    ):
        '''更新用户的状态或档案信息。可更新体重、状态、闯关任务、提醒时间、训练背景、饮食习惯等。在日常对话中了解到用户新信息时主动调用。

        Args:
            current_status(string): 状态 normal/sick/injured/tired/rest
            status_note(string): 状态备注
            weight_kg(number): 更新体重
            fitness_goal(string): 更新目标
            equipment(string): 更新器材
            has_supplements(boolean): 是否使用补剂
            supplement_details(string): 补剂详情
            reminder_time(string): 提醒时间HH:MM，传空字符串"none"表示关闭提醒
            quest_days(number): 选择闯关 3/7/30
            preferred_workout_time(string): 锻炼时间HH:MM
            health_notes(string): 健康备注
            training_experience(string): 训练经验 零基础/初学者/有基础/进阶
            training_frequency(string): 期望每周训练频率，如"每周3次"
            weak_parts(string): 薄弱部位，逗号分隔
            focus_parts(string): 重点想练的部位，逗号分隔
            diet_habit(string): 饮食习惯 正常饮食/高蛋白/素食/节食/不规律
            meals_per_day(number): 每日餐数
            protein_intake(string): 蛋白质摄入评估 充足/一般/不足/不清楚
            daily_activity(string): 日常活动量 久坐/轻度活动/中度活动/重体力
            ai_analysis(string): AI综合分析与训练方向建议，当收集到足够信息后由你生成
        '''
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        p = db.get_profile(user_id, group_id)
        if not p:
            yield event.plain_result("用户尚未建档，请先创建档案。")
            return

        updated = []

        # 字符串字段：非空才更新
        str_fields = {
            "current_status": current_status, "status_note": status_note,
            "fitness_goal": fitness_goal, "equipment": equipment,
            "supplement_details": supplement_details,
            "preferred_workout_time": preferred_workout_time,
            "health_notes": health_notes,
            "training_experience": training_experience,
            "training_frequency": training_frequency,
            "weak_parts": weak_parts, "focus_parts": focus_parts,
            "diet_habit": diet_habit, "protein_intake": protein_intake,
            "daily_activity": daily_activity, "ai_analysis": ai_analysis,
        }
        for key, val in str_fields.items():
            if val:
                old = getattr(p, key)
                setattr(p, key, val)
                updated.append(f"{key}: {old} → {val}")

        # 数值字段：非零才更新
        if weight_kg:
            updated.append(f"weight_kg: {p.weight_kg} → {weight_kg}")
            p.weight_kg = weight_kg
            # 同步写入体重记录表，供进步报告使用
            wr = WeightRecord(
                user_id=user_id, group_id=group_id,
                record_date=date.today().isoformat(),
                weight_kg=weight_kg, source="update_status",
            )
            db.add_weight_record(wr)
        if meals_per_day:
            updated.append(f"meals_per_day: {p.meals_per_day} → {meals_per_day}")
            p.meals_per_day = meals_per_day

        # 布尔字段：仅在明确涉及补剂话题时才更新，避免其他字段更新时意外清除
        if supplement_details or has_supplements:
            if has_supplements != p.has_supplements:
                updated.append(f"has_supplements: {p.has_supplements} → {has_supplements}")
                p.has_supplements = has_supplements

        # reminder_time 特殊处理："none" 表示关闭提醒
        if reminder_time:
            new_time = "" if reminder_time.lower() == "none" else reminder_time
            if new_time != p.reminder_time:
                updated.append(f"reminder_time: {p.reminder_time} → {new_time or '已关闭'}")
                p.reminder_time = new_time
                # 刷新提醒调度
                if self.reminder:
                    self.reminder.refresh()

        if quest_days:
            updated.append(f"quest_days: {p.quest_days} → {quest_days}")
            p.quest_days = quest_days
            p.quest_progress = 0

        db.save_profile(p)
        msg = f"已更新: {', '.join(updated)}" if updated else "没有需要更新的字段。"
        yield event.plain_result(msg)

    @filter.llm_tool(name="record_checkin")
    async def tool_record_checkin(
        self, event: AstrMessageEvent,
        workout_type: str, workout_detail: str,
        duration_min: int, feeling: str,
        calories_est: int = 0, note: str = "",
    ):
        '''记录用户健身打卡。自动计算经验值、触发随机事件、检查升级和闯关进度。

        Args:
            workout_type(string): 训练类型 力量/有氧/拉伸/混合
            workout_detail(string): 具体训练内容
            duration_min(number): 训练时长分钟
            feeling(string): 感受 轻松/适中/吃力/很累
            calories_est(number): 估算消耗大卡
            note(string): 备注
        '''
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        p = db.get_profile(user_id, group_id)
        if not p:
            yield event.plain_result("用户尚未建档，请先创建档案。")
            return

        today = date.today().isoformat()
        existing = db.get_today_checkin(user_id, group_id)
        if existing:
            yield event.plain_result("今天已经打过卡了，明天继续加油！")
            return

        record = CheckinRecord(
            user_id=user_id, group_id=group_id, checkin_date=today,
            workout_type=workout_type, workout_detail=workout_detail,
            duration_min=int(duration_min), calories_est=int(calories_est),
            feeling=feeling, note=note,
        )
        db.add_checkin(record)

        # 经验值计算
        base_exp = 50
        feeling_bonus = {"轻松": 0, "适中": 10, "吃力": 25, "很累": 40}.get(feeling, 0)
        duration_bonus = min((int(duration_min) // 10) * 5, 30)
        streak = db.get_checkin_streak(user_id, group_id)
        streak_bonus = min(streak * 3, 45)
        total_exp = base_exp + feeling_bonus + duration_bonus + streak_bonus

        # 随机事件
        evt = None
        if self.random_event_enabled:
            evt = roll_random_event()
        event_msg = ""
        if evt:
            if evt["type"] == "exp_mult":
                total_exp *= evt["value"]
            elif evt["type"] == "exp_add":
                total_exp += evt["value"]
            event_msg = evt["msg"]

        # 更新经验和等级
        old_level = p.level
        p.exp += int(total_exp)
        p.level = calc_level(p.exp)
        leveled_up = p.level > old_level

        # 闯关进度
        quest_msg = ""
        quest_complete = False
        if p.quest_days > 0 and p.quest_progress < p.quest_days:
            p.quest_progress += 1
            if p.quest_progress >= p.quest_days:
                quest_complete = True
                quest_bonus = {3: 150, 7: 500, 30: 2000}.get(p.quest_days, 100)
                p.exp += quest_bonus
                p.level = calc_level(p.exp)
                quest_names = {3: "新手试炼", 7: "进阶挑战", 30: "BOSS战"}
                qname = quest_names.get(p.quest_days, f"{p.quest_days}天")
                quest_msg = f"🏆 闯关【{qname}】通关！奖励 {quest_bonus} 经验！"

        db.save_profile(p)

        # 升级时设置群头衔
        title_msg = ""
        if leveled_up:
            new_title = get_title(p.level)
            if self.title_sync_enabled:
                ok = await set_qq_group_title(event, user_id, f"Lv.{p.level} {new_title}")
                title_msg = f"🎉 升级到 Lv.{p.level}【{new_title}】！"
                if ok:
                    title_msg += " 群头衔已更新！"
            else:
                title_msg = f"🎉 升级到 Lv.{p.level}【{new_title}】！"

        # 构建 RPG 文本
        rpg_text = f"✨ +{int(total_exp)}exp"
        if event_msg:
            rpg_text += f" | {event_msg}"
        if title_msg:
            rpg_text += f"\n{title_msg}"
        if quest_msg:
            rpg_text += f"\n{quest_msg}"
        if not leveled_up and not quest_complete:
            next_exp = exp_for_next_level(p.level)
            rpg_text += f" | Lv.{p.level} ({p.exp}/{next_exp})"
        if streak > 1:
            rpg_text += f" | 🔥连续{streak}天"

        # 加练判定上下文
        history = db.get_checkin_history(user_id, group_id, days=7)
        avg_dur = sum(h.get("duration_min", 0) for h in history) / max(len(history), 1)
        extra_ctx = json.dumps({
            "feeling": feeling, "duration_min": duration_min,
            "avg_duration_7d": round(avg_dur, 1), "streak": streak,
            "quest_progress": p.quest_progress, "quest_days": p.quest_days,
            "fitness_goal": p.fitness_goal, "equipment": p.equipment,
            "health_notes": p.health_notes, "current_status": p.current_status,
            "has_supplements": p.has_supplements,
            "supplement_details": p.supplement_details,
        }, ensure_ascii=False)

        # ===== v2.0 集成：成就检查 =====
        new_achievements = []
        if self.achievement_enabled:
            total_checkins = db.get_total_checkins(user_id, group_id)
            ach_context = {"streak": streak, "total_checkins": total_checkins}
            new_achievements = self.achievement_system.check_achievements(
                user_id, group_id, "checkin", ach_context
            )
            if leveled_up:
                level_achs = self.achievement_system.check_achievements(
                    user_id, group_id, "levelup",
                    {"level": p.level, "old_level": old_level}
                )
                new_achievements.extend(level_achs)
            if quest_complete:
                quest_achs = self.achievement_system.check_achievements(
                    user_id, group_id, "quest_complete", {}
                )
                new_achievements.extend(quest_achs)

        # 成就经验值奖励
        ach_exp = 0
        ach_msg = ""
        for a in new_achievements:
            ach_exp += a.get("exp", 0)
            ach_msg += f"\n🏅 解锁成就【{a['name']}】+{a['exp']}exp"
        if ach_exp > 0:
            pre_ach_level = p.level
            p.exp += ach_exp
            p.level = calc_level(p.exp)
            db.save_profile(p)
            # 成就经验导致升级时也更新头衔
            if p.level > pre_ach_level:
                new_title = get_title(p.level)
                if self.title_sync_enabled:
                    ok = await set_qq_group_title(event, user_id, f"Lv.{p.level} {new_title}")
                    ach_msg += f"\n🎉 成就奖励升级到 Lv.{p.level}【{new_title}】！"
                    if ok:
                        ach_msg += " 群头衔已更新！"
                else:
                    ach_msg += f"\n🎉 成就奖励升级到 Lv.{p.level}【{new_title}】！"

        # ===== v2.0 集成：疲劳评估 =====
        fatigue_result = self.fatigue_assessor.assess(user_id, group_id)
        fatigue_msg = ""
        if fatigue_result.score > 60:
            fatigue_msg = f"\n⚠️ 疲劳度 {fatigue_result.score}/100 - {fatigue_result.suggestion}"

        # ===== v2.0 集成：进步检测 =====
        progress_signals = self.progress_detector.detect_on_checkin(user_id, group_id)
        progress_msg = ""
        if progress_signals:
            progress_msg = "\n" + "\n".join(progress_signals[:2])  # 最多显示2条

        # ===== v2.0 集成：更新画像 =====
        try:
            self.portrait_manager.update_portrait(user_id, group_id)
        except Exception:
            pass  # 画像更新失败不影响打卡

        result = json.dumps({
            "rpg_text": rpg_text + ach_msg + fatigue_msg + progress_msg,
            "exp_gained": int(total_exp) + ach_exp,
            "streak": streak, "extra_training_context": extra_ctx,
        }, ensure_ascii=False)
        yield event.plain_result(result)

    @filter.llm_tool(name="makeup_checkin")
    async def tool_makeup_checkin(
        self, event: AstrMessageEvent,
        workout_type: str, workout_detail: str,
        duration_min: int, feeling: str,
        calories_est: int = 0, note: str = "",
    ):
        '''补卡：记录昨天忘记打卡的训练，经验值减半。仅支持补前一天的卡。

        Args:
            workout_type(string): 训练类型 力量/有氧/拉伸/混合
            workout_detail(string): 具体训练内容
            duration_min(number): 训练时长分钟
            feeling(string): 感受 轻松/适中/吃力/很累
            calories_est(number): 估算消耗大卡
            note(string): 备注
        '''
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        p = db.get_profile(user_id, group_id)
        if not p:
            yield event.plain_result("用户尚未建档，请先创建档案。")
            return

        yesterday = (date.today() - timedelta(days=1)).isoformat()

        # 检查昨天是否已有打卡
        conn = db.get_conn()
        try:
            row = conn.execute(
                "SELECT 1 FROM checkin_records WHERE user_id=? AND group_id=? AND checkin_date=?",
                (user_id, group_id, yesterday)
            ).fetchone()
        finally:
            conn.close()

        if row:
            yield event.plain_result("昨天已有打卡记录，无需补卡。")
            return

        # 创建昨天的打卡记录
        record = CheckinRecord(
            user_id=user_id, group_id=group_id, checkin_date=yesterday,
            workout_type=workout_type, workout_detail=workout_detail,
            duration_min=int(duration_min), calories_est=int(calories_est),
            feeling=feeling, note=f"[补卡] {note}",
        )
        db.add_checkin(record)

        # 经验值计算（减半）
        base_exp = 50
        feeling_bonus = {"轻松": 0, "适中": 10, "吃力": 25, "很累": 40}.get(feeling, 0)
        duration_bonus = min((int(duration_min) // 10) * 5, 30)
        streak = db.get_checkin_streak(user_id, group_id)
        streak_bonus = min(streak * 3, 45)
        full_exp = base_exp + feeling_bonus + duration_bonus + streak_bonus
        half_exp = full_exp // 2

        old_level = p.level
        p.exp += half_exp
        p.level = calc_level(p.exp)
        leveled_up = p.level > old_level

        # 闯关进度（补卡也算）
        quest_msg = ""
        quest_complete = False
        if p.quest_days > 0 and p.quest_progress < p.quest_days:
            p.quest_progress += 1
            if p.quest_progress >= p.quest_days:
                quest_complete = True
                quest_bonus = {3: 150, 7: 500, 30: 2000}.get(p.quest_days, 100)
                p.exp += quest_bonus
                p.level = calc_level(p.exp)
                quest_names = {3: "新手试炼", 7: "进阶挑战", 30: "BOSS战"}
                qname = quest_names.get(p.quest_days, f"{p.quest_days}天")
                quest_msg = f"🏆 闯关【{qname}】通关！奖励 {quest_bonus} 经验！"

        db.save_profile(p)

        # 成就检查（补卡也触发）
        ach_msg = ""
        ach_exp = 0
        if self.achievement_enabled:
            total_checkins = db.get_total_checkins(user_id, group_id)
            ach_context = {"streak": streak, "total_checkins": total_checkins}
            new_achievements = self.achievement_system.check_achievements(
                user_id, group_id, "checkin", ach_context
            )
            if leveled_up:
                level_achs = self.achievement_system.check_achievements(
                    user_id, group_id, "levelup",
                    {"level": p.level, "old_level": old_level}
                )
                new_achievements.extend(level_achs)
            if quest_complete:
                quest_achs = self.achievement_system.check_achievements(
                    user_id, group_id, "quest_complete", {}
                )
                new_achievements.extend(quest_achs)
            for a in new_achievements:
                ach_exp += a.get("exp", 0)
                ach_msg += f"\n🏅 解锁成就【{a['name']}】+{a['exp']}exp"
            if ach_exp > 0:
                p.exp += ach_exp
                p.level = calc_level(p.exp)
                db.save_profile(p)

        result = json.dumps({
            "status": "补卡成功",
            "date": yesterday,
            "exp_gained": half_exp + ach_exp,
            "exp_full": full_exp,
            "streak": streak,
            "level": p.level,
            "quest_msg": quest_msg,
            "achievements": ach_msg,
        }, ensure_ascii=False)
        yield event.plain_result(result)

    # ==================== v2.0 新增 LLM Tools ====================

    @filter.llm_tool(name="record_diet")
    async def tool_record_diet(
        self, event: AstrMessageEvent,
        description: str, meal_type: str,
        calories_est: int, protein_est: float,
    ):
        '''记录用户的饮食打卡。AI 根据用户描述估算热量和蛋白质后调用。

        Args:
            description(string): 饮食描述
            meal_type(string): 餐次类型 早餐/午餐/晚餐/加餐
            calories_est(number): 估算热量(大卡)
            protein_est(number): 估算蛋白质(克)
        '''
        if not self.diet_log_enabled:
            yield event.plain_result("饮食打卡功能已关闭。")
            return

        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)

        # 检查用户是否已建档
        p = db.get_profile(user_id, group_id)
        if not p:
            yield event.plain_result("用户尚未建档，请先创建档案。")
            return

        record = self.diet_logger.log_meal(
            user_id, group_id, description, meal_type,
            int(calories_est), float(protein_est),
        )

        # 检查首次饮食打卡成就
        ach_msg = ""
        if self.achievement_enabled:
            achievements = self.achievement_system.check_achievements(
                user_id, group_id, "diet_log", {}
            )
            if achievements:
                for a in achievements:
                    ach_msg += f"\n🏅 解锁成就【{a['name']}】+{a['exp']}exp"

        result = json.dumps({
            "status": "饮食已记录",
            "meal_type": meal_type,
            "calories": calories_est,
            "protein": protein_est,
            "achievements": ach_msg,
        }, ensure_ascii=False)
        yield event.plain_result(result)

    @filter.llm_tool(name="get_diet_summary")
    async def tool_get_diet_summary(self, event: AstrMessageEvent, log_date: str = ""):
        '''查询用户某日的饮食汇总，默认今天。

        Args:
            log_date(string): 查询日期YYYY-MM-DD，默认今天
        '''
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        summary = self.diet_logger.get_daily_summary(user_id, group_id, log_date)
        yield event.plain_result(json.dumps(summary, ensure_ascii=False))

    @filter.llm_tool(name="generate_training_cycle")
    async def tool_generate_training_cycle(
        self, event: AstrMessageEvent, weeks: int = 4,
    ):
        '''为用户生成周期化训练计划（4-8周），包含渐进超负荷和去负荷周。

        Args:
            weeks(number): 训练周期周数，4-8之间，默认4
        '''
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        plans = self.periodization_engine.generate_cycle(user_id, group_id, int(weeks))
        overview = self.periodization_engine.get_cycle_overview(user_id, group_id)
        result = json.dumps({
            "status": f"已生成{len(plans)//7}周训练周期",
            "total_days": len(plans),
            "overview": overview,
        }, ensure_ascii=False)
        yield event.plain_result(result)

    @filter.llm_tool(name="get_cycle_overview")
    async def tool_get_cycle_overview(self, event: AstrMessageEvent):
        '''查看用户当前训练周期概览：阶段、本周重点、剩余周数。'''
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        overview = self.periodization_engine.get_cycle_overview(user_id, group_id)
        if not overview:
            yield event.plain_result("当前没有活跃的训练周期，可以让我帮你生成一个。")
            return
        yield event.plain_result(json.dumps(overview, ensure_ascii=False))

    @filter.llm_tool(name="get_progress_report")
    async def tool_get_progress_report(self, event: AstrMessageEvent):
        '''生成用户的进步报告，对比近期和之前的训练数据。'''
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        report = self.progress_detector.generate_report(user_id, group_id)
        yield event.plain_result(report)

    @filter.llm_tool(name="get_achievements")
    async def tool_get_achievements(self, event: AstrMessageEvent):
        '''查询用户已解锁的成就列表。'''
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        unlocked = self.achievement_system.get_unlocked(user_id, group_id)
        if not unlocked:
            yield event.plain_result("还没有解锁任何成就，继续加油！")
            return
        yield event.plain_result(json.dumps(unlocked, ensure_ascii=False))

    @filter.llm_tool(name="get_today_plan")
    async def tool_get_today_plan(self, event: AstrMessageEvent):
        '''查询用户今天的训练计划。'''
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        plan = db.get_today_plan(user_id, group_id)
        if not plan:
            yield event.plain_result("今天还没有训练计划。")
            return
        result = json.dumps({
            "plan_date": plan.plan_date, "workout_type": plan.workout_type,
            "workout_detail": plan.workout_detail, "intensity": plan.intensity,
            "is_rest_day": plan.is_rest_day, "adjusted": plan.adjusted,
            "adjust_reason": plan.adjust_reason,
        }, ensure_ascii=False)
        yield event.plain_result(result)

    @filter.llm_tool(name="save_training_plan")
    async def tool_save_training_plan(
        self, event: AstrMessageEvent,
        workout_type: str, workout_detail: str,
        plan_date: str = "", intensity: str = "normal",
        is_rest_day: bool = False, adjusted: bool = False,
        adjust_reason: str = "",
    ):
        '''保存或更新用户某天的训练计划，如果该日期已有计划会覆盖。

        Args:
            workout_type(string): 训练类型
            workout_detail(string): 详细训练内容
            plan_date(string): 计划日期YYYY-MM-DD，默认今天
            intensity(string): 强度 low/normal/high
            is_rest_day(boolean): 是否休息日
            adjusted(boolean): 是否为动态调整
            adjust_reason(string): 调整原因
        '''
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        plan = TrainingPlan(
            user_id=user_id, group_id=group_id,
            plan_date=plan_date or date.today().isoformat(),
            workout_type=workout_type, workout_detail=workout_detail,
            intensity=intensity, is_rest_day=is_rest_day,
            adjusted=adjusted, adjust_reason=adjust_reason,
        )
        db.save_plan(plan)
        day_type = "休息日" if is_rest_day else workout_type
        yield event.plain_result(f"训练计划已保存: {plan.plan_date} - {day_type}")

    @filter.llm_tool(name="get_checkin_stats")
    async def tool_get_checkin_stats(self, event: AstrMessageEvent, days: int = 30):
        '''查询用户最近的打卡统计数据，包括连续天数、历史记录等。

        Args:
            days(number): 查询最近多少天，默认30
        '''
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        history = db.get_checkin_history(user_id, group_id, days=int(days))
        streak = db.get_checkin_streak(user_id, group_id)
        total = len(history)
        total_dur = sum(h.get("duration_min", 0) for h in history)
        total_cal = sum(h.get("calories_est", 0) for h in history)
        result = json.dumps({
            "streak": streak, "total_checkins": total,
            "total_duration_min": total_dur, "total_calories": total_cal,
            "avg_duration_min": round(total_dur / max(total, 1), 1),
            "recent_records": history[:5],
        }, ensure_ascii=False)
        yield event.plain_result(result)

    @filter.llm_tool(name="set_qq_title")
    async def tool_set_qq_title(self, event: AstrMessageEvent, title: str):
        '''手动设置用户的QQ群专属头衔，通常升级时自动设置，此工具用于手动修正。

        Args:
            title(string): 要设置的头衔文本
        '''
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        ok = await set_qq_group_title(event, user_id, title)
        msg = f"群头衔设置{'成功' if ok else '失败(需要机器人是群主)'}：{title}"
        yield event.plain_result(msg)

    # ==================== 进群欢迎 ====================

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    async def on_group_event(self, event: AstrMessageEvent):
        """监听新人进群事件，自动欢迎并引导建档"""
        if not self._is_group_enabled(event):
            return

        raw = getattr(event.message_obj, "raw_message", None)
        if not isinstance(raw, dict):
            return

        # 只处理新人进群事件
        if raw.get("notice_type") != "group_increase":
            return

        uid = str(raw.get("user_id", ""))
        # 忽略机器人自己进群
        if uid == event.get_self_id():
            return

        # 获取新人昵称
        try:
            info = await event.bot.get_stranger_info(user_id=int(uid))
            nickname = info.get("nickname", uid)
        except Exception:
            nickname = uid

        # 获取群 ID
        group_id = str(event.unified_msg_origin)
        profile = db.get_profile(uid, group_id)

        if profile and profile.onboarding_step == "complete":
            # 老用户回归
            title = get_title(profile.level)
            msg = (
                f"欢迎回来，Lv.{profile.level}【{title}】{nickname}！🎉\n"
                f"你的健身档案还在，随时可以继续打卡哦～"
            )
        else:
            # 新人欢迎 + 引导建档
            msg = (
                f"🏋️ 欢迎 {nickname} 加入！\n"
                f"我是群里的智能健身教练，可以帮你：\n"
                f"📋 建立专属健身档案\n"
                f"📝 生成个性化训练计划\n"
                f"✅ 每日打卡赚经验升级\n"
                f"⚔️ 闯关任务挑战\n\n"
                f"发送「健身注册」开始建档（通过私聊采集信息，保护隐私）～"
            )

        await event.send(event.plain_result(msg))

    # ==================== 主动回复 ====================

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    async def on_proactive_reply(self, event: AstrMessageEvent):
        """以可配置概率主动回复群消息"""
        if not self.proactive_reply_enabled:
            return
        if not self._is_group_enabled(event):
            return

        # 概率判定
        if random.randint(1, 100) > self.proactive_reply_probability:
            return

        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)

        # 忽略机器人自己的消息
        if user_id == event.get_self_id():
            return

        # 获取消息文本
        msg_text = event.message_str.strip() if event.message_str else ""
        if not msg_text:
            return

        # 获取用户档案（有档案的用户才触发）
        profile = db.get_profile(user_id, group_id)
        if not profile or profile.onboarding_step != "complete":
            return

        nickname = profile.nickname or event.get_sender_name()

        # 构建档案摘要
        profile_info = (
            f"健身目标: {profile.fitness_goal}, "
            f"等级: Lv.{profile.level}, "
            f"状态: {profile.current_status}"
        )

        persona_line = f"人格风格: {self.persona_prompt}" if self.persona_prompt else ""

        prompt = PROACTIVE_REPLY_PROMPT.format(
            message=msg_text[:200],
            nickname=nickname,
            profile_info=profile_info,
            persona_line=persona_line,
        )

        # 用低成本模型生成回复
        provider_id = self.lite_provider_id or self.chat_provider_id
        try:
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            if resp and resp.completion_text:
                reply = resp.completion_text.strip()
                if reply:
                    await event.send(event.plain_result(reply))
        except Exception as e:
            logger.debug(f"主动回复生成失败: {e}")

    # ==================== 私聊建档状态机 ====================

    @filter.event_message_type(EventMessageType.PRIVATE_MESSAGE)
    async def on_private_onboarding(self, event: AstrMessageEvent):
        """监听私聊消息，处理建档对话"""
        user_id = event.get_sender_id()
        session = self._onboarding_sessions.get(user_id)
        if not session:
            return

        msg = event.message_str.strip() if event.message_str else ""
        if not msg:
            return

        step = session["step"]
        data = session["data"]

        try:
            if step == "height_weight":
                nums = [s for s in msg.replace("，", " ").replace(",", " ").split() if s]
                parsed = []
                for s in nums:
                    try:
                        parsed.append(float(s))
                    except ValueError:
                        continue
                if len(parsed) < 2:
                    await event.bot.send_private_msg(
                        user_id=int(user_id),
                        message="❌ 没看懂，请输入身高和体重，用空格隔开\n比如：175 70",
                    )
                    return
                data["height_cm"] = parsed[0]
                data["weight_kg"] = parsed[1]
                session["step"] = "age_gender"
                await event.bot.send_private_msg(
                    user_id=int(user_id),
                    message="✅ 收到！\n\n👤 第2步：请告诉我你的年龄和性别\n比如：25 男",
                )

            elif step == "age_gender":
                parts = msg.replace("，", " ").replace(",", " ").split()
                age = 0
                gender = ""
                for p in parts:
                    try:
                        age = int(p)
                    except ValueError:
                        if p in ("男", "male", "m", "M"):
                            gender = "male"
                        elif p in ("女", "female", "f", "F"):
                            gender = "female"
                if not age or not gender:
                    await event.bot.send_private_msg(
                        user_id=int(user_id),
                        message="❌ 请输入年龄和性别\n比如：25 男",
                    )
                    return
                data["age"] = age
                data["gender"] = gender
                session["step"] = "goal"
                await event.bot.send_private_msg(
                    user_id=int(user_id),
                    message=(
                        "✅ 收到！\n\n🎯 第3步：你的健身目标是什么？\n"
                        "A. 增肌\nB. 减脂\nC. 塑形\nD. 维持健康\n\n"
                        "直接回复 A/B/C/D 或者打字都行"
                    ),
                )

            elif step == "goal":
                goal_map = {
                    "a": "增肌", "b": "减脂", "c": "塑形", "d": "维持健康",
                    "增肌": "增肌", "减脂": "减脂", "塑形": "塑形", "维持健康": "维持健康",
                }
                goal = goal_map.get(msg.lower().strip(), "")
                if not goal:
                    await event.bot.send_private_msg(
                        user_id=int(user_id),
                        message="❌ 请选择 A/B/C/D 或直接输入目标（增肌/减脂/塑形/维持健康）",
                    )
                    return
                data["fitness_goal"] = goal
                session["step"] = "body_condition"
                await event.bot.send_private_msg(
                    user_id=int(user_id),
                    message=(
                        "✅ 收到！\n\n🏃 第4步：你觉得自己目前的体质如何？\n"
                        "A. 偏瘦\nB. 正常\nC. 偏胖\nD. 肥胖\n\n"
                        "直接回复 A/B/C/D 或者打字"
                    ),
                )

            elif step == "body_condition":
                cond_map = {
                    "a": "偏瘦", "b": "正常", "c": "偏胖", "d": "肥胖",
                    "偏瘦": "偏瘦", "正常": "正常", "偏胖": "偏胖", "肥胖": "肥胖",
                }
                cond = cond_map.get(msg.lower().strip(), "")
                if not cond:
                    await event.bot.send_private_msg(
                        user_id=int(user_id),
                        message="❌ 请选择 A/B/C/D 或直接输入（偏瘦/正常/偏胖/肥胖）",
                    )
                    return
                data["body_condition"] = cond
                session["step"] = "equipment"
                await event.bot.send_private_msg(
                    user_id=int(user_id),
                    message=(
                        "✅ 收到！\n\n🏠 第5步：你在哪里锻炼？有什么器材？\n"
                        "比如：\n"
                        "- 家里，有哑铃和瑜伽垫\n"
                        "- 健身房，全器械\n"
                        "- 没有器材，纯徒手\n\n"
                        "随便说就行"
                    ),
                )

            elif step == "equipment":
                data["equipment"] = msg
                session["step"] = "schedule"
                await event.bot.send_private_msg(
                    user_id=int(user_id),
                    message=(
                        "✅ 收到！\n\n⏰ 第6步：你的作息时间\n"
                        "请告诉我起床时间、睡觉时间、偏好锻炼时间\n"
                        "比如：7:00 23:00 18:00\n"
                        "（起床 睡觉 锻炼，用空格隔开）"
                    ),
                )

            elif step == "schedule":
                import re
                times = re.findall(r'\d{1,2}:\d{2}', msg)
                if len(times) < 3:
                    await event.bot.send_private_msg(
                        user_id=int(user_id),
                        message="❌ 请输入3个时间（起床 睡觉 锻炼）\n比如：7:00 23:00 18:00",
                    )
                    return
                data["wake_time"] = times[0]
                data["sleep_time"] = times[1]
                data["preferred_workout_time"] = times[2]
                # 建议提醒时间：锻炼前30分钟
                try:
                    h, m = map(int, times[2].split(":"))
                    rm = h * 60 + m - 30
                    if rm < 0:
                        rm += 1440
                    data["reminder_time"] = f"{rm // 60:02d}:{rm % 60:02d}"
                except Exception:
                    data["reminder_time"] = "17:30"
                session["step"] = "quest"
                await event.bot.send_private_msg(
                    user_id=int(user_id),
                    message=(
                        "✅ 收到！\n\n⚔️ 最后一步：选择你的闯关任务\n"
                        "A. 3天新手试炼（奖励150经验）\n"
                        "B. 7天进阶挑战（奖励500经验）\n"
                        "C. 30天BOSS战（奖励2000经验）\n"
                        "D. 暂时不选\n\n"
                        "回复 A/B/C/D"
                    ),
                )

            elif step == "quest":
                quest_map = {"a": 3, "b": 7, "c": 30, "d": 0}
                q = quest_map.get(msg.lower().strip(), -1)
                if q == -1:
                    await event.bot.send_private_msg(
                        user_id=int(user_id),
                        message="❌ 请选择 A/B/C/D",
                    )
                    return
                data["quest_days"] = q

                # ===== 建档完成，保存数据 =====
                group_id = session["group_id"]
                profile = db.get_profile(user_id, group_id) or UserProfile(
                    user_id=user_id, group_id=group_id,
                )
                profile.nickname = data.get("nickname", profile.nickname)
                profile.height_cm = data.get("height_cm", 0)
                profile.weight_kg = data.get("weight_kg", 0)
                profile.age = data.get("age", 0)
                profile.gender = data.get("gender", "")
                profile.fitness_goal = data.get("fitness_goal", "")
                profile.body_condition = data.get("body_condition", "")
                profile.equipment = data.get("equipment", "")
                profile.wake_time = data.get("wake_time", "07:00")
                profile.sleep_time = data.get("sleep_time", "23:00")
                profile.preferred_workout_time = data.get("preferred_workout_time", "18:00")
                profile.reminder_time = data.get("reminder_time", "17:30")
                profile.quest_days = data.get("quest_days", 0)
                profile.onboarding_step = "complete"
                db.save_profile(profile)

                # 生成训练周期
                cycle_msg = ""
                try:
                    plans = self.periodization_engine.generate_cycle(user_id, group_id, 4)
                    cycle_msg = f"已自动生成4周训练周期（共{len(plans)}天计划）。"
                except Exception as e:
                    logger.warning(f"自动生成训练周期失败: {e}")

                # 刷新提醒
                if self.reminder:
                    self.reminder.refresh()

                # 清理会话
                del self._onboarding_sessions[user_id]

                # 私聊通知完成
                await event.bot.send_private_msg(
                    user_id=int(user_id),
                    message=(
                        "🎉 建档完成！你的健身档案已保存～\n\n"
                        f"📊 身高: {profile.height_cm}cm | 体重: {profile.weight_kg}kg\n"
                        f"🎯 目标: {profile.fitness_goal} | 体质: {profile.body_condition}\n"
                        f"⏰ 每日提醒: {profile.reminder_time}\n"
                        f"{('⚔️ 闯关: ' + str(profile.quest_days) + '天挑战') if profile.quest_days > 0 else ''}\n"
                        f"{cycle_msg}\n\n"
                        "现在回到群里，@我 就可以开始聊天和打卡了！"
                    ),
                )

                # 群里通知
                group_origin = session["group_origin"]
                try:
                    # 从 group_origin 提取纯群号
                    parts = group_origin.split(":")
                    qq_group_id = int(parts[-1]) if len(parts) >= 3 else int(group_origin)
                    title = get_title(profile.level)
                    title_msg = ""
                    if self.title_sync_enabled:
                        try:
                            await event.bot.set_group_special_title(
                                group_id=qq_group_id,
                                user_id=int(user_id),
                                special_title=f"Lv.{profile.level} {title}",
                                duration=-1,
                            )
                            title_msg = f"\n已设置群头衔: Lv.{profile.level} {title}"
                        except Exception:
                            pass
                    await event.bot.send_group_msg(
                        group_id=qq_group_id,
                        message=f"🎉 {profile.nickname} 已完成建档！Lv.{profile.level}【{title}】{title_msg}\n欢迎新伙伴加入健身之旅！💪",
                    )
                except Exception as e:
                    logger.warning(f"群内建档通知发送失败: {e}")

        except Exception as e:
            logger.error(f"私聊建档处理异常: {e}")
            await event.bot.send_private_msg(
                user_id=int(user_id),
                message="😅 出了点问题，请重新在群里发「健身注册」再试一次",
            )
            self._onboarding_sessions.pop(user_id, None)

    # ==================== 手动指令 (备用) ====================

    @filter.command("健身注册")
    async def cmd_register(self, event: AstrMessageEvent):
        """手动触发建档 — 通过私聊采集隐私数据"""
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        profile = db.get_profile(user_id, group_id)

        if profile and profile.onboarding_step == "complete":
            yield event.plain_result("你已经建过档了哦～想更新信息的话直接告诉我就行")
            return

        nickname = event.get_sender_name()
        if not profile:
            profile = UserProfile(
                user_id=user_id, group_id=group_id,
                nickname=nickname, onboarding_step="started",
            )
            db.save_profile(profile)

        # 初始化私聊建档会话
        self._onboarding_sessions[user_id] = {
            "step": "height_weight",
            "data": {"nickname": nickname},
            "group_id": group_id,
            "group_origin": group_id,
        }

        # 尝试发送私聊消息
        try:
            await event.bot.send_private_msg(
                user_id=int(user_id),
                message=(
                    f"嗨 {nickname}，欢迎开始你的健身之旅！🏋️\n"
                    "我是你的智能健身教练，接下来在私聊里完成建档，保护你的隐私～\n\n"
                    "📏 第1步：请告诉我你的身高(cm)和体重(kg)\n"
                    "比如：175 70"
                ),
            )
            yield event.plain_result(
                f"📩 已私聊 {nickname}，请在私聊中完成建档～\n"
                "（如果没收到私聊，请先加机器人为好友）"
            )
        except Exception as e:
            logger.warning(f"发送私聊建档消息失败: {e}")
            # 私聊失败，回退到群内建档
            del self._onboarding_sessions[user_id]
            yield event.plain_result(
                f"嗨 {nickname}，欢迎开始你的健身之旅！🏋️\n"
                "我是你的智能健身教练，先来了解一下你吧～\n\n"
                "请告诉我你的基本信息：身高（cm）、体重（kg）、年龄和性别？\n"
                "比如：'我身高175，体重70kg，25岁，男'"
            )

    @filter.command("打卡")
    async def cmd_checkin(self, event: AstrMessageEvent):
        """手动打卡指令"""
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        existing = db.get_today_checkin(user_id, group_id)
        if existing:
            yield event.plain_result("今天已经打过卡啦，明天继续加油！💪")
            return
        yield event.plain_result(
            "收到！告诉我你今天练了什么吧～\n"
            "比如：'今天做了30分钟跑步和20个俯卧撑，感觉还行'"
        )

    @filter.command("我的档案")
    async def cmd_my_profile(self, event: AstrMessageEvent):
        """查看个人档案"""
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        profile = db.get_profile(user_id, group_id)

        if not profile:
            yield event.plain_result("你还没有建立健身档案哦，@我 说'我想开始健身'就可以开始建档～")
            return

        streak = db.get_checkin_streak(user_id, group_id)
        supp = profile.supplement_details if profile.has_supplements else "无"
        title = get_title(profile.level)
        next_exp = exp_for_next_level(profile.level)
        exp_to_next = max(next_exp - profile.exp, 0)

        quest_info = "未选择"
        if profile.quest_days > 0:
            quest_names = {3: "新手试炼", 7: "进阶挑战", 30: "BOSS战"}
            qname = quest_names.get(profile.quest_days, f"{profile.quest_days}天")
            done = "✅ 已通关" if profile.quest_progress >= profile.quest_days else f"{profile.quest_progress}/{profile.quest_days}"
            quest_info = f"{qname} ({done})"

        text = (
            f"📋 {profile.nickname} 的健身档案\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⚔️ Lv.{profile.level}【{title}】\n"
            f"✨ 经验值: {profile.exp} (距下级 {exp_to_next})\n"
            f"🏰 闯关任务: {quest_info}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"身高: {profile.height_cm}cm | 体重: {profile.weight_kg}kg\n"
            f"年龄: {profile.age} | 性别: {profile.gender}\n"
            f"目标: {profile.fitness_goal}\n"
            f"体质: {profile.body_condition}\n"
            f"器材: {profile.equipment or '无'}\n"
            f"补剂: {supp}\n"
            f"锻炼时间: {profile.preferred_workout_time}\n"
            f"提醒时间: {profile.reminder_time}\n"
            f"当前状态: {profile.current_status}\n"
            f"连续打卡: {streak}天 🔥\n"
        )
        if profile.ai_analysis:
            text += f"━━━━━━━━━━━━━━━\n📊 教练分析: {profile.ai_analysis}\n"
        yield event.plain_result(text)

    @filter.command("今日计划")
    async def cmd_today_plan(self, event: AstrMessageEvent):
        """查看今日训练计划"""
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        plan = db.get_today_plan(user_id, group_id)

        if not plan:
            yield event.plain_result("今天还没有训练计划，@我 说'帮我安排今天的训练'我来给你规划～")
            return

        status = "（已调整）" if plan.adjusted else ""
        text = (
            f"📝 今日训练计划 {status}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"类型: {plan.workout_type}\n"
            f"强度: {plan.intensity}\n"
            f"内容:\n{plan.workout_detail}\n"
        )
        if plan.adjusted:
            text += f"\n调整原因: {plan.adjust_reason}"
        yield event.plain_result(text)

    @filter.command("我的计划")
    async def cmd_my_plan(self, event: AstrMessageEvent):
        """查看训练方向、综合分析和近期计划"""
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        profile = db.get_profile(user_id, group_id)

        if not profile:
            yield event.plain_result("你还没有建立健身档案哦，@我 说'我想开始健身'就可以开始建档～")
            return

        title = get_title(profile.level)
        text = f"📝 {profile.nickname} 的训练规划\n━━━━━━━━━━━━━━━\n"

        # 基础信息概要
        text += f"⚔️ Lv.{profile.level}【{title}】| 目标: {profile.fitness_goal}\n"
        text += f"器材: {profile.equipment or '未记录'}\n"
        if profile.training_experience:
            text += f"训练经验: {profile.training_experience}\n"
        if profile.focus_parts:
            text += f"重点部位: {profile.focus_parts}\n"
        if profile.training_frequency:
            text += f"训练频率: {profile.training_frequency}\n"

        # AI 综合分析
        if profile.ai_analysis:
            text += f"━━━━━━━━━━━━━━━\n📊 训练方向分析:\n{profile.ai_analysis}\n"
        else:
            text += f"━━━━━━━━━━━━━━━\n📊 训练方向分析: 还在收集信息中，多跟我聊聊你的情况～\n"

        # 近7天计划
        plans = db.get_upcoming_plans(user_id, group_id, days=7)
        if plans:
            text += f"━━━━━━━━━━━━━━━\n📅 近期计划:\n"
            for p in plans:
                day_type = "🏖️ 休息日" if p.is_rest_day else f"{p.workout_type}"
                adjusted = " (已调整)" if p.adjusted else ""
                text += f"  {p.plan_date}: {day_type}{adjusted}\n"
        else:
            text += f"━━━━━━━━━━━━━━━\n📅 近期计划: 暂无，@我 说'帮我安排这周的训练'来生成～\n"

        yield event.plain_result(text)

    # ==================== v2.0 手动指令 ====================

    @filter.command("我的成就")
    async def cmd_achievements(self, event: AstrMessageEvent):
        """查看已解锁成就"""
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        unlocked = self.achievement_system.get_unlocked(user_id, group_id)

        if not unlocked:
            yield event.plain_result("你还没有解锁任何成就，继续打卡就能解锁哦～ 💪")
            return

        text = f"🏅 已解锁成就 ({len(unlocked)}/{len(ACHIEVEMENTS)})\n━━━━━━━━━━━━━━━\n"
        for a in unlocked:
            text += f"🏅 {a['name']} - {a['desc']} (+{a['exp']}exp)\n"
            text += f"   解锁时间: {a['unlocked_at'][:10]}\n"

        # 未解锁的成就
        locked = [aid for aid in ACHIEVEMENTS if aid not in {a['id'] for a in unlocked}]
        if locked:
            text += f"\n🔒 未解锁: {len(locked)} 个成就等你挑战"

        yield event.plain_result(text)

    @filter.command("饮食记录")
    async def cmd_diet_record(self, event: AstrMessageEvent):
        """查看今日饮食汇总"""
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        summary = self.diet_logger.get_daily_summary(user_id, group_id)

        if summary["meal_count"] == 0:
            yield event.plain_result("今天还没有饮食记录，告诉我你吃了什么我帮你记录～ 🍽️")
            return

        text = f"🍽️ 今日饮食记录\n━━━━━━━━━━━━━━━\n"
        for m in summary["meals"]:
            text += f"  {m['meal_type']}: {m['description']} ({m['calories']}kcal, {m['protein']}g蛋白)\n"
        text += f"━━━━━━━━━━━━━━━\n"
        text += f"📊 总计: {summary['total_calories']}kcal | {summary['total_protein']}g蛋白质\n"
        text += f"共 {summary['meal_count']} 餐"

        yield event.plain_result(text)

    @filter.command("补卡")
    async def cmd_makeup(self, event: AstrMessageEvent):
        """引导用户补卡"""
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)

        yesterday = (date.today() - timedelta(days=1)).isoformat()

        # 检查昨天是否已有打卡
        conn = db.get_conn()
        try:
            row = conn.execute(
                "SELECT 1 FROM checkin_records WHERE user_id=? AND group_id=? AND checkin_date=?",
                (user_id, group_id, yesterday)
            ).fetchone()
        finally:
            conn.close()

        if row:
            yield event.plain_result("昨天已有打卡记录，不需要补卡哦～")
            return

        yield event.plain_result(
            f"📝 补卡模式（补 {yesterday} 的训练）\n"
            f"注意：补卡经验减半\n\n"
            f"请告诉我你昨天练了什么，比如：\n"
            f"'昨天做了40分钟力量训练，练了胸和三头，感觉适中'"
        )

    @filter.command("训练周期")
    async def cmd_training_cycle(self, event: AstrMessageEvent):
        """查看当前训练周期概览"""
        user_id = event.get_sender_id()
        group_id = str(event.unified_msg_origin)
        overview = self.periodization_engine.get_cycle_overview(user_id, group_id)

        if not overview:
            yield event.plain_result("当前没有活跃的训练周期，@我 说'帮我安排训练周期'来生成一个～")
            return

        deload_info = " (去负荷周)" if overview["is_deload_week"] else ""
        text = (
            f"📅 训练周期概览\n━━━━━━━━━━━━━━━\n"
            f"类型: {overview['cycle_type']}\n"
            f"当前: 第 {overview['current_week']}/{overview['total_weeks']} 周{deload_info}\n"
            f"剩余: {overview['remaining_weeks']} 周\n"
            f"周期: {overview['start_date']} ~ {overview['end_date']}\n"
        )
        if overview["deload_week"] > 0:
            text += f"去负荷周: 第 {overview['deload_week']} 周\n"

        yield event.plain_result(text)

    # ==================== 管理员指令 ====================

    async def _is_admin(self, event: AstrMessageEvent) -> bool:
        """检查发送者是否为群主/管理员"""
        try:
            group_id = event.get_group_id()
            user_id = event.get_sender_id()
            info = await event.bot.get_group_member_info(
                group_id=int(group_id), user_id=int(user_id), no_cache=True
            )
            return info.get("role", "") in ("owner", "admin")
        except Exception:
            return False

    @filter.command("查看档案")
    async def cmd_view_profile(self, event: AstrMessageEvent):
        """管理员查看指定用户档案（需要@目标用户）"""
        if not await self._is_admin(event):
            yield event.plain_result("该指令仅群主/管理员可用")
            return

        # 从消息中提取被@的用户
        target_uid = None
        if hasattr(event.message_obj, "message") and event.message_obj.message:
            for seg in event.message_obj.message:
                if hasattr(seg, "type") and seg.type == "at":
                    qq = str(seg.data.get("qq", ""))
                    if qq and qq != event.get_self_id():
                        target_uid = qq
                        break

        if not target_uid:
            yield event.plain_result("请@要查看的用户，例如：查看档案 @某人")
            return

        group_id = str(event.unified_msg_origin)
        profile = db.get_profile(target_uid, group_id)
        if not profile:
            yield event.plain_result(f"用户 {target_uid} 尚未建立健身档案。")
            return

        streak = db.get_checkin_streak(target_uid, group_id)
        title = get_title(profile.level)
        supp = profile.supplement_details if profile.has_supplements else "无"

        quest_info = "未选择"
        if profile.quest_days > 0:
            quest_names = {3: "新手试炼", 7: "进阶挑战", 30: "BOSS战"}
            qname = quest_names.get(profile.quest_days, f"{profile.quest_days}天")
            done = "✅ 已通关" if profile.quest_progress >= profile.quest_days else f"{profile.quest_progress}/{profile.quest_days}"
            quest_info = f"{qname} ({done})"

        text = (
            f"📋 {profile.nickname} 的健身档案（管理员查看）\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⚔️ Lv.{profile.level}【{title}】| ✨ {profile.exp}exp\n"
            f"🏰 闯关: {quest_info} | 🔥 连续{streak}天\n"
            f"━━━━━━━━━━━━━━━\n"
            f"身高: {profile.height_cm}cm | 体重: {profile.weight_kg}kg\n"
            f"年龄: {profile.age} | 性别: {profile.gender}\n"
            f"目标: {profile.fitness_goal} | 体质: {profile.body_condition}\n"
            f"器材: {profile.equipment or '无'} | 补剂: {supp}\n"
            f"训练经验: {profile.training_experience or '未知'}\n"
            f"训练频率: {profile.training_frequency or '未知'}\n"
            f"薄弱部位: {profile.weak_parts or '未知'} | 重点部位: {profile.focus_parts or '未知'}\n"
            f"饮食: {profile.diet_habit or '未知'} | 餐数: {profile.meals_per_day or '未知'}\n"
            f"蛋白质: {profile.protein_intake or '未知'} | 活动量: {profile.daily_activity or '未知'}\n"
            f"作息: {profile.wake_time}起/{profile.sleep_time}睡\n"
            f"锻炼: {profile.preferred_workout_time} | 提醒: {profile.reminder_time or '已关闭'}\n"
            f"状态: {profile.current_status} {profile.status_note}\n"
            f"健康备注: {profile.health_notes or '无'}\n"
            f"建档进度: {profile.onboarding_step}\n"
            f"UID: {profile.user_id}\n"
        )
        if profile.ai_analysis:
            text += f"━━━━━━━━━━━━━━━\n📊 AI分析: {profile.ai_analysis}\n"
        yield event.plain_result(text)

    @filter.command("查看所有档案")
    async def cmd_view_all_profiles(self, event: AstrMessageEvent):
        """管理员查看本群所有已建档用户概览"""
        if not await self._is_admin(event):
            yield event.plain_result("该指令仅群主/管理员可用")
            return

        group_id = str(event.unified_msg_origin)
        profiles = db.get_all_profiles_in_group(group_id)

        if not profiles:
            yield event.plain_result("本群还没有任何已建档用户。")
            return

        lines = [f"📊 本群健身档案总览（共 {len(profiles)} 人）\n━━━━━━━━━━━━━━━"]
        for p in profiles:
            level = p.get("level", 1)
            title = get_title(level)
            nickname = p.get("nickname", p["user_id"])
            goal = p.get("fitness_goal", "")
            streak = db.get_checkin_streak(p["user_id"], p["group_id"])
            status = p.get("current_status", "normal")
            status_icon = {"normal": "✅", "sick": "🤒", "injured": "🤕", "tired": "😴", "rest": "🏖️"}.get(status, "❓")
            lines.append(
                f"{status_icon} Lv.{level}【{title}】{nickname}\n"
                f"   目标: {goal} | 🔥{streak}天 | exp:{p.get('exp', 0)}"
            )

        yield event.plain_result("\n".join(lines))
