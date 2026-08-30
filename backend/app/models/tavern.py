"""酒馆模式的数据模型：角色卡 / 世界书 / 会话 / 消息。

与小说侧完全独立，不复用 novels / characters / chapters / memories。
"""
from datetime import datetime
from sqlalchemy import String, Text, Integer, Float, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class TavernCard(Base):
    __tablename__ = "tavern_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # 角色卡介绍：只给创作者本人看，永远不进 prompt
    creator_note: Mapped[str] = mapped_column(Text, default="")

    personality: Mapped[str] = mapped_column(Text, default="")
    opening_scene: Mapped[str] = mapped_column(Text, default="")
    system_instruction: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")

    # 对话示例：[{user, assistant}]，转成真实的 few-shot 消息轮。
    # 决定角色说话腔调最有效的字段，比在 personality 里用文字描述强一档。
    # 形状与小说侧 novels.writer_examples 一致，复用 ExampleTurn 前端类型
    dialogue_examples: Mapped[list] = mapped_column(JSON, default=list)

    # 勾选的 tavern_rules.id（不是小说侧的 prompt_rules）。默认 [] 表示不注入——
    # 酒馆是全新功能，没有"老书护栏不能丢"的问题，所以不要小说侧那套 NULL 三态语义
    enabled_rule_ids: Mapped[list] = mapped_column(JSON, default=list)

    # 头像文件的访问路径，照小说侧角色的存法：/api/avatars/{filename}
    avatar_url: Mapped[str] = mapped_column(String(300), default="")

    # 期望回复字数，0 = 不作要求。max_tokens 是硬截断（会切在句子中间），
    # 这个是写进提示词的软约束，模型会自己收尾
    reply_length: Mapped[int] = mapped_column(Integer, default=0)

    # 世界书关键词往回扫几条消息，1 = 只看玩家刚发的这句。
    # 调大能让"上一句提过的词"继续生效，代价是角色自己的回复也参与匹配，
    # 词条容易自己喂自己、连续触发好几轮
    scan_depth: Mapped[int] = mapped_column(Integer, default=3)

    # 除自己的世界书外，还要一起匹配的其他卡 id。
    # 用"卡引用卡"而不是给词条加共享标记：card_id 是 NOT NULL，SQLite 改不了可空性
    linked_book_card_ids: Mapped[list] = mapped_column(JSON, default=list)

    context_turns: Mapped[int] = mapped_column(Integer, default=20)
    temperature: Mapped[float] = mapped_column(Float, default=0.9)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048)
    model_ref: Mapped[str] = mapped_column(String(100), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class TavernInstructionPreset(Base):
    """常用系统指令。存在用户名下，建卡时可以直接取用。

    不复用小说侧的 writer_presets：那张表装的是写正文的预设（带 examples），
    混进来会让两边的列表互相污染。
    """
    __tablename__ = "tavern_instruction_presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class TavernRule(Base):
    """酒馆写作规则。与小说侧 prompt_rules 分开两张表。

    小说侧那批规则是按写正文调的（"不要大段心理描写"之类），套到逐轮对话上会打架；
    共用一张表还会让两边的列表互相污染。这里也没有内置规则，所以不需要
    is_builtin / builtin_key——酒馆默认不注入任何规则。
    """
    __tablename__ = "tavern_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class TavernWorldEntry(Base):
    __tablename__ = "tavern_world_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tavern_cards.id"), nullable=False, index=True
    )

    # 触发关键词，逗号分隔，照 glossary_entries.forbidden_variants 的存法
    keywords: Mapped[str] = mapped_column(String(500), default="")

    content: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # 常驻词条：不看关键词，每轮都注入。用来放"世界观底色"这类必须一直在的设定
    constant: Mapped[bool] = mapped_column(Boolean, default=False)

    # 插入深度：0 = 拼进 system 开头；n>0 = 插到倒数第 n 条消息之前。
    # 深度注入对"别忘了你是谁"这类提醒明显更有效——离当前对话越近，模型越不会忽略
    depth: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class TavernSession(Base):
    __tablename__ = "tavern_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tavern_cards.id"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(200), default="")

    # 玩家身份：空则 {{user}} 替换成 "user"
    persona_name: Mapped[str] = mapped_column(String(100), default="")
    persona_desc: Mapped[str] = mapped_column(Text, default="")

    # 早期对话压缩成的剧情梗概，以及已压缩到的消息 id（含）
    summary: Mapped[str] = mapped_column(Text, default="")
    summarized_upto_id: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class TavernSessionCard(Base):
    """故事线的参与角色。一张卡一行，sort_order 决定不点名时的发言顺序。

    TavernSession.card_id 仍是主卡：权限校验（_get_owned_session）和会话级操作
    （摘要、帮我想想）都认它，不要改成只靠这张表。
    """
    __tablename__ = "tavern_session_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tavern_sessions.id"), nullable=False, index=True
    )
    card_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tavern_cards.id"), nullable=False, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class TavernMessage(Base):
    __tablename__ = "tavern_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tavern_sessions.id"), nullable=False, index=True
    )

    role: Mapped[str] = mapped_column(String(20), nullable=False)

    # 说话人。NULL = 玩家消息，或群聊之前的老数据（读的时候回落到主卡）
    card_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tavern_cards.id"), nullable=True
    )

    # 存原始文本，{{user}} / {{char}} 不在这里替换。改了 persona 名字后历史消息跟着变
    content: Mapped[str] = mapped_column(Text, default="")

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
