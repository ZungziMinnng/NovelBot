from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class StyleScene(BaseModel):
    summary: str = ""  # 一句话场景概括；旧数据没有
    scene_type: str
    text: str
    speakers: list[str] = []
    input: str = ""  # 导入时反推的玩家输入，游戏叙事示例的 user 侧；旧数据没有


class StyleCharacter(BaseModel):
    name: str
    role: str = ""


class StyleProfilePreview(BaseModel):
    name: str
    style_desc: str = ""
    stats: dict = {}
    characters: list[StyleCharacter] = []
    scenes: list[StyleScene] = []


class StyleProfileCreate(StyleProfilePreview):
    """与 Preview 同字段：导入返回什么，用户改完确认后原样提交回来。"""


class StyleProfileUpdate(BaseModel):
    name: Optional[str] = None
    style_desc: Optional[str] = None
    characters: Optional[list[StyleCharacter]] = None
    scenes: Optional[list[StyleScene]] = None


class StyleProfileOut(StyleProfilePreview):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StyleAdaptIn(BaseModel):
    mode: str
    scene_indexes: list[int]
    character: str = ""
    name_map: dict[str, str] = {}  # 示例里的中性名 → 用户这边的真名，取用时手填
    model: str = ""  # 空 = 默认快速模型
