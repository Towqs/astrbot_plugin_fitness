"""疲劳度评估模块"""
from dataclasses import dataclass
from . import database as db


# 感受 -> 疲劳分值映射
FEELING_SCORE_MAP = {
    "轻松": 10,
    "适中": 30,
    "吃力": 60,
    "很累": 90,
}


@dataclass
class FatigueResult:
    score: int           # 0-100
    suggestion: str      # advice text
    should_adjust: bool  # whether to adjust next day plan


class FatigueAssessor:
    """疲劳度评估器"""

    def calculate_fatigue_score(self, recent_feelings: list[str]) -> int:
        """根据最近 3-5 天感受计算疲劳度评分(0-100)

        感受映射: 轻松=10, 适中=30, 吃力=60, 很累=90
        取最近 3-5 条感受，加权平均（越近权重越高）。
        """
        if not recent_feelings:
            return 0

        # 取最近 3-5 条
        feelings = recent_feelings[-5:]

        # 转换为分值，未知感受忽略
        scores = []
        for f in feelings:
            if f in FEELING_SCORE_MAP:
                scores.append(FEELING_SCORE_MAP[f])

        if not scores:
            return 0

        # 加权平均：权重线性递增，最近的权重最大
        total_weight = 0
        weighted_sum = 0
        for i, s in enumerate(scores):
            w = i + 1  # 1, 2, 3, ...
            weighted_sum += s * w
            total_weight += w

        raw = weighted_sum / total_weight
        return max(0, min(100, round(raw)))

    def should_rest(self, score: int, user_status: str,
                    recent_feelings: list[str] | None = None) -> bool:
        """判断是否需要休息

        - score > 75
        - user_status in ("sick", "injured")
        - 最近 3 天感受全部为"吃力"或"很累"
        """
        if score > 75:
            return True
        if user_status in ("sick", "injured"):
            return True
        if recent_feelings and len(recent_feelings) >= 3:
            last3 = recent_feelings[-3:]
            if all(f in ("吃力", "很累") for f in last3):
                return True
        return False

    def assess(self, user_id: str, group_id: str) -> FatigueResult:
        """评估当前疲劳度，返回评分和建议"""
        # 读取最近 5 天打卡历史
        history = db.get_checkin_history(user_id, group_id, days=5)

        # 提取感受列表（按日期升序，最近的在后面）
        feelings = [r["feeling"] for r in reversed(history) if r.get("feeling")]

        # 计算疲劳度评分
        score = self.calculate_fatigue_score(feelings)

        # 检查用户状态
        profile = db.get_profile(user_id, group_id)
        user_status = profile.current_status if profile else "normal"

        # sick/injured 时强制设为 100
        if user_status in ("sick", "injured"):
            score = 100

        # 生成建议
        if score <= 40:
            suggestion = "状态良好，继续保持！"
        elif score <= 60:
            suggestion = "有些疲劳，注意控制强度"
        elif score <= 75:
            suggestion = "疲劳度较高，建议降低训练强度"
        else:
            suggestion = "身体需要休息，建议安排休息日"

        should_adjust = score > 75

        return FatigueResult(
            score=score,
            suggestion=suggestion,
            should_adjust=should_adjust,
        )
