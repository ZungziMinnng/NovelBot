"""主角设定由模组锁定。

「玩家扮演谁」在这套引擎里只有一个来源：`role = 'protagonist'` 的那张角色卡
（主角模板）。锁定不是第二份主角设定，只是把建局时「玩家能改」这一步关掉。

所以要钉住的就三件事：拼法两边一致、锁上之后接口层也拦得住（界面只读不是唯一
的防线）、以及**没有那张卡时锁不生效**——锁着一个空名字等于谁都开不了局。
"""
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.rpg import create_session
from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgModule, RpgNpc
from app.models.user import User
from app.schemas.rpg import RpgSessionCreate
from app.services.rpg_state import protagonist_identity


def _npc(**kwargs):
    base = {"name": "阿隼", "role": "protagonist", "description": "", "persona": ""}
    base.update(kwargs)
    return RpgNpc(module_id=1, **base)


class IdentityTests(unittest.TestCase):
    def test_no_card_means_no_fixed_identity(self):
        self.assertIsNone(protagonist_identity([]))
        self.assertIsNone(protagonist_identity([_npc(role="npc")]))

    def test_a_card_without_a_name_does_not_count(self):
        # 名字是必填栏，空的那张卡拿不出「定死的值」——当没有卡处理，
        # 否则锁上之后 char_name 会是空串，而 GM 提示词里玩家就没有名字了
        self.assertIsNone(protagonist_identity([_npc(name="  ")]))

    def test_the_blurb_and_the_persona_are_joined(self):
        # 卡上是分开的两栏，这一局只有 char_desc 一栏。拼法必须和前端
        # protagonist.ts 逐字一致，否则弹窗里显示的和存进去的不是一回事
        name, desc = protagonist_identity([_npc(description="猎户出身", persona="话少，认死理")])
        self.assertEqual(name, "阿隼")
        self.assertEqual(desc, "猎户出身\n\n话少，认死理")

    def test_an_empty_column_leaves_no_blank_lines(self):
        self.assertEqual(protagonist_identity([_npc(description="猎户出身")])[1], "猎户出身")
        self.assertEqual(protagonist_identity([_npc(persona="话少")])[1], "话少")
        self.assertEqual(protagonist_identity([_npc()])[1], "")


class LockTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.db = async_sessionmaker(engine, expire_on_commit=False)()
        self.user = User(username="alice", password_hash="x")
        self.db.add(self.user)
        await self.db.commit()

    async def _module(self, *, card: RpgNpc | None = None, **kwargs):
        module = RpgModule(
            user_id=self.user.id, name="测试模组",
            stat_defs=[], relation_stat_defs=[], **kwargs,
        )
        self.db.add(module)
        await self.db.commit()
        if card is not None:
            card.module_id = module.id
            self.db.add(card)
            await self.db.commit()
        return module

    async def test_the_player_names_themselves_by_default(self):
        # 默认不锁，行为和加这一列之前一模一样：主角卡只是预填，玩家改了就算他的
        module = await self._module(card=_npc(description="猎户出身"))
        sess = await create_session(
            module.id, RpgSessionCreate(char_name="别的名字", char_desc="别的出身"),
            self.user, self.db,
        )
        self.assertEqual(sess.char_name, "别的名字")
        self.assertEqual(sess.char_desc, "别的出身")

    async def test_a_locked_module_overrides_whatever_was_posted(self):
        # 界面上那两栏是只读的，但界面拦不住直接打接口
        module = await self._module(
            lock_protagonist=True,
            card=_npc(description="猎户出身", persona="话少，认死理"),
        )
        sess = await create_session(
            module.id, RpgSessionCreate(char_name="绕过去", char_desc="绕过去"),
            self.user, self.db,
        )
        self.assertEqual(sess.char_name, "阿隼")
        self.assertEqual(sess.char_desc, "猎户出身\n\n话少，认死理")
        # 标题也跟着走，否则局列表里那一行还叫「绕过去的冒险」
        self.assertEqual(sess.title, "阿隼的冒险")

    async def test_locking_without_a_card_falls_back_to_the_player(self):
        # 拿不出定死的值就当没锁。界面上这个开关在没有主角卡时是灰的，
        # 但老数据、导入的模组、以及直接打接口都可能出现这个组合
        module = await self._module(lock_protagonist=True)
        sess = await create_session(
            module.id, RpgSessionCreate(char_name="阿隼"), self.user, self.db,
        )
        self.assertEqual(sess.char_name, "阿隼")

    async def test_the_npc_cards_are_not_mistaken_for_the_protagonist(self):
        module = await self._module(lock_protagonist=True, card=_npc(name="老陈", role="npc"))
        sess = await create_session(
            module.id, RpgSessionCreate(char_name="阿隼"), self.user, self.db,
        )
        self.assertEqual(sess.char_name, "阿隼")


if __name__ == "__main__":
    unittest.main()
