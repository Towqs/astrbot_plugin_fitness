"""成就系统模块"""
from datetime import datetime
from . import database as db
from .models import Achievement

# 成就定义
ACHIEVEMENTS = {
    "first_checkin":  {"name": "初出茅庐", "desc": "完成首次打卡",       "exp": 50},
    "streak_7":       {"name": "周周不落", "desc": "连续打卡7天",        "exp": 100},
    "streak_30":      {"name": "月度铁人", "desc": "连续打卡30天",       "exp": 500},
    "streak_100":     {"name": "百日征途", "desc": "连续打卡100天",      "exp": 2000},
    "first_levelup":  {"name": "破茧成蝶", "desc": "首次升级",          "exp": 30},
    "reach_lv5":      {"name": "中流砥柱", "desc": "达到Lv.5",          "exp": 200},
    "reach_lv10":     {"name": "登峰造极", "desc": "达到Lv.10",         "exp": 1000},
    "first_quest":    {"name": "勇者启程", "desc": "首次完成闯关任务",    "exp": 100},
    "total_50":       {"name": "半百之力", "desc": "累计打卡50次",       "exp": 300},
    "total_100":      {"name": "百炼成钢", "desc": "累计打卡100次",      "exp": 800},
    "total_365":      {"name": "年度传说", "desc": "累计打卡365次",      "exp": 5000},
    "first_diet":     {"name": "营养达人", "desc": "首次饮食打卡",       "exp": 30},
}


class AchievementSystem:
    """成就系统"""

    def check_achievements(
        self, user_id: str, group_id: str, trigger: str, context: dict
    ) -> list[dict]:
        """检查并解锁成就，返回新解锁的成就列表

        trigger: checkin / levelup / quest_complete / diet_log
        context: 触发上下文 {streak, total_checkins, level, ...}
        """
        newly_unlocked = []

        if trigger == "checkin":
            streak = context.get("streak", 0)
            total = context.get("total_checkins", 0)

            # 首次打卡
            if total == 1:
                r = self._try_unlock(user_id, group_id, "first_checkin")
                if r:
                    newly_unlocked.append(r)

            # 连续打卡成就
            streak_achievements = {7: "streak_7", 30: "streak_30", 100: "streak_100"}
            for days, aid in streak_achievements.items():
                if streak >= days:
                    r = self._try_unlock(user_id, group_id, aid)
                    if r:
                        newly_unlocked.append(r)

            # 累计打卡成就
            total_achievements = {50: "total_50", 100: "total_100", 365: "total_365"}
            for count, aid in total_achievements.items():
                if total >= count:
                    r = self._try_unlock(user_id, group_id, aid)
                    if r:
                        newly_unlocked.append(r)

        elif trigger == "levelup":
            level = context.get("level", 1)
            old_level = context.get("old_level", 1)

            # 首次升级
            if old_level == 1 and level > 1:
                r = self._try_unlock(user_id, group_id, "first_levelup")
                if r:
                    newly_unlocked.append(r)

            # 等级成就
            if level >= 5:
                r = self._try_unlock(user_id, group_id, "reach_lv5")
                if r:
                    newly_unlocked.append(r)
            if level >= 10:
                r = self._try_unlock(user_id, group_id, "reach_lv10")
                if r:
                    newly_unlocked.append(r)

        elif trigger == "quest_complete":
            r = self._try_unlock(user_id, group_id, "first_quest")
            if r:
                newly_unlocked.append(r)

        elif trigger == "diet_log":
            r = self._try_unlock(user_id, group_id, "first_diet")
            if r:
                newly_unlocked.append(r)

        return newly_unlocked

    def get_unlocked(self, user_id: str, group_id: str) -> list[dict]:
        """获取已解锁成就列表"""
        records = db.get_achievements(user_id, group_id)
        result = []
        for a in records:
            info = ACHIEVEMENTS.get(a.achievement_id, {})
            result.append({
                "id": a.achievement_id,
                "name": info.get("name", a.achievement_id),
                "desc": info.get("desc", ""),
                "exp": info.get("exp", 0),
                "unlocked_at": a.unlocked_at,
            })
        return result

    def _try_unlock(self, user_id: str, group_id: str, achievement_id: str) -> dict | None:
        """尝试解锁成就，已解锁则返回 None"""
        if db.is_achievement_unlocked(user_id, group_id, achievement_id):
            return None
        return self._unlock(user_id, group_id, achievement_id)

    def _unlock(self, user_id: str, group_id: str, achievement_id: str) -> dict:
        """解锁成就并持久化，返回成就信息"""
        now = datetime.now().isoformat()
        a = Achievement(
            user_id=user_id,
            group_id=group_id,
            achievement_id=achievement_id,
            unlocked_at=now,
        )
        db.save_achievement(a)

        info = ACHIEVEMENTS.get(achievement_id, {})
        return {
            "id": achievement_id,
            "name": info.get("name", achievement_id),
            "desc": info.get("desc", ""),
            "exp": info.get("exp", 0),
        }
