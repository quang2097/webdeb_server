import json
import os
import re
import asyncio
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

from google import genai
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.document import Embedding

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-2.5-flash-lite")
EMBEDDING_DIM = 768
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))

gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


MOJIBAKE_HINTS = ("Ã", "Ä", "áº", "á»", "Â", "â€", "ï")


def repair_mojibake(text: str) -> str:
    if not any(hint in text for hint in MOJIBAKE_HINTS):
        return text

    original_score = sum(text.count(hint) for hint in MOJIBAKE_HINTS)
    best_text = text
    best_score = original_score

    for encoding in ("latin1", "cp1252"):
        try:
            repaired = text.encode(encoding, errors="ignore").decode("utf-8", errors="ignore")
        except UnicodeError:
            continue

        bad_score = sum(repaired.count(hint) for hint in MOJIBAKE_HINTS)
        if bad_score < best_score:
            best_text = repaired
            best_score = bad_score

    return best_text


def clean_extracted_text(text: str) -> str:
    text = repair_mojibake(text)
    text = re.sub(r"!\[\]\([^)]+\)", " ", text)
    text = re.sub(r"\*\*?\[:-?\d+-?:\]\*\*?", " ", text)
    text = text.replace("\uf06e", "-")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, chunk_size: int = 3500, overlap: int = 500) -> list[str]:
    text = clean_extracted_text(text)
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap

    return chunks


def post_ollama(path: str, payload: dict) -> dict:
    url = f"{OLLAMA_BASE_URL.rstrip('/')}{path}"
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        detail = e.read().decode("utf-8")
        raise RuntimeError(f"Ollama request failed ({e.code}): {detail}") from e
    except URLError as e:
        raise RuntimeError(f"Cannot connect to Ollama at {OLLAMA_BASE_URL}: {e}") from e


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    result = post_ollama("/api/embed", {
        "model": EMBEDDING_MODEL,
        "input": texts,
    })
    vectors = result.get("embeddings")
    if vectors is None:
        raise RuntimeError(f"Ollama embedding response missing 'embeddings': {result}")

    for vector in vectors:
        if len(vector) != EMBEDDING_DIM:
            raise RuntimeError(
                f"Embedding dimension mismatch: expected {EMBEDDING_DIM}, got {len(vector)}"
            )

    return vectors


def embed_texts_in_batches(texts: list[str]) -> list[list[float]]:
    vectors = []

    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[start:start + EMBEDDING_BATCH_SIZE]
        vectors.extend(embed_texts(batch))

    return vectors


async def index_document(db: AsyncSession, document_id, markdown_text: str):
    await db.execute(delete(Embedding).where(Embedding.doc_id == document_id))

    chunks = chunk_text(markdown_text)
    if not chunks:
        return

    embed_inputs = [
        f"Represent this document chunk for retrieval:\n{chunk}"
        for chunk in chunks
    ]
    vectors = await asyncio.to_thread(embed_texts_in_batches, embed_inputs)

    for chunk, vector in zip(chunks, vectors):
        db.add(Embedding(
            doc_id=document_id,
            emb_chunk=chunk,
            emb_vector=vector,
        ))

    await db.commit()


def embed_query(question: str) -> list[float]:
    return embed_texts([
        f"Represent this user question for retrieving relevant document chunks:\n{question}"
    ])[0]


async def vector_search(db: AsyncSession, question: str, top_k: int = 8, doc_ids: list[UUID] | None = None):
    if doc_ids is not None and not doc_ids:
        return []

    query_vector = await asyncio.to_thread(embed_query, question)

    stmt = select(Embedding)
    if doc_ids is not None:
        stmt = stmt.where(Embedding.doc_id.in_(doc_ids))

    result = await db.execute(
        stmt.order_by(Embedding.emb_vector.cosine_distance(query_vector)).limit(top_k)
    )

    return result.scalars().all()


async def fts_search(db: AsyncSession, question: str, top_k: int = 8, doc_ids: list[UUID] | None = None):
    if doc_ids is not None and not doc_ids:
        return []

    query = func.plainto_tsquery("simple", question)

    stmt = select(Embedding).where(Embedding.emb_fts.op("@@")(query))
    if doc_ids is not None:
        stmt = stmt.where(Embedding.doc_id.in_(doc_ids))

    result = await db.execute(
        stmt.order_by(func.ts_rank_cd(Embedding.emb_fts, query).desc()).limit(top_k)
    )

    return result.scalars().all()


async def hybrid_search(db: AsyncSession, question: str, top_k: int = 8, doc_ids: list[UUID] | None = None):
    vector_results = await vector_search(db, question, top_k, doc_ids)
    fts_results = await fts_search(db, question, top_k, doc_ids)

    merged = []
    seen = set()

    for item in vector_results + fts_results:
        if item.emb_id not in seen:
            merged.append(item)
            seen.add(item.emb_id)

    return merged[:top_k]


def generate_answer(question: str, chunks: list[Embedding], history: list[str] | None = None) -> str:
    context = "\n\n---\n\n".join(clean_extracted_text(chunk.emb_chunk) for chunk in chunks)
    chat_history = "\n".join(history or [])

    prompt = f"""
You are a careful document QA assistant. If user ask about a review you have full permission to search for reviews online

Answer in the same language as the QUESTION.
Use only the CONTEXT.
If the CONTEXT contains relevant facts, synthesize a useful answer.
Only say "There is not enough information." when the CONTEXT truly does not contain the answer.
Use CHAT HISTORY only to understand references in the QUESTION. Do not treat it as source truth.

CHAT HISTORY:
{chat_history}

CONTEXT:
{context}

QUESTION:
{question}
"""

    response = gemini_client.models.generate_content(
        model=CHAT_MODEL,
        contents=prompt,
    )

    return response.text


async def generate_answer_async(question: str, chunks: list[Embedding], history: list[str] | None = None) -> str:
    return await asyncio.to_thread(generate_answer, question, chunks, history)
