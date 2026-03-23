"""饮食打卡模块"""
from datetime import date, timedelta
from . import database as db
from .models import DietRecord


class DietLogger:
    """饮食打卡管理器"""

    def log_meal(
        self, user_id: str, group_id: str,
        description: str, meal_type: str,
        calories_est: int, protein_est: float,
        log_date: str = ""
    ) -> DietRecord:
        """记录一餐饮食"""
        record = DietRecord(
            user_id=user_id,
            group_id=group_id,
            log_date=log_date or date.today().isoformat(),
            meal_type=meal_type,
            description=description,
            calories_est=calories_est,
            protein_est=protein_est,
        )
        db.add_diet_record(record)
        return record

    def get_daily_summary(self, user_id: str, group_id: str, log_date: str = "") -> dict:
        """获取某日饮食汇总：总热量、总蛋白质、各餐明细"""
        target_date = log_date or date.today().isoformat()
        records = db.get_diet_records_by_date(user_id, group_id, target_date)

        total_cal = sum(r.calories_est for r in records)
        total_protein = sum(r.protein_est for r in records)

        meals = []
        for r in records:
            meals.append({
                "meal_type": r.meal_type,
                "description": r.description,
                "calories": r.calories_est,
                "protein": r.protein_est,
            })

        return {
            "date": target_date,
            "total_calories": total_cal,
            "total_protein": round(total_protein, 1),
            "meal_count": len(records),
            "meals": meals,
        }

    def get_weekly_avg(self, user_id: str, group_id: str) -> dict:
        """计算最近 7 天平均每日热量和蛋白质"""
        today = date.today()
        daily_totals = []

        for i in range(7):
            d = (today - timedelta(days=i)).isoformat()
            records = db.get_diet_records_by_date(user_id, group_id, d)
            if records:
                cal = sum(r.calories_est for r in records)
                pro = sum(r.protein_est for r in records)
                daily_totals.append({"calories": cal, "protein": pro})

        if not daily_totals:
            return {"avg_calories": 0, "avg_protein": 0.0, "days_with_data": 0}

        avg_cal = sum(d["calories"] for d in daily_totals) / len(daily_totals)
        avg_pro = sum(d["protein"] for d in daily_totals) / len(daily_totals)

        return {
            "avg_calories": round(avg_cal),
            "avg_protein": round(avg_pro, 1),
            "days_with_data": len(daily_totals),
        }
