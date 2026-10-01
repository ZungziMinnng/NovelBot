from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class StyleProfile(Base):
    """文风库：从一本 txt 里提取的原材料，小说 / 酒馆 / 游戏三边共用。

    存的是原文段落，不是做好的 few-shot 对——三个模式要的形状不一样，
    取用时才按模式现转，转完拷贝进目标，目标不存 profile_id（同预设库的理由）。
    不复用 writer_presets：那张表是写正文的预设，混进来两边列表互相污染。
    """
    __tablename__ = "style_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # 模型写的文风说明
    style_desc: Mapped[str] = mapped_column(Text, default="")
    # 代码算的统计：{avg_sentence_len, dialogue_ratio, avg_para_len, person}
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    # 原书主要角色：[{name, role}]，name 已是替换后的中性名
    characters: Mapped[list] = mapped_column(JSON, default=list)
    # 候选段落全部入库：[{scene_type, text, speakers}]。
    # 「默认三段」是取用时才勾的——酒馆要按角色挑段，只存三段会不够用
    scenes: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
