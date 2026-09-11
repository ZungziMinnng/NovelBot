"""角色/实体/地点 current_state 的按章快照。

快照代表「某章第一次生成之前的干净状态」，用于重新生成或重新确认同一章时
先回滚再重新累积——否则状态只增不减（summarizer 里非空值才覆盖），
被删掉的设定会永久留在状态卡里。

快照按 (novel_id, chapter_number, volume) 存在 Memory 表，memory_type=state_snapshot。
"""
import json
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.memory import Memory
from app.models.character import Character
from app.models.world_entity import WorldEntity
from app.models.location import Location

logger = logging.getLogger(__name__)

# 快照 JSON 里的分区名 → ORM 模型
_SECTIONS: dict[str, type] = {
    "characters": Character,
    "entities": WorldEntity,
    "locations": Location,
}


async def find(
    session: AsyncSession, novel_id: int, chapter_number: int, volume: int,
) -> Memory | None:
    return (await session.execute(
        select(Memory)
        .where(
            Memory.novel_id == novel_id,
            Memory.chapter_number == chapter_number,
            Memory.volume == volume,
            Memory.memory_type == "state_snapshot",
        )
        .order_by(Memory.id.desc())
    )).scalars().first()


async def create(
    session: AsyncSession, novel_id: int, chapter_number: int, volume: int,
) -> None:
    """捕获当前全量 current_state 作为本章的干净底子。"""
    payload = {}
    for section, model in _SECTIONS.items():
        rows = (await session.execute(
            select(model).where(model.novel_id == novel_id)
        )).scalars().all()
        payload[section] = {str(r.id): r.current_state for r in rows}
    session.add(Memory(
        novel_id=novel_id, chapter_number=chapter_number, volume=volume,
        memory_type="state_snapshot", content=json.dumps(payload, ensure_ascii=False),
    ))


async def restore(session: AsyncSession, snapshot: Memory) -> bool:
    """把 current_state 恢复到快照那一刻。解析失败返回 False（调用方按「无快照」处理）。"""
    try:
        data = json.loads(snapshot.content)
    except Exception:
        logger.warning("状态快照解析失败 memory_id=%s", snapshot.id, exc_info=True)
        return False

    for section, model in _SECTIONS.items():
        for obj_id, state in (data.get(section) or {}).items():
            obj = await session.get(model, int(obj_id))
            if obj:
                obj.current_state = state
                flag_modified(obj, "current_state")

    logger.info("已从快照回滚章节 %s 的状态", snapshot.chapter_number)
    return True


async def rollback_or_create(
    session: AsyncSession, novel_id: int, chapter_number: int, volume: int,
) -> bool:
    """回滚到本章生成前的状态；没有快照就以当前状态建一个。返回是否真的回滚了。

    「不存在才创建、存在只恢复不覆盖」确保快照始终代表本章第一次生成之前，
    否则重复生成会把已污染的状态写进快照。
    """
    snapshot = await find(session, novel_id, chapter_number, volume)
    if snapshot and await restore(session, snapshot):
        return True
    if not snapshot:
        await create(session, novel_id, chapter_number, volume)
    return False


async def patch_latest(
    session: AsyncSession, novel_id: int, section: str, obj_id: int, state: dict | None,
) -> None:
    """把一处人工修改同步进最新快照，这样回滚只冲掉 AI 累积的部分、保住手改。

    只管最新那张快照：回头重新确认很老的章节仍会丢掉之后的手改，
    那种情况本来就该整体重算。快照缺失或损坏时静默跳过，人工修改本身已经落库。
    """
    snapshot = (await session.execute(
        select(Memory)
        .where(Memory.novel_id == novel_id, Memory.memory_type == "state_snapshot")
        .order_by(Memory.chapter_number.desc(), Memory.id.desc())
    )).scalars().first()
    if not snapshot:
        return
    try:
        data = json.loads(snapshot.content)
    except Exception:
        logger.warning("同步人工修改时快照解析失败 memory_id=%s", snapshot.id, exc_info=True)
        return
    data.setdefault(section, {})[str(obj_id)] = state
    snapshot.content = json.dumps(data, ensure_ascii=False)
