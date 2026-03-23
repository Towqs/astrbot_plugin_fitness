"""周期化训练和去负荷模块"""
import json
from datetime import date, timedelta
from typing import Optional
from . import database as db
from .models import TrainingPlan, TrainingCycle


# 强度等级映射
INTENSITY_LEVELS = {"low": 1, "normal": 2, "high": 3}

# 训练类型模板（按目标）
CYCLE_TEMPLATES = {
    "增肌": [
        {"type": "力量", "focus": "胸/三头"},
        {"type": "力量", "focus": "背/二头"},
        {"type": "力量", "focus": "腿/肩"},
        {"type": "有氧", "focus": "低强度有氧"},
        {"type": "力量", "focus": "胸/背"},
        {"type": "力量", "focus": "腿/手臂"},
        {"type": "休息", "focus": "休息日"},
    ],
    "减脂": [
        {"type": "混合", "focus": "全身力量+有氧"},
        {"type": "有氧", "focus": "中强度有氧"},
        {"type": "力量", "focus": "上肢力量"},
        {"type": "有氧", "focus": "HIIT"},
        {"type": "力量", "focus": "下肢力量"},
        {"type": "有氧", "focus": "低强度有氧"},
        {"type": "休息", "focus": "休息日"},
    ],
    "default": [
        {"type": "力量", "focus": "上肢"},
        {"type": "有氧", "focus": "有氧训练"},
        {"type": "力量", "focus": "下肢"},
        {"type": "拉伸", "focus": "拉伸恢复"},
        {"type": "力量", "focus": "全身"},
        {"type": "有氧", "focus": "有氧训练"},
        {"type": "休息", "focus": "休息日"},
    ],
}


class PeriodizationEngine:
    """周期化训练引擎"""

    def generate_cycle(
        self, user_id: str, group_id: str, weeks: int = 4
    ) -> list[TrainingPlan]:
        """生成 N 周训练周期计划，包含渐进超负荷

        weeks: 4-8 周
        返回生成的所有 TrainingPlan 列表
        """
        weeks = max(4, min(8, weeks))

        profile = db.get_profile(user_id, group_id)
        goal = profile.fitness_goal if profile else ""
        template = CYCLE_TEMPLATES.get(goal, CYCLE_TEMPLATES["default"])

        # 结束现有活跃周期
        existing = db.get_active_cycle(user_id, group_id)
        if existing:
            db.complete_cycle(existing.id)

        # 创建新周期
        start = date.today()
        end = start + timedelta(weeks=weeks) - timedelta(days=1)

        # 确定去负荷周（最后一周如果 >= 4 周）
        deload_week = weeks if weeks >= 4 else 0

        cycle = TrainingCycle(
            user_id=user_id,
            group_id=group_id,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            total_weeks=weeks,
            current_week=1,
            cycle_type=goal or "综合训练",
            status="active",
            deload_week=deload_week,
        )
        db.save_training_cycle(cycle)

        # 生成每天的训练计划
        plans = []
        intensities = self._generate_intensity_progression(weeks, deload_week)

        for week_idx in range(weeks):
            week_intensity = intensities[week_idx]
            for day_idx in range(7):
                plan_date = start + timedelta(weeks=week_idx, days=day_idx)
                day_template = template[day_idx % len(template)]

                is_rest = day_template["type"] == "休息"
                plan = TrainingPlan(
                    user_id=user_id,
                    group_id=group_id,
                    plan_date=plan_date.isoformat(),
                    workout_type=day_template["type"],
                    workout_detail=day_template["focus"],
                    intensity=week_intensity if not is_rest else "low",
                    is_rest_day=is_rest,
                )
                db.save_plan(plan)
                plans.append(plan)

        return plans

    def _generate_intensity_progression(self, weeks: int, deload_week: int) -> list[str]:
        """生成渐进超负荷的强度序列

        例如 4 周: normal → normal → high → low(deload)
        例如 6 周: normal → normal → high → high → high → low(deload)
        例如 8 周: normal → normal → normal → high → high → high → high → low(deload)
        """
        intensities = []
        # 非去负荷周的数量
        training_weeks = weeks - (1 if deload_week > 0 else 0)
        # 前 1/3 为 normal，后面为 high
        normal_count = max(training_weeks // 3, 1)

        for w in range(1, weeks + 1):
            if w == deload_week:
                intensities.append("low")
            elif w <= normal_count:
                intensities.append("normal")
            else:
                intensities.append("high")
        return intensities

    def get_cycle_overview(self, user_id: str, group_id: str) -> Optional[dict]:
        """获取当前周期概览"""
        cycle = db.get_active_cycle(user_id, group_id)
        if not cycle:
            return None

        remaining = cycle.total_weeks - cycle.current_week
        is_deload = cycle.current_week == cycle.deload_week

        return {
            "cycle_type": cycle.cycle_type,
            "total_weeks": cycle.total_weeks,
            "current_week": cycle.current_week,
            "remaining_weeks": remaining,
            "is_deload_week": is_deload,
            "start_date": cycle.start_date,
            "end_date": cycle.end_date,
            "deload_week": cycle.deload_week,
        }

    def check_deload_needed(self, user_id: str, group_id: str) -> bool:
        """检查是否需要去负荷周

        连续 3 周以上 normal/high 强度训练 → 需要去负荷
        """
        history = db.get_checkin_history(user_id, group_id, days=28)
        if len(history) < 9:  # 至少 3 周的数据（每周 3 次）
            return False

        # 按周分组
        today = date.today()
        weeks_data = {}
        for h in history:
            try:
                d = date.fromisoformat(h.get("checkin_date", ""))
                week_num = (today - d).days // 7
                weeks_data.setdefault(week_num, []).append(h)
            except ValueError:
                continue

        # 检查最近 3 周是否都有高强度训练
        consecutive_hard = 0
        for week in sorted(weeks_data.keys()):
            if week > 4:
                break
            feelings = [h.get("feeling", "") for h in weeks_data[week]]
            hard_count = sum(1 for f in feelings if f in ("吃力", "很累"))
            if hard_count >= len(feelings) * 0.5:
                consecutive_hard += 1
            else:
                consecutive_hard = 0

        return consecutive_hard >= 3

    def generate_deload_week(self, user_id: str, group_id: str) -> list[TrainingPlan]:
        """生成去负荷周计划（全 low 强度）"""
        profile = db.get_profile(user_id, group_id)
        goal = profile.fitness_goal if profile else ""
        template = CYCLE_TEMPLATES.get(goal, CYCLE_TEMPLATES["default"])

        start = date.today()
        # 找到下周一
        days_until_monday = (7 - start.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        monday = start + timedelta(days=days_until_monday)

        plans = []
        for day_idx in range(7):
            plan_date = monday + timedelta(days=day_idx)
            day_template = template[day_idx % len(template)]
            is_rest = day_template["type"] == "休息"

            plan = TrainingPlan(
                user_id=user_id,
                group_id=group_id,
                plan_date=plan_date.isoformat(),
                workout_type=day_template["type"],
                workout_detail=f"[去负荷] {day_template['focus']}",
                intensity="low",
                is_rest_day=is_rest,
                adjusted=True,
                adjust_reason="去负荷周：降低强度恢复身体",
            )
            db.save_plan(plan)
            plans.append(plan)

        # 更新周期的去负荷标记
        cycle = db.get_active_cycle(user_id, group_id)
        if cycle:
            db.update_cycle_week(cycle.id, cycle.current_week)

        return plans

    def adjust_cycle(self, user_id: str, group_id: str, reason: str) -> None:
        """根据画像变化调整后续周计划（降低强度）"""
        cycle = db.get_active_cycle(user_id, group_id)
        if not cycle:
            return

        # 将后续未完成的 high 强度计划降为 normal
        today = date.today().isoformat()
        conn = db.get_conn()
        try:
            conn.execute(
                "UPDATE training_plans SET intensity='normal', adjusted=1, adjust_reason=? "
                "WHERE user_id=? AND group_id=? AND plan_date>? AND intensity='high'",
                (reason, user_id, group_id, today)
            )
            conn.commit()
        finally:
            conn.close()
