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


PROFILE_CYCLE_TEMPLATES = {
    "增肌_male": [
        {"type": "力量", "focus": "推胸肩三头"},
        {"type": "力量", "focus": "拉背二头"},
        {"type": "力量", "focus": "下肢力量"},
        {"type": "有氧", "focus": "低强度有氧"},
        {"type": "力量", "focus": "胸肩三头"},
        {"type": "力量", "focus": "背二头"},
        {"type": "休息", "focus": "休息日"},
    ],
    "增肌_female": [
        {"type": "力量", "focus": "臀腿"},
        {"type": "力量", "focus": "背肩体态"},
        {"type": "混合", "focus": "核心有氧"},
        {"type": "休息", "focus": "休息日"},
        {"type": "力量", "focus": "臀腿强化"},
        {"type": "力量", "focus": "上肢塑形"},
        {"type": "拉伸", "focus": "拉伸恢复"},
    ],
    "减脂_male": [
        {"type": "混合", "focus": "全身循环"},
        {"type": "有氧", "focus": "中强度有氧"},
        {"type": "力量", "focus": "推胸肩三头"},
        {"type": "有氧", "focus": "HIIT"},
        {"type": "力量", "focus": "下肢力量"},
        {"type": "混合", "focus": "核心有氧"},
        {"type": "休息", "focus": "休息日"},
    ],
    "减脂_female": [
        {"type": "力量", "focus": "臀腿"},
        {"type": "有氧", "focus": "中强度有氧"},
        {"type": "力量", "focus": "背肩体态"},
        {"type": "混合", "focus": "核心有氧"},
        {"type": "力量", "focus": "臀腿强化"},
        {"type": "有氧", "focus": "低强度有氧"},
        {"type": "休息", "focus": "休息日"},
    ],
    "default_male": [
        {"type": "力量", "focus": "推胸肩三头"},
        {"type": "有氧", "focus": "有氧训练"},
        {"type": "力量", "focus": "拉背二头"},
        {"type": "拉伸", "focus": "拉伸恢复"},
        {"type": "力量", "focus": "下肢力量"},
        {"type": "混合", "focus": "核心有氧"},
        {"type": "休息", "focus": "休息日"},
    ],
    "default_female": [
        {"type": "力量", "focus": "臀腿"},
        {"type": "有氧", "focus": "有氧训练"},
        {"type": "力量", "focus": "背肩体态"},
        {"type": "拉伸", "focus": "拉伸恢复"},
        {"type": "混合", "focus": "核心有氧"},
        {"type": "力量", "focus": "上肢塑形"},
        {"type": "休息", "focus": "休息日"},
    ],
}


# 动作模板库：focus area → 器材类别 → 具体动作（"序号.动作名 组数x次数"）
EXERCISE_TEMPLATES: dict[str, dict[str, str]] = {
    "推胸肩三头": {
        "健身房": "1.杠铃卧推 4组x8次 2.坐姿推肩 3组x10次 3.上斜哑铃卧推 3组x10次 4.侧平举 3组x15次 5.绳索下压 3组x12次",
        "家庭哑铃": "1.哑铃卧推 4组x10次 2.哑铃推肩 3组x10次 3.哑铃飞鸟 3组x12次 4.哑铃侧平举 3组x15次 5.哑铃臂屈伸 3组x12次",
        "纯徒手": "1.标准俯卧撑 4组x15次 2.宽距俯卧撑 3组x12次 3.倒立撑(靠墙) 3组x8次 4.窄距俯卧撑 3组x12次 5.臂屈伸(椅子) 3组x12次",
    },
    "拉背二头": {
        "健身房": "1.引体向上 4组x8次 2.坐姿划船 4组x10次 3.坐姿下拉 3组x10次 4.杠铃弯举 3组x10次 5.锤式弯举 3组x12次",
        "家庭哑铃": "1.哑铃划船 4组x10次 2.俯身飞鸟 3组x12次 3.哑铃耸肩 3组x12次 4.哑铃弯举 3组x12次 5.锤式弯举 3组x12次",
        "纯徒手": "1.反手引体向上 4组x8次 2.桌子反向划船 4组x10次 3.俯卧挺身 3组x15次 4.毛巾弯举 3组x15次 5.超人式 3组x12次",
    },
    "胸肩三头": {
        "健身房": "1.上斜杠铃卧推 4组x8次 2.哑铃推肩 3组x10次 3.龙门架夹胸 3组x12次 4.侧平举 4组x15次 5.绳索下压 3组x12次",
        "家庭哑铃": "1.上斜哑铃卧推 4组x10次 2.哑铃推肩 3组x10次 3.哑铃飞鸟 3组x12次 4.哑铃侧平举 4组x15次 5.窄距俯卧撑 3组x10次",
        "纯徒手": "1.宽距俯卧撑 4组x15次 2.倒立撑(靠墙) 3组x8次 3.钻石俯卧撑 3组x10次 4.臂屈伸(椅子) 3组x12次 5.平板支撑 3组x45秒",
    },
    "背二头": {
        "健身房": "1.坐姿下拉 4组x10次 2.杠铃划船 4组x8次 3.坐姿划船 3组x10次 4.杠铃弯举 3组x10次 5.牧师凳弯举 3组x12次",
        "家庭哑铃": "1.单臂哑铃划船 4组x10次 2.俯身飞鸟 3组x12次 3.哑铃耸肩 3组x12次 4.哑铃弯举 3组x12次 5.锤式弯举 3组x12次",
        "纯徒手": "1.桌子反向划船 4组x10次 2.俯卧挺身 4组x15次 3.超人式 3组x12次 4.毛巾弯举 3组x15次 5.平板支撑 3组x45秒",
    },
    "臀腿": {
        "健身房": "1.杠铃深蹲 4组x8次 2.臀推 4组x10次 3.罗马尼亚硬拉 3组x10次 4.腿举 3组x12次 5.臀外展 3组x15次",
        "家庭哑铃": "1.哑铃深蹲 4组x12次 2.哑铃臀桥 4组x12次 3.哑铃罗马尼亚硬拉 3组x10次 4.哑铃箭步蹲 3组x10次 5.侧卧蚌式 3组x15次",
        "纯徒手": "1.深蹲 4组x20次 2.臀桥 4组x20次 3.保加利亚分腿蹲 3组x10次 4.箭步蹲 3组x12次 5.侧卧蚌式 3组x20次",
    },
    "臀腿强化": {
        "健身房": "1.臀推 4组x8次 2.保加利亚分腿蹲 3组x10次 3.罗马尼亚硬拉 3组x10次 4.腿弯举 3组x12次 5.绳索后踢腿 3组x15次",
        "家庭哑铃": "1.哑铃臀桥 4组x12次 2.保加利亚分腿蹲 3组x10次 3.哑铃硬拉 3组x10次 4.单腿臀桥 3组x12次 5.提踵 3组x20次",
        "纯徒手": "1.单腿臀桥 4组x12次 2.保加利亚分腿蹲 3组x10次 3.深蹲跳 3组x12次 4.箭步蹲 3组x12次 5.提踵 3组x25次",
    },
    "背肩体态": {
        "健身房": "1.坐姿划船 4组x10次 2.坐姿下拉 3组x10次 3.面拉 3组x15次 4.哑铃侧平举 3组x15次 5.俯身飞鸟 3组x12次",
        "家庭哑铃": "1.哑铃划船 4组x10次 2.俯身飞鸟 3组x12次 3.哑铃侧平举 3组x15次 4.哑铃推肩 3组x10次 5.俯卧挺身 3组x15次",
        "纯徒手": "1.桌子反向划船 4组x10次 2.俯卧挺身 3组x15次 3.YTWL肩胛训练 3组x10次 4.靠墙天使 3组x12次 5.平板支撑 3组x45秒",
    },
    "上肢塑形": {
        "健身房": "1.坐姿推胸 3组x12次 2.坐姿划船 3组x12次 3.哑铃推肩 3组x10次 4.侧平举 3组x15次 5.绳索下压 3组x12次",
        "家庭哑铃": "1.哑铃卧推 3组x12次 2.哑铃划船 3组x12次 3.哑铃推肩 3组x10次 4.哑铃侧平举 3组x15次 5.哑铃弯举 3组x12次",
        "纯徒手": "1.标准俯卧撑 3组x12次 2.桌子反向划船 3组x10次 3.窄距俯卧撑 3组x10次 4.俯卧挺身 3组x15次 5.平板支撑 3组x45秒",
    },
    "核心有氧": {
        "健身房": "1.跑步机慢跑 15分钟 2.平板支撑 3组x45秒 3.卷腹 3组x15次 4.登山跑 3组x30秒 5.划船机 8分钟",
        "家庭哑铃": "1.开合跳 4组x30次 2.平板支撑 3组x45秒 3.卷腹 3组x15次 4.登山跑 3组x30秒 5.哑铃农夫走 3组x40秒",
        "纯徒手": "1.开合跳 4组x30次 2.平板支撑 3组x45秒 3.卷腹 3组x15次 4.登山跑 3组x30秒 5.死虫 3组x12次",
    },
    "全身循环": {
        "健身房": "1.杠铃深蹲 3组x10次 2.杠铃卧推 3组x10次 3.坐姿划船 3组x10次 4.壶铃摆荡 3组x15次 5.跑步机快走 15分钟",
        "家庭哑铃": "1.哑铃深蹲 3组x12次 2.哑铃卧推 3组x12次 3.哑铃划船 3组x12次 4.哑铃硬拉 3组x10次 5.开合跳 3组x30次",
        "纯徒手": "1.深蹲 3组x20次 2.俯卧撑 3组x12次 3.臀桥 3组x20次 4.登山跑 3组x30秒 5.开合跳 3组x30次",
    },
    # ===== 增肌模板 =====
    "胸/三头": {
        "健身房": "1.杠铃卧推 4组x8次 2.上斜哑铃卧推 3组x10次 3.龙门架夹胸 3组x12次 4.绳索下压 3组x12次 5.仰卧臂屈伸 3组x10次",
        "家庭哑铃": "1.哑铃卧推 4组x10次 2.哑铃飞鸟 3组x12次 3.俯卧撑 3组x15次 4.哑铃臂屈伸 3组x12次 5.窄距俯卧撑 3组x10次",
        "纯徒手": "1.标准俯卧撑 4组x15次 2.宽距俯卧撑 3组x12次 3.窄距俯卧撑 3组x12次 4.钻石俯卧撑 3组x10次 5.臂屈伸(椅子) 3组x12次",
    },
    "背/二头": {
        "健身房": "1.引体向上 4组x8次 2.杠铃划船 4组x8次 3.坐姿下拉 3组x10次 4.杠铃弯举 3组x10次 5.锤式弯举 3组x12次",
        "家庭哑铃": "1.哑铃划船 4组x10次 2.哑铃耸肩 3组x12次 3.俯身飞鸟 3组x12次 4.哑铃弯举 3组x12次 5.锤式弯举 3组x12次",
        "纯徒手": "1.反手引体向上 4组x8次 2.俯卧挺身 4组x15次 3.超人式 3组x12次 4.毛巾弯举 3组x15次 5.桌子反向划船 3组x10次",
    },
    "腿/肩": {
        "健身房": "1.杠铃深蹲 4组x8次 2.腿举 3组x10次 3.罗马尼亚硬拉 3组x10次 4.哑铃推肩 3组x10次 5.侧平举 3组x15次",
        "家庭哑铃": "1.哑铃深蹲 4组x12次 2.哑铃箭步蹲 3组x10次 3.哑铃硬拉 3组x10次 4.哑铃推肩 3组x10次 5.哑铃侧平举 3组x15次",
        "纯徒手": "1.深蹲 4组x20次 2.箭步蹲 3组x12次 3.保加利亚分腿蹲 3组x10次 4.倒立撑(靠墙) 3组x8次 5.侧平举(弹力带) 3组x15次",
    },
    "胸/背": {
        "健身房": "1.杠铃卧推 4组x8次 2.引体向上 4组x8次 3.哑铃飞鸟 3组x12次 4.坐姿划船 3组x10次 5.龙门架夹胸 3组x12次",
        "家庭哑铃": "1.哑铃卧推 4组x10次 2.哑铃划船 4组x10次 3.哑铃飞鸟 3组x12次 4.俯身飞鸟 3组x12次 5.俯卧撑 3组x15次",
        "纯徒手": "1.标准俯卧撑 4组x15次 2.桌子反向划船 4组x10次 3.宽距俯卧撑 3组x12次 4.俯卧挺身 3组x15次 5.超人式 3组x12次",
    },
    "腿/手臂": {
        "健身房": "1.杠铃深蹲 4组x8次 2.腿弯举 3组x10次 3.杠铃弯举 3组x10次 4.绳索下压 3组x12次 5.小腿提踵 3组x15次",
        "家庭哑铃": "1.哑铃深蹲 4组x12次 2.哑铃箭步蹲 3组x10次 3.哑铃弯举 3组x12次 4.哑铃臂屈伸 3组x12次 5.提踵 3组x20次",
        "纯徒手": "1.深蹲 4组x20次 2.箭步蹲 3组x12次 3.毛巾弯举 3组x15次 4.臂屈伸(椅子) 3组x12次 5.提踵 3组x25次",
    },
    # ===== 减脂模板 =====
    "全身力量+有氧": {
        "健身房": "1.杠铃深蹲 3组x10次 2.杠铃卧推 3组x10次 3.坐姿划船 3组x10次 4.跑步机快走 15分钟 5.波比跳 3组x8次",
        "家庭哑铃": "1.哑铃深蹲 3组x12次 2.哑铃卧推 3组x12次 3.哑铃划船 3组x12次 4.开合跳 3组x30次 5.波比跳 3组x8次",
        "纯徒手": "1.深蹲 3组x20次 2.俯卧撑 3组x15次 3.俯卧挺身 3组x15次 4.开合跳 3组x30次 5.波比跳 3组x8次",
    },
    "上肢力量": {
        "健身房": "1.杠铃卧推 4组x10次 2.坐姿下拉 3组x10次 3.哑铃推肩 3组x10次 4.绳索夹胸 3组x12次 5.杠铃弯举 3组x10次",
        "家庭哑铃": "1.哑铃卧推 4组x10次 2.哑铃划船 3组x12次 3.哑铃推肩 3组x10次 4.哑铃飞鸟 3组x12次 5.哑铃弯举 3组x12次",
        "纯徒手": "1.标准俯卧撑 4组x15次 2.桌子反向划船 3组x10次 3.倒立撑(靠墙) 3组x8次 4.宽距俯卧撑 3组x12次 5.毛巾弯举 3组x15次",
    },
    "下肢力量": {
        "健身房": "1.杠铃深蹲 4组x10次 2.腿举 3组x12次 3.罗马尼亚硬拉 3组x10次 4.腿弯举 3组x12次 5.小腿提踵 3组x15次",
        "家庭哑铃": "1.哑铃深蹲 4组x12次 2.哑铃箭步蹲 3组x10次 3.哑铃硬拉 3组x10次 4.哑铃提踵 3组x15次 5.臀桥 3组x15次",
        "纯徒手": "1.深蹲 4组x20次 2.箭步蹲 3组x12次 3.保加利亚分腿蹲 3组x10次 4.臀桥 3组x20次 5.提踵 3组x25次",
    },
    "HIIT": {
        "健身房": "1.波比跳 4组x10次 2.壶铃摆荡 4组x15次 3.战绳 4组x30秒 4.跳箱 4组x8次 5.冲刺跑 4组x20秒",
        "家庭哑铃": "1.波比跳 4组x10次 2.哑铃抓举 4组x10次 3.登山跑 4组x20次 4.哑铃摆荡 4组x15次 5.高抬腿 4组x30秒",
        "纯徒手": "1.波比跳 4组x10次 2.登山跑 4组x20次 3.高抬腿 4组x30秒 4.深蹲跳 4组x12次 5.俯卧撑跳 4组x8次",
    },
    # ===== 通用模板 =====
    "上肢": {
        "健身房": "1.杠铃卧推 4组x8次 2.引体向上 3组x8次 3.哑铃推肩 3组x10次 4.杠铃弯举 3组x10次 5.绳索下压 3组x12次",
        "家庭哑铃": "1.哑铃卧推 4组x10次 2.哑铃划船 3组x12次 3.哑铃推肩 3组x10次 4.哑铃弯举 3组x12次 5.哑铃臂屈伸 3组x12次",
        "纯徒手": "1.标准俯卧撑 4组x15次 2.桌子反向划船 3组x10次 3.倒立撑(靠墙) 3组x8次 4.窄距俯卧撑 3组x12次 5.臂屈伸(椅子) 3组x12次",
    },
    "下肢": {
        "健身房": "1.杠铃深蹲 4组x8次 2.罗马尼亚硬拉 3组x10次 3.腿举 3组x10次 4.腿弯举 3组x12次 5.小腿提踵 3组x15次",
        "家庭哑铃": "1.哑铃深蹲 4组x12次 2.哑铃硬拉 3组x10次 3.哑铃箭步蹲 3组x10次 4.臀桥 3组x15次 5.提踵 3组x20次",
        "纯徒手": "1.深蹲 4组x20次 2.箭步蹲 3组x12次 3.保加利亚分腿蹲 3组x10次 4.臀桥 3组x20次 5.提踵 3组x25次",
    },
    "全身": {
        "健身房": "1.杠铃深蹲 3组x8次 2.杠铃卧推 3组x8次 3.杠铃划船 3组x8次 4.哑铃推肩 3组x10次 5.杠铃硬拉 3组x6次",
        "家庭哑铃": "1.哑铃深蹲 3组x12次 2.哑铃卧推 3组x10次 3.哑铃划船 3组x10次 4.哑铃推肩 3组x10次 5.哑铃硬拉 3组x10次",
        "纯徒手": "1.深蹲 3组x20次 2.俯卧撑 3组x15次 3.俯卧挺身 3组x15次 4.倒立撑(靠墙) 3组x8次 5.臀桥 3组x20次",
    },
    # ===== 有氧/恢复模板 =====
    "低强度有氧": {
        "健身房": "1.跑步机快走 30分钟 2.椭圆机 15分钟 3.拉伸放松 10分钟",
        "家庭哑铃": "1.快走/慢跑 30分钟 2.开合跳 3组x20次 3.拉伸放松 10分钟",
        "纯徒手": "1.快走/慢跑 30分钟 2.开合跳 3组x20次 3.拉伸放松 10分钟",
    },
    "中强度有氧": {
        "健身房": "1.跑步机慢跑 25分钟 2.划船机 10分钟 3.椭圆机 10分钟 4.拉伸 5分钟",
        "家庭哑铃": "1.慢跑 25分钟 2.开合跳 4组x30次 3.高抬腿 3组x30秒 4.拉伸 5分钟",
        "纯徒手": "1.慢跑 25分钟 2.开合跳 4组x30次 3.高抬腿 3组x30秒 4.拉伸 5分钟",
    },
    "有氧训练": {
        "健身房": "1.跑步机慢跑 20分钟 2.椭圆机 15分钟 3.拉伸放松 10分钟",
        "家庭哑铃": "1.慢跑 20分钟 2.开合跳 3组x25次 3.高抬腿 3组x20秒 4.拉伸 10分钟",
        "纯徒手": "1.慢跑 20分钟 2.开合跳 3组x25次 3.高抬腿 3组x20秒 4.拉伸 10分钟",
    },
    "拉伸恢复": {
        "健身房": "1.泡沫轴放松 10分钟 2.全身拉伸 15分钟 3.瑜伽球放松 10分钟",
        "家庭哑铃": "1.全身拉伸 15分钟 2.瑜伽基础体式 15分钟 3.深呼吸放松 5分钟",
        "纯徒手": "1.全身拉伸 15分钟 2.瑜伽基础体式 15分钟 3.深呼吸放松 5分钟",
    },
}

# 去负荷动作模板：组数和次数减少约 40%
DELOAD_TEMPLATES: dict[str, dict[str, str]] = {
    "胸/三头": {
        "健身房": "1.杠铃卧推 2组x8次 2.上斜哑铃卧推 2组x8次 3.绳索下压 2组x10次",
        "家庭哑铃": "1.哑铃卧推 2组x8次 2.哑铃飞鸟 2组x10次 3.窄距俯卧撑 2组x10次",
        "纯徒手": "1.标准俯卧撑 2组x12次 2.窄距俯卧撑 2组x10次 3.臂屈伸(椅子) 2组x10次",
    },
    "背/二头": {
        "健身房": "1.引体向上 2组x6次 2.坐姿下拉 2组x8次 3.杠铃弯举 2组x8次",
        "家庭哑铃": "1.哑铃划船 2组x8次 2.俯身飞鸟 2组x10次 3.哑铃弯举 2组x10次",
        "纯徒手": "1.俯卧挺身 2组x12次 2.超人式 2组x10次 3.毛巾弯举 2组x12次",
    },
    "腿/肩": {
        "健身房": "1.杠铃深蹲 2组x8次 2.腿举 2组x8次 3.哑铃推肩 2组x8次",
        "家庭哑铃": "1.哑铃深蹲 2组x10次 2.哑铃箭步蹲 2组x8次 3.哑铃推肩 2组x8次",
        "纯徒手": "1.深蹲 2组x15次 2.箭步蹲 2组x10次 3.倒立撑(靠墙) 2组x6次",
    },
    "胸/背": {
        "健身房": "1.杠铃卧推 2组x8次 2.引体向上 2组x6次 3.坐姿划船 2组x8次",
        "家庭哑铃": "1.哑铃卧推 2组x8次 2.哑铃划船 2组x8次 3.俯卧撑 2组x12次",
        "纯徒手": "1.标准俯卧撑 2组x12次 2.桌子反向划船 2组x8次 3.俯卧挺身 2组x12次",
    },
    "腿/手臂": {
        "健身房": "1.杠铃深蹲 2组x8次 2.杠铃弯举 2组x8次 3.绳索下压 2组x10次",
        "家庭哑铃": "1.哑铃深蹲 2组x10次 2.哑铃弯举 2组x10次 3.哑铃臂屈伸 2组x10次",
        "纯徒手": "1.深蹲 2组x15次 2.毛巾弯举 2组x12次 3.臂屈伸(椅子) 2组x10次",
    },
    "全身力量+有氧": {
        "健身房": "1.杠铃深蹲 2组x8次 2.杠铃卧推 2组x8次 3.跑步机快走 10分钟",
        "家庭哑铃": "1.哑铃深蹲 2组x10次 2.哑铃卧推 2组x10次 3.开合跳 2组x20次",
        "纯徒手": "1.深蹲 2组x15次 2.俯卧撑 2组x12次 3.开合跳 2组x20次",
    },
    "上肢力量": {
        "健身房": "1.杠铃卧推 2组x8次 2.坐姿下拉 2组x8次 3.哑铃推肩 2组x8次",
        "家庭哑铃": "1.哑铃卧推 2组x8次 2.哑铃划船 2组x10次 3.哑铃推肩 2组x8次",
        "纯徒手": "1.标准俯卧撑 2组x12次 2.桌子反向划船 2组x8次 3.倒立撑(靠墙) 2组x6次",
    },
    "下肢力量": {
        "健身房": "1.杠铃深蹲 2组x8次 2.罗马尼亚硬拉 2组x8次 3.腿弯举 2组x10次",
        "家庭哑铃": "1.哑铃深蹲 2组x10次 2.哑铃箭步蹲 2组x8次 3.臀桥 2组x12次",
        "纯徒手": "1.深蹲 2组x15次 2.箭步蹲 2组x10次 3.臀桥 2组x15次",
    },
    "HIIT": {
        "健身房": "1.波比跳 2组x8次 2.壶铃摆荡 2组x10次 3.跳箱 2组x6次",
        "家庭哑铃": "1.波比跳 2组x8次 2.登山跑 2组x15次 3.高抬腿 2组x20秒",
        "纯徒手": "1.波比跳 2组x8次 2.登山跑 2组x15次 3.深蹲跳 2组x10次",
    },
    "上肢": {
        "健身房": "1.杠铃卧推 2组x8次 2.引体向上 2组x6次 3.哑铃推肩 2组x8次",
        "家庭哑铃": "1.哑铃卧推 2组x8次 2.哑铃划船 2组x10次 3.哑铃推肩 2组x8次",
        "纯徒手": "1.标准俯卧撑 2组x12次 2.桌子反向划船 2组x8次 3.倒立撑(靠墙) 2组x6次",
    },
    "下肢": {
        "健身房": "1.杠铃深蹲 2组x8次 2.罗马尼亚硬拉 2组x8次 3.腿举 2组x8次",
        "家庭哑铃": "1.哑铃深蹲 2组x10次 2.哑铃硬拉 2组x8次 3.哑铃箭步蹲 2组x8次",
        "纯徒手": "1.深蹲 2组x15次 2.箭步蹲 2组x10次 3.臀桥 2组x15次",
    },
    "全身": {
        "健身房": "1.杠铃深蹲 2组x6次 2.杠铃卧推 2组x6次 3.杠铃划船 2组x6次",
        "家庭哑铃": "1.哑铃深蹲 2组x10次 2.哑铃卧推 2组x8次 3.哑铃划船 2组x8次",
        "纯徒手": "1.深蹲 2组x15次 2.俯卧撑 2组x12次 3.俯卧挺身 2组x12次",
    },
    "低强度有氧": {
        "健身房": "1.跑步机快走 20分钟 2.拉伸放松 10分钟",
        "家庭哑铃": "1.快走 20分钟 2.拉伸放松 10分钟",
        "纯徒手": "1.快走 20分钟 2.拉伸放松 10分钟",
    },
    "中强度有氧": {
        "健身房": "1.跑步机慢跑 15分钟 2.拉伸 5分钟",
        "家庭哑铃": "1.慢跑 15分钟 2.拉伸 5分钟",
        "纯徒手": "1.慢跑 15分钟 2.拉伸 5分钟",
    },
    "有氧训练": {
        "健身房": "1.跑步机慢跑 15分钟 2.椭圆机 10分钟 3.拉伸 5分钟",
        "家庭哑铃": "1.慢跑 15分钟 2.开合跳 2组x20次 3.拉伸 5分钟",
        "纯徒手": "1.慢跑 15分钟 2.开合跳 2组x20次 3.拉伸 5分钟",
    },
    "拉伸恢复": {
        "健身房": "1.泡沫轴放松 8分钟 2.全身拉伸 10分钟",
        "家庭哑铃": "1.全身拉伸 10分钟 2.深呼吸放松 5分钟",
        "纯徒手": "1.全身拉伸 10分钟 2.深呼吸放松 5分钟",
    },
}

# 有效器材类别
EQUIPMENT_CATEGORIES = ("健身房", "家庭哑铃", "纯徒手")

DELOAD_FOCUS_FALLBACKS = {
    "推胸肩三头": "上肢",
    "拉背二头": "上肢",
    "胸肩三头": "胸/三头",
    "背二头": "背/二头",
    "臀腿": "下肢力量",
    "臀腿强化": "下肢力量",
    "背肩体态": "上肢力量",
    "上肢塑形": "上肢力量",
    "核心有氧": "全身力量+有氧",
    "全身循环": "全身力量+有氧",
}


def _resolve_equipment_category(equipment: str) -> str:
    """将用户的 equipment 字段映射到三个标准类别之一"""
    if not equipment:
        return "纯徒手"
    eq = equipment.lower()
    if "健身房" in equipment or "gym" in eq:
        return "健身房"
    if "哑铃" in equipment or "dumbbell" in eq:
        return "家庭哑铃"
    return "纯徒手"


def _get_workout_detail(focus: str, equipment_category: str, intensity: str) -> str:
    """根据 focus area、器材类别和强度返回具体动作字符串

    intensity == "low" 时使用 DELOAD_TEMPLATES，否则使用 EXERCISE_TEMPLATES。
    找不到模板时返回原始 focus 字符串作为 fallback。
    """
    templates = DELOAD_TEMPLATES if intensity == "low" else EXERCISE_TEMPLATES
    fallback_focus = DELOAD_FOCUS_FALLBACKS.get(focus, "") if intensity == "low" else ""
    focus_map = (
        templates.get(focus)
        or (DELOAD_TEMPLATES.get(fallback_focus) if fallback_focus else None)
        or EXERCISE_TEMPLATES.get(focus)
    )
    if not focus_map:
        return focus
    return focus_map.get(equipment_category, focus_map.get("纯徒手", focus))


def _normalize_goal(goal: str) -> str:
    if "增肌" in goal:
        return "增肌"
    if "减脂" in goal or "减重" in goal or "瘦" in goal:
        return "减脂"
    return "default"


def _normalize_gender(gender: str) -> str:
    gender = (gender or "").lower()
    if gender in ("female", "f", "女") or "女" in gender:
        return "female"
    if gender in ("male", "m", "男") or "男" in gender:
        return "male"
    return ""


def _select_cycle_template(profile) -> list[dict[str, str]]:
    goal = _normalize_goal(profile.fitness_goal if profile else "")
    gender = _normalize_gender(profile.gender if profile else "")
    if gender:
        template = PROFILE_CYCLE_TEMPLATES.get(f"{goal}_{gender}")
        if template:
            return template
    return CYCLE_TEMPLATES.get(goal, CYCLE_TEMPLATES["default"])


def _add_week_guidance(detail: str, week_idx: int, intensity: str) -> str:
    week_no = week_idx + 1
    if intensity == "low":
        tip = "本周去负荷，控制到平时约6成强度。"
    elif intensity == "high":
        tip = "主动作在动作标准前提下尝试小幅加重或多1-2次。"
    else:
        tip = "先稳定动作质量，保留1-2次余力。"
    return f"{detail} | 第{week_no}周目标：{tip}"


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
        template = _select_cycle_template(profile)
        equipment_cat = _resolve_equipment_category(profile.equipment if profile else "")

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
                detail = day_template["focus"] if is_rest else _get_workout_detail(
                    day_template["focus"], equipment_cat, week_intensity
                )
                if not is_rest:
                    detail = _add_week_guidance(detail, week_idx, week_intensity)
                plan = TrainingPlan(
                    user_id=user_id,
                    group_id=group_id,
                    plan_date=plan_date.isoformat(),
                    workout_type=day_template["type"],
                    workout_detail=detail,
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
        template = _select_cycle_template(profile)
        equipment_cat = _resolve_equipment_category(profile.equipment if profile else "")

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
            detail = day_template["focus"] if is_rest else _get_workout_detail(
                day_template["focus"], equipment_cat, "low"
            )

            plan = TrainingPlan(
                user_id=user_id,
                group_id=group_id,
                plan_date=plan_date.isoformat(),
                workout_type=day_template["type"],
                workout_detail=f"[去负荷] {detail}",
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
