"""RPG 游戏化系统 - 等级、称号、经验值共享常量与工具函数"""

# 等级称号
LEVEL_TITLES = {
    1: "见习学徒",
    2: "青铜举铁将",
    3: "白银冲刺者",
    4: "黄金燃脂师",
    5: "铂金体魄王",
    6: "钻石战神",
    7: "大师·不灭意志",
    8: "宗师·钢铁之躯",
    9: "传说·无尽耐力",
    10: "神话·健身之神",
}

# 非线性升级曲线
LEVEL_EXP_TABLE = {
    1: 0,
    2: 100,
    3: 250,
    4: 500,
    5: 850,
    6: 1350,
    7: 2050,
    8: 3000,
    9: 4500,
    10: 6500,
}

def calc_level(exp: int) -> int:
    """经验值 → 等级"""
    lv = 1
    for level, required in sorted(LEVEL_EXP_TABLE.items()):
        if exp >= required:
            lv = level
        else:
            break
    return lv


def exp_for_next_level(current_level: int) -> int:
    """下一级所需总经验"""
    if current_level >= 10:
        return LEVEL_EXP_TABLE[10]
    return LEVEL_EXP_TABLE.get(current_level + 1, 9999)


def get_title(level: int) -> str:
    """获取等级对应称号"""
    return LEVEL_TITLES.get(level, f"Lv.{level}")
