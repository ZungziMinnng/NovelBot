import type { IconType } from 'react-icons'
import {
  GiAnvil, GiBackpack, GiBattery75, GiBiceps, GiBrain, GiBrokenHeart,
  GiClover, GiCrossedSwords, GiCrown, GiEyeball, GiFamilyTree, GiFeather,
  GiFlame, GiHealthNormal, GiHearts, GiHourglass, GiLaurelCrown, GiMagicSwirl,
  GiMeal, GiOpenBook, GiProgression, GiRibbon, GiRose, GiScreaming,
  GiShakingHands, GiShield, GiSprint, GiTiredEye, GiTwoCoins, GiUpgrade,
  GiYinYang,
} from 'react-icons/gi'

/**
 * 属性名 → 图标。图标来自 game-icons.net（经 react-icons/gi），CC BY 3.0，署名在关于页。
 *
 * 按名字猜，而不是让模组作者手选：作者定义一条属性时本来就在想数值怎么设，
 * 再插一步「挑个图标」只会让人烦。猜不中就不画——宁可没图标，也别配错图标，
 * 「学识」旁边画把剑比什么都不画更让人出戏。
 */

/** 越靠前越优先。包含匹配时先撞到谁就用谁，所以具体的要排在笼统的前面：
 *  「血统声望」该走血统那条，不该走声望那条。 */
const RULES: Array<[string[], IconType]> = [
  // —— 排在最前：这几个的名字里套着后面更笼统的词 ——
  [['血统', '家世', '出身'], GiFamilyTree],
  [['血量', '生命', '健康', 'HP'], GiHealthNormal],

  // —— 玩家常见数值 ——
  [['精力', '体力', '能量', '耐力'], GiBattery75],
  [['理智', '精神', '心神', 'San'], GiBrain],
  [['资金', '金钱', '银两', '灵石', '金币', '钱'], GiTwoCoins],
  [['声望', '名声', '名望'], GiLaurelCrown],
  [['魔力', '灵力', '内力', '法力', '真气'], GiMagicSwirl],
  [['学识', '知识', '学问'], GiOpenBook],
  [['耐心'], GiHourglass],
  [['进度', '进展'], GiProgression],

  // —— 关系数值 ——
  [['好感', '亲密'], GiHearts],
  [['信任'], GiShakingHands],
  [['敬畏', '威望', '威严'], GiCrown],
  [['羞耻', '娇羞', '羞'], GiRose],

  // —— 跑团味的六维，模组作者自己加的居多 ——
  [['力量', '膂力'], GiBiceps],
  [['敏捷', '速度', '身法'], GiSprint],
  [['智力', '悟性'], GiBrain],
  [['防御', '护甲', '坚韧'], GiShield],
  [['攻击', '武力', '战力'], GiCrossedSwords],
  [['幸运', '运气', '气运'], GiClover],
  [['感知', '洞察', '观察'], GiEyeball],
  [['魅力', '颜值', '风姿'], GiRibbon],

  // —— 状态条 ——
  [['饥饿', '饱食', '温饱'], GiMeal],
  [['欲望', '情欲', '兴奋'], GiFlame],
  [['恐惧', '惊惧', '惊吓'], GiScreaming],
  [['疲劳', '困倦', '睡意'], GiTiredEye],
  [['堕落', '腐化', '污染'], GiBrokenHeart],

  // —— 修真/东方 ——
  [['修为', '道行', '境界'], GiYinYang],
  [['因果', '业力', '功德'], GiFeather],

  // —— 成长与家当 ——
  [['经验', '等级', '熟练'], GiUpgrade],
  [['负重', '装备', '行囊'], GiBackpack],
  [['锻造', '工艺', '手艺'], GiAnvil],
]

/** 拿不准就返回 null，调用方自己决定留不留位置 */
export function statIcon(name: string): IconType | null {
  const n = (name || '').trim()
  if (!n) return null

  // 先跑一遍全等：「声望」自己要能命中声望那条，
  // 否则它会在包含匹配里被更靠前的「血统声望」规则截胡
  for (const [keys, Icon] of RULES) {
    if (keys.some(k => n === k)) return Icon
  }
  for (const [keys, Icon] of RULES) {
    if (keys.some(k => n.includes(k))) return Icon
  }
  return null
}
