"""温控监控接口：维护温控记录，覆盖确认记录、标记超限、重新采集等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.temperature import TemperatureService

router = APIRouter(prefix="/api/temperature", tags=["温控监控"])

service = TemperatureService()

LIST_FIELDS = ["记录编号", "关联运单", "测点编号", "实时温度", "温度上限", "温度下限", "采集时间"]
STATUSES = ["正常", "偏高", "偏低", "已离线"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号检索"),
    status: str | None = Query(default=None, description="正常、偏高、偏低、已离线"),
    waybill: str | None = Query(default=None, description="按关联运单精确过滤"),
    point: str | None = Query(default=None, description="按测点编号精确过滤，概览下钻时使用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按记录编号、状态、运单、测点过滤温控监控列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword,
        status=status,
        waybill=waybill,
        point=point,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/overview")
def point_overview(
    waybill: str | None = Query(default=None, description="运单号；不传时汇总全部运单的测点"),
) -> dict[str, Any]:
    """测点温度概览：按运单返回每个测点的最新温度、上下限、状态与偏高幅度排序结果。

    运单下没有测点明细时 has_data=False，由前端给出说明。
    """
    return service.point_overview(waybill)


@router.get("/waybills")
def list_waybills() -> dict[str, Any]:
    """概览运单下拉：列出全部运单以及各自是否存在测点明细。"""
    items = service.list_waybills()
    return {"items": items, "total": len(items)}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出温控监控清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "temperature", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条温控记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"温控记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条温控记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="温控记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条温控记录执行确认记录、标记超限、重新采集；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
