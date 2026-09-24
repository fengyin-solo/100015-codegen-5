"""温控监控业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "temperature"
WAYBILL_MODULE = "waybill"
REQUIRED_FIELDS = ["记录编号", "关联运单", "测点编号"]
STATUS_ORDER = ["正常", "偏高", "偏低", "已离线"]
ACTION_RULES = {"确认记录": "正常", "标记超限": "偏高", "重新采集": "正常"}
NEGATIVE_ACTIONS = []


def _to_float(value: Any) -> float | None:
    """把实时温度、上下限转成数值；占位文本或空值返回 None，不参与幅度计算。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class TemperatureService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def summarize_waybill(self, waybill: str | None = None) -> dict[str, Any]:
        """按运单汇总测点温度概览：偏高测点按幅度从大到小排在最前。

        运单选项来自运单模块的全部运单号，再补上温控记录里出现过的关联运单；
        选中运单没有测点明细时返回说明文案，由前端展示而不是报错。
        """
        options: list[str] = []
        seen: set[str] = set()
        for row in store.rows(WAYBILL_MODULE):
            number = str(row.get("运单号") or "").strip()
            if number and number not in seen:
                seen.add(number)
                options.append(number)
        rows = store.rows(MODULE)
        for row in rows:
            number = str(row.get("关联运单") or "").strip()
            if number and number not in seen:
                seen.add(number)
                options.append(number)

        current = (waybill or "").strip() or (options[0] if options else "")

        points: list[dict[str, Any]] = []
        for row in rows:
            if str(row.get("关联运单") or "").strip() != current:
                continue
            status = str(row.get("status") or STATUS_ORDER[0])
            temp = _to_float(row.get("实时温度"))
            upper = _to_float(row.get("温度上限"))
            over_high = None
            if status == "偏高" and temp is not None and upper is not None:
                # 人工标记超限但当前读数已回落时，幅度按 0 展示，不出现负数
                over_high = max(round(temp - upper, 1), 0.0)
            points.append({
                "id": row.get("id"),
                "记录编号": row.get("记录编号"),
                "测点编号": row.get("测点编号"),
                "实时温度": row.get("实时温度"),
                "温度上限": row.get("温度上限"),
                "温度下限": row.get("温度下限"),
                "采集时间": row.get("采集时间"),
                "status": status,
                "偏高幅度": over_high,
            })
        points.sort(
            key=lambda point: (
                0 if point["status"] == "偏高" else 1,
                -(point["偏高幅度"] or 0),
                str(point["测点编号"] or ""),
            )
        )

        status_counts = {status: 0 for status in STATUS_ORDER}
        for point in points:
            if point["status"] in status_counts:
                status_counts[point["status"]] += 1

        message = None
        if not current:
            message = "暂无运单可查看，请先在运单管理中登记冷链运单"
        elif not points:
            message = f"运单 {current} 暂无测点明细，可先在下方登记温控记录"

        return {
            "waybill": current or None,
            "waybill_options": options,
            "total": len(points),
            "status_counts": status_counts,
            "points": points,
            "message": message,
        }

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"温控记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于温控监控可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"温控记录已{action}"
