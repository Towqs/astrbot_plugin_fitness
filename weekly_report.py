"""群周报模块"""
from datetime import date, timedelta
from . import database as db


class WeeklyReportGenerator:
    """群周报生成器"""

    def get_weekly_stats(self, group_id: str) -> dict:
        """获取本周统计：打卡人数、次数、打卡率、排行榜等"""
        today = date.today()
        # 本周一到今天
        monday = today - timedelta(days=today.weekday())
        monday_str = monday.isoformat()
        today_str = today.isoformat()

        # 获取群内所有已建档用户
        all_profiles = db.get_all_profiles_in_group(group_id)
        total_members = len(all_profiles)

        if total_members == 0:
            return {"empty": True, "total_members": 0}

        # 查询本周所有打卡记录
        conn = db.get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM checkin_records WHERE group_id=? AND checkin_date>=? AND checkin_date<=? ORDER BY checkin_date ASC",
                (group_id, monday_str, today_str)
            ).fetchall()
            checkins = [dict(r) for r in rows]
        finally:
            conn.close()

        total_checkins = len(checkins)
        checkin_users = set(c["user_id"] for c in checkins)
        checkin_rate = round(len(checkin_users) / total_members * 100) if total_members > 0 else 0

        # 连续打卡排行（前5）
        streak_ranking = []
        for p in all_profiles:
            uid = p["user_id"]
            streak = db.get_checkin_streak(uid, group_id)
            if streak > 0:
                streak_ranking.append({
                    "nickname": p.get("nickname", uid),
                    "streak": streak,
                })
        streak_ranking.sort(key=lambda x: x["streak"], reverse=True)
        streak_ranking = streak_ranking[:5]

        # 本周经验增长排行（前5）- 通过打卡次数近似
        user_checkin_count = {}
        for c in checkins:
            uid = c["user_id"]
            user_checkin_count[uid] = user_checkin_count.get(uid, 0) + 1

        exp_ranking = []
        uid_to_nick = {p["user_id"]: p.get("nickname", p["user_id"]) for p in all_profiles}
        for uid, count in user_checkin_count.items():
            exp_ranking.append({
                "nickname": uid_to_nick.get(uid, uid),
                "checkins": count,
            })
        exp_ranking.sort(key=lambda x: x["checkins"], reverse=True)
        exp_ranking = exp_ranking[:5]

        return {
            "empty": False,
            "total_members": total_members,
            "total_checkins": total_checkins,
            "checkin_users": len(checkin_users),
            "checkin_rate": checkin_rate,
            "streak_ranking": streak_ranking,
            "exp_ranking": exp_ranking,
            "week_start": monday_str,
            "week_end": today_str,
        }

    def format_report(self, stats: dict, ai_comment: str = "") -> str:
        """格式化周报文本"""
        if stats.get("empty", True):
            return "💪 本周群里还没有人打卡，新的一周从运动开始吧！"

        text = "📊 本周健身周报\n━━━━━━━━━━━━━━━\n"
        text += f"📅 {stats['week_start']} ~ {stats['week_end']}\n"
        text += f"👥 打卡人数: {stats['checkin_users']}/{stats['total_members']}\n"
        text += f"✅ 总打卡次数: {stats['total_checkins']}\n"
        text += f"📈 打卡率: {stats['checkin_rate']}%\n"

        if stats.get("streak_ranking"):
            text += "\n🔥 连续打卡排行:\n"
            for i, r in enumerate(stats["streak_ranking"], 1):
                medal = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i - 1]
                text += f"  {medal} {r['nickname']} - {r['streak']}天\n"

        if stats.get("exp_ranking"):
            text += "\n💪 本周活跃排行:\n"
            for i, r in enumerate(stats["exp_ranking"], 1):
                medal = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i - 1]
                text += f"  {medal} {r['nickname']} - {r['checkins']}次打卡\n"

        if ai_comment:
            text += f"\n━━━━━━━━━━━━━━━\n🏋️ 教练点评:\n{ai_comment}\n"

        return text

    def generate_report(self, group_id: str) -> dict:
        """聚合本周群数据，返回统计结果和格式化文本"""
        stats = self.get_weekly_stats(group_id)
        text = self.format_report(stats)
        return {"stats": stats, "text": text}
