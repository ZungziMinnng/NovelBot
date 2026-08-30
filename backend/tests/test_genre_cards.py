"""题材腔调卡：匹配优先级、手动覆盖、关闭、失效回落、卡文件完整性。"""
import unittest

from app.prompts import genre_cards

# 建书向导里提供的题材，每个都必须有卡——少一张就是静默无卡
WIZARD_GENRES = [
    "玄幻", "仙侠", "都市", "科幻", "历史", "言情", "悬疑",
    "武侠", "奇幻", "末世", "游戏", "军事", "古代权谋",
]


class CardFileTests(unittest.TestCase):
    def test_every_match_name_has_a_nonempty_card(self):
        for name in genre_cards._MATCH_ORDER:
            self.assertTrue(genre_cards.read_card(name), f"{name} 卡缺失或为空")

    def test_wizard_genres_all_resolve(self):
        for genre in WIZARD_GENRES:
            self.assertIsNotNone(
                genre_cards.resolve_card_name(genre), f"向导题材「{genre}」匹配不到卡",
            )

    def test_list_cards_covers_wizard_genres(self):
        names = {c["name"] for c in genre_cards.list_cards()}
        self.assertEqual(names, set(WIZARD_GENRES))
        self.assertTrue(all(c["body"] for c in genre_cards.list_cards()))


class AliasTests(unittest.TestCase):
    def test_alias_targets_are_real_cards(self):
        """别名指向的卡必须存在，否则匹配上了却读不出正文。"""
        for card, aliases in genre_cards.list_aliases().items():
            for alias in aliases:
                self.assertEqual(genre_cards.match_card_name(alias), card)
                self.assertTrue(genre_cards.read_card(card), f"{alias} 指向的 {card} 卡为空")

    def test_market_terms_now_match(self):
        """这些说法子串匹配抓不到，靠别名兜住。"""
        self.assertEqual(genre_cards.match_card_name("灵气复苏"), "都市")
        self.assertEqual(genre_cards.match_card_name("星际战舰"), "科幻")
        self.assertEqual(genre_cards.match_card_name("网游之剑侠"), "游戏")
        self.assertEqual(genre_cards.match_card_name("宫斗宅斗"), "古代权谋")

    def test_formal_name_beats_alias(self):
        """正式卡名优先于别名：「都市修真」是都市卡，不能被「修真」抢成仙侠。"""
        self.assertEqual(genre_cards.match_card_name("都市修真"), "都市")

    def test_longer_alias_wins(self):
        self.assertEqual(genre_cards.match_card_name("都市高武"), "都市")
        self.assertEqual(genre_cards.match_card_name("高武世界"), "玄幻")

    def test_still_no_match_for_unknown(self):
        self.assertIsNone(genre_cards.match_card_name("同人二创"))

    def test_list_cards_exposes_aliases(self):
        cards = {c["name"]: c["aliases"] for c in genre_cards.list_cards()}
        self.assertIn("灵气复苏", cards["都市"])
        self.assertIsInstance(cards["玄幻"], list)


class InjectHeaderTests(unittest.TestCase):
    def test_header_declares_priority_order(self):
        """冲突优先级必须写进注入头，否则几套提示词打起来时行为不可预测。"""
        card = genre_cards.load_card("玄幻")
        self.assertIn("优先级", card)
        self.assertIn("本章大纲", card)


class MatchTests(unittest.TestCase):
    def test_long_name_wins(self):
        """「古代权谋」不能被「历史」之类的短名抢先。"""
        self.assertEqual(genre_cards.match_card_name("古代权谋历史"), "古代权谋")

    def test_combined_genre_matches_by_substring(self):
        self.assertEqual(genre_cards.match_card_name("色情玄幻"), "玄幻")
        self.assertEqual(genre_cards.match_card_name("都市修真"), "都市")

    def test_no_match_returns_none(self):
        self.assertIsNone(genre_cards.match_card_name("同人二创"))
        self.assertIsNone(genre_cards.match_card_name(""))


class OverrideTests(unittest.TestCase):
    def test_override_beats_auto_match(self):
        self.assertEqual(genre_cards.resolve_card_name("玄幻", "都市"), "都市")
        self.assertIn("现实身份", genre_cards.load_card("玄幻", "都市"))

    def test_off_disables_card(self):
        self.assertIsNone(genre_cards.resolve_card_name("玄幻", genre_cards.OFF))
        self.assertEqual(genre_cards.load_card("玄幻", genre_cards.OFF), "")

    def test_stale_override_falls_back_to_auto(self):
        """指定的卡被删/改名后，回落到自动匹配，别静默变成无卡。"""
        self.assertEqual(genre_cards.resolve_card_name("玄幻", "已删除的卡"), "玄幻")

    def test_empty_override_is_auto(self):
        self.assertEqual(genre_cards.resolve_card_name("仙侠", ""), "仙侠")
        self.assertEqual(genre_cards.resolve_card_name("仙侠", "  "), "仙侠")

    def test_override_alone_works_without_genre(self):
        """题材没填也能靠手动指定拿到卡。"""
        self.assertEqual(genre_cards.resolve_card_name("", "武侠"), "武侠")

    def test_loaded_card_carries_inject_header(self):
        card = genre_cards.load_card("玄幻")
        self.assertTrue(card.startswith("=== 题材腔调参考 ==="))
        self.assertIn("核心驱动", card)


class ReadCardTests(unittest.TestCase):
    def test_unknown_name_returns_empty(self):
        """只认白名单里的卡名，防止 ../ 之类的路径拼接。"""
        self.assertEqual(genre_cards.read_card("../loader"), "")
        self.assertEqual(genre_cards.read_card(""), "")
        self.assertEqual(genre_cards.read_card(genre_cards.OFF), "")


if __name__ == "__main__":
    unittest.main()
