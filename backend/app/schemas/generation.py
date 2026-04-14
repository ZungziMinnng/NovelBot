from pydantic import BaseModel
from typing import Optional


class GenerateChapterRequest(BaseModel):
    novel_id: int
    chapter_number: int
    volume: int = 1
    instruction: str = ""  # 用户额外指令，如"重点描写战斗场景"
    target_words: int = 800


class GenerateOutlineRequest(BaseModel):
    novel_id: int
    level: str = "chapter"  # book / volume / chapter
    volume: int = 1


class GenerateCharacterRequest(BaseModel):
    novel_id: int
    character_id: int


class GenerateWorldRequest(BaseModel):
    novel_id: int
    raw_setting: str
    raw_rules: str = ""


# SSE 事件结构
class SSEEvent(BaseModel):
    event: str  # stage / token / done / error
    data: str
