import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from feature.user.service import require_unlocked_user
from database import get_db
from sqlalchemy import select
from models.document import Document
from models.novel import Novel
from uuid import UUID
from .service import (
    add_update_upload_information,
    check_small_rendered_images,
    create_pending_upload_records,
    create_upload_records,
    get_file_stem_from_markdown_path,
    get_reveal_asset_paths,
    process_pdf_background,
    save_pdf_file,
    save_upload_files,
    update_upload_information,
    upload_images_file,
)
from .schema import PDFUploadRequest
from feature.common.response import AllDocResponse, DocResponse, DocumentStatusResponse, UploadStartResponse, UploadUpdateResponse

router_upload = APIRouter(prefix="/upload", tags=["upload"])


@router_upload.post("/pdf/start", response_model=UploadStartResponse)
async def start_pdf_upload(
    background_tasks: BackgroundTasks,
    pdf_file: UploadFile = File(...),
    current_user = Depends(require_unlocked_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        paths = await save_pdf_file(pdf_file)
        new_novel, new_doc = await create_pending_upload_records(db, current_user, paths)

        background_tasks.add_task(
            process_pdf_background,
            new_doc.doc_id,
            paths["pdf_path"],
            paths["markdown_path"],
            paths["image_dir"],
        )

        return {
            "message": "PDF uploaded. Processing started.",
            "status": new_doc.doc_status,
            "novel_id": new_novel.novel_id,
            "novel_title": new_novel.novel_title,
            "novel_coverurl": new_novel.novel_coverurl,
            "document_id": new_doc.doc_id,
            "doc_title": new_doc.doc_title,
            "doc_fileurl": new_doc.doc_fileurl,
            "doc_markdownurl": new_doc.doc_markdownurl,
            "file_size": new_doc.file_size
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router_upload.post("/pdf", response_model=UploadStartResponse)
async def upload_pdf(
    background_tasks: BackgroundTasks,
    data: PDFUploadRequest = Depends(PDFUploadRequest.as_form),
    pdf_file: UploadFile = File(...),
    cover_file: UploadFile = File(...),
    current_user = Depends(require_unlocked_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        paths = await save_upload_files(pdf_file, cover_file)
        new_novel, new_doc = await create_upload_records(db, data, current_user, paths)

        background_tasks.add_task(
            process_pdf_background,
            new_doc.doc_id,
            paths["pdf_path"],
            paths["markdown_path"],
            paths["image_dir"],
        )

        return {
            "message": "PDF uploaded successfully. Processing started.",
            "status": new_doc.doc_status,
            "novel_id": new_novel.novel_id,
            "novel_title": new_novel.novel_title,
            "novel_coverurl": new_novel.novel_coverurl,
            "document_id": new_doc.doc_id,
            "doc_title": new_doc.doc_title,
            "doc_fileurl": new_doc.doc_fileurl,
            "doc_markdownurl": new_doc.doc_markdownurl,
            "tag_ids": data.tag_ids,
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 1. ĐÃ SỬA: Đưa API tĩnh (/all/status) lên TRÊN API động (/{document_id}/status)
# 2. ĐÃ SỬA: Gộp 3 câu query thành 1 câu query duy nhất để tăng tốc Server
@router_upload.get("/documents/all/status", response_model=AllDocResponse)    
async def get_all_document_status(
    current_user=Depends(require_unlocked_user),
    db: AsyncSession = Depends(get_db)
):
    
    # Lấy TẤT CẢ document của user này trong 1 lần gọi DB
    result = await db.execute(
        select(Document, Novel)
        .join(Novel, Document.doc_novel_id == Novel.novel_id)
        .where(Novel.novel_user == current_user.user_id)
    )
    rows = result.all()

    list_failed = []
    list_completed = []
    list_processing = []

    # Phân loại dữ liệu bằng Python (nhanh hơn rất nhiều so với bắt DB làm 3 lần)
    for doc, novel in rows:
        if doc.doc_status == "failed":
            list_failed.append(
                DocResponse(novel_id=str(doc.doc_novel_id), document_id=str(doc.doc_id))
            )
        elif doc.doc_status == "processing" or doc.doc_status == "pending" :
            list_processing.append(
                DocResponse(
                    novel_id=str(doc.doc_novel_id), 
                    document_id=str(doc.doc_id),
                    # Ép kiểu datetime sang string (nếu có giá trị)
                    doc_createdat=doc.doc_createdat.isoformat() if doc.doc_createdat else None,
                    doc_size=doc.file_size
                )
            )
        elif doc.doc_status == "completed":
            if novel.novel_title == "Untitled" and novel.novel_author == "Unknown" and novel.novel_coverurl is None:
                list_completed.append(
                    DocResponse(novel_id=str(doc.doc_novel_id), document_id=str(doc.doc_id))
                )

    return AllDocResponse(
        listFailed=list_failed,
        listCompleted=list_completed,
        listProcessing=list_processing
    )


# Đường dẫn động phải nằm dưới cùng
@router_upload.get("/documents/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: UUID,
    current_user = Depends(require_unlocked_user),
    db: AsyncSession = Depends(get_db),
):
    document = await db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    novel = await db.get(Novel, document.doc_novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")
    if current_user.user_role != "admin" and current_user.user_id != novel.novel_user:
        raise HTTPException(status_code=403, detail="Access denied")

    reveal_paths = get_reveal_asset_paths(document.doc_markdownurl)
    image_check = check_small_rendered_images(document.doc_markdownurl)

    return {
        "document_id": document.doc_id,
        "status": document.doc_status,
        "error": document.doc_error,
        "markdown_url": document.doc_markdownurl if document.doc_status == "completed" else None,
        **reveal_paths,
        "can_update_information": document.doc_status == "completed",
        "needs_image_upload": image_check["needs_image_upload"],
        "image_folder_url": image_check["image_folder_url"],
        "asset_folder_url": image_check["asset_folder_url"],
    }


@router_upload.post("/documents/{document_id}/images")
async def upload_document_image(
    document_id: UUID,
    image_file: UploadFile = File(...),
    current_user = Depends(require_unlocked_user),
    db: AsyncSession = Depends(get_db),
):
    document = await db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    novel = await db.get(Novel, document.doc_novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")

    if current_user.user_role != "admin" and current_user.user_id != novel.novel_user:
        raise HTTPException(status_code=403, detail="Access denied")

    if document.doc_status != "completed":
        raise HTTPException(status_code=400, detail="Document chưa xử lý xong")

    try:
        file_stem = get_file_stem_from_markdown_path(document.doc_markdownurl)
        image_path = await upload_images_file(image_file, file_stem)
        return {
            "message": "Image uploaded successfully",
            "image_path": image_path,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router_upload.put("/documents/{document_id}/information", response_model=UploadUpdateResponse)
async def update_document_information(
    document_id: UUID,
    data: PDFUploadRequest = Depends(PDFUploadRequest.as_form),
    cover_file: UploadFile = File(...),
    current_user = Depends(require_unlocked_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        document = await db.get(Document, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        novel = await db.get(Novel, document.doc_novel_id)
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")

        if current_user.user_role != "admin" and current_user.user_id != novel.novel_user:
            raise HTTPException(status_code=403, detail="Access denied")

        novel, document, tags = await update_upload_information(
            db,
            document,
            novel,
            data,
            cover_file,
        )

        return {
            "message": "Novel information updated successfully",
            "novel_id": novel.novel_id,
            "novel_title": novel.novel_title,
            "novel_author": novel.novel_author,
            "novel_description": novel.novel_description,
            "novel_coverurl": novel.novel_coverurl,
            "novel_series": novel.novel_series,
            "novel_isprivate": novel.novel_isprivate,
            "document_id": document.doc_id,
            "doc_title": document.doc_title,
            "tags": [
                {
                    "tag_id": tag.tag_id,
                    "tag_name": tag.tag_name,
                }
                for tag in tags
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# In feature/upload/router.py

@router_upload.put("/documents/{document_id}/add/information", response_model=UploadUpdateResponse)
async def update_document_information(
    document_id: UUID,
    data: PDFUploadRequest = Depends(PDFUploadRequest.as_form),
    # 1. MAKE THE COVER FILE OPTIONAL
    cover_file: UploadFile | None = File(None), 
    current_user = Depends(require_unlocked_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        document = await db.get(Document, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        novel = await db.get(Novel, document.doc_novel_id)
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")

        if current_user.user_role != "admin" and current_user.user_id != novel.novel_user:
            raise HTTPException(status_code=403, detail="Access denied")

        # 2. Pass the potentially None cover_file to the service
        novel, document, tags = await add_update_upload_information(
            db,
            document,
            novel,
            data,
            cover_file,
        )

        return {
            "message": "Novel information updated successfully",
            "novel_id": novel.novel_id,
            "novel_title": novel.novel_title,
            "novel_author": novel.novel_author,
            "novel_description": novel.novel_description,
            "novel_coverurl": novel.novel_coverurl,
            "novel_series": novel.novel_series,
            "novel_isprivate": novel.novel_isprivate,
            "document_id": document.doc_id,
            "doc_title": document.doc_title,
            "tags": [
                {
                    "tag_id": tag.tag_id,
                    "tag_name": tag.tag_name,
                }
                for tag in tags
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))