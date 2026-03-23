"""SQLite 数据库操作"""
import sqlite3
import os
from datetime import datetime, date, timedelta
from typing import Optional
from .models import UserProfile, CheckinRecord, TrainingPlan

DB_DIR = os.path.join("data", "astrbot_plugin_fitness")
DB_PATH = os.path.join(DB_DIR, "fitness.db")


def get_conn() -> sqlite3.Connection:
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库表"""
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                nickname TEXT DEFAULT '',
                height_cm REAL DEFAULT 0,
                weight_kg REAL DEFAULT 0,
                age INTEGER DEFAULT 0,
                gender TEXT DEFAULT '',
                fitness_goal TEXT DEFAULT '',
                body_condition TEXT DEFAULT '',
                health_notes TEXT DEFAULT '',
                equipment TEXT DEFAULT '',
                has_supplements INTEGER DEFAULT 0,
                supplement_details TEXT DEFAULT '',
                training_experience TEXT DEFAULT '',
                training_frequency TEXT DEFAULT '',
                weak_parts TEXT DEFAULT '',
                focus_parts TEXT DEFAULT '',
                diet_habit TEXT DEFAULT '',
                meals_per_day INTEGER DEFAULT 0,
                protein_intake TEXT DEFAULT '',
                daily_activity TEXT DEFAULT '',
                ai_analysis TEXT DEFAULT '',
                wake_time TEXT DEFAULT '07:00',
                sleep_time TEXT DEFAULT '23:00',
                preferred_workout_time TEXT DEFAULT '18:00',
                reminder_time TEXT DEFAULT '17:30',
                level INTEGER DEFAULT 1,
                exp INTEGER DEFAULT 0,
                quest_days INTEGER DEFAULT 0,
                quest_progress INTEGER DEFAULT 0,
                current_status TEXT DEFAULT 'normal',
                status_note TEXT DEFAULT '',
                onboarding_step TEXT DEFAULT 'started',
                created_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT '',
                PRIMARY KEY (user_id, group_id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS checkin_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                checkin_date TEXT NOT NULL,
                workout_type TEXT DEFAULT '',
                workout_detail TEXT DEFAULT '',
                duration_min INTEGER DEFAULT 0,
                calories_est INTEGER DEFAULT 0,
                feeling TEXT DEFAULT '',
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS training_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                plan_date TEXT NOT NULL,
                workout_type TEXT DEFAULT '',
                workout_detail TEXT DEFAULT '',
                intensity TEXT DEFAULT 'normal',
                is_rest_day INTEGER DEFAULT 0,
                adjusted INTEGER DEFAULT 0,
                adjust_reason TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            )
        """)
        conn.commit()

        # 数据库迁移：为旧表添加新字段（已存在则忽略）
        migrate_columns = [
            ("training_experience", "TEXT DEFAULT ''"),
            ("training_frequency", "TEXT DEFAULT ''"),
            ("weak_parts", "TEXT DEFAULT ''"),
            ("focus_parts", "TEXT DEFAULT ''"),
            ("diet_habit", "TEXT DEFAULT ''"),
            ("meals_per_day", "INTEGER DEFAULT 0"),
            ("protein_intake", "TEXT DEFAULT ''"),
            ("daily_activity", "TEXT DEFAULT ''"),
            ("ai_analysis", "TEXT DEFAULT ''"),
        ]
        for col_name, col_type in migrate_columns:
            try:
                c.execute(f"ALTER TABLE user_profiles ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass  # 列已存在
        conn.commit()
    finally:
        conn.close()


# ========== 用户档案操作 ==========

def get_profile(user_id: str, group_id: str) -> Optional[UserProfile]:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM user_profiles WHERE user_id=? AND group_id=?",
            (user_id, group_id)
        ).fetchone()
        if not row:
            return None
        p = UserProfile(user_id=row["user_id"], group_id=row["group_id"])
        for f in ["nickname","height_cm","weight_kg","age","gender","fitness_goal",
                  "body_condition","health_notes","equipment","supplement_details",
                  "training_experience","training_frequency","weak_parts","focus_parts",
                  "diet_habit","meals_per_day","protein_intake","daily_activity","ai_analysis",
                  "wake_time","sleep_time","preferred_workout_time","reminder_time",
                  "level","exp","quest_days","quest_progress",
                  "current_status","status_note","onboarding_step","created_at","updated_at"]:
            setattr(p, f, row[f])
        p.has_supplements = bool(row["has_supplements"])
        return p
    finally:
        conn.close()


def save_profile(p: UserProfile):
    now = datetime.now().isoformat()
    if not p.created_at:
        p.created_at = now
    p.updated_at = now
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO user_profiles (
                user_id, group_id, nickname, height_cm, weight_kg,
                age, gender, fitness_goal, body_condition, health_notes,
                equipment, has_supplements, supplement_details,
                training_experience, training_frequency, weak_parts, focus_parts,
                diet_habit, meals_per_day, protein_intake, daily_activity, ai_analysis,
                wake_time, sleep_time, preferred_workout_time, reminder_time,
                level, exp, quest_days, quest_progress,
                current_status, status_note, onboarding_step,
                created_at, updated_at
            ) VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
        """, (
            p.user_id, p.group_id, p.nickname, p.height_cm, p.weight_kg,
            p.age, p.gender, p.fitness_goal, p.body_condition, p.health_notes,
            p.equipment, int(p.has_supplements), p.supplement_details,
            p.training_experience, p.training_frequency, p.weak_parts, p.focus_parts,
            p.diet_habit, p.meals_per_day, p.protein_intake, p.daily_activity, p.ai_analysis,
            p.wake_time, p.sleep_time, p.preferred_workout_time, p.reminder_time,
            p.level, p.exp, p.quest_days, p.quest_progress,
            p.current_status, p.status_note, p.onboarding_step,
            p.created_at, p.updated_at
        ))
        conn.commit()
    finally:
        conn.close()


# ========== 打卡记录操作 ==========

def add_checkin(record: CheckinRecord):
    record.created_at = datetime.now().isoformat()
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO checkin_records (user_id, group_id, checkin_date, workout_type,
                workout_detail, duration_min, calories_est, feeling, note, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            record.user_id, record.group_id, record.checkin_date, record.workout_type,
            record.workout_detail, record.duration_min, record.calories_est,
            record.feeling, record.note, record.created_at
        ))
        conn.commit()
    finally:
        conn.close()


def get_today_checkin(user_id: str, group_id: str) -> Optional[CheckinRecord]:
    today = date.today().isoformat()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM checkin_records WHERE user_id=? AND group_id=? AND checkin_date=?",
            (user_id, group_id, today)
        ).fetchone()
        if not row:
            return None
        r = CheckinRecord()
        for f in ["id","user_id","group_id","checkin_date","workout_type","workout_detail",
                  "duration_min","calories_est","feeling","note","created_at"]:
            setattr(r, f, row[f])
        return r
    finally:
        conn.close()


def get_checkin_streak(user_id: str, group_id: str) -> int:
    """计算连续打卡天数"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT DISTINCT checkin_date FROM checkin_records WHERE user_id=? AND group_id=? ORDER BY checkin_date DESC",
            (user_id, group_id)
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return 0
    streak = 0
    check_date = date.today()
    for row in rows:
        d = date.fromisoformat(row["checkin_date"])
        if d == check_date:
            streak += 1
            check_date -= timedelta(days=1)
        elif d == check_date - timedelta(days=1):
            # 今天还没打卡，从昨天开始算
            if streak == 0:
                check_date = d
                streak = 1
                check_date -= timedelta(days=1)
            else:
                break
        else:
            break
    return streak


def get_checkin_history(user_id: str, group_id: str, days: int = 30) -> list:
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM checkin_records WHERE user_id=? AND group_id=? AND checkin_date>=? ORDER BY checkin_date DESC",
            (user_id, group_id, since)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ========== 训练计划操作 ==========

def save_plan(plan: TrainingPlan):
    plan.created_at = datetime.now().isoformat()
    conn = get_conn()
    try:
        # 先删除同日期的旧计划
        conn.execute(
            "DELETE FROM training_plans WHERE user_id=? AND group_id=? AND plan_date=?",
            (plan.user_id, plan.group_id, plan.plan_date)
        )
        conn.execute("""
            INSERT INTO training_plans (user_id, group_id, plan_date, workout_type,
                workout_detail, intensity, is_rest_day, adjusted, adjust_reason, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            plan.user_id, plan.group_id, plan.plan_date, plan.workout_type,
            plan.workout_detail, plan.intensity, int(plan.is_rest_day),
            int(plan.adjusted), plan.adjust_reason, plan.created_at
        ))
        conn.commit()
    finally:
        conn.close()


def get_today_plan(user_id: str, group_id: str) -> Optional[TrainingPlan]:
    today = date.today().isoformat()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM training_plans WHERE user_id=? AND group_id=? AND plan_date=?",
            (user_id, group_id, today)
        ).fetchone()
        if not row:
            return None
        t = TrainingPlan()
        for f in ["id","user_id","group_id","plan_date","workout_type","workout_detail",
                  "intensity","adjust_reason","created_at"]:
            setattr(t, f, row[f])
        t.is_rest_day = bool(row["is_rest_day"])
        t.adjusted = bool(row["adjusted"])
        return t
    finally:
        conn.close()


def get_upcoming_plans(user_id: str, group_id: str, days: int = 7) -> list:
    """获取从今天起未来N天的训练计划"""
    today = date.today()
    end = (today + timedelta(days=days)).isoformat()
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM training_plans WHERE user_id=? AND group_id=? AND plan_date>=? AND plan_date<=? ORDER BY plan_date ASC",
            (user_id, group_id, today.isoformat(), end)
        ).fetchall()
        result = []
        for row in rows:
            t = TrainingPlan()
            for f in ["id","user_id","group_id","plan_date","workout_type","workout_detail",
                      "intensity","adjust_reason","created_at"]:
                setattr(t, f, row[f])
            t.is_rest_day = bool(row["is_rest_day"])
            t.adjusted = bool(row["adjusted"])
            result.append(t)
        return result
    finally:
        conn.close()


def get_all_profiles_in_group(group_id: str) -> list:
    """获取群内所有用户档案（用于批量提醒）"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM user_profiles WHERE group_id=? AND onboarding_step='complete'",
            (group_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_active_profiles() -> list:
    """获取所有已完成建档的用户（用于定时任务）"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM user_profiles WHERE onboarding_step='complete'"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_profiles_by_reminder_time(reminder_time: str) -> list:
    """获取指定提醒时间的所有活跃用户（精确匹配）"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM user_profiles WHERE onboarding_step='complete' AND reminder_time=?",
            (reminder_time,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
