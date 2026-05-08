from pydantic import BaseModel


class GenerateChapterRequest(BaseModel):
    novel_id: int
    chapter_number: int
    volume: int = 1
    instruction: str = ""  # 用户额外指令，如"重点描写战斗场景"
    target_words: int = 800


class PlotSuggestionsRequest(BaseModel):
    novel_id: int
    chapter_number: int
    volume: int = 1


class ReviewRequest(BaseModel):
    novel_id: int
