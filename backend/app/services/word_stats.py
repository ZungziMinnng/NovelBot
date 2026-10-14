"""日更统计：按天记全书字数，当天净增 = 今天最后一次的全书字数 - 今天开始时的全书字数。

每个改正文的地方改完调一次 record(delta)。今天第一次记账时用「改完的总数 - 这次的增量」
倒推出当天起点，所以不用在改之前再查一次。
"""
from datetime import date, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.word_day import WordDay


async def _book_total(db: AsyncSession, novel_id: int) -> int:
    return int((await db.execute(
        select(func.coalesce(func.sum(Chapter.word_count), 0)).where(Chapter.novel_id == novel_id)
    )).scalar() or 0)


async def record(db: AsyncSession, novel_id: int, delta: int) -> None:
    """正文已改（未提交也行，查询前会自动 flush），delta 是这次改动的字数变化。"""
    if not delta:
        return
    total = await _book_total(db, novel_id)
    today = date.today().isoformat()
    row = (await db.execute(
        select(WordDay).where(WordDay.novel_id == novel_id, WordDay.day == today)
    )).scalar_one_or_none()
    if row is None:
        db.add(WordDay(novel_id=novel_id, day=today, base=total - delta, total=total))
    else:
        row.total = total


async def recent(db: AsyncSession, novel_id: int, days: int = 30) -> dict:
    """最近 days 天每天的净增（没动过的日子补 0），外加今天和这段时间的合计。"""
    days = max(1, min(days, 366))
    start = date.today() - timedelta(days=days - 1)
    rows = (await db.execute(
        select(WordDay).where(WordDay.novel_id == novel_id, WordDay.day >= start.isoformat())
    )).scalars().all()
    net_by_day = {r.day: r.total - r.base for r in rows}
    series = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        series.append({"day": d, "net": net_by_day.get(d, 0)})
    return {
        "today": series[-1]["net"],
        "total": sum(s["net"] for s in series),
        "days": series,
    }
