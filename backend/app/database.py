import logging
from pathlib import Path

from sqlalchemy import event, text, inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.database_url,
    echo=settings.sql_echo,
    connect_args={"check_same_thread": False, "timeout": 30},
)

@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def _is_expected_migration_error(exc: Exception) -> bool:
    if not isinstance(exc, OperationalError):
        return False
    message = str(exc).lower()
    return (
        "duplicate column name" in message
        or "already exists" in message
    )


async def _run_migrations() -> None:
    """运行增量 DDL 迁移，对已有数据库新增列（SQLite ALTER TABLE）"""
    migrations = [
        "ALTER TABLE novels ADD COLUMN writer_system_prompt TEXT DEFAULT ''",
        "ALTER TABLE novels ADD COLUMN enable_critic INTEGER DEFAULT 1",
        "ALTER TABLE novels ADD COLUMN writer_temperature REAL DEFAULT 0.85",
        "ALTER TABLE novels ADD COLUMN writer_max_tokens INTEGER DEFAULT 16384",
        # 修复存量 NULL 值，防止 or "" 静默吃掉用户设置
        "UPDATE novels SET writer_system_prompt = '' WHERE writer_system_prompt IS NULL",
        # 章节生成指令（构思备忘）
        "ALTER TABLE chapters ADD COLUMN instruction TEXT DEFAULT NULL",
        # 查询性能索引
        "CREATE INDEX IF NOT EXISTS idx_memories_novel_type_chapter ON memories(novel_id, memory_type, chapter_number)",
        "CREATE INDEX IF NOT EXISTS idx_memories_chapter_type ON memories(chapter_id, memory_type)",
        "CREATE INDEX IF NOT EXISTS idx_chapters_novel_vol_num ON chapters(novel_id, volume, number)",
        "CREATE INDEX IF NOT EXISTS idx_characters_novel ON characters(novel_id)",
        "CREATE INDEX IF NOT EXISTS idx_outlines_novel_level_vol_ch ON outlines(novel_id, level, volume, chapter_number)",
        # 上下文配置字段
        "ALTER TABLE novels ADD COLUMN rolling_summary_count INTEGER DEFAULT 8",
        "ALTER TABLE novels ADD COLUMN rag_top_k INTEGER DEFAULT 6",
        "ALTER TABLE novels ADD COLUMN chat_context_rounds INTEGER DEFAULT 20",
        "ALTER TABLE novels ADD COLUMN enable_thinking INTEGER DEFAULT 1",
        "ALTER TABLE novels ADD COLUMN thinking_level TEXT DEFAULT 'medium'",
        # 世界实体索引
        "CREATE INDEX IF NOT EXISTS idx_world_entities_novel ON world_entities(novel_id)",
        "CREATE INDEX IF NOT EXISTS idx_world_entities_novel_type ON world_entities(novel_id, type)",
        # 地点索引
        "CREATE INDEX IF NOT EXISTS idx_locations_novel ON locations(novel_id)",
        "CREATE INDEX IF NOT EXISTS idx_locations_novel_type ON locations(novel_id, type)",
        # 供应商关联
        "ALTER TABLE model_library ADD COLUMN provider_id INTEGER DEFAULT NULL",
        "ALTER TABLE characters ADD COLUMN avatar_url TEXT DEFAULT ''",
        "ALTER TABLE novels ADD COLUMN context_config TEXT DEFAULT '{}'",
        "ALTER TABLE novels ADD COLUMN gemini_stream INTEGER DEFAULT 0",
        # 思考档位拆分为 DeepSeek / Gemini 两套
        "ALTER TABLE novels ADD COLUMN deepseek_thinking_level TEXT DEFAULT 'high'",
        "ALTER TABLE novels ADD COLUMN gemini_thinking_level TEXT DEFAULT 'medium'",
        # 大纲范围支持
        "ALTER TABLE outlines ADD COLUMN start_chapter INTEGER DEFAULT 0",
        "ALTER TABLE outlines ADD COLUMN end_chapter INTEGER DEFAULT 0",
        "UPDATE outlines SET start_chapter = chapter_number, end_chapter = chapter_number WHERE chapter_number > 0 AND start_chapter = 0",
        "CREATE INDEX IF NOT EXISTS idx_outlines_novel_range ON outlines(novel_id, volume, start_chapter, end_chapter)",
        # Critic 模型 + 剧情细节审查
        "ALTER TABLE novels ADD COLUMN critic_model TEXT DEFAULT ''",
        "ALTER TABLE novels ADD COLUMN enable_detail_review INTEGER DEFAULT 0",
        "ALTER TABLE novels ADD COLUMN detail_review_model TEXT DEFAULT ''",
        # 全文上下文实验功能
        "ALTER TABLE novels ADD COLUMN enable_full_text_context INTEGER DEFAULT 0",
        "ALTER TABLE novels ADD COLUMN full_text_chapters INTEGER DEFAULT 20",
        # 嵌入模型配置
        "ALTER TABLE novels ADD COLUMN embedding_model TEXT DEFAULT ''",
        "ALTER TABLE model_library ADD COLUMN model_type TEXT NOT NULL DEFAULT 'chat'",
        "ALTER TABLE model_library ADD COLUMN context_window INTEGER DEFAULT 65536",
        "ALTER TABLE model_library ADD COLUMN input_price REAL DEFAULT 0",
        "ALTER TABLE model_library ADD COLUMN output_price REAL DEFAULT 0",
        "ALTER TABLE model_library ADD COLUMN price_currency TEXT DEFAULT 'CNY'",
        "ALTER TABLE model_library ADD COLUMN currency_to_cny_rate REAL DEFAULT 1",
        "UPDATE model_library SET model_type = 'chat' WHERE model_type IS NULL OR model_type = ''",
        "ALTER TABLE novels ADD COLUMN tags JSON DEFAULT '{}'",
        "ALTER TABLE novels ADD COLUMN estimated_chapters INTEGER DEFAULT 0",
        "ALTER TABLE novels ADD COLUMN enable_volume_split INTEGER DEFAULT 0",
        "ALTER TABLE novels ADD COLUMN skip_outline INTEGER DEFAULT 0",
        # 章节生成使用的模型标记
        "ALTER TABLE chapters ADD COLUMN model_used TEXT DEFAULT ''",
        # 移除已废弃的结构化长期记忆表（设计存档见 docs/memory_item_design.md）
        "DROP TABLE IF EXISTS memory_items",
        # 世界观变更日志
        "CREATE INDEX IF NOT EXISTS idx_worldview_changes_novel ON worldview_changes(novel_id, status, effective_chapter)",
        # 记忆重要性权重（1-5，默认3）
        "ALTER TABLE memories ADD COLUMN importance INTEGER DEFAULT 3",
        "ALTER TABLE world_entities ADD COLUMN importance INTEGER DEFAULT 3",
        "ALTER TABLE locations ADD COLUMN importance INTEGER DEFAULT 3",
        "ALTER TABLE factions ADD COLUMN importance INTEGER DEFAULT 3",
        "ALTER TABLE techniques ADD COLUMN importance INTEGER DEFAULT 3",
        "ALTER TABLE novel_notes ADD COLUMN importance INTEGER DEFAULT 3",
        # 写手 few-shot 示例轮
        "ALTER TABLE writer_presets ADD COLUMN examples JSON DEFAULT '[]'",
        "ALTER TABLE novels ADD COLUMN writer_examples JSON DEFAULT '[]'",
        "ALTER TABLE novels ADD COLUMN writer_use_custom_temperature INTEGER DEFAULT 1",
        # 供应商级代理开关（默认 1 = 沿用旧的全局代理行为，可直连的供应商手动关）
        "ALTER TABLE api_providers ADD COLUMN use_proxy BOOLEAN DEFAULT 1",
        # 实体固有功能字段（能力与作用，LLM 每章更新不写入）
        "ALTER TABLE world_entities ADD COLUMN function TEXT DEFAULT ''",
        # 按 novel_id 查询的性能索引补齐
        "CREATE INDEX IF NOT EXISTS idx_factions_novel ON factions(novel_id)",
        "CREATE INDEX IF NOT EXISTS idx_techniques_novel ON techniques(novel_id)",
        "CREATE INDEX IF NOT EXISTS idx_novel_notes_novel ON novel_notes(novel_id)",
        "CREATE INDEX IF NOT EXISTS idx_glossary_entries_novel ON glossary_entries(novel_id)",
        "CREATE INDEX IF NOT EXISTS idx_world_rules_novel ON world_rules(novel_id)",
        # 用户体系：根表归属
        "ALTER TABLE novels ADD COLUMN user_id INTEGER DEFAULT NULL",
        "ALTER TABLE writer_presets ADD COLUMN user_id INTEGER DEFAULT NULL",
        "ALTER TABLE api_providers ADD COLUMN user_id INTEGER DEFAULT NULL",
        "ALTER TABLE model_library ADD COLUMN user_id INTEGER DEFAULT NULL",
        "CREATE INDEX IF NOT EXISTS idx_novels_user ON novels(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_writer_presets_user ON writer_presets(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_api_providers_user ON api_providers(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_model_library_user ON model_library(user_id)",
        # 记忆条目是否注入上下文（逐条控制，目前用于关系里程碑）
        "ALTER TABLE memories ADD COLUMN in_context INTEGER DEFAULT 1",
        # 剧情设计 + 核心规则原始输入（新建向导选填，分开保存以便按需构建）
        "ALTER TABLE novels ADD COLUMN plot_design TEXT DEFAULT ''",
        "ALTER TABLE novels ADD COLUMN world_rules_seed TEXT DEFAULT ''",
        # 规则广场：全局规则库 + 每本书勾选
        # NULL = 从未配置（走内置默认）；[] = 用户显式全关。两者语义不同，不可互相塌陷
        "ALTER TABLE novels ADD COLUMN enabled_rule_ids JSON DEFAULT NULL",
        "CREATE INDEX IF NOT EXISTS idx_prompt_rules_user ON prompt_rules(user_id)",
        # 部分唯一索引：让内置规则的补种免竞态
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_prompt_rules_builtin ON prompt_rules(user_id, builtin_key) WHERE builtin_key != ''",
        # 酒馆模式：角色卡 / 世界书 / 会话 / 消息（表由 create_all 建，这里只补索引）
        "CREATE INDEX IF NOT EXISTS idx_tavern_cards_user ON tavern_cards(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_tavern_world_entries_card ON tavern_world_entries(card_id)",
        "CREATE INDEX IF NOT EXISTS idx_tavern_sessions_card ON tavern_sessions(card_id)",
        "CREATE INDEX IF NOT EXISTS idx_tavern_messages_session ON tavern_messages(session_id)",
        # 角色卡头像。表已由 create_all 建过，加列只能走 ALTER
        "ALTER TABLE tavern_cards ADD COLUMN avatar_url VARCHAR(300) DEFAULT ''",
        # 对话示例（few-shot 腔调样例）
        "ALTER TABLE tavern_cards ADD COLUMN dialogue_examples JSON DEFAULT '[]'",
        # 世界书：常驻词条 + 插入深度
        "ALTER TABLE tavern_world_entries ADD COLUMN constant BOOLEAN DEFAULT 0",
        "ALTER TABLE tavern_world_entries ADD COLUMN depth INTEGER DEFAULT 0",
        # 期望回复字数。max_tokens 只能硬截断，说不出"想要多长"
        "ALTER TABLE tavern_cards ADD COLUMN reply_length INTEGER DEFAULT 0",
        # 常用系统指令（表由 create_all 建，这里只补索引）
        "CREATE INDEX IF NOT EXISTS idx_tavern_instr_presets_user ON tavern_instruction_presets(user_id)",
        # 酒馆写作规则（表由 create_all 建，这里只补索引）
        "CREATE INDEX IF NOT EXISTS idx_tavern_rules_user ON tavern_rules(user_id)",
        # 世界书关键词扫描深度。默认 3 = 保持加这个开关之前的行为
        "ALTER TABLE tavern_cards ADD COLUMN scan_depth INTEGER DEFAULT 3",
        # 群聊：故事线的参与角色（表由 create_all 建，这里只补索引）
        "CREATE INDEX IF NOT EXISTS idx_tavern_session_cards_session ON tavern_session_cards(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_tavern_session_cards_card ON tavern_session_cards(card_id)",
        # 消息的说话人。NULL = 玩家，或群聊之前的老数据
        "ALTER TABLE tavern_messages ADD COLUMN card_id INTEGER DEFAULT NULL",
        # 共用世界书：这张卡还要一起匹配哪几张卡的词条
        "ALTER TABLE tavern_cards ADD COLUMN linked_book_card_ids JSON DEFAULT '[]'",
        # 老故事线补一条参与行，否则按参与表查会看不到它们
        "INSERT INTO tavern_session_cards (session_id, card_id, sort_order) "
        "SELECT id, card_id, 0 FROM tavern_sessions s WHERE NOT EXISTS "
        "(SELECT 1 FROM tavern_session_cards t WHERE t.session_id = s.id)",
        # 投稿元数据：作品简介 + 平台标签，番茄/起点开书必填
        "ALTER TABLE novels ADD COLUMN blurb TEXT DEFAULT ''",
        "ALTER TABLE novels ADD COLUMN submission_tags JSON DEFAULT '[]'",
        # 自定义投稿敏感词（表由 create_all 建，这里只补索引）
        "CREATE INDEX IF NOT EXISTS idx_sensitive_words_user ON sensitive_words(user_id)",
        # 题材腔调卡覆盖：'' = 按 genre 自动匹配，'none' = 不用卡，其他 = 指定卡名
        "ALTER TABLE novels ADD COLUMN genre_card TEXT DEFAULT ''",
        # 章纲执行计划：定位/情绪/章尾钩子（枚举见 services/outline_plan.py）
        "ALTER TABLE outlines ADD COLUMN chapter_role TEXT DEFAULT ''",
        "ALTER TABLE outlines ADD COLUMN emotion_tone TEXT DEFAULT ''",
        "ALTER TABLE outlines ADD COLUMN emotion_intensity INTEGER DEFAULT 0",
        "ALTER TABLE outlines ADD COLUMN hook_type TEXT DEFAULT ''",
        "ALTER TABLE outlines ADD COLUMN hook_strength INTEGER DEFAULT 0",
        # 卷级库存：留到结尾的牌 / 实力档位 / 已用掉的大爆点
        "ALTER TABLE volumes ADD COLUMN endgame_cards TEXT DEFAULT ''",
        "ALTER TABLE volumes ADD COLUMN power_tiers TEXT DEFAULT ''",
        "ALTER TABLE volumes ADD COLUMN tier_count INTEGER DEFAULT 0",
        "ALTER TABLE volumes ADD COLUMN words_per_tier INTEGER DEFAULT 0",
        "ALTER TABLE volumes ADD COLUMN spent_payoffs TEXT DEFAULT ''",
        # 隐藏的小说 / 写手预设。原来存 localStorage，换个入口（5173 vs 8000）就丢
        "ALTER TABLE users ADD COLUMN hidden_novel_ids JSON DEFAULT '[]'",
        "ALTER TABLE users ADD COLUMN hidden_preset_ids JSON DEFAULT '[]'",
        # 开书就要定下来的收尾方向：结局一句话 + 主角起点→终点
        "ALTER TABLE novels ADD COLUMN ending TEXT DEFAULT ''",
        "ALTER TABLE novels ADD COLUMN protagonist_arc TEXT DEFAULT ''",
    ]
    async with engine.begin() as conn:
        for sql in migrations:
            try:
                await conn.execute(text(sql))
            except Exception as exc:
                if _is_expected_migration_error(exc):
                    continue
                logger.exception("数据库迁移失败: %s", sql)
                raise
    # 章节号唯一约束：老库若已有重复章节号则跳过，不阻断启动
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_chapters_novel_number ON chapters(novel_id, number)"
            ))
    except Exception as exc:
        logger.warning("存在重复章节号，唯一索引 uq_chapters_novel_number 未生效: %s", exc)


async def _repair_data() -> None:
    """启动时幂等数据修复：卷号回写 + 悬空引用置空。"""
    repairs = [
        # 以章节表为准回写 Memory.volume，修复批量分卷未同步导致的卷号漂移
        """
        UPDATE memories SET volume = (
            SELECT c.volume FROM chapters c
            WHERE c.novel_id = memories.novel_id AND c.number = memories.chapter_number
        ) WHERE EXISTS (
            SELECT 1 FROM chapters c
            WHERE c.novel_id = memories.novel_id AND c.number = memories.chapter_number
              AND c.volume != memories.volume
        )
        """,
        # 悬空外键引用置空（foreign_keys=ON 之前必须清理）
        "UPDATE memories SET chapter_id = NULL WHERE chapter_id IS NOT NULL AND chapter_id NOT IN (SELECT id FROM chapters)",
        "UPDATE locations SET parent_id = NULL WHERE parent_id IS NOT NULL AND parent_id NOT IN (SELECT id FROM locations)",
    ]
    async with engine.begin() as conn:
        for sql in repairs:
            await conn.execute(text(sql))


async def _migrate_world_rules() -> None:
    """一次性：把老 core_setting 的 核心规则/特殊元素 段落拆分进 world_rules 表。

    仅在引入该表的那次启动运行（由 init_db 的 table_existed 守卫触发）。
    """
    from sqlalchemy import select
    from app.models.novel import Novel
    from app.services.world_rules_sync import split_core_setting_into_rules

    async with AsyncSessionLocal() as session:
        novels = (await session.execute(select(Novel))).scalars().all()
        for novel in novels:
            if novel.core_setting:
                await split_core_setting_into_rules(session, novel)
        await session.commit()


def _write_initial_password(password: str) -> None:
    """把首次生成的管理员密码落到数据目录，并打到控制台。

    只在新建库时调用一次。写文件是因为启动窗口可能被用户直接关掉、或滚屏冲掉。
    """
    banner = (
        "\n" + "=" * 58 + "\n"
        "  首次启动：已创建管理员账号\n"
        "      用户名：admin\n"
        f"      密码：{password}\n"
        "  这段密码也保存在 data/初始密码.txt，登录后请尽快修改。\n"
        + "=" * 58 + "\n"
    )
    print(banner, flush=True)
    try:
        path = Path(settings.data_dir) / "初始密码.txt"
        path.write_text(
            f"NovelBot 初始管理员账号\n\n用户名：admin\n密码：{password}\n\n"
            "登录后请在「设置」里修改密码，然后可以删除本文件。\n",
            encoding="utf-8",
        )
    except OSError:
        logger.warning("初始密码文件写入失败，请从上面的控制台输出中记下密码", exc_info=True)


async def seed_admin() -> int:
    """确保 admin 账户存在，并把无主的存量根表数据回填给 admin。幂等，每次启动可跑。"""
    import secrets
    from sqlalchemy import select
    from app.models.user import User
    from app.services.auth import hash_password

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        admin = result.scalar_one_or_none()
        if admin is None:
            # 随机生成而不是写死默认密码：这个库会被分发给别人用，
            # 写死等于所有装机共用一个已公开的密码
            password = secrets.token_urlsafe(9)
            admin = User(
                username="admin",
                password_hash=hash_password(password),
                is_admin=True,
            )
            session.add(admin)
            await session.commit()
            await session.refresh(admin)
            _write_initial_password(password)
        admin_id = admin.id

    async with engine.begin() as conn:
        for table in ("novels", "writer_presets", "api_providers", "model_library"):
            await conn.execute(
                text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"),
                {"uid": admin_id},
            )
    return admin_id


# 内置规则：(builtin_key, 名称, 分类, 内容来源模板)
# 内容取自磁盘模板，绝不在此复制正文——模板同时是种子来源和解析兜底来源
_BUILTIN_RULES = [
    ("writer_guardrails", "去AI味 / 一致性底线", "guardrail", "writer_guardrails.jinja2"),
]


async def seed_builtin_rules(user_ids: list[int] | None = None) -> None:
    """为用户补齐内置规则。

    幂等：按 (user_id, builtin_key) 存在即跳过，永不 UPDATE——用户对内置规则的
    编辑必须活过重启。种子失败不抛，由 resolve_rules_block 的模板兜底覆盖缺口。
    """
    from sqlalchemy import select
    from app.models.prompt_rule import PromptRule
    from app.models.user import User
    from app.prompts.loader import render

    try:
        async with AsyncSessionLocal() as session:
            if user_ids is None:
                user_ids = list((await session.execute(select(User.id))).scalars().all())
            if not user_ids:
                return
            existing = set(
                (await session.execute(
                    select(PromptRule.user_id, PromptRule.builtin_key)
                    .where(PromptRule.builtin_key != "")
                )).all()
            )
            added = 0
            for order, (key, name, category, template) in enumerate(_BUILTIN_RULES):
                content = render(template).strip()
                if not content:
                    logger.warning("内置规则模板 %s 渲染为空，跳过补种", template)
                    continue
                for uid in user_ids:
                    if (uid, key) in existing:
                        continue
                    session.add(PromptRule(
                        user_id=uid, name=name, content=content, category=category,
                        enabled=True, is_builtin=True, builtin_key=key, sort_order=order,
                    ))
                    added += 1
            if added:
                await session.commit()
                logger.info("补种内置规则 %s 条", added)
    except Exception:
        logger.exception("内置规则补种失败，将依赖 resolve_rules_block 的模板兜底")


async def init_db():
    from app.models import novel, chapter, character, memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, llm_usage, glossary_entry, user, text_replace_backup, tavern, sensitive_word  # noqa: F401
    async with engine.begin() as conn:
        existing = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).has_table("world_rules")
        )
        await conn.run_sync(Base.metadata.create_all)
    await _run_migrations()
    await _repair_data()
    if not existing:
        await _migrate_world_rules()
