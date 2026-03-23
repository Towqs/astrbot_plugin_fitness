"""用户画像模块"""
import json
from typing import Optional
from datetime import date, timedelta
from . import database as db
from .models import UserPortrait


class UserPortraitManager:
    """用户画像管理器"""

    def calculate_weight_trend(self, weight_records: list[dict]) -> dict:
        """计算体重趋势：方向(up/down/stable)、速率(kg/week)"""
        if len(weight_records) < 2:
            return {"direction": "stable", "rate_per_week": 0.0}

        # 按日期排序（升序）
        sorted_records = sorted(weight_records, key=lambda r: r.get("record_date", ""))
        first = sorted_records[0]["weight_kg"]
        last = sorted_records[-1]["weight_kg"]
        diff = last - first

        # 计算时间跨度（周）
        try:
            d1 = date.fromisoformat(sorted_records[0]["record_date"])
            d2 = date.fromisoformat(sorted_records[-1]["record_date"])
            weeks = max((d2 - d1).days / 7, 1)
        except (ValueError, KeyError):
            weeks = 1

        rate = round(diff / weeks, 2)

        if abs(diff) < 0.5:
            direction = "stable"
        elif diff > 0:
            direction = "up"
        else:
            direction = "down"

        return {"direction": direction, "rate_per_week": abs(rate)}

    def calculate_recovery_score(self, checkins: list[dict]) -> int:
        """根据打卡感受分布计算恢复能力评分(0-100)
        轻松=100, 适中=70, 吃力=40, 很累=10
        """
        if not checkins:
            return 50  # 默认中等

        score_map = {"轻松": 100, "适中": 70, "吃力": 40, "很累": 10}
        scores = []
        for c in checkins:
            f = c.get("feeling", "")
            if f in score_map:
                scores.append(score_map[f])

        if not scores:
            return 50

        return max(0, min(100, round(sum(scores) / len(scores))))

    def calculate_progress_speed(self, checkins: list[dict]) -> str:
        """根据历史数据判断进步速度：fast/normal/slow/stagnant

        对比最近2周 vs 前2周的平均训练时长和感受
        """
        if len(checkins) < 7:
            return "normal"

        # 按日期排序（升序）
        sorted_c = sorted(checkins, key=lambda r: r.get("checkin_date", ""))
        mid = len(sorted_c) // 2
        older = sorted_c[:mid]
        newer = sorted_c[mid:]

        # 平均时长对比
        old_dur = sum(c.get("duration_min", 0) for c in older) / max(len(older), 1)
        new_dur = sum(c.get("duration_min", 0) for c in newer) / max(len(newer), 1)

        # 感受评分对比
        feeling_score = {"轻松": 4, "适中": 3, "吃力": 2, "很累": 1}
        old_feel = sum(feeling_score.get(c.get("feeling", ""), 2) for c in older) / max(len(older), 1)
        new_feel = sum(feeling_score.get(c.get("feeling", ""), 2) for c in newer) / max(len(newer), 1)

        dur_change = (new_dur - old_dur) / max(old_dur, 1)
        feel_change = new_feel - old_feel

        # 综合判断
        if dur_change >= 0.15 and feel_change >= 0.3:
            return "fast"
        elif dur_change >= 0.05 or feel_change >= 0.1:
            return "normal"
        elif dur_change <= -0.1 or feel_change <= -0.3:
            return "slow"
        else:
            return "stagnant"

    def get_training_preference(self, checkins: list[dict]) -> dict:
        """统计训练类型偏好分布"""
        if not checkins:
            return {}

        type_count = {}
        for c in checkins:
            wt = c.get("workout_type", "")
            if wt:
                type_count[wt] = type_count.get(wt, 0) + 1

        total = sum(type_count.values())
        if total == 0:
            return {}

        return {k: round(v / total, 2) for k, v in type_count.items()}

    def update_portrait(self, user_id: str, group_id: str) -> UserPortrait:
        """聚合计算结果更新画像"""
        # 获取历史数据
        checkins = db.get_checkin_history(user_id, group_id, days=30)
        weight_records = db.get_weight_history(user_id, group_id, days=30)

        # 计算各维度
        weight_trend = self.calculate_weight_trend(weight_records)
        recovery_score = self.calculate_recovery_score(checkins)
        progress_speed = self.calculate_progress_speed(checkins)
        training_pref = self.get_training_preference(checkins)

        # 计算疲劳度（取最近5天感受）
        from .fatigue import FatigueAssessor
        assessor = FatigueAssessor()
        recent_feelings = [c.get("feeling", "") for c in checkins[:5] if c.get("feeling")]
        fatigue_score = assessor.calculate_fatigue_score(recent_feelings)

        # 获取或创建画像
        portrait = db.get_portrait(user_id, group_id)
        if not portrait:
            portrait = UserPortrait(user_id=user_id, group_id=group_id)

        portrait.weight_trend = json.dumps(weight_trend, ensure_ascii=False)
        portrait.training_preference = json.dumps(training_pref, ensure_ascii=False)
        portrait.recovery_score = recovery_score
        portrait.progress_speed = progress_speed
        portrait.fatigue_score = fatigue_score

        db.save_portrait(portrait)
        return portrait

    def get_portrait(self, user_id: str, group_id: str) -> Optional[UserPortrait]:
        """查询画像"""
        return db.get_portrait(user_id, group_id)
