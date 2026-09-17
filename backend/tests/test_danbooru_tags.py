"""Danbooru tag 词表校验。

卡的都是「LLM 编了个假 tag，但看起来很像真的」这类情况——它们不会报错，
只会让出的图悄悄少画一样东西，是这个功能最主要的失效方式。
"""
import unittest

from app.services import danbooru_tags as dt


class NormalizeTests(unittest.TestCase):
    def test_case_and_spaces(self):
        self.assertEqual(dt.normalize("Long Hair"), "long_hair")

    def test_weight_syntax_is_stripped(self):
        """LLM 经常吐 `(long_hair:1.2)` 这种带权重的写法。"""
        self.assertEqual(dt.normalize("(long_hair:1.2)"), "long_hair")

    def test_hyphens_survive(self):
        """`cross-section` / `x-ray` 的连字符是规范名的一部分，
        换成下划线就查不到了。"""
        self.assertEqual(dt.normalize("X-Ray"), "x-ray")
        self.assertEqual(dt.resolve("X-Ray"), "x-ray")

    def test_colon_inside_a_name_is_kept(self):
        """只有「冒号后面是数字」才是权重语法。作品名里的冒号得留着。"""
        self.assertEqual(dt.normalize("re:zero"), "re:zero")

    def test_character_name_suffix_parens_survive(self):
        """角色 tag 大量是 `name_(series)` 形态，结尾那个 `)` 不能被剥。
        曾经 strip('()') 把它剥成 `tsunade_(naruto`，同人角色名全查不到。"""
        self.assertEqual(dt.normalize("tsunade_(naruto)"), "tsunade_(naruto)")
        # 但整体被括号包住的权重壳还是要脱
        self.assertEqual(dt.normalize("(long_hair)"), "long_hair")


class ResolveTests(unittest.TestCase):
    def test_alias_maps_to_canonical(self):
        """用户说「子宫」，LLM 可能吐 womb，词表里的规范名是 uterus。"""
        self.assertEqual(dt.resolve("womb"), "uterus")

    def test_real_tags_resolve(self):
        for tag in ("uterus", "cross-section", "sound_effects", "emphasis_lines"):
            self.assertEqual(dt.resolve(tag), tag, tag)

    def test_hallucinated_tags_are_rejected(self):
        """这几个是实测中 LLM 真的编出来过的，词表里都没有。
        `masterpiece` / `best_quality` 尤其要挡住——现有的
        image_prompt_sd_tags.jinja2 还在教模型这么写。"""
        for fake in ("internal_cutaway", "masterpiece", "best_quality", "illustration"):
            self.assertIsNone(dt.resolve(fake), fake)

    def test_onomatopoeia_is_a_real_alias(self):
        """`onomatopoeia` 本身不是规范名，但**是 sound_effects 的注册别名**，
        所以查得到。别把它当幻觉词——写方案时我以为它不存在，实际词表里
        `sound_effects,0,24204,"onomatopoeia,sfx"` 明确挂着。"""
        self.assertEqual(dt.resolve("onomatopoeia"), "sound_effects")

    def test_artist_tags_are_not_in_the_table(self):
        """artist 整类在生成词表时就剔掉了，画风由 imageStyles.ts 管。"""
        self.assertIsNone(dt.resolve("wlop"))


class CheckTests(unittest.TestCase):
    def test_splits_hits_from_unknown(self):
        hits, unknown = dt.check(["1girl", "internal_cutaway", "uterus"])
        self.assertEqual(hits, ["1girl", "uterus"])
        self.assertEqual(unknown, ["internal_cutaway"])

    def test_input_order_is_preserved(self):
        """tag 顺序在 SDXL 里影响权重，前面的更重。按热度重排会打乱
        「主体在前、背景在后」这个意图——1girl 热度远高于 pagoda，
        重排的话背景会被顶到前面。"""
        hits, _ = dt.check(["pagoda", "1girl"])
        self.assertEqual(hits, ["pagoda", "1girl"])

    def test_alias_and_canonical_collapse_to_one(self):
        """womb 和 uterus 是同一个概念。都留下等于悄悄给它加权。"""
        hits, _ = dt.check(["womb", "uterus"])
        self.assertEqual(hits, ["uterus"])

    def test_blank_entries_are_dropped_silently(self):
        """LLM 输出末尾多个逗号很常见，空串不算「命不中」。"""
        hits, unknown = dt.check(["1girl", "", "   "])
        self.assertEqual(hits, ["1girl"])
        self.assertEqual(unknown, [])


class SearchTests(unittest.TestCase):
    def test_finds_the_real_tag_for_a_misspelling(self):
        """这就是这个函数存在的理由：LLM 把 cross-section 写成了别的形态，
        候选里得有真词让它改回来。"""
        self.assertIn("cross-section", dt.search("cross_section_view"))

    def test_searches_aliases_too(self):
        """`crossection` 是 cross-section 的注册别名。只扫规范名的话
        这个写法一个候选都搜不出来。"""
        self.assertIn("cross-section", dt.search("crossection"))

    def test_pure_semantic_jumps_are_out_of_reach(self):
        """能力边界，写下来免得以后误以为是 bug：`internal_cutaway` 搜不到
        `cross-section`，因为词表里没有 `cutaway` 这个词，两者一个词都不重。
        词面匹配到不了这种跳跃——上层得拿中文原文再问一次模型，
        这也是转换链路要有第二趟的原因。"""
        self.assertNotIn("cross-section", dt.search("internal_cutaway"))

    def test_matches_whole_words_not_substrings(self):
        """子串匹配会让 `ear` 命中 beard / search 一大片，噪声压过信号。

        断言查的是**规范名或它任一别名**里有 `ear` 这个整词，而不是只查规范名：
        `earrings` 是合法命中——它挂着别名 `ear_ring`，那里面 `ear` 是独立的词。
        只查规范名会把这种正确行为判成失败。
        """
        lookup, _ = dt._table()
        for hit in dt.search("ear"):
            forms = [f for f, canon in lookup.items() if canon == hit]
            self.assertTrue(
                any("ear" in f.replace("-", "_").split("_") for f in forms),
                f"{hit} 的写法里没有 ear 这个整词：{forms}",
            )

    def test_hotter_tags_come_first(self):
        hits = dt.search("hair")
        counts = [dt.post_count(h) for h in hits]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_nonsense_returns_empty(self):
        self.assertEqual(dt.search("zzzqqqxxx"), [])


class TableTests(unittest.TestCase):
    def test_table_actually_loaded(self):
        """上面每条测试都依赖词表真的在。文件缺失时 _table 会返回空表而不是
        抛错（故意的，别的功能不该被拖崩），那样上面的断言会以很难懂的方式失败
        ——所以这里明确卡一下。"""
        self.assertGreater(dt.post_count("1girl"), 1_000_000)


if __name__ == "__main__":
    unittest.main()
