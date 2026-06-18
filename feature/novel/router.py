import math
import shutil

from sqlalchemy.orm import joinedload,selectinload
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from feature.novel.schema import NovelBase
from feature.user.service import require_novel_owner_or_admin, require_unlocked_user
from database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from models.document import Document
from models.novel import Novel, Tag
from uuid import UUID
from feature.common.response import DocDetailResponse, MessageResponse, NovelContentResponse, NovelInfoResponse, NovelListItemResponse, NovelUpdateResponse, PaginatedDocResponse, PaginatedNovelResponse
import os

PDF_STORAGE_PATH = "local_storage/pdf/"
MARKDOWN_STORAGE_PATH = "local_storage/markdown/"
MARKDOWN_REVEAL_STORAGE_PATH = "local_storage/markdown_reveal/"
IMAGE_STORAGE_PATH = "local_storage/image/"
COVER_STORAGE_PATH = "local_storage/cover/"
IMAGE_SECONDARY_STORAGE_PATH = "local_storage/image_secondary/"

router_novel = APIRouter(prefix="/novel", tags=["novel"])


@router_novel.get("/",response_model=list[NovelListItemResponse])
async def novel_list(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Novel).order_by(Novel.novel_updatedat.desc()))
    novels = result.scalars().all()
    return novels

@router_novel.get("/list", response_model=PaginatedNovelResponse)
async def get_all_novels(
    # Default to page 1, and 5 items per page
    page: int = Query(1, ge=1, description="Page number"),
    db: AsyncSession = Depends(get_db)
):
    limit = 10
    # 1. Calculate how many items to skip
    skip = (page - 1) * limit

    # 2. Query for the actual novels (with limit and offset)
    query = (
        select(Novel)
        .options(selectinload(Novel.tags)) 
        .where(Novel.novel_isprivate == False)
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    novels = result.scalars().all()

    # 3. (Optional but highly recommended) Get the total count of novels
    # This helps your Angular frontend know how many pages exist!
    count_query = (
        select(func.count())
        .select_from(Novel)
        .where(Novel.novel_isprivate == False) # <--- THÊM ĐIỀU KIỆN NÀY VÀO ĐÂY
    )
    total_result = await db.execute(count_query)
    total_novels = total_result.scalar()

    total_pages = math.ceil(total_novels / limit) if total_novels else 0

    return {
        "data": novels,
        "meta": {
            "current_page": page,
            "items_per_page": limit,
            "total_novels": total_novels,
            "total_pages": total_pages
        }
    }


@router_novel.get("/tag/{tag_id}", response_model=list[NovelListItemResponse])
async def get_novels_by_tag(tag_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Novel).join(Novel.tags).where(Tag.tag_id == tag_id).order_by(Novel.novel_updatedat.desc()))
    novels = result.scalars().all()
    return novels

@router_novel.get("/tags/strict", response_model=PaginatedNovelResponse)
async def get_novels_by_all_tags(
    tag_ids: list[UUID] = Query(...), 
    page: int = Query(1, ge=1, description="Page number"),
    db: AsyncSession = Depends(get_db)
):
    num_tags = len(tag_ids)
    limit = 10
    skip = (page - 1) * limit

    # 1. Fetch the actual paginated novels
    query = (
        select(Novel)
        .join(Novel.tags)
        .where(
            
            Tag.tag_id.in_(tag_ids),
            Novel.novel_isprivate == False # <--- Gom chung điều kiện lọc vào đây
        )
        .options(selectinload(Novel.tags)) 
        .group_by(Novel.novel_id)
        .having(func.count(Tag.tag_id) == num_tags)
        .order_by(Novel.novel_updatedat.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    novels = result.scalars().all()
    
    # 2. Build a subquery to correctly count the total number of matches
    subquery = (
        select(Novel.novel_id)
        .join(Novel.tags)
        .where(
            Tag.tag_id.in_(tag_ids),
            Novel.novel_isprivate == False # <--- Gom chung điều kiện vào đây trước khi tạo subquery
        )
        .group_by(Novel.novel_id)
        .having(func.count(Tag.tag_id) == num_tags)
        .subquery() # <--- Đóng gói thành subquery ở bước cuối cùng
    )
    
    # Count how many rows the subquery returned
    count_query = (
        select(func.count())
        .select_from(subquery)
        # KHÔNG cần thêm .where(isprivate == False) ở đây nữa vì dữ liệu bên trong subquery đã "sạch" rồi
    )
    total_result = await db.execute(count_query)
    total_novels = total_result.scalar()

    # 3. Calculate total pages
    total_pages = math.ceil(total_novels / limit) if total_novels else 0

    # 4. Return the formatted response for Angular
    return {
        "data": novels,
        "meta": {
            "current_page": page,
            "items_per_page": limit,
            "total_novels": total_novels,
            "total_pages": total_pages
        }
    }


@router_novel.get("/content/{novel_id}", response_model=NovelContentResponse)
async def get_novel_by_id(novel_id: UUID, db: AsyncSession = Depends(get_db)):
    result  = await db.execute(select(Novel).where(Novel.novel_id == novel_id))
    novel = result.scalar_one_or_none()
    docresult  = await db.execute(select(Document).where(Document.doc_novel_id == novel_id))
    doc = docresult.scalars().one_or_none()
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")
    return {
        "novel_id": novel.novel_id,
        "novel_title": novel.novel_title,
        "novel_author": novel.novel_author,
        "novel_description": novel.novel_description,
        "novel_coverurl": novel.novel_coverurl,
        "novel_series": novel.novel_series,
        "document":
            {
                "doc_id": doc.doc_id,
                "doc_title": doc.doc_title,
                "doc_fileurl": doc.doc_fileurl,
                "doc_markdownurl": doc.doc_markdownurl,
                "doc_status": doc.doc_status,
                "doc_error": doc.doc_error,
            }
            if doc else None
    }


     
    
@router_novel.get("/info/{document_id}", response_model=NovelInfoResponse)
async def get_novel_by_document_id(document_id: UUID, db: AsyncSession = Depends(get_db)):
    
    # 1. Truy vấn 1 lần lấy trọn ổ: Document + Novel liên kết + Tags của Novel đó
    query = (
        select(Document)
        .options(
            joinedload(Document.novel)          # Lấy thông tin Novel
            .selectinload(Novel.tags)           # Kéo theo danh sách Tags của Novel đó
        )
        .where(Document.doc_id == document_id)
    )
    
    result = await db.execute(query)
    doc = result.scalar_one_or_none()
    
    # 2. Bắt lỗi nếu không tìm thấy Document
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # 3. Lấy ra novel từ object document (SQLAlchemy đã tự động gắn vào nhờ Relationship)
    novel = doc.novel
    
    # Bắt lỗi nếu Document này chưa được liên kết với Novel nào
    if not novel:
        raise HTTPException(status_code=404, detail="Tài liệu này hiện chưa được liên kết với bất kỳ truyện nào (doc_novel_id bị trống).")

    # 4. Trả về Response
    return {
        "novel_id": novel.novel_id,
        "novel_title": novel.novel_title,
        "novel_author": novel.novel_author,
        "novel_description": novel.novel_description,
        "novel_coverurl": novel.novel_coverurl,
        "novel_series": novel.novel_series,
        "novel_isprivate": novel.novel_isprivate,
        "tags": novel.tags, # Dữ liệu tags cũng đã được tự động kéo về
    }
    
    
@router_novel.delete("/{novel_id}", response_model=MessageResponse)
async def delete_novel(novel_id: UUID, current_user = Depends(require_novel_owner_or_admin), db: AsyncSession = Depends(get_db)):
    novel = await db.get(Novel, novel_id)
    doc_fileurl = await db.scalar(select(Document.doc_fileurl).where(Document.doc_novel_id == novel_id))
    doc_id = doc_fileurl.split("/")[-1].split(".")[0] if doc_fileurl else None
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found") 

    try:
        await db.delete(novel)
        await db.commit()
    except Exception as db_error:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(db_error)}")

    if doc_id:
        files_to_delete = [
            os.path.join(COVER_STORAGE_PATH, f"{doc_id}"),
            os.path.join(MARKDOWN_STORAGE_PATH, f"{doc_id}.md"),
            os.path.join(MARKDOWN_REVEAL_STORAGE_PATH, f"{doc_id}.md"),
            os.path.join(PDF_STORAGE_PATH, f"{doc_id}.pdf")
        ]
        
        for file_path in files_to_delete:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass
        
        shutil.rmtree(os.path.join(IMAGE_STORAGE_PATH, f"{doc_id}"), ignore_errors=True)
        shutil.rmtree(os.path.join(IMAGE_SECONDARY_STORAGE_PATH, f"{doc_id}"), ignore_errors=True)  
    
    return {"message": "Novel deleted successfully"}

@router_novel.put("/{novel_id}", response_model=NovelUpdateResponse)
async def update_novel(novel_id: UUID, novel_data: NovelBase, current_user = Depends(require_novel_owner_or_admin), db: AsyncSession = Depends(get_db)):
    novel = await db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")
    
    
    novel.novel_title = novel_data.novel_title if novel_data.novel_title is not None else novel.novel_title
    novel.novel_author = novel_data.novel_author if novel_data.novel_author is not None else novel.novel_author
    novel.novel_description = novel_data.novel_description if novel_data.novel_description is not None else novel.novel_description
    novel.novel_coverurl = novel_data.novel_coverurl if novel_data.novel_coverurl is not None else novel.novel_coverurl
    novel.novel_series = novel_data.novel_series if novel_data.novel_series is not None else novel.novel_series
    novel.novel_isprivate = novel_data.novel_isprivate if novel_data.novel_isprivate is not None else novel.novel_isprivate
    
    if novel_data.tags is not None:
        tag_result = await db.execute(
            select(Tag).where(Tag.tag_id.in_(novel_data.tags))
        )
        new_tags = tag_result.scalars().all()
        novel.tags = new_tags
     
    
    await db.commit()
    await db.refresh(novel)
    
    return {
        "message": "Novel updated successfully",
        "novel": novel,
    }

@router_novel.get("/documents", response_model=PaginatedDocResponse)
async def get_user_documents(
    current_user = Depends(require_unlocked_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1, description="Page number"),
):  
    size = 10
    try:
        offset_value = (page - 1) * size

        # 1. Get total count for this user's documents
        count_query = (
            select(func.count())
            .select_from(Document)
            .join(Novel, Document.doc_novel_id == Novel.novel_id)
            .where(Novel.novel_user == current_user.user_id)
        )
        total_items = await db.scalar(count_query) or 0

        # 2. Get paginated data
        result = await db.execute(
            select(Document)
            .options(joinedload(Document.novel))
            .join(Novel, Document.doc_novel_id == Novel.novel_id)
            .where(Novel.novel_user == current_user.user_id)
            .offset(offset_value)
            .limit(size)
        )
        documents = result.scalars().all()

        # 3. Format items
        items = [
            DocDetailResponse(
                novel_id=doc.doc_novel_id,
                document_id=doc.doc_id,
                doc_title=doc.doc_title,
                novel_title=doc.novel.novel_title,
                novel_author=doc.novel.novel_author,
                novel_cover=bool(doc.novel.novel_coverurl) if doc.novel.novel_coverurl else False,
                doc_isprivate=doc.novel.novel_isprivate,
                doc_status=doc.doc_status,
                doc_fileurl=doc.doc_fileurl if doc.doc_status == "completed" else None,
                                doc_markdownurl=doc.doc_markdownurl if doc.doc_status == "completed" else None
            )
            for doc in documents
        ]

        total_pages = (total_items + size - 1) // size if total_items > 0 else 0

        return {
            "items": items,
            "page": page,
            "size": size,
            "total_items": total_items,
            "total_pages": total_pages
        }

    except Exception as e:
        print(f"DEBUG ERROR: {e}")
        raise e
    

@router_novel.get("/admin/documents", response_model=PaginatedDocResponse)
async def get_admin_documents(
    current_user = Depends(require_unlocked_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1, description="Page number"),
):  
    size = 10
    if current_user.user_role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can access this endpoint")
        
    try:
        offset_value = (page - 1) * size

        # 1. Get total count for all documents
        count_query = select(func.count()).select_from(Document)
        total_items = await db.scalar(count_query) or 0

        # 2. Get paginated data
        result = await db.execute(
            select(Document)
            .options(joinedload(Document.novel))
            .join(Novel, Document.doc_novel_id == Novel.novel_id)
            .offset(offset_value)
            .limit(size)
        )
        documents = result.scalars().all()

        # 3. Format items
        items = [
            DocDetailResponse(
                novel_id=doc.doc_novel_id,
                document_id=doc.doc_id,
                doc_title=doc.doc_title,
                novel_title=doc.novel.novel_title,
                novel_author=doc.novel.novel_author,
                novel_cover=bool(doc.novel.novel_coverurl) if doc.novel.novel_coverurl else False,
                doc_isprivate=doc.novel.novel_isprivate,
                doc_status=doc.doc_status,
                doc_fileurl=doc.doc_fileurl if doc.doc_status == "completed" else None,
                doc_markdownurl=doc.doc_markdownurl if doc.doc_status == "completed" else None
            )
            for doc in documents
        ]

        total_pages = (total_items + size - 1) // size if total_items > 0 else 0

        return {
            "items": items,
            "page": page,
            "size": size,
            "total_items": total_items,
            "total_pages": total_pages
        }

    except Exception as e:
        print(f"DEBUG ERROR: {e}")
        raise e
