"""温控监控业务规则：状态流转、字段校验、筛选口径与测点概览汇总都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "temperature"
WAYBILL_MODULE = "waybill"
REQUIRED_FIELDS = ["记录编号", "关联运单", "测点编号"]
STATUS_ORDER = ["正常", "偏高", "偏低", "已离线"]
ACTION_RULES = {"确认记录": "正常", "标记超限": "偏高", "重新采集": "正常"}
NEGATIVE_ACTIONS = []

# 概览排序：偏高优先且按偏高幅度降序，随后偏低、离线、正常；同档再按测点编号兜底。
_STATE_RANK = {"偏高": 0, "偏低": 1, "已离线": 2, "正常": 3}


def _to_number(value: Any) -> float | None:
    """把种子或登记进来的温度值转成数字；空值或非数字文本返回 None，不参与比对。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).strip()
        return float(text) if text else None
    except ValueError:
        return None


class TemperatureService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        waybill: str | None = None,
        point: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if waybill:
            rows = [row for row in rows if str(row.get("关联运单", "")) == waybill]
        if point:
            rows = [row for row in rows if str(row.get("测点编号", "")) == point]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

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

    def list_waybills(self) -> list[dict[str, Any]]:
        """运单下拉：以运单档案为主，补上只在温控记录里出现、档案缺失的运单号。

        has_data 标记该运单下是否有测点明细，概览对 has_data=False 的运单给出说明。
        """
        rows = store.rows(MODULE)
        record_waybills = {str(row.get("关联运单", "")).strip() for row in rows}
        record_waybills.discard("")

        options: list[dict[str, Any]] = []
        seen: set[str] = set()
        for waybill in store.rows(WAYBILL_MODULE):
            code = str(waybill.get("运单号", "")).strip()
            if not code or code in seen:
                continue
            seen.add(code)
            options.append({
                "waybill_no": code,
                "status": waybill.get("status"),
                "has_data": code in record_waybills,
            })
        for code in sorted(record_waybills - seen):
            options.append({"waybill_no": code, "status": None, "has_data": True})
        return options

    def point_overview(self, waybill_no: str | None = None) -> dict[str, Any]:
        """按运单汇总每个测点的实时温度与上下限：取同测点采集时间最新的一条。

        状态以记录上的状态为准（偏高/偏低/已离线/正常），偏高测点按超出上限的
        幅度排在最前面，其余按偏低、已离线、正常顺延，同档按测点编号兜底。
        """
        rows = store.rows(MODULE)
        if waybill_no is not None:
            rows = [row for row in rows if str(row.get("关联运单", "")) == waybill_no]

        latest_by_point: dict[str, dict[str, Any]] = {}
        record_count = 0
        for row in rows:
            point = str(row.get("测点编号", "")).strip()
            if not point:
                continue
            record_count += 1
            current = latest_by_point.get(point)
            if current is None or self._is_newer(row, current):
                latest_by_point[point] = row

        points = [self._build_point(row) for row in latest_by_point.values()]
        points.sort(key=lambda item: (
            _STATE_RANK.get(str(item["state"]), 9),
            -float(item["deviation"] or 0),
            str(item["point_no"]),
        ))

        summary = {
            "total": len(points),
            "high": sum(1 for item in points if item["state"] == "偏高"),
            "low": sum(1 for item in points if item["state"] == "偏低"),
            "offline": sum(1 for item in points if item["state"] == "已离线"),
            "normal": sum(1 for item in points if item["state"] == "正常"),
        }
        return {
            "waybill_no": waybill_no,
            "has_data": record_count > 0,
            "record_count": record_count,
            "points": points,
            "summary": summary,
        }

    @staticmethod
    def _is_newer(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
        """比较采集时间，时间相同（含无法比较）时以更大的记录 id 为最新。"""
        candidate_time = str(candidate.get("采集时间", ""))
        current_time = str(current.get("采集时间", ""))
        if candidate_time != current_time:
            return candidate_time > current_time
        return int(candidate.get("id", 0)) >= int(current.get("id", 0))

    @staticmethod
    def _build_point(row: dict[str, Any]) -> dict[str, Any]:
        state = str(row.get("status") or "正常")
        if state not in _STATE_RANK:
            state = "正常"

        current = _to_number(row.get("实时温度"))
        upper = _to_number(row.get("温度上限"))
        lower = _to_number(row.get("温度下限"))

        deviation: float | None = None
        if state == "偏高" and current is not None and upper is not None:
            deviation = round(current - upper, 2)
        elif state == "偏低" and current is not None and lower is not None:
            deviation = round(lower - current, 2)

        return {
            "entry_id": row.get("id"),
            "record_no": row.get("记录编号"),
            "point_no": str(row.get("测点编号", "")),
            "waybill_no": row.get("关联运单"),
            "current_temp": current,
            "temp_upper": upper,
            "temp_lower": lower,
            "collected_at": row.get("采集时间"),
            "state": state,
            "deviation": deviation,
        }
