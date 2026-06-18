from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from feature.rag.service import generate_answer_async, hybrid_search
from feature.search.service import search_novels_by_text
from models.document import Document, Embedding
from models.novel import Novel
import asyncio

from feature.rag.service import clean_extracted_text, gemini_client, hybrid_search, CHAT_MODEL

def extract_search_query(question: str, chunk_texts: list[str]) -> str:
    context = "\n\n---\n\n".join(chunk_texts)
    prompt = f"""
You are a search query extractor for a novel library.

The user is trying to find a novel. Use the retrieved CONTEXT to infer the most likely novel title.
Return only one short search query, preferably the exact novel title.
If the title is unclear, return the best distinctive keyword, character name, faction name, or author-like phrase.
Do not explain.
Do not use quotes.

USER QUESTION:
{question}

RETRIEVED CONTEXT:
{context}
"""

    response = gemini_client.models.generate_content(
        model=CHAT_MODEL,
        contents=prompt,
    )
    return response.text.strip().strip('"').strip("'")


async def extract_search_query_async(question: str, chunk_texts: list[str]) -> str:
    return await asyncio.to_thread(extract_search_query, question, chunk_texts)


async def get_document_ids_by_novel(db: AsyncSession, novel_id: UUID) -> list[UUID]:
    result = await db.execute(
        select(Document.doc_id).where(Document.doc_novel_id == novel_id)
    )
    return list(result.scalars().all())


async def chat_with_novel(
    db: AsyncSession,
    novel_id: UUID,
    question: str,
    history: list[str],
    top_k: int,
) -> tuple[Novel, str, list[Embedding]]:
    novel = await db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")

    document_ids = await get_document_ids_by_novel(db, novel_id)
    if not document_ids:
        raise HTTPException(status_code=404, detail="No document found for this novel")

    chunks = await hybrid_search(db, question, top_k, doc_ids=document_ids)
    answer = await generate_answer_async(question, chunks, history)

    return novel, answer, chunks

async def ai_search_novels(db: AsyncSession, question: str, limit: int = 10, top_k: int = 8):
    chunks = await hybrid_search(db, question, top_k)
    chunk_texts = [clean_extracted_text(chunk.emb_chunk) for chunk in chunks]
    extracted_query = await extract_search_query_async(question, chunk_texts)

    novels = await search_novels_by_text(db, extracted_query, limit)

    return extracted_query, novels, chunk_texts
