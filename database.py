"""SQLite 数据库操作"""
import sqlite3
import os
from datetime import datetime, date, timedelta
from typing import Optional
from .models import (
    UserProfile, CheckinRecord, TrainingPlan,
    UserPortrait, DietRecord, Achievement, TrainingCycle, WeightRecord
)

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

        c.execute("""
            CREATE TABLE IF NOT EXISTS user_portraits (
                user_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                weight_trend TEXT DEFAULT '',
                training_preference TEXT DEFAULT '',
                recovery_score INTEGER DEFAULT 50,
                progress_speed TEXT DEFAULT 'normal',
                fatigue_score INTEGER DEFAULT 0,
                weekly_feedback TEXT DEFAULT '',
                updated_at TEXT DEFAULT '',
                PRIMARY KEY (user_id, group_id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS diet_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                log_date TEXT NOT NULL,
                meal_type TEXT DEFAULT '',
                description TEXT DEFAULT '',
                calories_est INTEGER DEFAULT 0,
                protein_est REAL DEFAULT 0,
                created_at TEXT DEFAULT ''
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                user_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                achievement_id TEXT NOT NULL,
                unlocked_at TEXT DEFAULT '',
                PRIMARY KEY (user_id, group_id, achievement_id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS training_cycles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                total_weeks INTEGER DEFAULT 4,
                current_week INTEGER DEFAULT 1,
                cycle_type TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                deload_week INTEGER DEFAULT 0,
                created_at TEXT DEFAULT ''
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS weight_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                record_date TEXT NOT NULL,
                weight_kg REAL NOT NULL,
                source TEXT DEFAULT 'manual',
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


# ========== 用户画像操作 ==========

def save_portrait(p: UserPortrait):
    now = datetime.now().isoformat()
    p.updated_at = now
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO user_portraits (
                user_id, group_id, weight_trend, training_preference,
                recovery_score, progress_speed, fatigue_score,
                weekly_feedback, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            p.user_id, p.group_id, p.weight_trend, p.training_preference,
            p.recovery_score, p.progress_speed, p.fatigue_score,
            p.weekly_feedback, p.updated_at
        ))
        conn.commit()
    finally:
        conn.close()


def get_portrait(user_id: str, group_id: str) -> Optional[UserPortrait]:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM user_portraits WHERE user_id=? AND group_id=?",
            (user_id, group_id)
        ).fetchone()
        if not row:
            return None
        p = UserPortrait(user_id=row["user_id"], group_id=row["group_id"])
        for f in ["weight_trend", "training_preference", "recovery_score",
                  "progress_speed", "fatigue_score", "weekly_feedback", "updated_at"]:
            setattr(p, f, row[f])
        return p
    finally:
        conn.close()


# ========== 饮食记录操作 ==========

def add_diet_record(record: DietRecord):
    record.created_at = datetime.now().isoformat()
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO diet_records (
                user_id, group_id, log_date, meal_type,
                description, calories_est, protein_est, created_at
            ) VALUES (?,?,?,?,?,?,?,?)
        """, (
            record.user_id, record.group_id, record.log_date, record.meal_type,
            record.description, record.calories_est, record.protein_est,
            record.created_at
        ))
        conn.commit()
    finally:
        conn.close()


def get_diet_records_by_date(user_id: str, group_id: str, log_date: str) -> list[DietRecord]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM diet_records WHERE user_id=? AND group_id=? AND log_date=? ORDER BY created_at ASC",
            (user_id, group_id, log_date)
        ).fetchall()
        result = []
        for row in rows:
            r = DietRecord()
            for f in ["id", "user_id", "group_id", "log_date", "meal_type",
                      "description", "calories_est", "protein_est", "created_at"]:
                setattr(r, f, row[f])
            result.append(r)
        return result
    finally:
        conn.close()


# ========== 成就操作 ==========

def save_achievement(a: Achievement):
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO achievements (
                user_id, group_id, achievement_id, unlocked_at
            ) VALUES (?,?,?,?)
        """, (
            a.user_id, a.group_id, a.achievement_id, a.unlocked_at
        ))
        conn.commit()
    finally:
        conn.close()


def get_achievements(user_id: str, group_id: str) -> list[Achievement]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM achievements WHERE user_id=? AND group_id=? ORDER BY unlocked_at ASC",
            (user_id, group_id)
        ).fetchall()
        result = []
        for row in rows:
            a = Achievement()
            for f in ["user_id", "group_id", "achievement_id", "unlocked_at"]:
                setattr(a, f, row[f])
            result.append(a)
        return result
    finally:
        conn.close()


def is_achievement_unlocked(user_id: str, group_id: str, achievement_id: str) -> bool:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM achievements WHERE user_id=? AND group_id=? AND achievement_id=?",
            (user_id, group_id, achievement_id)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# ========== 训练周期操作 ==========

def save_training_cycle(cycle: TrainingCycle):
    cycle.created_at = datetime.now().isoformat()
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO training_cycles (
                user_id, group_id, start_date, end_date,
                total_weeks, current_week, cycle_type,
                status, deload_week, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            cycle.user_id, cycle.group_id, cycle.start_date, cycle.end_date,
            cycle.total_weeks, cycle.current_week, cycle.cycle_type,
            cycle.status, cycle.deload_week, cycle.created_at
        ))
        conn.commit()
    finally:
        conn.close()


def get_active_cycle(user_id: str, group_id: str) -> Optional[TrainingCycle]:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM training_cycles WHERE user_id=? AND group_id=? AND status='active' ORDER BY created_at DESC LIMIT 1",
            (user_id, group_id)
        ).fetchone()
        if not row:
            return None
        c = TrainingCycle()
        for f in ["id", "user_id", "group_id", "start_date", "end_date",
                  "total_weeks", "current_week", "cycle_type",
                  "status", "deload_week", "created_at"]:
            setattr(c, f, row[f])
        return c
    finally:
        conn.close()


def update_cycle_week(cycle_id: int, current_week: int):
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE training_cycles SET current_week=? WHERE id=?",
            (current_week, cycle_id)
        )
        conn.commit()
    finally:
        conn.close()


def complete_cycle(cycle_id: int):
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE training_cycles SET status='completed' WHERE id=?",
            (cycle_id,)
        )
        conn.commit()
    finally:
        conn.close()


# ========== 体重记录操作 ==========

def add_weight_record(record: WeightRecord):
    record.created_at = datetime.now().isoformat()
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO weight_records (
                user_id, group_id, record_date, weight_kg,
                source, created_at
            ) VALUES (?,?,?,?,?,?)
        """, (
            record.user_id, record.group_id, record.record_date,
            record.weight_kg, record.source, record.created_at
        ))
        conn.commit()
    finally:
        conn.close()


def get_weight_history(user_id: str, group_id: str, days: int = 30) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM weight_records WHERE user_id=? AND group_id=? AND record_date>=? ORDER BY record_date DESC",
            (user_id, group_id, since)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_total_checkins(user_id: str, group_id: str) -> int:
    """获取用户累计打卡总次数（高效 COUNT 查询）"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM checkin_records WHERE user_id=? AND group_id=?",
            (user_id, group_id)
        ).fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()
