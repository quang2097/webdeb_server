import fitz as PDF
import pymupdf4llm
import os
import uuid
import asyncio
from uuid import UUID


from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import SessionLocal
from models.document import Document
from models.novel import Novel, NoveltoTags, Tag
from feature.rag.service import clean_extracted_text, index_document
import logging

logger = logging.getLogger(__name__)

PDF_STORAGE_PATH = "local_storage/pdf/"
MARKDOWN_STORAGE_PATH = "local_storage/markdown/"
MARKDOWN_REVEAL_STORAGE_PATH = "local_storage/markdown_reveal/"
IMAGE_STORAGE_PATH = "local_storage/image/"
COVER_STORAGE_PATH = "local_storage/cover/"
IMAGE_SECONDARY_STORAGE_PATH = "local_storage/image_secondary/"

SMALL_RENDERED_IMAGE_BYTES = 10 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def ensure_storage_dirs():
    os.makedirs(PDF_STORAGE_PATH, exist_ok=True)
    os.makedirs(MARKDOWN_STORAGE_PATH, exist_ok=True)
    os.makedirs(MARKDOWN_REVEAL_STORAGE_PATH, exist_ok=True)
    os.makedirs(IMAGE_STORAGE_PATH, exist_ok=True)
    os.makedirs(COVER_STORAGE_PATH, exist_ok=True)
    os.makedirs(IMAGE_SECONDARY_STORAGE_PATH, exist_ok=True)


def get_reveal_markdown_path(markdown_path: str) -> str:
    return os.path.join(MARKDOWN_REVEAL_STORAGE_PATH, os.path.basename(markdown_path))


def get_asset_folder_path(markdown_path: str) -> str:
    file_stem = os.path.splitext(os.path.basename(markdown_path))[0]
    return os.path.join(IMAGE_SECONDARY_STORAGE_PATH, file_stem)


def get_file_stem_from_markdown_path(markdown_path: str) -> str:
    return os.path.splitext(os.path.basename(markdown_path))[0]


def get_reveal_asset_paths(markdown_path: str | None) -> dict[str, str | None]:
    if not markdown_path:
        return {
            "markdown_reveal_url": None,
            "image_folder_url": None,
            "asset_folder_url": None,
        }

    file_stem = os.path.splitext(os.path.basename(markdown_path))[0]
    image_dir = os.path.join(IMAGE_STORAGE_PATH, file_stem)

    return {
        "markdown_reveal_url": get_reveal_markdown_path(markdown_path),
        "image_folder_url": image_dir,
        "asset_folder_url": get_asset_folder_path(markdown_path),
    }


def check_small_rendered_images(markdown_path: str | None) -> dict:
    """
    Scan ảnh render từ PDF, trả về bool needs_image_upload
    và các path liên quan để frontend dùng.
    """
    if not markdown_path:
        return {
            "needs_image_upload": False,
            "image_folder_url": None,
            "asset_folder_url": None,
            "small_image_count": 0,
            "total_image_count": 0,
        }

    file_stem = get_file_stem_from_markdown_path(markdown_path)
    image_dir = os.path.join(IMAGE_STORAGE_PATH, file_stem)
    asset_dir = os.path.join(IMAGE_SECONDARY_STORAGE_PATH, file_stem)

    if not os.path.exists(image_dir):
        return {
            "needs_image_upload": False,
            "image_folder_url": image_dir,
            "asset_folder_url": asset_dir,
            "small_image_count": 0,
            "total_image_count": 0,
        }

    image_paths = []
    for root, _, files in os.walk(image_dir):
        for filename in files:
            file_path = os.path.join(root, filename)
            if os.path.isfile(file_path):
                image_paths.append(file_path)

    small_images = [
        path for path in image_paths
        if os.path.getsize(path) <= SMALL_RENDERED_IMAGE_BYTES
    ]

    return {
        "needs_image_upload": bool(small_images),
        "image_folder_url": image_dir if image_paths else None,
        "asset_folder_url": asset_dir if small_images else None,
        "small_image_count": len(small_images),
        "total_image_count": len(image_paths),
    }

    
def pdf_to_data(pdf_path: str, image_dir: str):
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"The file {pdf_path} does not exist.")
    
    try:
        os.makedirs(image_dir, exist_ok=True)
        
        with PDF.open(pdf_path) as document:
            md_text = pymupdf4llm.to_markdown(
                doc=document,
                write_images=True,
                image_path=image_dir
            )
        return md_text
    
    except Exception as e:
        raise RuntimeError(f"An error occurred while processing the PDF: {e}")
    
def save_markdown(md_text: str, markdown_path: str):
    try:
        os.makedirs(os.path.dirname(markdown_path), exist_ok=True)
        with open(markdown_path, "w", encoding="utf-8") as md_file:
            md_file.write(md_text)
        return markdown_path
    except Exception as e:
        raise RuntimeError(f"An error occurred while saving the markdown file: {e}")


async def _write_file_streaming(file: UploadFile, path: str):
    """Ghi file theo chunk, tránh load toàn bộ vào RAM."""
    with open(path, "wb") as f:
        while chunk := await file.read(64 * 1024):
            f.write(chunk)


async def save_upload_files(pdf_file: UploadFile, cover_file: UploadFile):
    if pdf_file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    cover_ext = os.path.splitext(cover_file.filename or "")[1].lower()
    if not cover_ext or cover_ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=400, detail="Cover phải là ảnh jpg/png/webp")

    ensure_storage_dirs()

    upload_id = uuid.uuid4().hex
    pdf_ext = os.path.splitext(pdf_file.filename or "")[1].lower() or ".pdf"

    pdf_path = os.path.join(PDF_STORAGE_PATH, f"{upload_id}{pdf_ext}")
    await _write_file_streaming(pdf_file, pdf_path)

    cover_path = os.path.join(COVER_STORAGE_PATH, f"{upload_id}{cover_ext}")
    await _write_file_streaming(cover_file, cover_path)

    return {
        "upload_id": upload_id,
        "pdf_path": pdf_path,
        "cover_path": cover_path,
        "image_dir": os.path.join(IMAGE_STORAGE_PATH, upload_id),
        "markdown_path": os.path.join(MARKDOWN_STORAGE_PATH, f"{upload_id}.md"),
    }


async def save_pdf_file(pdf_file: UploadFile):
    if pdf_file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    ensure_storage_dirs()

    upload_id = uuid.uuid4().hex
    pdf_ext = os.path.splitext(pdf_file.filename or "")[1].lower() or ".pdf"

    pdf_path = os.path.join(PDF_STORAGE_PATH, f"{upload_id}{pdf_ext}")
    await _write_file_streaming(pdf_file, pdf_path)

    return {
        "upload_id": upload_id,
        "pdf_path": pdf_path,
        "image_dir": os.path.join(IMAGE_STORAGE_PATH, upload_id),
        "markdown_path": os.path.join(MARKDOWN_STORAGE_PATH, f"{upload_id}.md"),
    }


async def save_cover_file(cover_file: UploadFile, file_stem: str):
    cover_ext = os.path.splitext(cover_file.filename or "")[1].lower()
    if not cover_ext or cover_ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=400, detail="Cover phải là ảnh jpg/png/webp")

    ensure_storage_dirs()

    cover_path = os.path.join(COVER_STORAGE_PATH, f"{file_stem}{cover_ext}")
    await _write_file_streaming(cover_file, cover_path)

    return cover_path


async def replace_novel_tags(db: AsyncSession, novel_id: UUID, tag_ids: list[UUID]):
    unique_tag_ids = list(dict.fromkeys(tag_ids))

    # Validate trước
    if unique_tag_ids:
        result = await db.execute(select(Tag).where(Tag.tag_id.in_(unique_tag_ids)))
        tags = result.scalars().all()
        found_tag_ids = {tag.tag_id for tag in tags}
        missing_tag_ids = [str(tid) for tid in unique_tag_ids if tid not in found_tag_ids]
        if missing_tag_ids:
            raise HTTPException(status_code=400, detail=f"Tag not found: {', '.join(missing_tag_ids)}")
    else:
        tags = []

    await db.execute(delete(NoveltoTags).where(NoveltoTags.novel_id == novel_id))

    if unique_tag_ids:
        db.add_all([
            NoveltoTags(novel_id=novel_id, tag_id=tag_id)
            for tag_id in unique_tag_ids
        ])

    return tags


async def create_upload_records(db: AsyncSession, data, current_user, paths: dict):
    new_novel = Novel(
        novel_title=data.novel_title,
        novel_author=data.novel_author,
        novel_user=current_user.user_id,
        novel_description=data.novel_description,
        novel_coverurl=paths["cover_path"],
        novel_series=data.novel_series,
        novel_isprivate=data.novel_isprivate,
    )
    db.add(new_novel)
    await db.flush()

    new_doc = Document(
        doc_novel_id=new_novel.novel_id,
        doc_title=data.novel_title,
        doc_source=data.doc_source,
        doc_fileurl=paths["pdf_path"],
        doc_markdownurl=paths["markdown_path"],
        doc_status="pending",
    )
    db.add(new_doc)
    await replace_novel_tags(db, new_novel.novel_id, data.tag_ids)
    await db.commit()
    await db.refresh(new_doc)

    return new_novel, new_doc


UNTITLED = "Untitled"
UNKNOWN_AUTHOR = "Unknown"


async def create_pending_upload_records(db: AsyncSession, current_user, paths: dict):
    new_novel = Novel(
        novel_title=UNTITLED,
        novel_author=UNKNOWN_AUTHOR,
        novel_user=current_user.user_id,
        novel_isprivate=True,
    )
    db.add(new_novel)
    await db.flush()

    new_doc = Document(
        doc_novel_id=new_novel.novel_id,
        doc_title=UNTITLED,
        doc_source="upload",
        doc_fileurl=paths["pdf_path"],
        doc_markdownurl=paths["markdown_path"],
        doc_status="pending",
    )
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)

    return new_novel, new_doc


async def update_upload_information(db: AsyncSession, document: Document, novel: Novel, data, cover_file: UploadFile):
    if document.doc_status != "completed":
        raise HTTPException(status_code=400, detail="Document processing is not completed")

    cover_path = await save_cover_file(cover_file, str(document.doc_id))

    novel.novel_title = data.novel_title
    novel.novel_author = data.novel_author
    novel.novel_description = data.novel_description
    novel.novel_coverurl = cover_path
    novel.novel_series = data.novel_series
    novel.novel_isprivate = data.novel_isprivate
    document.doc_title = data.novel_title

    tags = await replace_novel_tags(db, novel.novel_id, data.tag_ids)

    await db.commit()
    await db.refresh(novel)
    await db.refresh(document)

    return novel, document, tags

# In feature/upload/service.py

async def add_update_upload_information(
    db: AsyncSession, 
    document: Document, 
    novel: Novel, 
    data, 
    # Update type hint here too
    cover_file: UploadFile | None 
):
    if document.doc_status != "completed":
        raise HTTPException(status_code=400, detail="Document processing is not completed")

    # 1. ONLY SAVE THE COVER IF A NEW ONE WAS PROVIDED
    if cover_file is not None:
        cover_path = await save_cover_file(cover_file, str(document.doc_id))
        novel.novel_coverurl = cover_path 
        # If cover_file is None, novel.novel_coverurl remains unchanged from the DB

    novel.novel_title = data.novel_title
    novel.novel_author = data.novel_author
    novel.novel_description = data.novel_description
    novel.novel_series = data.novel_series
    novel.novel_isprivate = data.novel_isprivate
    document.doc_title = data.novel_title

    tags = await replace_novel_tags(db, novel.novel_id, data.tag_ids)

    await db.commit()
    await db.refresh(novel)
    await db.refresh(document)

    return novel, document, tags


async def process_pdf_background(document_id, pdf_path: str, markdown_path: str, image_dir: str):
    async with SessionLocal() as db:
        document = await db.get(Document, document_id)
        if not document:
            return

        try:
            document.doc_status = "processing"
            document.doc_error = None

            # Tính toán khối lượng file (theo byte) từ đường dẫn thực tế
            if os.path.exists(pdf_path):
                file_size = os.path.getsize(pdf_path)
                document.file_size = file_size or 0

            await db.commit()

            extracted_text = await asyncio.to_thread(pdf_to_data, pdf_path, image_dir)
            markdown_reveal_path = get_reveal_markdown_path(markdown_path)
            await asyncio.to_thread(save_markdown, extracted_text, markdown_reveal_path)

            md_text = clean_extracted_text(extracted_text)
            await asyncio.to_thread(save_markdown, md_text, markdown_path)
            document.doc_markdownurl = markdown_reveal_path

            await index_document(db, document.doc_id, md_text)

            document.doc_status = "completed"
            await db.commit()
        except Exception as e:
            logger.error(f"PDF processing failed for doc {document_id}: {e}", exc_info=True)
            document.doc_status = "failed"
            document.doc_error = str(e)
            await db.commit()


async def upload_images_file(image_file: UploadFile, file_stem: str):
    if image_file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Chỉ chấp nhận ảnh jpg/png/webp")

    ensure_storage_dirs()

    image_ext = os.path.splitext(image_file.filename or "")[1].lower()
    asset_dir = os.path.join(IMAGE_SECONDARY_STORAGE_PATH, file_stem)
    os.makedirs(asset_dir, exist_ok=True)

    image_name = f"{uuid.uuid4().hex}{image_ext}" if image_ext else f"{uuid.uuid4().hex}.jpg"
    image_path = os.path.join(asset_dir, image_name)
    await _write_file_streaming(image_file, image_path)

    return image_path