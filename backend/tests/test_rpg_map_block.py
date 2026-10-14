from app.models.rpg import RpgLocation
from app.services.rpg_context import map_block


def _loc(id_, name, parent_id=None, sort_order=0):
    return RpgLocation(id=id_, name=name, parent_id=parent_id, sort_order=sort_order)


def test_no_locations_gives_nothing():
    assert map_block([], 600) == ""


def test_flat_map_lists_names_and_rule_without_hierarchy():
    text = map_block([_loc(1, "栖凤台", sort_order=1), _loc(2, "藏剑阁", sort_order=2)], 600)
    assert "栖凤台、藏剑阁" in text
    assert "地图之外的地方只能当谈资" in text
    assert "地图层级" not in text


def test_nested_map_keeps_hierarchy_after_names():
    text = map_block([_loc(1, "山门"), _loc(2, "演武场", parent_id=1)], 600)
    assert "山门、演武场" in text
    assert "山门（演武场）" in text
    assert text.index("地图之外") < text.index("地图层级")
