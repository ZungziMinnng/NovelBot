import unittest

# Novel 的 relationship 需要全部关联模型注册后才能初始化 mapper
from app.models import novel as _novel, chapter, character, memory as _memory, model_library, writer_preset, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry  # noqa: F401
from app.models.character import Character
from app.models.location import Location
from app.models.world_entity import WorldEntity
from app.services.entity_embeddings import (
    _char_text,
    _entity_text,
    _location_text,
    _state_snippet,
)
from app.services.summarizer import _apply_entity_updates, _apply_location_updates


class StateSnippetTests(unittest.TestCase):
    def test_empty_state_returns_empty(self):
        self.assertEqual(_state_snippet({}), "")
        self.assertEqual(_state_snippet(None), "")
        self.assertEqual(_state_snippet("not a dict"), "")

    def test_scalar_list_dict_values(self):
        text = _state_snippet({
            "境界": "金丹期",
            "titles": ["剑首", "长老"],
            "relationship_changes": {"李四": "结仇"},
            "空值": "",
        })
        self.assertIn("境界=金丹期", text)
        self.assertIn("titles=剑首、长老", text)
        self.assertIn("relationship_changes=李四:结仇", text)
        self.assertNotIn("空值", text)

    def test_all_empty_values_returns_empty(self):
        self.assertEqual(_state_snippet({"a": "", "b": [], "c": {}}), "")

    def test_truncated_to_limit(self):
        text = _state_snippet({"记录": "长" * 500}, limit=100)
        self.assertLessEqual(len(text), 100)


class EmbedTextTests(unittest.TestCase):
    def test_char_text_includes_state(self):
        c = Character(name="张三", role="主角", description="少年剑客",
                      current_state={"境界": "筑基"})
        text = _char_text(c)
        self.assertIn("张三", text)
        self.assertIn("当前状态", text)
        self.assertIn("境界=筑基", text)

    def test_char_text_without_state(self):
        c = Character(name="张三", role="主角", description="少年剑客", current_state={})
        self.assertNotIn("当前状态", _char_text(c))

    def test_entity_text_includes_state(self):
        e = WorldEntity(name="青锋剑", type="item", description="一把剑",
                        current_state={"owner": "张三"})
        text = _entity_text(e)
        self.assertIn("owner=张三", text)

    def test_location_text_includes_state(self):
        loc = Location(name="青云山", type="山脉", description="一座山",
                       current_state={"控制势力": "青云门"})
        text = _location_text(loc, "东域")
        self.assertIn("[东域]", text)
        self.assertIn("控制势力=青云门", text)


class ApplyUpdatesReturnIdsTests(unittest.TestCase):
    def test_entity_updates_returns_updated_ids(self):
        e1 = WorldEntity(name="青锋剑", type="item", current_state={})
        e1.id = 11
        e2 = WorldEntity(name="玉佩", type="item", current_state={})
        e2.id = 12
        matched, unmatched, updated_ids = _apply_entity_updates(
            [e1, e2],
            {"青锋剑": {"owner": "张三"}, "不存在的东西": {"owner": "谁"}},
        )
        self.assertEqual(matched, 1)
        self.assertEqual(unmatched, ["不存在的东西"])
        self.assertEqual(updated_ids, [11])

    def test_location_updates_returns_updated_ids(self):
        l1 = Location(name="青云山", type="山脉", current_state={})
        l1.id = 21
        matched, unmatched, updated_ids = _apply_location_updates(
            [l1], {"青云山": {"状态": "被毁"}},
        )
        self.assertEqual(matched, 1)
        self.assertEqual(updated_ids, [21])


if __name__ == "__main__":
    unittest.main()
