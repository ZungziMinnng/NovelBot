import unittest

from sqlalchemy import select

import test_rpg_opening_cast as opening
from app.api.routes import rpg as routes
from app.models.rpg import RpgLocation, RpgMessage, RpgModule, RpgNpc, RpgSession
from app.schemas.rpg import RpgSessionTweakIn
from app.services.rpg_context import here_npcs, npc_place


class TweakLocationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.world = opening.OpeningCastTests()
        await self.world.asyncSetUp()
        self.store = self.world.store
        self.npc = self.world.wife
        self.other = self.world.vendor
        self.session = await self.world.open()
        self.npc.ai_scheduled = True
        self.npc.random_movement = True
        self.npc.relation_enabled = False
        self.store.add_all([
            RpgLocation(module_id=self.world.module.id, name=name)
            for name in ["Market", "Kitchen", "Bedroom"]
        ])
        self.session.npc_states = {}
        self.session.npc_places = {str(self.npc.id): "Bedroom", str(self.other.id): "Kitchen"}
        self.session.npc_random_places = {str(self.npc.id): "Bedroom"}
        await self.store.commit()

    async def asyncTearDown(self):
        await self.world.asyncTearDown()

    async def tweak(self, places):
        return await routes.tweak_session(
            self.session.id, RpgSessionTweakIn(npc_places=places), self.world.user, self.store,
        )

    async def test_unmet_npc_moves_immediately_and_persists_without_changing_home(self):
        messages_before = list((await self.store.execute(select(RpgMessage.id))).scalars())
        clock_before = (self.session.day, self.session.slot, self.session.slot_actions)
        result = await self.tweak({str(self.npc.id): " Market "})
        self.assertEqual(result.notes, [])
        async with self.world.sessions() as reader:
            saved = await reader.get(RpgSession, self.session.id)
            self.assertEqual(saved.npc_places, {
                str(self.npc.id): "Market", str(self.other.id): "Kitchen",
            })
            self.assertEqual(saved.npc_random_places, {})
            self.assertEqual((saved.day, saved.slot, saved.slot_actions), clock_before)
            self.assertIn(self.npc.id, {npc.id for npc in here_npcs(
                [self.npc, self.other], saved.location, saved.slot, saved.npc_places,
            )})
        await self.store.refresh(self.npc)
        self.assertEqual(self.npc.location, "Bedroom")
        self.assertTrue(self.npc.random_movement)
        self.assertEqual(messages_before, list((await self.store.execute(select(RpgMessage.id))).scalars()))

    async def test_restore_routine_clears_random_override_and_following(self):
        self.session.npc_followers = [self.npc.id, self.other.id]
        await self.store.commit()
        await self.tweak({str(self.npc.id): None})
        self.assertNotIn(str(self.npc.id), self.session.npc_places)
        self.assertEqual(self.session.npc_random_places, {})
        self.assertEqual(self.session.npc_followers, [self.other.id])
        self.assertEqual(npc_place(
            self.npc, self.session.slot, self.session.npc_places,
            self.session.npc_followers, self.session.location,
        ), "Kitchen")

    async def test_remote_move_ends_following_and_empty_patch_preserves_positions(self):
        self.session.npc_followers = [self.npc.id]
        await self.store.commit()
        await self.tweak({})
        self.assertEqual(self.session.npc_random_places, {str(self.npc.id): "Bedroom"})
        self.assertEqual(self.session.npc_followers, [self.npc.id])
        await self.tweak({str(self.npc.id): "Kitchen"})
        self.assertEqual(self.session.npc_followers, [])
        self.assertEqual(self.session.npc_places[str(self.npc.id)], "Kitchen")

    async def test_invalid_characters_and_destinations_leave_positions_unchanged(self):
        foreign_module = RpgModule(user_id=2, name="Other")
        self.store.add(foreign_module)
        await self.store.flush()
        foreign_npc = RpgNpc(module_id=foreign_module.id, name="Foreign")
        protagonist = RpgNpc(module_id=self.world.module.id, name="Player", role="protagonist")
        self.store.add_all([
            foreign_npc, protagonist, RpgLocation(module_id=foreign_module.id, name="Foreign room"),
        ])
        await self.store.commit()
        original = dict(self.session.npc_places)
        for destination in ["Missing", "Foreign room"]:
            result = await self.tweak({
                str(self.npc.id): destination, str(foreign_npc.id): "Market",
                str(protagonist.id): "Market", "missing-id": "Market",
            })
            self.assertEqual(len(result.notes), 4)
            self.assertEqual(self.session.npc_places, original)
            self.assertEqual(self.session.npc_random_places, {str(self.npc.id): "Bedroom"})


if __name__ == "__main__":
    unittest.main()
