from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SearchNovelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    novel_id: UUID
    novel_title: str
    novel_author: str
    novel_description: str | None = None
    novel_coverurl: str | None = None
    novel_series: str | None = None






