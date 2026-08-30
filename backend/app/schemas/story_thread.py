from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


ThreadKind = Literal["foreshadowing", "secret"]
ThreadStatus = Literal["active", "resolved", "abandoned", "expired"]


class StoryThreadCreate(BaseModel):
    novel_id: int
    kind: ThreadKind
    title: str = ""
    content: str = Field(min_length=1)
    status: ThreadStatus = "active"
    source_chapter: int = Field(default=0, ge=0)
    due_chapter: int = Field(default=0, ge=0)
    resolved_chapter: int = Field(default=0, ge=0)
    resolution: str = ""
    known_by: list[str] = Field(default_factory=list)
    related_entities: list[str] = Field(default_factory=list)
    importance: int = Field(default=3, ge=1, le=5)
    source: str = "manual"

    @model_validator(mode="after")
    def normalize_kind_fields(self):
        if self.kind == "foreshadowing":
            self.known_by = []
        elif self.kind == "secret":
            self.due_chapter = 0
        return self


class StoryThreadUpdate(BaseModel):
    kind: Optional[ThreadKind] = None
    title: Optional[str] = None
    content: Optional[str] = Field(default=None, min_length=1)
    status: Optional[ThreadStatus] = None
    source_chapter: Optional[int] = Field(default=None, ge=0)
    due_chapter: Optional[int] = Field(default=None, ge=0)
    resolved_chapter: Optional[int] = Field(default=None, ge=0)
    resolution: Optional[str] = None
    known_by: Optional[list[str]] = None
    related_entities: Optional[list[str]] = None
    importance: Optional[int] = Field(default=None, ge=1, le=5)


class StoryThreadOut(BaseModel):
    id: int
    novel_id: int
    kind: ThreadKind
    title: str
    content: str
    status: ThreadStatus
    source_chapter: int
    due_chapter: int
    resolved_chapter: int
    resolution: str
    known_by: list[str]
    related_entities: list[str]
    importance: int
    source: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
