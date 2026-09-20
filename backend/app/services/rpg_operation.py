import asyncio
import inspect
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta
from functools import wraps

from fastapi import HTTPException
from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.responses import StreamingResponse

from app.models.rpg import RpgMessage, RpgModule, RpgSave, RpgSession


_tasks: ContextVar[list | None] = ContextVar("rpg_operation_tasks", default=None)
_cleanup_tasks: set[asyncio.Task] = set()
LEASE_SECONDS = 120


def retain_task(task):
    tasks = _tasks.get()
    if tasks is not None:
        tasks.append(task)
    return task


def exclusive_session(function):
    signature = inspect.signature(function)

    @wraps(function)
    async def wrapped(*args, **kwargs):
        arguments = signature.bind(*args, **kwargs).arguments
        db, user = arguments["db"], arguments["user"]
        session_id = arguments.get("session_id")
        if session_id is None:
            model, identity = ((RpgMessage, arguments["message_id"])
                               if "message_id" in arguments else (RpgSave, arguments["save_id"]))
            row = await db.get(model, identity)
            if row is None:
                raise HTTPException(404, "记录不存在")
            session_id = row.session_id
        sess = await db.get(RpgSession, session_id)
        module = await db.get(RpgModule, sess.module_id) if sess else None
        if module is None or module.user_id != user.id:
            raise HTTPException(404, "游戏不存在")
        token = uuid.uuid4().hex
        now = datetime.utcnow()
        result = await db.execute(update(RpgSession).where(
            RpgSession.id == session_id,
            or_(RpgSession.operation_token == "", RpgSession.operation_token.is_(None),
                RpgSession.operation_until < now),
        ).values(operation_token=token, operation_until=now + timedelta(seconds=LEASE_SECONDS),
                 updated_at=RpgSession.updated_at).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            await db.rollback()
            raise HTTPException(409, "这一局还有操作正在处理，请稍后再试")
        await db.commit()
        await db.refresh(sess)
        factory = async_sessionmaker(db.bind, expire_on_commit=False)
        tasks = []
        context_token = _tasks.set(tasks)

        async def heartbeat():
            while True:
                await asyncio.sleep(LEASE_SECONDS / 3)
                async with factory() as store:
                    await store.execute(update(RpgSession).where(
                        RpgSession.id == session_id, RpgSession.operation_token == token,
                    ).values(operation_until=datetime.utcnow() + timedelta(seconds=LEASE_SECONDS),
                             updated_at=RpgSession.updated_at))
                    await store.commit()

        pulse = asyncio.create_task(heartbeat())

        async def release():
            try:
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                pulse.cancel()
                await asyncio.gather(pulse, return_exceptions=True)
                async with factory() as store:
                    await store.execute(update(RpgSession).where(
                        RpgSession.id == session_id, RpgSession.operation_token == token,
                    ).values(operation_token="", operation_until=None,
                             updated_at=RpgSession.updated_at))
                    await store.commit()

        async def finish():
            cleanup = asyncio.create_task(release())
            _cleanup_tasks.add(cleanup)
            cleanup.add_done_callback(_cleanup_tasks.discard)
            await asyncio.shield(cleanup)

        try:
            response = await function(*args, **kwargs)
        except BaseException:
            try:
                await db.rollback()
            finally:
                _tasks.reset(context_token)
                await finish()
            raise
        _tasks.reset(context_token)
        if isinstance(response, StreamingResponse):
            iterator = response.body_iterator

            async def body():
                try:
                    while True:
                        stream_token = _tasks.set(tasks)
                        try:
                            chunk = await anext(iterator)
                        except StopAsyncIteration:
                            break
                        finally:
                            _tasks.reset(stream_token)
                        yield chunk
                finally:
                    stream_token = _tasks.set(tasks)
                    try:
                        await iterator.aclose()
                    finally:
                        _tasks.reset(stream_token)
                        await finish()

            response.body_iterator = body()
        else:
            await finish()
        return response

    return wrapped
