from feature.auth.router import router_auth
from feature.user.router import router_user
from feature.tag.router import router_tag
from feature.novel.router import router_novel
from feature.upload.router import router_upload
from feature.admin.router import router_admin
from feature.report.router import router_report
from feature.search.router import router_search
from feature.chatbot.router import router_chatbot
from feature.storage.router import router_storage
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from feature.tag.service import seed_default_tags
import models
from database import SessionLocal, engine, Base
from sqlalchemy import text
from fastapi import APIRouter, FastAPI,  Depends 

# Trong main.py

app = FastAPI()
app.include_router(router_auth)
app.include_router(router_user)
app.include_router(router_tag)
app.include_router(router_upload)
app.include_router(router_novel)
app.include_router(router_admin)
app.include_router(router_report)
app.include_router(router_search)
app.include_router(router_chatbot)
app.include_router(router_storage)


# CORS configuration
origins = [
    "http://localhost:4200",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,       
    allow_credentials=True,       
    allow_methods=["*"],          
    allow_headers=["*"],           
)

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    async with engine.begin() as conn:
        await conn.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'novels'
                      AND column_name = 'novel_descriptionurl'
                ) THEN
                    ALTER TABLE novels ADD COLUMN IF NOT EXISTS novel_description VARCHAR;
                    UPDATE novels
                    SET novel_description = novel_descriptionurl
                    WHERE novel_description IS NULL;
                END IF;
            END $$;
        """))
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        await seed_default_tags(db)
        

@app.get("/")
async def root():
    return {"message": "PDF web"}
