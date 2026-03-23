"""数据模型定义"""
from dataclasses import dataclass


@dataclass
class UserProfile:
    """用户个人档案"""
    user_id: str           # 平台用户ID
    group_id: str          # 群组ID
    nickname: str = ""
    height_cm: float = 0.0
    weight_kg: float = 0.0
    age: int = 0
    gender: str = ""       # male/female
    fitness_goal: str = "" # 增肌/减脂/塑形/维持健康
    body_condition: str = "" # 体质描述：偏瘦/正常/偏胖/肥胖
    health_notes: str = ""   # 健康备注：伤病、慢性病等
    
    # 训练背景
    training_experience: str = ""  # 训练经验：零基础/初学者(0-6月)/有基础(6月-2年)/进阶(2年+)
    training_frequency: str = ""   # 期望训练频率：每周几次
    weak_parts: str = ""           # 薄弱部位，逗号分隔
    focus_parts: str = ""          # 重点想练的部位，逗号分隔

    # 饮食与生活
    diet_habit: str = ""           # 饮食习惯：正常饮食/高蛋白/素食/节食/不规律
    meals_per_day: int = 0         # 每日餐数
    protein_intake: str = ""       # 蛋白质摄入评估：充足/一般/不足/不清楚
    daily_activity: str = ""       # 日常活动量：久坐/轻度活动/中度活动/重体力

    # 器材与补剂
    equipment: str = ""      # 拥有的健身器材，逗号分隔
    has_supplements: bool = False
    supplement_details: str = "" # 补剂详情：乳清蛋白粉、肌酸等

    # AI 综合分析
    ai_analysis: str = ""    # AI 建档完成后的综合分析与训练方向建议
    
    # 作息
    wake_time: str = "07:00"
    sleep_time: str = "23:00"
    preferred_workout_time: str = "18:00"  # 偏好锻炼时间
    reminder_time: str = "17:30"           # 提醒时间
    
    # RPG 游戏化
    level: int = 1                   # 等级
    exp: int = 0                     # 经验值
    quest_days: int = 0              # 闯关天数: 3/7/30
    quest_progress: int = 0          # 当前闯关进度天数
    
    # 状态
    current_status: str = "normal"  # normal/sick/injured/tired/rest
    status_note: str = ""           # 状态备注
    onboarding_step: str = "started" # 建档进度
    
    created_at: str = ""
    updated_at: str = ""


@dataclass
class CheckinRecord:
    """打卡记录"""
    id: int = 0
    user_id: str = ""
    group_id: str = ""
    checkin_date: str = ""     # YYYY-MM-DD
    workout_type: str = ""     # 训练类型：力量/有氧/拉伸休息
    workout_detail: str = ""   # 具体内容
    duration_min: int = 0      # 时长（分钟）
    calories_est: int = 0      # 估算消耗大卡
    feeling: str = ""          # 感受：轻松/适中/吃力/很累
    note: str = ""
    created_at: str = ""


@dataclass 
class TrainingPlan:
    """训练计划"""
    id: int = 0
    user_id: str = ""
    group_id: str = ""
    plan_date: str = ""        # YYYY-MM-DD
    workout_type: str = ""
    workout_detail: str = ""   # 详细训练内容
    intensity: str = "normal"  # low/normal/high
    is_rest_day: bool = False
    adjusted: bool = False     # 是否被动态调整过
    adjust_reason: str = ""
    created_at: str = ""
