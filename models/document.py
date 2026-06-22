from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Computed, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import relationship
from database import Base
import uuid

class Document(Base):
    __tablename__ = "documents"
    doc_id        = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_novel_id  = Column(UUID(as_uuid=True), ForeignKey("novels.novel_id", ondelete="CASCADE"), nullable=True)
    doc_title     = Column(String, nullable=False)
    doc_source    = Column(String, nullable=True)   # "novel" | "upload"
    doc_fileurl   = Column(String, nullable=True)
    doc_markdownurl = Column(String, nullable=True)
    doc_status    = Column(String, nullable=False, default="pending")
    doc_error     = Column(Text, nullable=True)
    doc_createdat = Column(DateTime(timezone=True), server_default=text("now()"))
    file_size     = Column(Integer, nullable=True)

    novel = relationship("Novel", back_populates="documents")
    embeddings = relationship("Embedding", back_populates="document", cascade="all, delete-orphan")

class Embedding(Base):
    __tablename__ = "embeddings"
    emb_id     = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id     = Column(UUID(as_uuid=True), ForeignKey("documents.doc_id"), nullable=False)
    emb_vector = Column(Vector(768))
    emb_chunk  = Column(Text, nullable=False)
    emb_fts    = Column(
        TSVECTOR,
        Computed("to_tsvector('simple', coalesce(emb_chunk, ''))", persisted=True),
    )

    document = relationship("Document", back_populates="embeddings")

    __table_args__ = (
        Index("ix_embeddings_emb_fts", "emb_fts", postgresql_using="gin"),
    )
