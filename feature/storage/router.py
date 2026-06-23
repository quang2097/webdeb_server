import mimetypes
from pathlib import Path
import re
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from feature.storage.service import increase_novel_downloads, increase_novel_views
from models import novel
from models.novel import Novel
from urllib.parse import quote
from uuid import UUID
from fastapi.responses import JSONResponse
from fastapi import Query 

router_storage = APIRouter(prefix="/storage", tags=["Storage"])


BASE_DIR = Path(__file__).resolve().parent.parent.parent / "local_storage"

ALLOWED_TYPES = {
    "pdf": (BASE_DIR / "pdf", "application/pdf"),
    "markdown": (BASE_DIR / "markdown", "text/markdown"),
    "markdown_reveal": (BASE_DIR / "markdown_reveal", "text/markdown"),
    "cover": (BASE_DIR / "cover", None),
    "image": (BASE_DIR / "image", "image/png"),
    "image_secondary": (BASE_DIR / "image_secondary", "image/png"),
}

ALLOWED_ORIGIN = "http://localhost:4200"

from fastapi.responses import JSONResponse

@router_storage.get("/list/local_storage/image_secondary/{folder_path:path}")
async def get_secondary_image_list(folder_path: str):
    folder = BASE_DIR / "image_secondary"
    target_dir = (folder / folder_path).resolve()

    if not str(target_dir).startswith(str(folder.resolve())):
        raise HTTPException(status_code=400, detail="Invalid folder path")

    if not target_dir.exists() or not target_dir.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found")

    image_urls = []
    valid_extensions = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

    for file_path in target_dir.iterdir():
        if file_path.is_file() and file_path.suffix.lower() in valid_extensions:
            url = f"http://localhost:8000/storage/view/local_storage/image_secondary/{folder_path}/{file_path.name}"
            image_urls.append(url)

    image_urls.sort()

    return JSONResponse(
        content={"images": image_urls},
        headers={"Access-Control-Allow-Origin": ALLOWED_ORIGIN}
    )

@router_storage.get("/view/local_storage/{file_type}/{filename}/{novel_id:uuid}")
async def serve_file(file_type: str, filename: str, novel_id: UUID,db: AsyncSession = Depends(get_db)):
    if file_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Invalid file type")

    folder, media_type = ALLOWED_TYPES[file_type]
    file_path = (folder / filename).resolve()

    if not str(file_path).startswith(str(folder.resolve())):
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    
    await increase_novel_views(db, novel_id)


    return FileResponse(
        path=file_path,
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{file_path.name}"',
            "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
            "Access-Control-Allow-Methods": "GET, OPTIONS",
        },
    )

@router_storage.get("/download/local_storage/{file_type}/{filename}/{novel_id:uuid}")
async def download_file(file_type: str, filename: str, novel_id: UUID,db: AsyncSession = Depends(get_db)):
    if file_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Invalid file type")

    folder, media_type = ALLOWED_TYPES[file_type] 
    file_path = (folder / filename).resolve()

    if not str(file_path).startswith(str(folder.resolve())):
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    
    result  = await db.execute(select(Novel).where(Novel.novel_id == novel_id));
    novel = result.scalar_one_or_none()

    if novel is None:
        raise HTTPException(status_code=404, detail="Novel not found")

    await increase_novel_downloads(db, novel_id)

    safe_title = re.sub(r'[\\/*?:"<>|]', "", novel.novel_title).strip()
    download_name = f"{safe_title}_{file_path.name}"
    ascii_fallback = download_name.encode("ascii", "ignore").decode() or file_path.name
    encoded_name = quote(download_name)

    return FileResponse(
    path=file_path,
    media_type=media_type,
    headers={
        "Content-Disposition": (
            f'attachment; filename="{ascii_fallback}"; '
            f"filename*=UTF-8''{encoded_name}"
        ),
        "Access-Control-Expose-Headers": "Content-Disposition",
    },
)

@router_storage.get("/view/local_storage/{file_type}/{filename:path}")
async def serve_generic_file(
    file_type: str, 
    filename: str, 
    novel_id: UUID = Query(None), 
    db: AsyncSession = Depends(get_db)
):
    if file_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Invalid file type")
    
    folder, _ = ALLOWED_TYPES[file_type]
    file_path = (folder / filename).resolve()

    if not str(file_path).startswith(str(folder.resolve())):
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    if novel_id:
        await increase_novel_views(db, novel_id)

    media_type, _ = mimetypes.guess_type(file_path.name)
    media_type = media_type or "application/octet-stream"

    return FileResponse(
        path=file_path,
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{file_path.name}"',
            "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
        },
    )


    