from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from feature.novel.service import require_user_on_novel
from database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from feature.user.service import require_user
from models.report import Report
from models.user import User
from .schema import ReportCreate
from uuid import UUID

router_report = APIRouter(prefix="/report", tags=["report"])

@router_report.post("/{novel_id}")
async def create_report(report_data: ReportCreate, data: list = Depends(require_user_on_novel), db: AsyncSession = Depends(get_db)):
    new_report = Report(
        report_reason=report_data.reason,
        report_novel_id=data[0],
        report_type="novel",
        report_user_id=data[1]
    )
    db.add(new_report)
    await db.commit()
    await db.refresh(new_report)
    return {"message": "Report created successfully", "report_id": new_report.report_id}

@router_report.put("/{report_id}")
async def update_report(report_id: UUID, report_data: ReportCreate, current_user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    report = await db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.report_user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized to update this report")
    report.report_reason = report_data.reason
    await db.commit()
    await db.refresh(report)
    return {"message": "Report updated successfully", "report": report}

@router_report.get("/")
async def get_reports(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
):
    size = 10
    offset_value = (page - 1) * size
    
    query = select(Report).offset(offset_value).limit(size)
    result = await db.execute(query)
    reports = result.scalars().all()
    
    count_query = select(func.count()).select_from(Report)
    total_items = await db.scalar(count_query) or 0
    
    total_pages = (total_items + size - 1) // size if total_items > 0 else 0

    return {
        "items": reports,
        "page": page,
        "size": size,
        "total_items": total_items,
        "total_pages": total_pages
    }

@router_report.delete("/{report_id}")
async def delete_report(report_id: UUID, current_user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    report = await db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.report_user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this report")
    await db.delete(report)
    await db.commit()
    return {"message": "Report deleted successfully"}

@router_report.get("/mine")
async def get_reports(
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
):
    size = 10
    offset_value = (page - 1) * size
    
    query = select(Report).offset(offset_value).limit(size)
    result = await db.execute(select(Report).where(Report.report_user_id == current_user.user_id))
    reports = result.scalars().all()

    count_query = select(func.count()).select_from(Report)
    total_items = await db.scalar(count_query) or 0
    
    total_pages = (total_items + size - 1) // size if total_items > 0 else 0

    return {
        "items": reports,
        "page": page,
        "size": size,
        "total_items": total_items,
        "total_pages": total_pages
    }
