"""训练完成度与训练负荷工具函数"""

VALID_PLAN_COMPLETIONS = {"completed", "partial", "off_plan", "unknown"}

FEELING_LOAD_FACTORS = {
    "轻松": 1.0,
    "适中": 1.3,
    "吃力": 1.7,
    "很累": 2.1,
}


def normalize_plan_completion(value: str) -> str:
    """规范化计划完成度枚举，未知值统一兜底为 unknown。"""
    completion = (value or "unknown").strip().lower()
    return completion if completion in VALID_PLAN_COMPLETIONS else "unknown"


def calculate_training_load(duration_min: int, feeling: str) -> int:
    """训练负荷 = 训练时长 * 感受强度系数。"""
    try:
        duration = int(duration_min)
    except (TypeError, ValueError):
        duration = 0
    if duration <= 0:
        return 0
    factor = FEELING_LOAD_FACTORS.get(feeling, FEELING_LOAD_FACTORS["适中"])
    return round(duration * factor)


def summarize_quality(records: list[dict]) -> dict:
    """汇总打卡记录中的负荷与计划完成率。"""
    total_load = sum(int(r.get("training_load") or 0) for r in records)
    completed = 0
    partial = 0
    off_plan = 0

    for record in records:
        completion = normalize_plan_completion(record.get("plan_completion", "unknown"))
        if completion == "completed":
            completed += 1
        elif completion == "partial":
            partial += 1
        elif completion == "off_plan":
            off_plan += 1

    denominator = completed + partial + off_plan
    completion_rate = round(completed / denominator * 100) if denominator else 0
    return {
        "total_training_load": total_load,
        "avg_training_load": round(total_load / max(len(records), 1), 1),
        "plan_completion_rate": completion_rate,
        "completed_count": completed,
        "partial_count": partial,
        "off_plan_count": off_plan,
        "completion_count": denominator,
    }


def format_quality_line(plan_completion: str, plan_match_note: str, training_load: int) -> str:
    """生成打卡反馈中的执行质量文本。"""
    completion = normalize_plan_completion(plan_completion)
    lines = [f"📊 训练负荷: {int(training_load or 0)}"]
    note = (plan_match_note or "").strip()
    if completion == "completed":
        lines.append("今日计划完成度：完成")
    elif completion == "partial":
        suffix = f" - {note}" if note else ""
        lines.append(f"今日计划完成度：部分完成{suffix}")
    elif completion == "off_plan":
        suffix = f" - {note}" if note else ""
        lines.append(f"今日计划完成度：未按计划{suffix}")
    return "\n".join(lines)
