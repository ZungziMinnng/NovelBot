from pydantic import BaseModel, Field
from typing import Literal, Optional


class GenerateChapterRequest(BaseModel):
    novel_id: int
    chapter_number: int
    volume: int = 1
    instruction: str = ""  # 用户额外指令，如"重点描写战斗场景"
    target_words: int = 2500
    pov: Optional[str] = None  # 本章视角角色名；空则回退到男主


class AnnotationItem(BaseModel):
    paragraph: Optional[int] = None
    text: str


class RewriteChapterRequest(BaseModel):
    novel_id: int
    chapter_number: int
    annotations: list[AnnotationItem]
    target_words: int = 0
    rewrite_model: str = ""
    pov: Optional[str] = None  # 本章视角角色名；空则回退到男主


class PassageRewriteRequest(BaseModel):
    novel_id: int
    mode: Literal["rewrite", "expand", "condense"] = "rewrite"
    # 编辑框里可能有没保存的改动，所以直接收文字而不是章节 id
    selected: str = Field(min_length=1, max_length=8000)
    before: str = ""
    after: str = ""
    instruction: str = Field(default="", max_length=500)
    model: str = ""


class ReviewRequest(BaseModel):
    novel_id: int
