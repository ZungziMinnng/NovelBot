import json
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
        "ALTER TABLE tavern_cards ADD COLUMN profile_sections JSON DEFAULT '{}'",
        "ALTER TABLE tavern_cards ADD COLUMN summary_model_ref VARCHAR(100) DEFAULT ''",
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
        "ALTER TABLE users ADD COLUMN tavern_prompts JSON DEFAULT '{}'",
        # 开书就要定下来的收尾方向：结局一句话 + 主角起点→终点
        "ALTER TABLE novels ADD COLUMN ending TEXT DEFAULT ''",
        "ALTER TABLE novels ADD COLUMN protagonist_arc TEXT DEFAULT ''",
        # RPG 文字冒险（表由 create_all 建，这里只补索引）
        "CREATE INDEX IF NOT EXISTS idx_rpg_modules_user ON rpg_modules(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_rpg_world_entries_module ON rpg_world_entries(module_id)",
        "CREATE INDEX IF NOT EXISTS idx_rpg_npcs_module ON rpg_npcs(module_id)",
        "CREATE INDEX IF NOT EXISTS idx_rpg_sessions_module ON rpg_sessions(module_id)",
        "CREATE INDEX IF NOT EXISTS idx_rpg_messages_session ON rpg_messages(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_rpg_saves_session ON rpg_saves(session_id, id)",
        "ALTER TABLE users ADD COLUMN rpg_prompts JSON DEFAULT '{}'",
        # RPG 换成数值驱动：数值定义 + 游戏类型 + 判定的两个开关
        "ALTER TABLE rpg_modules ADD COLUMN genre VARCHAR(100) DEFAULT ''",
        "ALTER TABLE rpg_modules ADD COLUMN stat_defs JSON DEFAULT '[]'",
        "ALTER TABLE rpg_modules ADD COLUMN relation_stat_defs JSON DEFAULT '[]'",
        "ALTER TABLE rpg_modules ADD COLUMN random_check BOOLEAN DEFAULT 1",
        # 世界书的数值门槛。空 = 无条件，老行拿到 '{}' 行为不变
        "ALTER TABLE rpg_world_entries ADD COLUMN trigger_condition JSON DEFAULT '{}'",
        # 角色卡字段（照抄酒馆卡的结构）
        "ALTER TABLE rpg_npcs ADD COLUMN role VARCHAR(20) DEFAULT 'npc'",
        "ALTER TABLE rpg_npcs ADD COLUMN description TEXT DEFAULT ''",
        "ALTER TABLE rpg_npcs ADD COLUMN profile_sections JSON DEFAULT '{}'",
        "ALTER TABLE rpg_npcs ADD COLUMN dialogue_examples JSON DEFAULT '[]'",
        # 道具 / 地点 / 动作按钮（表由 create_all 建，这里只补索引）
        "CREATE INDEX IF NOT EXISTS idx_rpg_items_module ON rpg_items(module_id)",
        "CREATE INDEX IF NOT EXISTS idx_rpg_locations_module ON rpg_locations(module_id)",
        "CREATE INDEX IF NOT EXISTS idx_rpg_actions_module ON rpg_actions(module_id)",
        # 时段（分幕）：模组给默认表，每局各存一份自己的。老库拿到 '[]'/''
        # 就是「不用时段」，行为与加这些列之前完全一致
        "ALTER TABLE rpg_modules ADD COLUMN time_slots JSON DEFAULT '[]'",
        "ALTER TABLE rpg_sessions ADD COLUMN time_slots JSON DEFAULT '[]'",
        "ALTER TABLE rpg_sessions ADD COLUMN slot VARCHAR(20) DEFAULT ''",
        "ALTER TABLE rpg_sessions ADD COLUMN day INTEGER DEFAULT 1",
        # 分线对话与大事记。**没有回填、没有新表**：thread_id 默认 NULL，
        # 而 NULL 就是场面线，已有数据自动变成一条完整的场面线
        "ALTER TABLE rpg_messages ADD COLUMN thread_id INTEGER DEFAULT NULL",
        "CREATE INDEX IF NOT EXISTS idx_rpg_messages_thread ON rpg_messages(session_id, thread_id)",
        "ALTER TABLE rpg_sessions ADD COLUMN chronicle JSON DEFAULT '[]'",
        # 地图：地点的坐标（百分比，0 = 还没摆过）+ 这一局去过哪儿（迷雾）。
        # 老库拿到 0 和 '[]'，地图会按兜底网格排、当前地点和邻居照样亮着
        "ALTER TABLE rpg_locations ADD COLUMN x INTEGER DEFAULT 0",
        "ALTER TABLE rpg_locations ADD COLUMN y INTEGER DEFAULT 0",
        # 可选的地点层级：空是大地图，非空表示父地点内部的小地图节点
        "ALTER TABLE rpg_locations ADD COLUMN parent_id INTEGER DEFAULT NULL",
        "CREATE INDEX IF NOT EXISTS idx_rpg_locations_parent ON rpg_locations(module_id, parent_id)",
        "ALTER TABLE rpg_sessions ADD COLUMN visited JSON DEFAULT '[]'",
        # GM 边玩边记的 NPC 近况。老库拿到 '{}'，角色卡上那一块不显示
        "ALTER TABLE rpg_sessions ADD COLUMN npc_notes JSON DEFAULT '{}'",
        # 道具定义上的「开局就有」。老库拿到 0 = 一件都不带，开局背包照旧只看
        # rpg_modules.default_inventory，和加这一列之前一模一样
        "ALTER TABLE rpg_items ADD COLUMN start_with BOOLEAN DEFAULT 0",
        # 玩法类别（模拟 / 探索冒险 / 经营策略）。老库拿到 'rpg'，而 'rpg' 的
        # 玩法规则就是照着现在这套 GM 提示词写的，所以老模组行为完全不变
        "ALTER TABLE rpg_modules ADD COLUMN play_style VARCHAR(20) DEFAULT 'rpg'",
        # 摘要专用模型。老库拿到 ''，而消费端一律写 summary_model_ref or
        # fast_model_ref，空串就是跟着裁决模型走，和没有这一列时一样
        "ALTER TABLE rpg_modules ADD COLUMN summary_model_ref VARCHAR(100) DEFAULT ''",
        # 分线概要。老库拿到 '{}' = 每条角色线都还没压缩过，从头开始滚，
        # 场面线继续用原来的 summary / summarized_upto_id 两列
        "ALTER TABLE rpg_sessions ADD COLUMN thread_summaries JSON DEFAULT '{}'",
        "ALTER TABLE rpg_sessions ADD COLUMN thread_upto JSON DEFAULT '{}'",
        # 作息表：把「这个人在哪儿」按当前时段取。老库拿到 '{}' = 没有作息表，
        # 一律落回 location，和加这一列之前逐字一致
        "ALTER TABLE rpg_npcs ADD COLUMN slot_locations JSON DEFAULT '{}'",
        # 时段跳转时的外场简报（一次便宜的模型调用）。默认关：老模组保持
        # 「结束时段零模型调用」，这是当初就写进文档和界面上的承诺，
        # 不能因为加了新功能就悄悄把它变成假的
        "ALTER TABLE rpg_modules ADD COLUMN offscreen_brief BOOLEAN DEFAULT 0",
        # 角色是否交给 AI 调度。默认关：老模组不勾就一个模型调用都不多，
        # 行为和加这一列之前逐字一致
        "ALTER TABLE rpg_npcs ADD COLUMN ai_scheduled BOOLEAN DEFAULT 0",
        # AI 调度的产物：{"3": "在图书馆翻了一下午旧报纸"}。老库拿到 '{}' =
        # 谁都没被调度过，角色卡上不出现这一行
        "ALTER TABLE rpg_sessions ADD COLUMN npc_activities JSON DEFAULT '{}'",
        # 剧情挪动的人物位置：{"3": "校长办公室"}。老库拿到 '{}' = 谁的位置
        # 都没被剧情改过，一律按作息表 / 常驻地点算，和加这一列之前逐字一致
        "ALTER TABLE rpg_sessions ADD COLUMN npc_places JSON DEFAULT '{}'",
        # RPG 写作规则（rpg_rules 表由 create_all 建，这里只补索引）+ 模组勾选的
        # 规则 id。老库拿到 '[]' = 不勾任何规则、不注入，行为与加这列之前一致
        "CREATE INDEX IF NOT EXISTS idx_rpg_rules_user ON rpg_rules(user_id)",
        "ALTER TABLE rpg_modules ADD COLUMN enabled_rule_ids JSON DEFAULT '[]'",
        # 统一时间线：消息自带地点和在场名单（都是写入时快照，理由见 RpgMessage）。
        # 老库拿到 '' 和 NULL——**NULL 的语义是「不知道」，当所有人可见**，
        # 所以老存档里没有任何一条消息会因为这次改动消失
        "ALTER TABLE rpg_messages ADD COLUMN location VARCHAR(100) DEFAULT ''",
        "ALTER TABLE rpg_messages ADD COLUMN present JSON DEFAULT NULL",
        # 老消息按线回填在场名单：从角色线来的就是那一个人。用字符串拼而不是
        # json_array()，免得依赖 SQLite 编译时带没带 JSON1
        #
        # 场面线（thread_id IS NULL）当年是群戏和独处混在一条线上，分不出来，
        # 保持 NULL = 所有人可见。**别图省事把它填成 '[]'**——那等于宣布老存档
        # 里所有群戏都是玩家一个人干的，每个 NPC 对共同经历集体失忆
        #
        # 幂等：填过的行 present 非空，不再匹配；新消息 thread_id 恒为 NULL
        "UPDATE rpg_messages SET present = '[' || thread_id || ']' "
        "WHERE thread_id IS NOT NULL AND present IS NULL",
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


async def _backfill_rpg_clock(bind=None) -> None:
    """给「模组设了时段、这一局还没站上去」的旧局补一个当前时段。

    时段是这批新加的列，这批之前开的局拿到的是 '[]' 和 ''。**只补 slot，不碰
    time_slots**：会话那一列是「玩家建局时改过的表」，空就是跟模组走（见
    rpg_state.slot_table）。早期版本把模组的表整个拷进了局里，那等于补一次档就
    把这一局永久冻住——模组后来改对了，局里还是旧的。

    幂等：补过的局 slot 非空，下次启动不再匹配。纯 Python 而不是写进上面那串 SQL，
    是因为要取 JSON 数组的第一个元素，交给 SQL 做要依赖 json_extract。
    bind 只为测试能指向自己的库——**默认那个 engine 指向真实数据**。
    """
    async with (bind or engine).begin() as conn:
        rows = (await conn.execute(text(
            "SELECT s.id, s.slot, m.time_slots FROM rpg_sessions s "
            "JOIN rpg_modules m ON m.id = s.module_id"
        ))).all()
        for session_id, current, from_module in rows:
            if str(current or "").strip():
                continue
            names = [str(x).strip() for x in _json_list(from_module) if str(x).strip()]
            if not names:
                continue
            await conn.execute(
                text("UPDATE rpg_sessions SET slot = :slot WHERE id = :id"),
                {"slot": names[0], "id": session_id},
            )


async def _repair_concatenated_clock(bind=None) -> None:
    """清理「早，中，晚」被吃成「早中晚」留下的脏数据。

    前端那个输入框曾经每敲一个字就 join→split→join 一次，逗号在往返里被丢掉，
    于是整张时段表存成了一个格子，名字是几格连写。表现是时钟只有一格，按一下
    「结束这个时段」直接翻篇到第二天。

    判据是精确的：**这一局的时段表只有一格，且它的名字正好是模组那几格的名字连写**。
    别的形状一律不碰，所以玩家自己起的名字不会误伤；清过一次就不再匹配，是幂等的。
    修法是丢掉这一局自己那份（它本来也是历史遗留的拷贝），退回「跟模组走」。
    """
    async with (bind or engine).begin() as conn:
        rows = (await conn.execute(text(
            "SELECT s.id, s.time_slots, m.time_slots FROM rpg_sessions s "
            "JOIN rpg_modules m ON m.id = s.module_id"
        ))).all()
        for session_id, own, from_module in rows:
            single = [str(x).strip() for x in _json_list(own) if str(x).strip()]
            names = [str(x).strip() for x in _json_list(from_module) if str(x).strip()]
            if len(single) != 1 or len(names) < 2:
                continue
            if single[0] != "".join(names):
                continue
            await conn.execute(
                text("UPDATE rpg_sessions SET time_slots = '[]', slot = :slot WHERE id = :id"),
                {"slot": names[0], "id": session_id},
            )
            logger.info("RPG 第 %s 局：时段表被连写成「%s」，已退回跟模组走", session_id, single[0])


async def _rpg_timeline_is_legacy(conn) -> bool:
    """rpg_messages 还没有 location 列吗？——「这是加列那一次启动」的判据。

    必须**在 create_all 之后、加列迁移之前**问。create_all 只建缺的表、从不改
    已有的表，所以老库在这一刻一定还没有这一列；新建的库带着列建出来，判据为
    假，而新库本来也没有老消息要回填。放到 _run_migrations 之后问就恒为假了。

    抽成函数而不是写在 init_db 里，是为了能被测——init_db 动的是真实数据库。
    """
    return not await conn.run_sync(
        lambda c: any(
            col["name"] == "location" for col in inspect(c).get_columns("rpg_messages")
        )
    )


async def _backfill_rpg_timeline(bind=None) -> None:
    """统一时间线的老库回填：作废按线写的概要指针，让窗口重新发原文。

    老库里 summary / summarized_upto_id 记的是**场面线**压到哪。统一成一条时间线
    之后，那个指针之前、属于角色线的那些消息从来没有被压进任何一份概要，却会被
    history_window 当成「已经压过了」跳过——早先私聊的内容就这么静默消失，而且
    不报错。归零让它们重新发原文，随后摘要器按统一时间线重新压一遍。

    窗口本来就有 context_turns * 2 封顶（见 rpg_context.history_window），
    所以归零只是让最近那段重新发一次，撑不爆上下文。

    **只跑一次**，判据由调用方给（init_db 的 legacy_timeline）——这条 UPDATE
    自己不是幂等的：新局攒起来的 summarized_upto_id 会被下次启动再清一次。
    bind 只为测试能指向自己的库，默认那个 engine 指向真实数据。
    """
    async with (bind or engine).begin() as conn:
        result = await conn.execute(text(
            "UPDATE rpg_sessions SET summarized_upto_id = 0 WHERE summarized_upto_id > 0"
        ))
    if result.rowcount:
        logger.info(
            "统一时间线：%s 局的旧概要指针已归零，将按新时间线重新压缩", result.rowcount
        )


def _json_list(raw) -> list:
    """把库里的 JSON 列读成列表。用 text() 裸查拿不到类型转换，拿到的是字符串。"""
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


async def _repair_data() -> None:
    """启动时幂等数据修复：卷号回写 + 悬空引用置空 + RPG 时钟补齐。"""
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
    await _repair_concatenated_clock()
    await _backfill_rpg_clock()


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
    from app.models import novel, chapter, character, memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, llm_usage, glossary_entry, user, text_replace_backup, tavern, sensitive_word, rpg  # noqa: F401
    async with engine.begin() as conn:
        existing = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).has_table("world_rules")
        )
        await conn.run_sync(Base.metadata.create_all)
        # 判据要在这里取：加列迁移一跑，它恒为假。理由见 _rpg_timeline_is_legacy
        legacy_timeline = await _rpg_timeline_is_legacy(conn)
    await _run_migrations()
    await _repair_data()
    if not existing:
        await _migrate_world_rules()
    if legacy_timeline:
        await _backfill_rpg_timeline()
