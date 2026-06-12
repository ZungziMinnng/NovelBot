from pydantic import BaseModel
from typing import Optional


class GenerateChapterRequest(BaseModel):
    novel_id: int
    chapter_number: int
    volume: int = 1
    instruction: str = ""  # 用户额外指令，如"重点描写战斗场景"
    target_words: int = 800
    nsfw_mode: bool = False


class AnnotationItem(BaseModel):
    paragraph: Optional[int] = None
    text: str


class RewriteChapterRequest(BaseModel):
    novel_id: int
    chapter_number: int
    annotations: list[AnnotationItem]
    target_words: int = 0
    rewrite_model: str = ""
    nsfw_mode: bool = False


class ReviewRequest(BaseModel):
    novel_id: int
