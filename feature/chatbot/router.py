from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from feature.chatbot.schema import ChatSearchRequest, ChatbotRequest, ChatbotResponse, ChatSearchResponse
from feature.chatbot.service import ai_search_novels, chat_with_novel
from feature.rag.service import clean_extracted_text

router_chatbot = APIRouter(prefix="/chatbot", tags=["chatbot"])

@router_chatbot.post("/search", response_model=ChatSearchResponse)
async def ai_search(data: ChatSearchRequest, db: AsyncSession = Depends(get_db)):
    extracted_query, novels, chunk_texts = await ai_search_novels(
        db,
        data.question,
        data.limit,
        data.top_k,
    )
    if not novels:
        raise HTTPException(status_code=404, detail="No novels found matching the AI search query")

    return {
        "query": data.question,
        "extracted_query": extracted_query,
        "novels": novels,
        "chunks": chunk_texts,
    }


@router_chatbot.post("/novel", response_model=ChatbotResponse)
async def chatbot_by_novel(data: ChatbotRequest, db: AsyncSession = Depends(get_db)):
    novel, answer, chunks = await chat_with_novel(
        db=db,
        novel_id=data.novel_id,
        question=data.question,
        history=data.history,
        top_k=data.top_k,
    )

    return {
        "novel_id": novel.novel_id,
        "novel_title": novel.novel_title,
        "answer": answer,
        "chunks": [clean_extracted_text(chunk.emb_chunk) for chunk in chunks],
    }
