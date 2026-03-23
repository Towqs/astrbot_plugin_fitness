"""进步检测模块"""
from datetime import date, timedelta
from . import database as db


class ProgressDetector:
    """进步检测器"""

    def detect_on_checkin(self, user_id: str, group_id: str) -> list[str]:
        """打卡时检测进步信号，返回进步提示消息列表

        对比最近 2 周 vs 前 2 周的数据
        """
        history = db.get_checkin_history(user_id, group_id, days=28)
        if len(history) < 4:
            return []

        # 按日期排序（升序）
        sorted_h = sorted(history, key=lambda r: r.get("checkin_date", ""))
        mid = len(sorted_h) // 2
        older = sorted_h[:mid]
        newer = sorted_h[mid:]

        signals = []
        changes = self._compare_periods(newer, older)

        for change in changes:
            if change["type"] == "duration_up":
                signals.append(f"📈 训练时长提升了 {change['pct']}%，继续保持！")
            elif change["type"] == "feeling_better":
                signals.append("😊 训练感受有所改善，身体在适应！")
            elif change["type"] == "frequency_up":
                signals.append(f"🔥 训练频率提升，最近两周打卡 {change['count']} 次！")

        return signals

    def generate_report(self, user_id: str, group_id: str) -> str:
        """生成详细进步报告"""
        history = db.get_checkin_history(user_id, group_id, days=28)
        if len(history) < 2:
            return "数据不足，继续打卡积累数据后再来查看进步报告～"

        sorted_h = sorted(history, key=lambda r: r.get("checkin_date", ""))
        mid = len(sorted_h) // 2
        older = sorted_h[:mid]
        newer = sorted_h[mid:]

        old_dur = sum(c.get("duration_min", 0) for c in older) / max(len(older), 1)
        new_dur = sum(c.get("duration_min", 0) for c in newer) / max(len(newer), 1)

        feeling_score = {"轻松": 4, "适中": 3, "吃力": 2, "很累": 1}
        old_feel = sum(feeling_score.get(c.get("feeling", ""), 2) for c in older) / max(len(older), 1)
        new_feel = sum(feeling_score.get(c.get("feeling", ""), 2) for c in newer) / max(len(newer), 1)

        streak = db.get_checkin_streak(user_id, group_id)

        report = "📊 进步报告\n━━━━━━━━━━━━━━━\n"
        report += f"📅 分析周期: 最近 {len(history)} 次打卡\n"
        report += f"⏱️ 平均时长: {round(old_dur)}min → {round(new_dur)}min"
        if new_dur > old_dur:
            report += f" ↑{round((new_dur-old_dur)/max(old_dur,1)*100)}%"
        report += "\n"
        report += f"💪 平均感受: {round(old_feel,1)} → {round(new_feel,1)}"
        if new_feel > old_feel:
            report += " (改善)"
        report += "\n"
        report += f"🔥 当前连续打卡: {streak}天\n"
        report += f"📈 近期频率: {len(newer)}次/{len(history)}次总计\n"

        # 体重趋势
        weight_records = db.get_weight_history(user_id, group_id, days=28)
        if len(weight_records) >= 2:
            sorted_w = sorted(weight_records, key=lambda r: r.get("record_date", ""))
            first_w = sorted_w[0]["weight_kg"]
            last_w = sorted_w[-1]["weight_kg"]
            diff = last_w - first_w
            report += f"⚖️ 体重变化: {first_w}kg → {last_w}kg ({'+' if diff > 0 else ''}{round(diff,1)}kg)\n"

        return report

    def _compare_periods(self, recent: list[dict], previous: list[dict]) -> list[dict]:
        """对比两个时间段的数据，返回变化指标"""
        changes = []

        # 平均时长对比
        old_dur = sum(c.get("duration_min", 0) for c in previous) / max(len(previous), 1)
        new_dur = sum(c.get("duration_min", 0) for c in recent) / max(len(recent), 1)
        if old_dur > 0 and (new_dur - old_dur) / old_dur >= 0.10:
            pct = round((new_dur - old_dur) / old_dur * 100)
            changes.append({"type": "duration_up", "pct": pct})

        # 感受对比
        feeling_score = {"轻松": 4, "适中": 3, "吃力": 2, "很累": 1}
        old_feel = sum(feeling_score.get(c.get("feeling", ""), 2) for c in previous) / max(len(previous), 1)
        new_feel = sum(feeling_score.get(c.get("feeling", ""), 2) for c in recent) / max(len(recent), 1)
        if new_feel - old_feel >= 0.5:
            changes.append({"type": "feeling_better"})

        # 频率对比
        if len(recent) > len(previous):
            changes.append({"type": "frequency_up", "count": len(recent)})

        return changes
