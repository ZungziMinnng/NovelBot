"""RPG 模式的上下文装配。

安全底线：module.creator_note 是「只给作者看的备注」，本模块的任何返回值里
都不能出现它。test_rpg_context.py 用哨兵串守这一条。

和酒馆 build_tavern_messages 的四处实质差别，都写在各自的位置上：
【你】段排在世界设定之前、不做真实 few-shot 轮、裁决产出的 intent 参与世界书
扫描、判定结果走独立注入通道。
"""
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rpg import (
    RpgAction, RpgItem, RpgLocation, RpgMessage, RpgModule, RpgNpc, RpgRule,
    RpgSession, RpgSkill, RpgWorldEntry, normalize_profile_sections,
)
from app.services.context_budget import estimate_tokens, truncate_to_token_budget
from app.services.rpg_dice import OUTCOME_LABELS
from app.services.rpg_memory import event_memory
from app.services.rpg_play_style import style_block
from app.services.rpg_prompts import render
from app.services.rpg_suggestions import SuggestSources
from app.services.rpg_state import (
    EFFECT_CHARS, TIER_LABEL_CHARS, check_condition, chronicle_lines, def_map,
    norm_name, npc_activity, place_note, tier_list, tier_of,
)

# 跟着 NPC_TOKEN_BUDGET 一起从 8000 抬到 9800、12000、20000，这次到 21500
# （加进来的是【角色总表】那 1500）。这是**整段
# system 的总闸**，从尾部切；只把【在场】的额度放大而不动它，多出来的就是从
# 尾巴上抢的，而尾巴正是写作规则、概要、长期记忆和世界设定——等于拆东墙补西墙。
# 定这个数的办法是拿各块额度之和反推：下面九块加起来 19600，留约 9% 余量给
# 抬头话术和写作规则。改任何一块额度都要回来重算这个数，别只改一边
#
# **「帮我想想」那一套（SUGGEST_*，见下面「追加段」那一节）不在这里面。**
# 读它的是另一个模型、另一个读者：这里给的是叙事模型看的整段 system，
# 那边只要「下一步能做什么」。两套额度各算各的，所以调那边的数**不需要**
# 回来动这个 21500，反过来也一样
SYSTEM_TOKEN_BUDGET = 21500
WORLD_TOKEN_BUDGET = 3000
SUMMARY_TOKEN_BUDGET = 2000
# 被提到、但人不在跟前的人分到的份额。**不参与上面那 2000 的均分**：提到一个
# 旧相好，不该把「你自己那格」和「正跟你说话那个人那格」一起稀释掉，所以他们
# 另分一个固定的小份。没被提到、或提到的人还没攒出过内容时，这块钱一分不花
# （见 summary_block 的 aside）
ASIDE_SUMMARY_TOKEN_BUDGET = 300
# 【你】和【在场】是新增的两块。各自先限额再拼，否则总量超标时从尾部切，
# 先切掉的正好是排在后面的叙事样例和此前剧情。
# 800 是给内容的，多出来的 80 是给 PRIVATE_SHEET_NOTE 那句提醒的。不单给的话
# 那句话会挤占正文额度，而这一块超预算时先裁的是背包（见 _state_block）——
# 为了说一句「别人不知道你有什么」把真有的东西裁掉一件，很荒唐
STATE_TOKEN_BUDGET = 880
# 全体在场角色分这一份。一个写全了的角色（简介+人设+四栏档案）自己就能吃掉
# 两三千字，所以 3000 token 时**一个人写满就超**，五六个人同框必然走降级链；
# 而降级是**整块砍掉所有人的档案段**、不是按人截短，于是写得越长模型看到的
# 反而越少。10000 约合 6600 字，够五六个人各带一份完整档案——这正是
# _npc_block 的注释一直声称、但 3000 根本兑现不了的目标。
# 抬这个数必须同时抬 SYSTEM_TOKEN_BUDGET，否则多出来的是从尾巴上抢的
NPC_TOKEN_BUDGET = 10000
# 【外场】是「已经传开的事」，和状态同类：都是已发生的硬事实
CHRONICLE_TOKEN_BUDGET = 800
# 【数值的含义】是作者写死的一小段，每轮一遍。给得紧：它只该是几行钥匙，
# 真要长篇解释数值该写在世界观里
MEANING_TOKEN_BUDGET = 400
# 【场面】的额度。原先这里是给「借场面线的原文」留的三份额度（原文 600 +
# 开场白 600 + 概要 300），历史统一成一条之后没得借了——那些原文本来就在
# 窗口里。现在这一块只放**不在消息里的东西**：地点描述和在场名单，
# 几百 token 足够，额度小是因为它真的只剩这么点内容
SCENE_TOKEN_BUDGET = 400
# 【道具与技能】的额度。它是**静态的模组说明书**，每轮一模一样，所以给得紧：
# 一条只占「名字 + 一句话」，700 大约能放五六十条，够绝大多数模组一次列全
CATALOG_TOKEN_BUDGET = 700
# 每条说明留多少字。作者的道具描述可能写了两百字，整段塞进来就是把世界观
# 又抄了一遍——模型这里要的只是「这东西长什么样」
CATALOG_DESC_CHARS = 40

# 每个人卡片上「经历」那一段的条数和额度。它和「眼下」「最近」是一类东西
# （见 _one_npc），差别是它只追加、永不覆盖。
# 条数刻意比小说侧那份 character_history 的「最近 10 条」少一半：游戏侧一回合
# 比小说一章细得多，10 条摊开能占掉小半张卡，而它只是**指针**——真要看细节的
# 都在【此前剧情】里。额度是单人份，由 _npc_history_lines 从尾部裁
NPC_HISTORY_LINES = 5
NPC_HISTORY_TOKEN_BUDGET = 220

# 【关系的转折】整段的额度。**不并进 NPC_TOKEN_BUDGET**：那一块是「在场每个人
# 的卡」按人分，这一块是全局共享的一份事实锚按时间裁。混进去之后，话多的那个人
# 的经历会把别人的里程碑挤出预算，而里程碑恰恰是别人那份关系唯一的来历
MILESTONE_TOKEN_BUDGET = 400

# 【道具与技能】的抬头。这段话挡的是这一块自带的两个风险：一是模型看见清单
# 就默认玩家全都有（于是主角凭空掏出还没拿到的药水），二是它照着 effects 在
# 正文里自己报数字（数值是引擎按 effects 算的，两边一定对不上）
CATALOG_PREAMBLE = (
    "以下是这个模组里定义过的道具和本事，作用是让你知道这世界上到底有哪些东西，"
    "好在剧情里安排它们出现。**背包和技能栏的实况以【你】那一段为准**，"
    "标着「还没到他手里」「还没学会」的，只有剧情真让他拿到或学到才算数，别默认他有。"
    "数值增减一律由引擎结算，你不要在正文里报数字。"
)

# 【你】那一段的抬头。挡的是上面那条的反面：背包/技能/手上的事本来就该给 GM 看，
# 但 GM 同时在写屋里所有人的台词，没人告诉他这是玩家一个人的底细，于是路边摊贩
# 张口就问「你送信送到哪了」。三个口子（见过、说过、他交代的）必须留着，写成
# 「NPC 一律不知道」就会把镜像那个 bug 放回来——她亲眼看着你翻出剑谱，下一轮
# 却不知道你有（见 _scene_line）
PRIVATE_SHEET_NOTE = (
    "（下面的背包、技能、手上的事是他自己的底细。写给你看是让你判断事情做不做得成，"
    "不是屋里每个人都看过——除非那人亲眼见他拿出来过、他自己说过，"
    "或者这桩事本来就是那人交代给他的。当前处境写的是世上已经发生的事，不算底细。）"
)

# 【角色总表】的额度和抬头。这一块只有名字，没有任何设定——设定归【在场】，
# 那一块按「在场 + 被提到」筛，不在场又没被点名的人一个字都拿不到。于是模型
# 写到他时只有称谓可用（「太玄天宗宗主」），而称谓和真名一个字都不重叠，
# 结算那边的去重名单（filter_discoveries 的 known）就认不出这是已登记的人，
# 侧栏里凭空多出一条「新角色」。给一份名字清单是最小的解：几十 token，
# 让模型有名字可写，也就让 known 有东西可挡。
# 一条只占三五个 token，300 大约能列六七十人，够绝大多数模组一次列全
#
# **一句简介也是非给不可的**，理由同 catalog_block：只给名字的话，模型知道
# 有这么个人，却不知道他是谁的宗主、跟玩家什么关系，照样会自己编一个补上。
# 1500 大约放得下十五个写全了的角色；超了就先砍简介、只留名字（名字是这一块
# 的底线，见 roster_block），所以这个数松一点不要紧
ROSTER_TOKEN_BUDGET = 1500
# 每人简介留多少字。同 CATALOG_DESC_CHARS 的道理：作者可能在简介里写了一整段
# 来历，全塞进来就是把角色卡又抄了一遍，而这一块要的只是「他是谁」
ROSTER_DESC_CHARS = 60
ROSTER_PREAMBLE = (
    "以下是这个模组里已经登记的全部角色。写到他们中的任何一个时，**必须用这里的名字**，"
    "不能只用称谓或头衔代替（不要写「那位宗主」而不给名字）。"
    "**这不是在场名单**——谁在跟前看【场面】那一段。"
    "每人后面那一句是他不在场时你能用的全部信息；等他真出场、或者这一轮被提到，"
    "你会拿到完整的卡，那时候再照卡写。"
    "清单之外的人只能是无名路人，不要给他们名字和来历。"
)

# 裁决那一步用的角色名单（见 ref_roster）。它比【角色总表】瘦：那张表的长篇
# 规矩是给叙事模型立的，裁决只需要「谁是谁」够它认人。每人一行，简介留这么多字，
# 一般十来个角色也就几百字，跑在快模型上
REF_DESC_CHARS = 40

# ── 「帮我想想」那一路的独立预算 ──────────────────────────────────────────
# **这一组不进 SYSTEM_TOKEN_BUDGET。** 上面那 21500 是**叙事模型那一份**的总闸，
# 读者是写正文的 GM；这一组是**建议模型那一份**，读者是那个只输出三行候选的
# 便宜档。两边的读者完全不同，混进一个数里会让改任何一边都要重算另一边，
# 而它们本来没有关系。这一组自己封顶在 SUGGEST_TOKEN_BUDGET。
#
# 作者改模组改不到这里，所以额度写死。加块时记得同步 `suggest_blocks` 的
# 拼接顺序和它返回的 diag（各块 token，**前端不渲染**，只给调预算的人看）。
SUGGEST_STATE_BUDGET = 600
SUGGEST_CAST_BUDGET = 600
# 当前地点 + 能去的地方合成一块。地点表可能很长，所以给得比其它块松一点：
# 一条只占「名字 + 半句描述」，多数模组一次列得完
SUGGEST_PLACES_BUDGET = 700
SUGGEST_ACTIONS_BUDGET = 400
SUGGEST_WORLD_BUDGET = 400
SUGGEST_TOKEN_BUDGET = 2700
# 建议里的简介留多少字。同 CATALOG_DESC_CHARS 的道理：建议模型要的只是
# 「她是谁」，作者写在简介里的整段来历在这一块是纯浪费
SUGGEST_CAST_DESC_CHARS = 30
SUGGEST_PLACE_DESC_CHARS = 30

# 【外场】的抬头。这段固定话术是**口吻的一部分**，不是客套：大事记注入每
# 一条线，等于所有 NPC 全知，所以必须明说「听说」不等于「亲眼见过」，
# 否则玩家在密室里做的事，隔着半个镇子的老兵也会知道
CHRONICLE_PREAMBLE = (
    "以下是这一带已经传开的事。人尽皆知的传闻，不等于每个人亲眼见过——"
    "谁在场、谁只是听说，按各自的位置来。"
)

# 【关系的转折】的抬头。它挡的是这一块最容易出的事：模型看见一条「动心」，
# 就让当事人张口把这件事说出来。这些是已经发生过的事实，不是桌上的话题——
# 它进上下文是为了让模型**写这两个人时按它算**，不是为了让它被谁提起
MILESTONE_PREAMBLE = (
    "以下是已经发生过、把某两个人的关系推到现在这个样子的事。"
    "数值那一行只说「现在多近」，这里说的是「为什么会这样」——"
    "写到这两个人之间时按这些事实算，不要另编一段来历。"
)

# 【场面】的抬头。它挡的是一件单独的事：**模型是 GM，知道全场，但在场的
# 角色不是全知**。统一时间线之后它看得见玩家独自做的事、也看得见别人和玩家
# 的私聊，而它写的是面前这几个人的反应——没人愿意看到 NPC 张口就是她不该
# 知道的事。所以「谁知道什么」的判据必须写在这里
SCENE_PREAMBLE = (
    "在场的人只知道**自己也在场**的那些事。你在别处、或在别人不在场时做的事，"
    "他们不知道，除非有人告诉过他们——不要让他们主动提起。"
)

# 玩家在输入框上方明着选的三个模式。群聊=在场的都参与；私聊=只跟那一个人说话，
# 这段话也只记进她的记忆；独自行动=这一轮不跟人说话，但在场的人看着（见 turn_present）
GROUP_MODE = "group"
PRIVATE_MODE = "private"
SOLO_MODE = "solo"
TURN_MODES = (GROUP_MODE, PRIVATE_MODE, SOLO_MODE)

DEFAULT_CHAR_NAME = "冒险者"

# 各档位该怎么写。由后端查表生成而不是让模型自由发挥——
# roll-then-narrate 最常见的翻车就是模型拿到「失败」却写着写着自己救回来了
OUTCOME_GUIDANCE = {
    "crit_success": "做成了，而且比预想的更好。多给一点：一个额外的发现、一个没料到的便利，或是让在场的人对你另眼相看。",
    "success": "做成了，干净利落。不要额外加代价。",
    "narrow": "做成了，但付出了看得见的代价。",
    "fail": "没做成。事情卡在那儿，处境还因此麻烦了一点。",
    "crit_fail": "不但没做成，还引出了新的麻烦。",
}

# 代价要具体。数值名现在是模组作者自己取的，没法按名字查预设提示，
# 所以只留这一条通用的
DEFAULT_COST_HINT = "代价要具体：受伤、丢东西、弄出声响被发现、耽误时间、让某人对你更警惕，挑一个写实的。"

# 夹逼的后半句。头尾各写一遍是对硬事实最有效的做法，代价几十 token
OUTCOME_TAIL = {
    "crit_success": "不要在后面又加上代价。",
    "success": "不要在后面又加上代价。",
    "narrow": "不要把它写成干净利落的成功，代价必须落在纸面上。",
    "fail": "不要写着写着把它救回来。",
    "crit_fail": "不要写着写着把它救回来。",
}

_KEYWORD_SEP = re.compile(r"[,，、;；\n]+")


def _split_keywords(text: str) -> list[str]:
    """顿号和分号也算分隔符，理由同酒馆：中文列举本来就爱用顿号。"""
    return [k.strip() for k in _KEYWORD_SEP.split(text or "") if k.strip()]


def triggered_entries(
    entries: list[RpgWorldEntry],
    scan_text: str,
    sess: RpgSession | None = None,
    npcs: list[RpgNpc] | None = None,
) -> list[RpgWorldEntry]:
    """本轮生效的词条：常驻的全要，其余看关键词是否命中，最后一律过数值条件。

    子串匹配而不是分词：关键词是用户逐条写死的，「出现这个词就触发」才可预测。

    trigger_condition 是附加约束，加在关键词之后而不是替代它——
    「常驻+条件」就是阈值事件（好感过 50 她的态度变了），
    「关键词+条件」是提到了且够格才注入。这一层让世界书兼任事件系统。
    """
    haystack = (scan_text or "").lower()
    hits = []
    for entry in entries:
        if not entry.enabled or not (entry.content or "").strip():
            continue
        if entry.constant:
            matched = True
        else:
            matched = bool(haystack) and any(
                kw.lower() in haystack for kw in _split_keywords(entry.keywords)
            )
        if not matched:
            continue
        # sess 为 None 时跳过条件检查：纯关键词测试和预览都用不到状态
        if sess is not None and not check_condition(entry.trigger_condition, sess, npcs)[0]:
            continue
        hits.append(entry)
    return hits


def world_npcs(npcs: list[RpgNpc]) -> list[RpgNpc]:
    """能当「世界里的角色」用的那些。

    主角模板是开局时预填玩家自己的那张卡，不登场。前端一直按这条过滤
    （condition.ts 的 knownNpcs），后端也不能把它当 NPC 发进提示词。
    """
    return [n for n in npcs if (n.role or "npc") != "protagonist"]


def npc_place(
    npc: RpgNpc, slot: str = "", places: dict | None = None,
    followers: list | None = None, here: str = "",
) -> str:
    """这个人此刻在哪儿：剧情挪过她就听剧情的，否则跟着你，再否则作息表 → 常驻地点。

    **这不是第二个「在场」判据**，只是把 location 的取值方式换成了按时段查表。
    谁在场仍然只有一种问法（here_npcs），前端 condition.onstage 是它的镜像，
    两边一起改，否则会出现「面板上站在你面前、提示词里没这个人」。

    places 是这一局的 npc_places：玩家在对话框里说「你过来」之后，结算把她的
    位置写在里面。它是**剧情的事实**，优先于作息表这个**设定**；推时段时仍在
    玩家身边的人保留位置，离场者恢复日常安排。传 None（比如模组编辑页）就
    当它不存在，行为和加这一列之前逐字一致。

    followers 是这一局的 npc_followers，here 是玩家此刻的地点。跟上你的那一层
    解析出来就是 here，所以**玩家一走动她就在那儿了，零写入**——不需要任何
    「移动之后同步一遍」的收口，也就不可能和 sess.location 分叉。她被剧情单独
    挪过（places 里有她）时仍然以剧情为准，那正是「你在这儿等我」该有的效果。
    """
    over = str((places or {}).get(str(npc.id)) or "").strip()
    if over:
        return over
    if here and followers and npc.id in followers:
        return str(here).strip()
    table = npc.slot_locations if isinstance(npc.slot_locations, dict) else {}
    now = (slot or "").strip()
    if now:
        at = str(table.get(now) or "").strip()
        if at:
            return at
    return (npc.location or "").strip()


def named_npcs(npcs: list[RpgNpc], text: str) -> list[RpgNpc]:
    """名字（或触发词）在这段文字里出现过的人。

    给「位置」那条写入路径当允许名单：只有**刚写出来的正文里真的出现了**
    的人，才准结算改他的位置。比 onstage_npcs 的「被提到」再紧一层——
    玩家嘴上抱怨一句马尔福，不该把马尔福挪到他跟前；正文里写了他推门进来，
    才叫剧情真的动了这个人。

    认名字的口径和小节和 onstage_npcs 一致（真名子串 + 触发词）。
    """
    haystack = (text or "").lower()
    if not haystack:
        return []
    hits = []
    for npc in world_npcs(npcs):
        name = (npc.name or "").strip().lower()
        if (name and name in haystack) or any(
            kw.lower() in haystack for kw in _split_keywords(npc.keywords)
        ):
            hits.append(npc)
    return hits


def here_npcs(
    npcs: list[RpgNpc], location: str, slot: str = "", places: dict | None = None,
    followers: list | None = None,
) -> list[RpgNpc]:
    """就在玩家当前地点的人。

    「在场」只有这一个定义：注入设定要它，标记见过面也要它，写消息的 present 列
    也要它。两边各写一遍迟早会分叉——分叉的那一次就是「同屋的另一个人拿不到
    自己的设定，模型只能现编他」。

    slot 传空（没设时段、或调用方不关心时间）时作息表不参与，一律按常驻地点算，
    和没有这个功能时逐字一致。followers 传这一局的 npc_followers：跟着你的人
    在这里当然算在场，而 location 就是「她在哪儿」的答案。
    """
    here = norm_name(location)
    if not here:
        return []
    return [
        npc for npc in world_npcs(npcs)
        if norm_name(npc_place(npc, slot, places, followers, location)) == here
    ]


def present_ids(
    npcs: list[RpgNpc], location: str, slot: str = "", places: dict | None = None,
    followers: list | None = None,
) -> list[int]:
    """这一刻在场的 NPC id 列表。写进消息的 present 列（见 RpgMessage.present）。

    和 here_npcs 同源、不另算一套：「谁在场」全项目只有一个定义。它和
    onstage_npcs 的差别正是这里要的差别——**被提到但不在跟前的人不算在场**。
    算进去的话，你在酒馆提一句老兵，老兵就成了这场戏的见证人。

    **没有地点 = 所有人都在同一个场面里**，这条读法照抄 _settle 里那一份
    （那边管它叫 who）：模组一个地点都没建时 here_npcs 恒为空，不兜底的话
    这类纯对话模组的每条消息都会变成「只有玩家一个人」，每个 NPC 的视图全空。

    调用方必须在**写消息的那一刻**调它：npc_places 会被作息表和剧情改动，
    事后拿 sess 回查算出来的是「现在谁在」，不是「当时谁在」。
    """
    if not (location or "").strip():
        return [n.id for n in world_npcs(npcs)]
    return [n.id for n in here_npcs(npcs, location, slot, places, followers)]


def turn_present(
    npcs: list[RpgNpc], sess: RpgSession, mode: str, private_with: int | None,
) -> list[RpgNpc]:
    """这一轮算「在场」的那几个人。**写消息的 present 列和拼上下文共用这一份。**

    群聊和独自行动都是屋里站着谁就是谁——「独自行动」只是这一轮不跟人说话，
    不是「没人看见」。她眼睁睁看着你从箱底翻出剑谱，判成没人在场的话，下一轮
    她不知道你有剑谱，那是失忆 bug 的镜像版。

    私聊把名单收窄到那一个人，于是这段话只记进她的记忆。要求她**本来就在场**：
    不在跟前的人叫不到一边去，否则会凭空造出一段两人都不在同一个地方的对话。
    """
    ids = set(present_ids(
        npcs, sess.location, sess.slot, sess.npc_places, sess.npc_followers,
    ))
    if mode == PRIVATE_MODE and private_with in ids:
        ids = {private_with}
    return [n for n in npcs if n.id in ids]


def onstage_npcs(
    npcs: list[RpgNpc], location: str, scan_text: str, slot: str = "",
    places: dict | None = None, followers: list | None = None,
) -> list[RpgNpc]:
    """这一轮要注入设定的人：在场的，加上被名字或触发词提到的。

    后一半是为了「人不在这儿但这一轮聊到了他」——没有它，玩家问"老兵说过什么"
    时模型手上没有老兵的任何设定，只能现编。

    注意「注入」不等于「见过面」：被提到的人这一轮拿到设定，但不能因此算作
    他的外貌已经描写过。标记见过面的只有 here_npcs 那一份。
    """
    spots = {id(npc) for npc in here_npcs(npcs, location, slot, places, followers)}
    haystack = (scan_text or "").lower()
    hits = []
    for npc in world_npcs(npcs):
        if id(npc) in spots:
            hits.append(npc)
            continue
        if not haystack:
            continue
        name = (npc.name or "").strip().lower()
        if (name and name in haystack) or any(
            kw.lower() in haystack for kw in _split_keywords(npc.keywords)
        ):
            hits.append(npc)
    return hits


def _qty(item: dict) -> int:
    try:
        return int(item.get("qty", 1))
    except (TypeError, ValueError):
        return 1


def _flag_text(value) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    return str(value)


def _stat_text(specs: dict[str, dict], name: str, value) -> str:
    """一项数值怎么写给模型看。有上限就写成 62/100——
    模型判断「快没了」需要看到分母，只给 62 它不知道这是高还是低。

    作者写了分档就追加当前那一档的短标签：好感 62/100（亲近）。
    **只追加标签，不追加那一档的解释**——解释在【数值的含义】里整轮发一次。
    关系定义是全体 NPC 共用的一份，跟在数字后面等于同一句话按在场人数重复，
    而 NPC 那块的预算只有 800 字上下（见 _npc_block）。
    """
    spec = specs.get(name) or {}
    top = spec.get("max")
    text = f"{name} {value}/{top}" if top is not None else f"{name} {value}"
    tier = tier_of(spec, value)
    label = str((tier or {}).get("label") or "").strip()[:TIER_LABEL_CHARS]
    return f"{text}（{label}）" if label else text


def _meaning_block(module: RpgModule) -> str:
    """【数值的含义】段。作者写的「这个数值影响什么」+ 每一档什么样。

    整轮发一次，排在【你】之前：说明是**静态的定义**，但它是读懂后面所有数字
    的钥匙，被尾部截断切掉的话，模型看到的就又是一串没有意思的数字了。

    隐藏的数值也进这一块，同 _compose_state 的既定理由：隐藏只是不给玩家看，
    GM 得知道怀疑度到 80 了会发生什么。
    """
    groups = (("你的数值", module.stat_defs), ("对你的关系", module.relation_stat_defs))
    lines: list[str] = []
    for title, defs in groups:
        rows = []
        for name, spec in def_map(defs).items():
            effect = str(spec.get("effect") or "").strip()[:EFFECT_CHARS]
            bands = []
            for tier in tier_list(spec):
                label, note = tier["label"], tier["note"]
                if not label and not note:
                    continue
                at = tier["at"]
                bands.append(f"{at} 起 {label}={note}" if label and note else f"{at} 起 {label or note}")
            if not effect and not bands:
                continue
            row = f"- {name}：{effect}" if effect else f"- {name}："
            if bands:
                row = (row + "。" if effect else row) + "；".join(bands)
            rows.append(row)
        if rows:
            lines.append(f"{title}：")
            lines.extend(rows)
    if not lines:
        return ""
    return truncate_to_token_budget("【数值的含义】\n" + "\n".join(lines), MEANING_TOKEN_BUDGET)


def _scene_line(here: list[RpgNpc], mode: str) -> str:
    """【你】里的「此刻」那一行：这一轮到底是在干什么。

    三个模式是玩家在输入框上方**明着选的**，不是猜出来的。它必须写进提示词
    而不只是拿去筛在场名单——不写的话，选了「独自行动」模型照样会让旁边那位
    搭话，而那句话是她说的、她自己却不该记得（她这一轮压根没被当成对话方）。

    「独自行动」**不等于「没人看见」**：屋里站着谁就写谁在旁边看着。判成没人的
    话会出上一个失忆 bug 的镜像版——她亲眼看着你翻出剑谱，下一轮却不知道你有。
    """
    names = "、".join((n.name or "").strip() for n in here)
    if mode == PRIVATE_MODE and here:
        return f"此刻：你把{names}叫到一边单独说话，旁人听不见这一段"
    if mode == SOLO_MODE:
        if here:
            return f"此刻：你在做自己的事，没有在跟谁说话；{names}在旁边看着"
        return "此刻：没有别人在场，只有你一个人"
    if len(here) == 1:
        return f"此刻：你正在与{names}单独说话"
    if here:
        return f"此刻：在场的是你与{names}，这是群戏"
    return "此刻：没有别人在场，只有你一个人"


_PENDING_KIND_LABELS = {
    "npc": "人物", "place": "地点", "item": "东西", "skill": "本事", "task": "差事",
}
# 每类最多列几个名字。这一块和手上的事、当前处境共用 STATE_TOKEN_BUDGET 那
# 800 token，条目一多就会把背包挤掉（超预算时先裁的正是背包），所以宁可
# 写「等 N 项」也不把整份清单抄一遍
_PENDING_LISTED = 4


def _pending_names(rows, labelled: bool = False) -> list[str]:
    """待确认清单里的名字。非字典、空名字一律跳过——照上面 todo 那段的写法。"""
    names: list[str] = []
    for entry in rows or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        if labelled:
            kind = _PENDING_KIND_LABELS.get(str(entry.get("kind") or "").strip())
            if not kind:
                continue
            name = f"{kind} {name}"
        names.append(name)
    return names


def _pending_block(sess: RpgSession) -> str:
    """【待确认】：已经报上来、玩家或作者还没点头的那些。空串 = 一样都没有。

    不说的话 GM 会把同一件事当新的再报一遍（发现项按名字去重，于是永远进不来），
    或者张口替玩家把道具认下来、把差事收了线——那两件事都只能玩家点头。
    """
    groups = (
        ("待认领的道具", _pending_names(getattr(sess, "item_claims", None))),
        ("待登记的发现", _pending_names(getattr(sess, "discoveries", None), labelled=True)),
        ("待点头的收线", _pending_names(getattr(sess, "task_proposals", None))),
    )
    rows = []
    for title, names in groups:
        if not names:
            continue
        shown = "、".join(names[:_PENDING_LISTED])
        if len(names) > _PENDING_LISTED:
            shown += f"　等 {len(names)} 项"
        rows.append(f"- {title}：{shown}")
    if not rows:
        return ""
    return (
        "待确认（已经报过、还没被点头的：剧情里别当新的再来一遍，也别替玩家点头）\n"
        + "\n".join(rows)
    )


def _compose_state(
    sess: RpgSession, specs: dict[str, dict], items: list[dict], keep: int,
    here: list[RpgNpc] | None = None, mode: str = GROUP_MODE,
) -> str:
    lines = [f"【你】{(sess.char_name or '').strip() or DEFAULT_CHAR_NAME}"]
    # 跟在抬头后面、不排到末尾：_state_block 兜底那条路走 truncate_to_token_budget，
    # 刀是从尾巴上切的，放末尾这句会第一个被切掉
    lines.append(PRIVATE_SHEET_NOTE)
    if (sess.char_desc or "").strip():
        lines.append(sess.char_desc.strip())
    # 数值表整份给模型，包括 display=隐藏 的——隐藏只是不给玩家看见，
    # GM 得知道怀疑度已经 80 了
    stats = sess.stats or {}
    if stats:
        lines.append("状态：" + "　".join(
            _stat_text(specs, k, v) for k, v in stats.items()
        ))
    if (sess.location or "").strip():
        lines.append(f"所在：{sess.location.strip()}")
    # 时间只在模组设了时段时才出现。模型看得见才会照着写，
    # 看不见它就会自己编「不知不觉天黑了」
    slot = str(getattr(sess, "slot", "") or "").strip()
    if slot:
        lines.append(f"时间：第 {max(1, int(getattr(sess, 'day', 1) or 1))} 天 · {slot}")
    # 这一幕是几个人、在干什么。判据取**实际在跟前的人**加玩家选的模式，不再
    # 取「这条线是谁的」——线已经不存在了
    if here is not None:
        lines.append(_scene_line(here, mode))

    shown, rest = items[:keep], len(items) - keep
    rows = [
        f"- {item['name']}×{_qty(item)}"
        + (f"（{str(item.get('note')).strip()}）" if str(item.get("note") or "").strip() else "")
        for item in shown
    ]
    if rest > 0:
        rows.append(f"- 以及其他 {rest} 件杂物")
    lines.append("背包：\n" + "\n".join(rows) if rows else "背包：空")

    # 会哪些招。冷却中的也列出来并标明——GM 知道这一招正歇着，才会写
    # 「你伸手去掐诀，指尖还是麻的」而不是让玩家凭空又来一遍
    skills = [
        s for s in (sess.skills or [])
        if isinstance(s, dict) and str(s.get("name") or "").strip()
    ]
    if skills:
        lines.append("技能：" + "　".join(
            f"{str(s['name']).strip()}"
            + (f"（还要歇 {int(s['cooldown_left'])} 回合）"
               if int(s.get("cooldown_left") or 0) > 0 else "")
            for s in skills
        ))

    # 手上还挂着的事。GM 知道这些，才会让剧情往这几条上靠，而不是每一轮
    # 都开一摊新的。状态块统共只有 800 token，列多了会把别的挤掉，所以封顶 8 条
    todo = [
        str(t.get("name") or "").strip() for t in (sess.tasks or [])
        if isinstance(t, dict) and str(t.get("status") or "open") == "open"
        and str(t.get("name") or "").strip()
    ]
    if todo:
        line = "手上的事：" + "　".join(todo[:8])
        if len(todo) > 8:
            line += f"　以及其他 {len(todo) - 8} 桩事"
        lines.append(line)

    flags = {k: v for k, v in (sess.flags or {}).items() if v is not None}
    if flags:
        lines.append("当前处境：\n" + "\n".join(f"- {k}：{_flag_text(v)}" for k, v in flags.items()))

    # 排在最后：它是这一轮「还有什么悬着」，比已经落地的处境更靠后一层。
    # 三样都空时一个字都不出来（绝大多数轮次如此），不占那 800 的预算
    pending = _pending_block(sess)
    if pending:
        lines.append(pending)
    return "\n".join(lines)


def _state_block(
    sess: RpgSession, module: RpgModule, here: list[RpgNpc] | None = None,
    mode: str = GROUP_MODE,
) -> str:
    """【你】段。超预算时先裁背包，不让截断的刀切在数值上。

    背包按数量降序保留——囤了 20 支箭比捡了一块石头更可能被用上。
    """
    specs = def_map(module.stat_defs)
    items = [
        it for it in (sess.inventory or [])
        if isinstance(it, dict) and str(it.get("name") or "").strip()
    ]
    ordered = sorted(items, key=lambda it: -_qty(it))
    block = ""
    for keep in range(len(ordered), -1, -1):
        block = _compose_state(sess, specs, ordered, keep, here, mode)
        if estimate_tokens(block) <= STATE_TOKEN_BUDGET:
            return block
    # 背包裁空了还超，说明是角色描述太长，这时才允许截断
    return truncate_to_token_budget(block, STATE_TOKEN_BUDGET)


def _owned(rows) -> set[str]:
    """这一局已经在手上 / 已经会了的那些名字。"""
    return {
        norm_name(str(row.get("name") or ""))
        for row in rows or []
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    }


def _catalog_group(rows, owned: set[str], label: str, yes: str, no: str,
                   desc_chars: int, keep_rest: bool) -> list[str]:
    """一类东西的行。已经有的排前面：超预算时降级先丢的该是他还没有的那些。"""
    mine: list[str] = []
    rest: list[str] = []
    for row in rows or []:
        name = str(getattr(row, "name", "") or "").strip()
        if not name:
            continue
        has = norm_name(name) in owned
        desc = " ".join(str(getattr(row, "description", "") or "").split())[:desc_chars]
        line = f"- {name}（{yes if has else no}）" + (f"：{desc}" if desc else "")
        (mine if has else rest).append(line)
    if not keep_rest:
        rest = []
    return [f"{label}：", *mine, *rest] if (mine or rest) else []


def catalog_block(items, skills, sess: RpgSession) -> str:
    """【道具与技能】——这个模组定义过的东西的说明书。

    没有这一块的话，没勾「开局就有」/「开局就会」的道具和技能，GM 压根不知道
    它们存在，于是这一局里**永远不会出现**——作者辛苦定义的一摊东西，除非手动
    写进开局背包，否则玩家一辈子见不着。这是它存在的唯一理由。

    只给名字加一句话，**不给 effects**：数值增减是引擎按 effects 算的，把数字
    摆进提示词只会诱导模型在正文里自己报一遍，两边一定对不上。

    超预算时三级降级：先砍掉说明只留名字，再砍掉「他还没有的」那一半，
    最后才真截断——切掉的顺序是从最不要紧的开始。
    """
    owned_items = _owned(getattr(sess, "inventory", None))
    owned_skills = _owned(getattr(sess, "skills", None))
    block = ""
    for desc_chars, keep_rest in ((CATALOG_DESC_CHARS, True), (0, True), (0, False)):
        lines = [
            *_catalog_group(items, owned_items, "道具", "他身上有", "还没到他手里",
                            desc_chars, keep_rest),
            *_catalog_group(skills, owned_skills, "本事", "他已经会", "还没学会",
                            desc_chars, keep_rest),
        ]
        if not lines:
            return ""
        block = "【道具与技能】\n" + CATALOG_PREAMBLE + "\n" + "\n".join(lines)
        if estimate_tokens(block) <= CATALOG_TOKEN_BUDGET:
            return block
    return truncate_to_token_budget(block, CATALOG_TOKEN_BUDGET)


def _when(entry: dict) -> str:
    """一条流水的时间戳。时间是引擎在写入那一刻盖的（见
    rpg_settlement.apply_proposal），不是模型填的，所以可以直接信。
    没配时段表的模组只有「第 N 天」。"""
    try:
        day = max(1, int(entry.get("day") or 1))
    except (TypeError, ValueError):
        day = 1
    slot = str(entry.get("slot") or "").strip()
    return f"第 {day} 天 · {slot}" if slot else f"第 {day} 天"


def _npc_history_lines(sess: RpgSession, npc_id: int) -> list[str]:
    """这个人最近几条经历，一行一条。从尾部取——新的比旧的更可能用得上。

    额度是按**单人**给的：不这么裁的话，一个玩得久的人能自己吃掉整块
    NPC_TOKEN_BUDGET，把同场其他人的卡挤没。
    """
    rows = (sess.npc_history or {}).get(str(npc_id)) or []
    lines = [
        f"{_when(entry)}｜{str(entry.get('content') or '').strip()}"
        for entry in rows
        if isinstance(entry, dict) and str(entry.get("content") or "").strip()
    ]
    if not lines:
        return []
    body = truncate_to_token_budget(
        "\n".join(lines[-NPC_HISTORY_LINES:]), NPC_HISTORY_TOKEN_BUDGET, keep_end=True,
    )
    return [line for line in body.split("\n") if line.strip()]


def _one_npc(
    npc: RpgNpc, sess: RpgSession, specs: dict, examples: bool, profile: bool,
) -> str:
    """一个人的卡片。examples/profile 是降级开关，见 _npc_block。"""
    state = (sess.npc_states or {}).get(str(npc.id)) or {}
    # 档案先归一：老库里可能存着向导早期发的英文键，而下面是拿 key 当标签直接拼的，
    # 键是英文模型看到的就是 "background：…"。外貌那一格也顺手归到顶层，
    # 免得同一段长相在卡上出现两遍
    sections, appearance = normalize_profile_sections(npc.profile_sections, npc.appearance)
    # 姓名带标签，不发裸名字。裸名字加换行再接简介，中文里会被读成所属关系：
    # 「步明台 / 藏剑阁盲眼剑修遗孀……」被模型读成了「步明台的遗孀」，于是它把
    # 名字判给了死去的丈夫，又给那个寡妇现编了一个名字。卡上别的字段本来就都
    # 带标签（对你／眼下／最近／经历），名册那两块也有冒号，只有这里是裸的
    lines = [f"姓名：{npc.name}"]
    if (npc.description or "").strip():
        lines.append(npc.description.strip())
    if (npc.persona or "").strip():
        lines.append(npc.persona.strip())
    # 外貌一律发。原先按 met 只在「还没见过」时给，省下的是每轮一段长相，
    # 代价有两笔：见过面之后人去了别处、又被提到，模型手上就没有长相，只能
    # 现编一个；更要命的是截断把整张卡切掉时 met 照样会被标记（见 _npc_block），
    # 于是那个人的长相从此永远不会再出现。长相是认出一个人的最低要求，
    # 不该拿去换 token——真出现「反复描写同一张脸」，那该在提示词里治
    # 年龄和长相一起发，理由同上：它也是「认出这个人」的一部分，缺了模型就现编
    # 一个，而年龄一编错，说话的口气和称呼跟着全错
    if (npc.age or "").strip():
        lines.append(f"年龄：{npc.age.strip()}")
    if appearance.strip():
        lines.append(appearance.strip())
    # 这一局被改写掉的外貌，**紧贴作者原文后面**发，并明说以它为准。
    #
    # 位置是这块的全部意义：作者那段写着「平坦」的原文永远在那儿，模型把它当
    # 设定、把别处一句「眼下：……」当细节，二选一时挑设定。两行挨着、并且指名
    # 后者推翻前者，它才有依据改口。
    #
    # 不参与下面的档案降级（在 `if profile:` 之外）：和上面那段作者原文同一个
    # 道理——长相是认出一个人的最低要求，何况这一份才是此刻**真的**那样
    rewritten = (sess.npc_appearance or {}).get(str(npc.id)) or {}
    if isinstance(rewritten, dict) and rewritten:
        lines.append(
            "外貌已被改写（以此为准，作者的设定已被推翻）："
            + "；".join(f"{k} {v}" for k, v in rewritten.items())
        )
    # 标签就是键本身，所以键必须是中文——normalize 之后一定是（也只剩有内容的）
    if profile:
        for key, text in sections.items():
            lines.append(f"{key}：{text}")
    # 关系数值是这个模式的核心：模型得知道「好感 62/100」才知道
    # 她现在该用什么态度说话
    relations = [
        _stat_text(specs, k, v) for k, v in state.items() if k != "met"
    ]
    if relations:
        lines.append("对你：" + "　".join(relations))
    # 这一局 GM 记下来的近况：伤在哪、身上带着什么、会什么。作者写的档案是
    # 死的，这一行是活的，所以它和 profile_sections 一起降级也不合适——
    # 「她左肩还在流血」比「她的背景故事」更该留在提示词里，排在示例之前
    notes = (sess.npc_notes or {}).get(str(npc.id)) or {}
    if isinstance(notes, dict) and notes:
        # 不用「此刻：」：_compose_state 已经拿它表示「你在和谁单独说话」，
        # 两块隔着几百字，同一个词两个意思
        lines.append("眼下：" + "；".join(f"{k} {v}" for k, v in notes.items()))
    # AI 调度替她写的「最近在做什么」。她不在场时在别处自己过，玩家下回撞见
    # 她得看得出这段日子没白过——不然调度就只是个后台空转的计数器。
    # 紧跟在「眼下」后面：两行是一类东西（这一局里活着的近况），
    # 排在作者写的档案之后、对话示例之前
    activity = npc_activity(sess, npc.id)
    if activity:
        lines.append(f"最近：{activity}")
    # 这个人身上过了什么事（只追加的流水，见 models.RpgSession.npc_history）。
    # 排在「眼下」「最近」之后：那两行说「现在什么样」，这一段说「发生过什么」，
    # 越靠后越像背景；但仍排在对话示例之前，理由同 notes——
    # 「她上次差点没回来」比「她的背景故事」更该留在提示词里
    history = _npc_history_lines(sess, npc.id)
    if history:
        lines.append("经历：\n" + "\n".join(f"- {line}" for line in history))
    # 对话示例只作为文字引用，不做真实 few-shot 轮：那会让模型学着
    # 连玩家那一侧一起写
    if examples:
        shown = [
            f"玩家：{str(ex.get('user') or '').strip()}\n{npc.name}：{str(ex.get('assistant') or '').strip()}"
            for ex in (npc.dialogue_examples or [])
            if isinstance(ex, dict) and str(ex.get("assistant") or "").strip()
        ]
        if shown:
            lines.append("说话的样子：\n" + "\n".join(shown))
    return "\n".join(lines)


def _npc_block(
    npcs: list[RpgNpc], sess: RpgSession, module: RpgModule,
    here_ids: set[int] | None = None,
) -> str:
    """【在场】段。超预算时**从队尾逐个降级**（示例 → 档案 → 整张卡），最后才截断。

    队尾 = 最不相关的人，见下面 ordered 的排序：在跟前的一律排在前面，队尾
    只会是「只是被触发词扫到」的边缘人。所以这条链是**弃车保帅**——**站在你
    跟前的人一份都不会少**；被提到但不在跟前的人排在他们后面，只有前面的人
    全降级完了才会轮到，越靠后的先丢。

    原先那一版是**连坐**：`for examples, profile in ((True,True),(False,True),
    (False,False))` 先把**全体**的示例砍掉、再把**全体**的档案砍掉，正在跟你
    说话的那个人一起挨刀。实测三个真实存档的用量是 22%~44%，这条链一次都没
    跑过，所以它平时不发作；真发作那次砍错人的代价却由最相关的人承担。

    最后那道 truncate_to_token_budget 是兜底：卡全丢光了（只剩地点名册那几行）
    还超，才允许切。预算 NPC_TOKEN_BUDGET。

    在场的排前面：onstage_npcs 是按 sort_order 追加的，一个只是被提到名字
    的人能把真正站在跟前的人挤到后面、进而挤出预算。
    """
    specs = def_map(module.relation_stat_defs)
    here = (sess.location or "").strip()
    if here_ids is None:
        here_ids = {
            npc.id for npc in npcs
            if not here or norm_name(npc_place(
                npc, sess.slot, sess.npc_places, sess.npc_followers, here,
            )) == norm_name(here)
        }
    # 稳定排序：同组内仍按 sort_order。地点为空时全员等价，不重排
    ordered = sorted(npcs, key=lambda npc: npc.id not in here_ids)

    roster = ""
    if here:
        local = [npc for npc in ordered if npc.id in here_ids]
        if local:
            roster = (
                f"当前地点：{here}\n"
                "下面列出的是地图中已经登记、此刻就在当前地点的角色。"
                "优先让这些角色出场和互动；不要为同一职位、同一功能或同一场景另造一个有名 NPC。\n"
                "如果玩家刚抵达或只是观察环境，开场先从这份名册中选合适的角色回应；"
                "只有玩家明确避开人群、独处或要求新角色时才不让他们出场。\n"
                "括号里的 ID 只供系统识别，不要写进正文。\n"
                "地点角色名册：" + "、".join(
                    f"{n.name}(ID:{n.id})" for n in local
                ) + "\n\n"
            )

    # 档位：0 = 完整，1 = 丢说话示例，2 = 再丢四栏档案，3 = 整个人的卡不要了
    levels = ((True, True), (False, True), (False, False), None)
    marks = [0] * len(ordered)

    def compose() -> str:
        cards = (
            _one_npc(n, sess, specs, *levels[marks[i]]) if levels[marks[i]] else ""
            for i, n in enumerate(ordered)
        )
        return "【在场】\n" + roster + "\n\n".join(card for card in cards if card)

    block = compose()
    if estimate_tokens(block) <= NPC_TOKEN_BUDGET:
        return block
    # 从队尾往前逐个降级，每降一级重新估一次，装下就收手：最不相关的那个人
    # 先把细节丢光，丢光他还不够，才轮到排在他前面的那个人
    for i in range(len(ordered) - 1, -1, -1):
        for _ in range(len(levels) - 1):
            marks[i] += 1
            block = compose()
            if estimate_tokens(block) <= NPC_TOKEN_BUDGET:
                return block
    # 卡全丢光还超（只剩地点名册那几行），说明是描述本身太长，这时才允许切
    return truncate_to_token_budget(block, NPC_TOKEN_BUDGET)


def roster_block(npcs: list[RpgNpc]) -> str:
    """【角色总表】——这个模组登记过的所有角色，一人一行。空串 = 一个都没登记。

    同 catalog_block 的道理，只是换成人：没有这一块，不在场又没被点名的人
    对模型就等于不存在，于是它只能用称谓写他（「太玄天宗宗主」）。后果有两层——
    正文里那个人没有名字，而称谓骗过了结算的去重，他会被当成新角色报上来。

    **一行只有名字、常驻地、一句简介**，完整设定仍然是【在场】那一块的事
    （在场 + 被提到才发）——全员发全套设定就是把整个模组每轮抄一遍。而那句
    简介是非给不可的：少了它，模型只知道名单上有个叫姬清弦的人，不知道她是
    谁的宗主、跟玩家什么关系，于是照样自己编一个补上。

    带上常驻地点：没有它，模型看见一串名字会以为这些人都能随手叫过来。

    超预算时先砍简介、只留名字，最后才真截断——**名字是这一块的全部意义**，
    宁可没有简介也不能让排在后面的人连名字都掉出去（那正是这一块要修的 bug）。
    """
    rows = []
    for npc in world_npcs(npcs):
        name = (npc.name or "").strip()
        if not name:
            continue
        # 这里不查 npc_places / 作息表：那是「此刻在哪」，属于在场判定，
        # 而这一块给的是「他一般在哪」——一份静态的花名册
        place = (npc.location or "").strip()
        rows.append((
            name,
            f"（常在{place}）" if place else "",
            " ".join(str(npc.description or "").split()),
        ))
    if not rows:
        return ""
    block = ""
    for desc_chars in (ROSTER_DESC_CHARS, 0):
        block = "【角色总表】\n" + ROSTER_PREAMBLE + "\n" + "\n".join(
            f"- {name}{place}" + (f"：{desc[:desc_chars]}" if desc_chars else "")
            for name, place, desc in rows
        )
        if estimate_tokens(block) <= ROSTER_TOKEN_BUDGET:
            return block
    return truncate_to_token_budget(block, ROSTER_TOKEN_BUDGET)


def ref_roster(npcs: list[RpgNpc]) -> str:
    """裁决那一步看的角色名单：一人一行，名字 + 一句身份。空串 = 一个都没登记。

    **裁决也得认人。** 玩家说「回想自己的身世」，字面上一个名字都没有——
    onstage_npcs 只认全名和触发词，谁也匹配不上，于是那一轮模型手上没有任何
    卡可用，只能照世界观那两句现编。可这句话指向谁，看着这份名单的模型一眼
    就能认出来（他是宗主的私生子，宗主是澹台红绡），把它写进 refs 就行。

    比 roster_block 瘦：那一段的长篇规矩（不许拿称谓代替名字、这不是在场名单）
    是给叙事模型立的，和「这一轮涉及谁」这件事无关。
    """
    rows = []
    for npc in world_npcs(npcs):
        name = (npc.name or "").strip()
        if not name:
            continue
        desc = " ".join(str(npc.description or "").split())
        rows.append(f"- {name}：{desc[:REF_DESC_CHARS]}")
    return "\n".join(rows)


def resolve_refs(raw, npcs: list[RpgNpc]) -> list[str]:
    """把裁决报上来的 refs 收敛成模组里**真实存在**的角色名。

    白名单是必须的：模型多报一个名字，那一轮就凭空多出一张卡；更糟的是那个
    编出来的名字会被叙事模型当成真人写进正文。所以只认 world_npcs 里的名字。

    只报一半也认：「红绡」归到「澹台红绡」上——onstage_npcs 那边是全名子串匹配，
    少一个字就匹配不上，而玩家嘴里很少叫全名。
    """
    words = [
        str(w).strip() for w in (raw if isinstance(raw, list) else []) if str(w).strip()
    ]
    if not words:
        return []
    names = []
    for npc in world_npcs(npcs):
        name = (npc.name or "").strip()
        if name and any(w == name or w in name or name in w for w in words):
            names.append(name)
    return names


def judgement_blocks(judgement: dict) -> tuple[str, str]:
    """判定结果的头尾两块。头块插在玩家那句话最前面，尾块追加在最后面。"""
    outcome = judgement.get("outcome") or "success"
    attr = (judgement.get("attr") or "").strip()
    guidance = OUTCOME_GUIDANCE.get(outcome, OUTCOME_GUIDANCE["success"])
    if outcome in ("narrow", "fail", "crit_fail"):
        guidance = f"{guidance}{DEFAULT_COST_HINT}"
    label = OUTCOME_LABELS.get(outcome, outcome)
    head = render(
        "rpg_judgement.jinja2",
        intent=judgement.get("intent") or "这个行动",
        attr=attr or "数值",
        rate=int(judgement.get("rate") or 0),
        dice=int(judgement.get("dice") or 0),
        outcome_label=label,
        guidance=guidance,
    ).strip()
    tail = (
        f"（再次确认：本回合结果是「{label}」。"
        f"{OUTCOME_TAIL.get(outcome, '照这个结果写。')}）"
    )
    return head, tail


def _inject_by_depth(messages: list[dict], entries: list[RpgWorldEntry]) -> None:
    """把词条并进倒数第 depth 条消息的开头，原地改 messages。

    不新增消息行，理由同酒馆：各供应商对 user/assistant 交替有要求。
    """
    if not entries:
        return
    tail = len(messages) - 1  # 0 是 system
    if tail <= 0:
        return
    by_index: dict[int, list[str]] = {}
    for entry in entries:
        depth = max(1, min(int(entry.depth or 1), tail))
        by_index.setdefault(len(messages) - depth, []).append(entry.content.strip())
    for idx, blocks in by_index.items():
        note = "【世界设定】\n" + "\n\n".join(blocks)
        messages[idx]["content"] = f"{note}\n\n{messages[idx]['content']}"


def facts_block(facts: list[str]) -> str:
    """引擎已经算完的事实。道具、移动、动作按钮走的是死数字，模型只负责把它写出来。"""
    rows = "\n".join(f"- {f}" for f in facts)
    return (
        "【本回合已定事实 · 由系统结算，不可更改】\n"
        f"{rows}\n"
        "把这些写进正文，写成读者能看见的画面，不要改动它们，也不要在正文里写出数字本身。"
        "效果是应用上限和条件后的实际变化；未变化或未生效的项目不能写成获得，也不能另给补偿。"
        "行动消耗与跨天恢复是先后两笔变化，不能把恢复误写成行动本身的收益。"
    )


def current_scene_block(sess: RpgSession, here: list[RpgNpc], mode: str, action_time=None) -> str:
    location = (sess.location or "").strip() or "未登记地点"
    lines = [
        "【本轮当前场景 · 硬事实】",
        f"玩家{'本轮行动结束后' if action_time else '本轮开始时'}位于「{location}」。",
        "历史消息中的地点属于过去；除非玩家本轮明确要求移动，不要把当前行动写成刚从其他地点出来。",
        f"本轮最终地点由系统确定为「{location}」；若本轮有移动，只写抵达这个目的地，不要继续替玩家进入另一处地点。",
        "分别登记的主殿、偏殿、后院等是不同地点，不能当作同一场景的装饰随意切换。",
        "在场角色与玩家处于同一地点，不要在开场描写中把他们改放到别处；角色独自离场时，要写清谁离开、如何离开。",
    ]
    slot = str(getattr(sess, "slot", "") or "").strip()
    if slot:
        label = "本轮行动结束时间" if action_time else "当前时间"
        lines.append(f"{label}：第 {max(1, int(getattr(sess, 'day', 1) or 1))} 天 · {slot}。")
    # 刚推过时段的那一轮另有一块贴在玩家那句话前面，见 time_jump_block
    names = "、".join((npc.name or "").strip() for npc in here if (npc.name or "").strip())
    if names:
        lines.append(f"当前在场角色：{names}。")
    elif mode != SOLO_MODE:
        lines.append("当前没有登记在场角色。")
    return "\n".join(lines)


def time_jump_block(sess: RpgSession, action_time=None) -> str:
    """刚推过时段的那一轮，把时间跳跃贴在玩家那句话前面。空 = 没有待补的时间。

    这一块**不放 system**。推时段是纯引擎的，对话流里一条消息都不留，于是模型
    眼前只有「上一幕的长篇正文 + 玩家的下一句」，天然读成无缝衔接，接着上一轮
    的时刻往下写（整段深夜的正文压得过 system 末尾的一句提示）。位置同
    facts_block：离当前对话越近模型越不会忽略。

    说完就完——time_jump_from 由 rpg_turn 在这一轮发出之后清掉。
    """
    jump = str(getattr(sess, "time_jump_from", "") or "").strip()
    if action_time:
        start, end = action_time
        preceding = (
            f"此前已从「{jump}」跳到「{start}」，这段行动开始前的空白不要补写。\n"
            if jump and jump != start else ""
        )
        return (
            "【本轮行动起止时间 · 已由系统结算】\n"
            f"{preceding}本轮行动从「{start}」开始，到「{end}」结束。\n"
            "请描写这段行动的执行过程和已结算的结果，收束在结束时刻。"
            "这段时间属于当前行动，不是应当跳过的空白；不要从结束时刻重新开始执行。"
            "消耗先发生，跨天恢复随后发生；面板是两者结算后的状态，不可再次扣费或推进时间。"
        )
    if not jump:
        return ""
    slot = str(getattr(sess, "slot", "") or "").strip()
    day = max(1, int(getattr(sess, "day", 1) or 1))
    now = f"第 {day} 天 · {slot}" if slot else f"第 {day} 天"
    return (
        "【时间已推进 · 不可忽略】\n"
        f"上一幕结束于「{jump}」，现在是「{now}」。\n"
        "中间这段空白没人描写过，也不要补写。\n"
        "本轮从这个时刻写起：光线、气温、周围人的作息都按它算，不要延续上一幕的时刻。"
    )


def scene_break_block(sess: RpgSession) -> str:
    """刚瞬移过的那一轮，把「上一幕已经结束」贴在玩家那句话前面。空 = 没有待说的断场。

    这一块**不放 system**，理由逐字同 time_jump_block：地点总览点【移动到这里】
    是纯引擎瞬移，对话流里一条消息都不留，于是模型眼前只有「上一幕的长篇正文 +
    玩家的下一句」，天然读成无缝衔接——接着离开时那一幕的场面往下演。
    current_scene_block 里那句「历史消息中的地点属于过去」埋在 system 末尾，
    压不过对话流里上一幕那整段正文。

    说完就完——scene_break_from 由 rpg_turn 在这一轮发出之后清掉。
    """
    was = str(getattr(sess, "scene_break_from", "") or "").strip()
    if not was:
        return ""
    now = str(getattr(sess, "location", "") or "").strip()
    if now and norm_name(now) != norm_name(was):
        where = f"上一幕发生在「{was}」，你离开了那里，现在在「{now}」。"
    else:
        where = f"上一幕发生在「{was}」。你离开过那里，现在又回到了这里。"
    return (
        "【场景已切换 · 不可忽略】\n"
        f"{where}\n"
        "那一幕已经结束：不要接着它的场面、姿势、没说完的话往下写。\n"
        "此刻在场的人见到你是重新照面，不是上一幕的延续。"
    )


def _inject_judgement(messages: list[dict], judgement: dict) -> None:
    """判定块夹在玩家那句话的头和尾。必须在 _inject_by_depth 之后调用——
    depth=1 的世界书也落在这条消息上，判定块得排在它前面。

    放这儿而不是 system：离当前对话越近模型越不会忽略，而判定结果是这一轮
    最不能被忽略的事实。
    """
    head, tail = judgement_blocks(judgement)
    last = messages[-1]
    last["content"] = f"{head}\n\n{last['content']}\n\n{tail}"


PLAYER_SLOT = "player"


def message_slots(message: RpgMessage) -> list[str]:
    """这条消息该记在哪几个格子里。

    一个格子就是「一套独立的最近 N 条 + 一份自己的概要」：玩家一个，每个 NPC
    一个。**记忆按格子分，而不是按一条大流水账切**——这是玩家要的那件事：
    「和角色的对话单独存，上下文是她那边单独的最近 N 条外加摘要」。

    - **玩家格永远有份**：发生在你眼前的事，没有你记不得的道理。这一条是
      「走到别处就忘了刚才」那个 bug 的正解——原先 `present` 有人时只记进在场
      那几个 NPC 的格子、玩家格不收，于是主卧那场戏只躺在对方名下；一走到别的
      地点，窗口按**新地点**现算在场名单，对方那一格整个不进，原文和她那份概要
      两头落空，模型转头就从更早的状态重讲。老消息（`present` 为 null / `[]`）
      照旧进玩家格，等于维持「null = 对所有人可见」的老口径。
    - `present` 有人 → **再**记进在场每一个人的格子。一场三个人的戏在三个格子
      里各留一份，散场之后单独再遇见其中任何一个，她都还记得那场戏。

    玩家格装全部，不等于她们互相知道：NPC 格仍然只收她自己在场的那些，压出来
    的那份概要也只在她在跟前时注入。**GM 看得见全貌，她们看不见。**

    群戏在多个格子里各留一份**是有意的**：她们各自记得自己那个角度。代价是
    那一段会被压进好几份概要（各压各的），换来的是散场之后不丢。
    """
    slots = [PLAYER_SLOT]
    if message.present:
        slots.extend(str(i) for i in message.present)
    return slots


def slot_upto(sess: RpgSession, slot: str) -> int:
    """这个格子已经压到第几条了。玩家格用老那两列，NPC 格用按 id 分格的那两列。"""
    if slot == PLAYER_SLOT:
        return int(sess.summarized_upto_id or 0)
    try:
        return int((sess.thread_upto or {}).get(slot, 0) or 0)
    except (TypeError, ValueError):
        return 0


def slot_summary(sess: RpgSession, slot: str) -> str:
    if slot == PLAYER_SLOT:
        return (sess.summary or "").strip()
    return str((sess.thread_summaries or {}).get(slot, "") or "").strip()


def slot_window(
    module: RpgModule, sess: RpgSession, history: list[RpgMessage], slot: str,
) -> list[RpgMessage]:
    """一个格子自己的最近 N 条（已经压进它那份概要的不再发原文）。

    **压缩必须调用这同一个函数来判断溢出**（见 `rpg_turn._maybe_summarize`）。
    两边各写一遍筛选迟早会分叉，而分叉的那一次是静默丢记忆：这边不发原文、
    那边不压进概要，指针却照样往前走。
    """
    limit = max(1, module.context_turns or 20) * 2
    upto = slot_upto(sess, slot)
    return [m for m in history if m.id > upto and slot in message_slots(m)][-limit:]


def summary_block(
    sess: RpgSession, here: list[RpgNpc], aside: list[RpgNpc] = (),
) -> str:
    """【此前剧情】：你自己那一份，加此刻在跟前的每个人各自那一份，
    再加这一轮被提到、但人不在跟前的人各自那一份。

    分段标出来源，不糊成一团：模型看到「（与柳如烟）」这个抬头才知道下面那段
    是她也经历过的，敢直接接话；混在一起它会拿不准哪些能说出口。

    额度按份数均分再拼，而不是拼完再从尾部切：从尾部切先切掉的正是排在后面的
    NPC 那几份——偏偏是你正在跟她说话的那一份。

    **aside 那几份不参与这次均分**，各拿一个固定的 ASIDE_SUMMARY_TOKEN_BUDGET：
    提到一个旧相好，不该把「你自己那格」和「正跟你说话那个人那格」一起稀释掉。
    只有攒出过内容的人算一份，所以随口提一句是零成本的。
    """
    slots: list[tuple[str, str]] = [("你的经历", slot_summary(sess, PLAYER_SLOT))]
    for npc in here:
        slots.append((f"与{npc.name}", slot_summary(sess, str(npc.id))))
    parts = [(title, text) for title, text in slots if text]
    others: list[tuple[str, str]] = []
    for npc in aside:
        text = slot_summary(sess, str(npc.id))
        if text:
            others.append((f"与{npc.name}", text))
    if not parts and not others:
        return ""
    body: list[str] = []
    if parts:
        share = max(1, SUMMARY_TOKEN_BUDGET // len(parts))
        body += [
            f"（{title}）\n{truncate_to_token_budget(text, share)}"
            for title, text in parts
        ]
    body += [
        f"（{title}）\n{truncate_to_token_budget(text, ASIDE_SUMMARY_TOKEN_BUDGET)}"
        for title, text in others
    ]
    return "【此前剧情】\n" + "\n\n".join(body)


def history_window(
    module: RpgModule,
    sess: RpgSession,
    history: list[RpgMessage],
    here_ids: set[int] | None,
) -> list[RpgMessage]:
    """发原文的窗口：玩家那一格，加此刻在跟前的每个人那一格，按时间并起来。

    公开而不是私有：「帮我想想」也要按同一套规则取最近发生的事，
    两边各切一次的话，窗口的边界迟早对不上。

    `here_ids` 传 `None` 和传空集合，结果**一样**。原先这两支是不同的行为
    （`None` = 不筛，空集 = 屋里没人所以要筛），区分它们是有意义的；玩家格
    改成装全部消息之后（见 `message_slots`），「筛」这一支本来就不再筛掉
    玩家的东西，两支于是重合。参数留着是因为各调用方各自能拿到什么不一样。

    在场名单是**当场算出来的**，不是玩家在界面上点了谁。这一条是玩家报过的
    那个失忆 bug 的正解：原先按 `focus_npc_id` 走两支，点了人才取她在场的
    那些，没点就只取「人数 > 1 的群戏」。而面包屑上的「看全部」本来就是默认
    态，于是跟她一对一聊十轮（`present=[5]`）之后随口再说一句，模型眼前只剩
    开场白——真实存档里实测，32 条消息只剩 1 条。点谁只是界面上的筛选。

    在场的人那一格是**额外**带进来的：把**她自己的**更早记忆也捞进这一轮，
    这样走进她跟前时不必等她开口就能接上旧事。

    关键词扫描完成后，调用方也可把本轮提到的角色 id 并进 here_ids，取回其
    独立的历史窗口。这只扩大回忆范围，不改变谁在场或消息的记忆归属。

    **每格各取各的 N 条，不在合并之后再砍一刀**。砍了就会重演上面那个 bug 的
    另一个版本：你一个人赶路四十轮，她那十几轮对话会被自己的脚步声挤出窗口，
    而她那份概要还没到压缩线——于是又一次谁也不记得。合并只去重和排序。
    """
    slots = [PLAYER_SLOT] + [str(i) for i in sorted(here_ids or ())]
    picked: dict[int, RpgMessage] = {}
    for slot in slots:
        for m in slot_window(module, sess, history, slot):
            picked[m.id] = m
    return [picked[i] for i in sorted(picked)]


def scene_block(sess: RpgSession, description: str, here: list[RpgNpc]) -> str:
    """【场面】：当前这一幕不在消息里的那些信息。空串 = 这一轮不拼。

    历史统一成一条之后，这一块**不再是「借历史」**——原先它干的是把场面线的
    原文读时复制给角色线，那是在补「历史被切开了」的窟窿。现在没有窟窿可补：
    所有消息都在同一条时间线上，模型本来就看得见开场白、看见你刚才做了什么、
    看见群戏里谁说了什么。

    剩下的只有**消息里没有的东西**：

    - **地点描述**。`_compose_state` 里只有地点名（「所在：地窖」），描述从来
      没进过上下文——作者写了一整段地窖的样子，模型一个字没见过
    - **在场名单**。`_npc_block` 给了每个人的设定，但那是「这一轮要注入的人」，
      含被提到但不在跟前的人；这一行专门回答「眼前站着谁」
    - **这个地方现在的样子**（`place_notes` 里那一句）。地点描述是作者写死的
      原样，被玩家改过的部分只在这一句里：门踹坏了、桌子掀了。它不进任何
      记忆格——那是事实，不是叙事，压成梗概只会丢字（见 RpgSession.place_notes）

    description 由调用方查好传进来（`build_rpg_messages` 顺手查了 RpgLocation），
    这里保持纯函数：能直接测，也不用把整个 module 塞进来。

    两样都从**活状态**读，不从消息读。这是它和旧 scene_background 的根本差别：
    那个读的是历史，所以必须防「复制进别的线会让同一段戏各演化一遍」；这个读的
    是当前状态，拼多少次都一样，一个字都不写回任何地方。
    """
    name = (sess.location or "").strip()
    parts: list[str] = []
    if name:
        text = (description or "").strip()
        # 近况跟在描述后面、单独一行：作者写的那段是这地方本来的样子，这一句
        # 是被玩家改过的地方，混成一段模型分不清哪句能改、哪句是设定
        note = place_note(sess, name)
        parts.append(
            f"地点：{name}"
            + (f"\n{text}" if text else "")
            + (f"\n现在：{note}" if note else "")
        )

    # 在场名单。空名单也要写出来——「没有别人」和「没提」对模型是两回事，
    # 不写的话它会照着上下文里的角色自己安排一个站到跟前。
    #
    # 私聊时这份名单已经由调用方收窄成那一个人了：三处（在场名单、人设卡、
    # 记忆归属）必须一起收窄，只收窄记忆那一处的话，模型看见这里还站着别人
    # 就会让他插话，而那句话按私聊记账——他说过的话他自己不记得
    if here:
        parts.append("在场：" + "、".join((n.name or "").strip() for n in here))
    elif name:
        parts.append("在场：只有你一个人")

    if not parts:
        return ""
    return truncate_to_token_budget(
        "【场面】\n" + SCENE_PREAMBLE + "\n\n" + "\n\n".join(parts),
        SCENE_TOKEN_BUDGET,
    )


def milestone_block(sess: RpgSession) -> str:
    """【关系的转折】：已经发生过、把某两个人的关系推到现在这样的那几件事。
    空串 = 一条都没有，这一段整块不拼。

    数值那一行（「对你：好感 62」）只给结论不给来历。只给数字的话，模型写
    「她为什么会信你」时手上没有依据，只能现编一段旧事，而那段旧事下一轮
    又不记得了，于是每轮编一个新的——里程碑就是拿来钉住这个的。

    **常驻，不按在场筛**：一段关系是两个人之间的事，只挑在场那个人的里程碑，
    等于同一个数字在不同回合下有不同来历。

    截断只作用在条目上、标题和抬头单独拼：整段丢进 truncate 的话，超预算时
    keep_end 砍掉的正好是开头那两行，模型会收到一串没有抬头的裸条目。
    （注：上面 chronicle_block 是老写法，有同样的问题，这次没动它。）
    """
    rows = [
        entry for entry in (sess.npc_milestones or [])
        if isinstance(entry, dict) and str(entry.get("content") or "").strip()
    ]
    if not rows:
        return ""
    lines = []
    for entry in rows:
        pair = "↔".join(str(entry.get(key) or "").strip() for key in ("a", "b"))
        kind = str(entry.get("type") or "").strip()
        lines.append(
            f"- {_when(entry)}｜{kind}｜{pair}：{str(entry.get('content')).strip()}"
        )
    # keep_end 保新弃旧：最近的转折更可能是这一轮用得上的，同 chronicle
    body = truncate_to_token_budget(
        "\n".join(lines), MILESTONE_TOKEN_BUDGET, keep_end=True,
    )
    if not body.strip():
        return ""
    return "【关系的转折】\n" + MILESTONE_PREAMBLE + "\n" + body


# ── 「帮我想想」的追加段 ───────────────────────────────────────────────────

# 标签协议。选它而不是 JSON，是因为**退化方向不同**：标签写错或忘写，那一行
# 就退化成普通建议，行为和加这个功能之前逐字一致；JSON 写坏则是整次调用解析
# 失败，玩家直接看到「没想出来」。便宜档小模型写字远比写 JSON 稳
SUGGEST_TAG_GUIDE = (
    "=== 这一轮怎么标 ===\n"
    "六行照旧，行首不要编号。只有前三行（做的事那三条）能挂标签：如果某一行靠的是"
    "上面清单里的某样东西，就在那一行最前面加一个方括号标签，格式是 [类型|清单里的原名]：\n"
    "  [技|技能名] / [物|道具名] / [去|地点名] / [行|动作名]\n"
    "名字必须逐字抄自上面对应的清单；抄不出原名就不要加标签，当成普通的一句话写。\n"
    "后三行是玩家说出口的台词，一律不挂标签。\n"
    "清单是空的、或者你想做的事不在上面，前三行就全写普通的一句话。\n"
    "宁可前三行全是普通的一句话，也不要为了凑一个标签编一个做不到的动作。"
)


def _fit_lines(title: str, lines: list[str], budget: int) -> str:
    """按行从尾部砍，直到装进预算。**行是这里的最小单位**——半行不如没有。"""
    while lines and estimate_tokens(f"{title}\n" + "\n".join(lines)) > budget:
        lines.pop()
    return f"{title}\n" + "\n".join(lines) if lines else ""


def suggest_cast_block(here: list[RpgNpc], sess: RpgSession, module: RpgModule) -> str:
    """【在场】的紧凑版：一人一行。

    **不复用 `_npc_block`**。那个给的是完整的卡（简介/人设/外貌/四栏档案/对话
    示例），一个写满的角色实测能吃掉两三千 token；更要命的是它的降级链是
    **从尾部砍人**，于是作者写得越长的角色，在建议里越看不见——而且不报错。
    建议只需要「她是谁、对我什么态度、眼下什么状况」，所以这里一行一人。
    """
    if not here:
        return ""
    specs = def_map(module.relation_stat_defs)
    lines: list[str] = []
    for npc in here:
        state = (sess.npc_states or {}).get(str(npc.id)) or {}
        bits = []
        relations = [_stat_text(specs, k, v) for k, v in state.items() if k != "met"]
        if relations:
            bits.append("对你：" + "　".join(relations))
        notes = (sess.npc_notes or {}).get(str(npc.id)) or {}
        if isinstance(notes, dict) and notes:
            bits.append("眼下：" + "；".join(f"{k} {v}" for k, v in notes.items()))
        activity = npc_activity(sess, npc.id)
        if activity:
            bits.append(f"最近：{activity}")
        # 简介只留一小截：建议模型要的是「她是谁」，不是她的一整段来历
        desc = (npc.description or "").strip().replace("\n", " ")[:SUGGEST_CAST_DESC_CHARS]
        who = (npc.name or "").strip() + (f"（{desc}）" if desc else "")
        tail = "　".join(bits)
        lines.append(f"- {who}：{tail}" if tail else f"- {who}")
    return _fit_lines("【在场】", lines, SUGGEST_CAST_BUDGET)


def suggest_places_block(
    sess: RpgSession, locations: list[RpgLocation], npcs: list[RpgNpc],
) -> str:
    """【地方】：现在在哪，以及能去哪儿。

    **列模组里的全部地点，不按 `connections` 过滤**。`rpg_turn._move` 明说移动
    不看连接——连接只用来画地图和散迷雾。拿它当白名单会让模型只能建议邻居，
    而玩家其实哪儿都能去；挨着当前地点的只加一句「就在这儿附近」当路标。
    """
    here = norm_name(sess.location or "")
    near: set[str] = set()
    body = ""
    for loc in locations:
        if norm_name(loc.name) != here:
            continue
        near = {norm_name(c) for c in (loc.connections or [])}
        body = (loc.description or "").strip().replace("\n", " ")
        break

    lines: list[str] = []
    if (sess.location or "").strip():
        lines.append(f"现在在：{sess.location.strip()}")
        if body:
            lines.append(body[:SUGGEST_PLACE_DESC_CHARS * 4])
        note = place_note(sess, sess.location)
        if note:
            lines.append(f"现在：{note}")

    ways: list[str] = []
    for loc in locations:
        key = norm_name(loc.name)
        if not key or key == here:
            continue
        # enter_requires 不满足的不列：列了模型就会建议一个点了必然被挡在外面的地方
        if not check_condition(loc.enter_requires, sess, npcs)[0]:
            continue
        desc = (loc.description or "").strip().replace("\n", " ")[:SUGGEST_PLACE_DESC_CHARS]
        line = f"- {loc.name}" + (f"：{desc}" if desc else "")
        if key in near:
            line += "（就在这儿附近）"
        ways.append(line)
    if ways:
        lines.append("能去：")
        lines.extend(ways)

    return _fit_lines("【地方】", lines, SUGGEST_PLACES_BUDGET)


def suggest_actions_block(usable: list[tuple[RpgAction, str]]) -> str:
    """【能用上的按钮】：作者替这一局定义好的动作。

    这是现成的「这个角色能做什么」清单，比让模型自己编稳得多。传进来的
    `usable` 已经过 `_action_gate`，这里不重判——判据只该有一份。

    **不给 effects 数字**，理由同 CATALOG_PREAMBLE：数值是引擎按 effects 算的，
    摆进提示词只会诱导模型在正文里自己报数字，两边必然对不上。
    """
    lines: list[str] = []
    for action, who in usable:
        name = (action.name or "").strip()
        if not name:
            continue
        hint = (action.prompt_hint or "").strip()
        line = f"- {name}" + (f"（点了等于说：{hint}）" if hint else "")
        if action.needs_target:
            # 远程动作的对象是整份名册，点一个具体名字反而把模型往那个人身上
            # 带——它不是「只能对张三」，只是「此刻至少有一个能对上」的例子
            tip = "" if action.target_anywhere else (f"，比如{who}" if who else "")
            line += f"（要先选一个人{tip}）"
        if action.cost_slot:
            line += "（费一格时段）"
        lines.append(line)
    return _fit_lines("【能用上的按钮】", lines, SUGGEST_ACTIONS_BUDGET)


def suggest_blocks(
    module: RpgModule, sess: RpgSession, sources: SuggestSources,
    here: list[RpgNpc], scan_text: str,
) -> tuple[str, dict]:
    """「帮我想想」的追加段。返回 (文本, 各块 token 的诊断)。

    **拼在 `rpg_suggest.jinja2` 的渲染结果之后，不往那个模板里加变量。**
    模板用户可自定义，往里加占位符对他们的旧版本就是**静默失效**：新变量在老
    覆写里没有，`StrictUndefined` 不报错，他们只是悄悄拿不到资料，我们查不出来。
    项目里 `_place_block` 和 `style_block` 都是这个姿势。

    代价要认下来：资料段排在那句「只输出 3 行」之后，靠 `SUGGEST_TAG_GUIDE`
    那段结尾指令扳回来。另外覆写成 JSON 输出的用户会和这段指令打架（整段 JSON
    被当成一行 → 一条自由文本）——退化安全，且「不为新功能打坏用户的格式」
    优先，所以不为了兼容它写一个脆弱的双格式解析器。
    """
    blocks: list[tuple[str, str]] = []

    state = truncate_to_token_budget(
        _state_block(sess, module, here), SUGGEST_STATE_BUDGET
    )
    if state:
        blocks.append(("state", state))
    cast = suggest_cast_block(here, sess, module)
    if cast:
        blocks.append(("cast", cast))
    places = suggest_places_block(sess, sources.locations, sources.npcs)
    if places:
        blocks.append(("places", places))
    buttons = suggest_actions_block(sources.usable)
    if buttons:
        blocks.append(("actions", buttons))

    # 只取 depth<=0 的：depth>0 的词条本意是插进消息流某个位置，建议这条路
    # 没有消息流可插。scan_text 由调用方限定成最近两条，理由同 build_rpg_messages：
    # 扫全文会让模型自己写的旁白反复命中同一条词条，自己喂自己
    hits = [
        e for e in triggered_entries(sources.entries, scan_text, sess, sources.npcs)
        if (e.depth or 0) <= 0
    ]
    if hits:
        blocks.append(("world", truncate_to_token_budget(
            "【世界设定】\n" + "\n\n".join(e.content.strip() for e in hits),
            SUGGEST_WORLD_BUDGET,
        )))

    if not blocks:
        return "", {}
    text = "\n\n" + "\n\n".join(body for _name, body in blocks) + "\n\n" + SUGGEST_TAG_GUIDE
    diag = {name: estimate_tokens(body) for name, body in blocks}
    diag["total"] = sum(diag.values())
    return text, diag


async def load_suggest_sources(
    session: AsyncSession, module: RpgModule, npcs: list[RpgNpc],
) -> SuggestSources:
    """把「这次建议能引用什么」一次查齐。

    `usable` **刻意留空**：动作的可用性判据是 `rpg_turn._action_gate`，而
    `rpg_turn` 反向依赖本模块，这里 import 它会成环。调用方拿到之后自己填。
    """
    async def rows(model):
        return list((await session.execute(
            select(model).where(model.module_id == module.id)
        )).scalars().all())

    return SuggestSources(
        npcs=npcs,
        items=await rows(RpgItem),
        skills=await rows(RpgSkill),
        locations=await rows(RpgLocation),
        actions=await rows(RpgAction),
        entries=await rows(RpgWorldEntry),
    )


async def resolve_rules(
    session: AsyncSession, user_id: int | None, ids: list[int]
) -> str:
    """按模组勾选的 id 拼 RPG 写作规则，无兜底——空就是空。

    照酒馆 tavern_context.resolve_rules：RPG 默认不注入规则，没有小说侧那套
    「NULL 回退到内置护栏」的语义。失效 id（规则被删）自然筛掉。
    """
    if not ids:
        return ""
    wanted = {int(i) for i in ids}
    rules = (await session.execute(
        select(RpgRule)
        .where(RpgRule.user_id == user_id, RpgRule.enabled.is_(True))
        .order_by(RpgRule.sort_order, RpgRule.id)
    )).scalars().all()
    return "\n\n".join(
        r.content.strip() for r in rules if r.id in wanted and r.content.strip()
    )


async def build_rpg_messages(
    session: AsyncSession,
    module: RpgModule,
    sess: RpgSession,
    history: list[RpgMessage],
    new_input: str,
    judgement: dict | None = None,
    facts: list[str] | None = None,
    mode: str = GROUP_MODE,
    private_with: int | None = None,
    action_time: tuple[str, str] | None = None,
) -> tuple[list[dict], dict]:
    """组装发给叙事模型的 messages，返回 (messages, diag)。

    judgement 是本轮的判定结果（roll 列的内容）。need_check 为假或为 None 时
    不注入判定块，这一轮就是纯叙事。

    facts 是引擎已经结算完的事实（用了药水回 20 精力、门锁着进不去）。它和
    judgement 走同一条通道：都是「不可更改的已定结果」，模型只负责落成画面。

    history 是**全部**历史，调用方不再按线切——线已经不存在了。原先那两个参数
    （thread_id、scene_history）一个管「这一轮归哪条线」、一个管「把场面线借给
    角色线」，现在都没得借：所有消息本来就在同一条时间线上。

    mode 是玩家在输入框上方明着选的那三个模式之一（群聊 / 私聊 / 独自行动），
    private_with 只在私聊时有值。**这里和路由写 present 时必须算出同一份在场
    名单**——那边决定这段话记进谁的记忆，这边决定模型看见谁站在跟前，两边差
    一个人就会出「他说过的话他自己不记得」。

    creator_note 永不出现在返回值里。
    """
    npcs = (await session.execute(
        select(RpgNpc)
        .where(RpgNpc.module_id == module.id)
        .order_by(RpgNpc.sort_order, RpgNpc.id)
    )).scalars().all()
    # 真的在跟前的那几个（按地点算，私聊收窄之前的全集，私聊那支要用它）。
    # 标记见过面只认下面那份收窄过的 here：onstage 里还含被提到的人，
    # 他们的卡这一轮发了，但人并没见到，不能算见过
    local_here = here_npcs(
        list(npcs), sess.location, sess.slot, sess.npc_places, sess.npc_followers,
    )
    here = local_here
    # 在场名单要在窗口之前算：窗口按它筛（见 history_window）。用 turn_present
    # 而不是上面这份 here，是为了和**写**消息那一刻用的是同一个定义——尤其是
    # 「一个地点都没建的模组 = 所有人都在同一个场面里」那条兜底，两边必须一致，
    # 否则那类模组写进去的 present 全员都有、读出来却按空名单筛，整段历史消失
    present_npcs = turn_present(list(npcs), sess, mode, private_with)
    present_set = {n.id for n in present_npcs}
    # 私聊把**三处一起**收窄：记忆归属（present，路由那边）、人设卡、【场面】
    # 名单。只收窄记忆那一处的话，模型看见屋里还站着别人就会让他插话，而那句
    # 话按私聊记账——他说过的话他自己不记得
    if mode == PRIVATE_MODE:
        here = present_npcs
    window = history_window(module, sess, history, present_set)
    # scan_depth=1 就只扫玩家刚发的这句。往回扫得越多，GM 自己的旁白越容易
    # 让词条反复命中——它提到了那个词，下一轮扫描又扫到，自己喂自己
    back = max(0, int(module.scan_depth or 3) - 1)
    intent = (judgement or {}).get("intent") or ""
    # intent 一起参与扫描：玩家写「我撬门」、词条关键词是「锁」，子串匹配不上；
    # 裁决归一化出的「用铁丝撬开生锈的铁锁」能命中。
    # 那次调用本来就要发生，检索召回是顺手买到的
    #
    # refs 是裁决认出来的人（「回想自己的身世」→ 澹台红绡）。玩家那句话里
    # 一个名字都没有、触发词也命中不了，光靠字面匹配永远捞不到她的卡；把名字
    # 并进扫描文本，下面 onstage_npcs 就能照常把整张卡发出去——**这一轮**就发，
    # 不是等下一轮。顺手也让它参与词条触发（提到谁，跟谁有关的词条就该出来）
    refs = resolve_refs((judgement or {}).get("refs"), npcs)
    scan_parts = (
        ([m.content for m in window[-back:]] if back else []) + [new_input, intent] + refs
    )
    scan_text = "\n".join(p for p in scan_parts if p)

    entries = (await session.execute(
        select(RpgWorldEntry)
        .where(RpgWorldEntry.module_id == module.id)
        .order_by(RpgWorldEntry.sort_order, RpgWorldEntry.id)
    )).scalars().all()
    # 词条的数值条件里可以写「赫敏的好感≥50」，所以要先拿到 npcs 再筛词条。
    # npcs 和 here 在上面（窗口之前）已经取过，这里不重取
    hits = triggered_entries(list(entries), scan_text, sess, list(npcs))
    onstage = onstage_npcs(
        list(npcs), sess.location, scan_text, sess.slot, sess.npc_places,
        sess.npc_followers,
    )
    if mode == PRIVATE_MODE:
        context_npcs = present_npcs + [
            npc for npc in named_npcs(list(npcs), scan_text)
            if npc.id not in present_set
        ]
    else:
        context_npcs = onstage
    recall_ids = present_set | {npc.id for npc in context_npcs}
    if recall_ids != present_set:
        window = history_window(module, sess, history, recall_ids)
    # 当前地点的描述。只按名字查一条——用不上整张表，多查的每一条都会在
    # 每轮上下文里凭空多算一次 token
    # 模组的道具表和技能表。整表取而不是按背包筛——这一块的用处恰恰是告诉 GM
    # 「还有哪些他没拿到的东西」，筛掉就等于又回到了它看不见的老样子
    module_items = (await session.execute(
        select(RpgItem)
        .where(RpgItem.module_id == module.id)
        .order_by(RpgItem.sort_order, RpgItem.id)
    )).scalars().all()
    module_skills = (await session.execute(
        select(RpgSkill)
        .where(RpgSkill.module_id == module.id)
        .order_by(RpgSkill.sort_order, RpgSkill.id)
    )).scalars().all()

    place_description = ""
    if (sess.location or "").strip():
        place_description = (await session.execute(
            select(RpgLocation.description)
            .where(
                RpgLocation.module_id == module.id,
                RpgLocation.name == (sess.location or "").strip(),
            )
            .limit(1)
        )).scalars().first() or ""

    sections: list[str] = []
    sections.append(render(
        "rpg_gm.jinja2",
        char_name=(sess.char_name or "").strip() or DEFAULT_CHAR_NAME,
        genre=(module.genre or "").strip(),
        reply_length=max(0, int(module.reply_length or 0)),
    ).strip())

    # 玩法规则紧跟在 GM 指令后面，作为独立的一段而不是模板里的一个变量：
    # 改过 rpg_gm.jinja2 的用户存的是旧版本，往模板里塞占位符对他们就是静默失效。
    # 排在 system_instruction 之前，作者自己写的规则仍然能压过类别的通用规则
    sections.append(style_block(module.play_style))

    if (module.system_instruction or "").strip():
        sections.append(module.system_instruction.strip())

    if (module.worldview or "").strip():
        sections.append("【世界观】\n" + module.worldview.strip())

    # 【数值的含义】紧贴在数值前面：它是读懂下面所有数字的钥匙，而被尾部
    # 截断切掉的话，模型看到的就又是一串没有意思的数字了
    meaning_block = _meaning_block(module)
    if meaning_block:
        sections.append(meaning_block)

    # 【你】排在【世界设定】之前：状态每轮都在变，世界书是静态背景，
    # 硬事实靠前。整体截断从尾部切，靠前的不会被切掉
    state_block = _state_block(sess, module, here, mode)
    sections.append(state_block)

    # 【道具与技能】紧跟【你】：它解释的正是【你】那一段里列出来的那几件东西，
    # 隔开就得让模型自己跨段对名字。也因为靠前，整段超预算从尾部切时它不会先没
    catalog = catalog_block(module_items, module_skills, sess)
    if catalog:
        sections.append(catalog)

    # 【角色总表】紧贴【在场】之前：下面那一块是这份名单里某几个人的详细卡，
    # 先给全名单再给卡，模型才知道卡是名单的子集而不是全世界只有这几个人。
    # **私聊不发**：那一刻的规矩是「屋里只有你们俩」，连别人的名字都不该出现——
    # 名字一露脸模型就会让他被提起，而这段话按私聊记账，等于又漏一次账。
    # 收窄的只是这份**总表**：你在私聊里主动提到的人照样拿得到卡（见下面
    # context_npcs 那一支），被牺牲掉的是「模型自己想提起谁」这条路径
    roster = "" if mode == PRIVATE_MODE else roster_block(list(npcs))
    if roster:
        sections.append(roster)

    # 第二跳：先算长期回忆，把入选往事牵涉到的人捞出来，好让下面 _npc_block 给他们出卡。
    # 提到「药园那把火」→ 命中那条往事 → 放火的人的完整卡也一起进上下文，
    # 而不是只剩一句 summary、模型对这个人一无所知只能现编。
    # 计算挪到这里、section 文本仍在原位置追加（memories 变量复用），是为了不动块的排序
    hop_ids: set[int] = set()
    memories = event_memory(history, present_set, new_input,
                            window_ids={m.id for m in window},
                            out_participants=hop_ids)

    # 往事里牵涉、但还没在 context_npcs 里的人，补进来出卡。排在在场之后，
    # _npc_block 超预算从队尾降档时先降他们，不挤占眼前在场的人
    have = {n.id for n in context_npcs}
    context_npcs = context_npcs + [n for n in world_npcs(npcs)
                                   if n.id in hop_ids and n.id not in have]
    npc_block = _npc_block(context_npcs, sess, module, here_ids=present_set) if context_npcs else ""
    if npc_block:
        sections.append(npc_block)

    # 【外场】排在【在场】之后、【世界设定】之前：整体截断从尾部切，
    # 大事记是「已经发生过的硬事实」，和状态同类；放最后的话一旦超预算，
    # 被切掉的正好是跨线记忆——那恰恰是它存在的理由。
    # keep_end=True 保新弃旧：最近传开的事更可能是这一轮用得上的
    chronicle = chronicle_lines(sess)
    chronicle_block = ""
    if chronicle:
        chronicle_block = truncate_to_token_budget(
            "【外场】\n" + CHRONICLE_PREAMBLE + "\n"
            + "\n".join(f"- {line}" for line in chronicle),
            CHRONICLE_TOKEN_BUDGET, keep_end=True,
        )
        sections.append(chronicle_block)

    # 【场面】紧跟在【外场】后面：两块都是「不在消息里的背景」，位置的理由也
    # 一样（整体截断从尾部切，背景要排前面）。差别是【外场】讲的是传开的传闻，
    # 这一块讲的是眼前这一幕——地点长什么样、谁站在这里
    #
    # **必须在扫完 scan_text 之后**才拼：地点描述扫进关键词的话，写地窖的模组
    # 每进一次地窖就命中那条词条；而模型自己写的旁白又会让它下一轮再命中，
    # 自己喂自己。旧的 scene_background 有同一条规矩，理由照旧
    scene = scene_block(sess, place_description or "", here)
    if scene:
        sections.append(scene)

    # depth=0 拼进 system，depth>0 留到下面按深度插进对话流
    system_hits = [e for e in hits if (e.depth or 0) <= 0]
    depth_hits = [e for e in hits if (e.depth or 0) > 0]
    if system_hits:
        sections.append(truncate_to_token_budget(
            "【世界设定】\n" + "\n\n".join(e.content.strip() for e in system_hits),
            WORLD_TOKEN_BUDGET,
        ))

    # 叙事样例只作为文字引用，不做真实 few-shot 轮：那会让模型学着
    # 连玩家那一侧一起写，正是酒馆群聊给对话示例降级的同一个理由
    if (module.narration_sample or "").strip():
        sections.append("【叙事样例】\n" + module.narration_sample.strip())

    # 概要按格子注入，名单跟窗口用**同一份** present_npcs 而不是 here：那类
    # 一个地点都没建的模组里 here 是空的，拿 here 拼的话她的原文发了、她那份
    # 长期记忆却不发——正是上下文对不上的那种裂
    # window_ids 让回忆块跳过窗口内的消息：那几条整段正文已经原样发出去了，
    # 再摘一次纯属重复占额度。memories 已在【角色总表】后提前算过（为了第二跳捞人），
    # 这里只负责按原顺序把文本追加进 sections
    if memories:
        sections.append(memories)
    # 【关系的转折】紧跟在长期回忆之后：两块都是「过去的事」，而里程碑正是那些
    # 回忆被压掉之后还该留下的事实锚——关系数值现在的样子就是它们攒出来的。
    # 空 = 一条都没有，老局的上下文一个字都不变
    milestones = milestone_block(sess)
    if milestones:
        sections.append(milestones)
    # 被提到、但人不在跟前的人再各补一小格：这一块存在的意义就是「你俩之间
    # 发生过什么」。只有关系数值没有旧事，模型只能现编一段「上次她……」
    aside = [n for n in context_npcs if n.id not in present_set]
    prior = summary_block(sess, present_npcs, aside)
    if prior:
        sections.append(prior)

    # 写作规则放 sections 末尾，同酒馆：它约束的是「怎么写」，最贴近本轮生成，
    # 排最后离叙事最近、模型最不会忽略。空即不注入
    rules_block = await resolve_rules(session, module.user_id, module.enabled_rule_ids or [])
    if rules_block:
        sections.append(rules_block)

    scene_anchor = current_scene_block(sess, here, mode, action_time)

    anchor_budget = estimate_tokens(scene_anchor) + 2
    system_content = truncate_to_token_budget(
        "\n\n".join(sections), max(1, SYSTEM_TOKEN_BUDGET - anchor_budget),
    )
    system_content = f"{system_content}\n\n{scene_anchor}"

    messages = [{"role": "system", "content": system_content}]
    # 窗口里混着好几个地点的消息时，在切换处打一行分隔——这正是 RpgMessage.location
    # 那个写入时快照的用处：没有它，三天前在铁匠铺说的话会被读成眼前这场对话。
    #
    #  - **只在窗口真的跨了地点时才加**。单地点的局（绝大多数老局、和一直待在
    #    一个地方的玩家）prompt 一个字不变。
    #  - **空地点不触发，也不推进 previous**。空 = 「不知道」（迁移过来的老消息、
    #    一个地点都没建的模组），当成「换到了无名地点」会在老存档里凭空刷一串
    #    分隔；不推进 previous 则保证「A → 空 → A」不会误报第二次切换。
    #  - **做成消息前缀，不插独立消息**：插一条会打断 user/assistant 交替，
    #    Anthropic 和 Gemini 那两条格式都过不去。
    window_places = [(m.location or "").strip() for m in window]
    multi_place = len({p for p in window_places if p}) > 1
    previous = ""
    for m, place in zip(window, window_places):
        content = m.content
        if multi_place and place and place != previous:
            content = f"（以下发生在「{place}」）\n{content}"
        if place:
            previous = place
        messages.append({"role": m.role, "content": content})
    messages.append({"role": "user", "content": new_input})

    _inject_by_depth(messages, depth_hits)
    # 事实块在判定块之后注入，于是排在更靠前的位置：引擎算出的死数字比
    # 概率判定更硬，冲突时以它为准
    if judgement and judgement.get("need_check") and judgement.get("outcome"):
        _inject_judgement(messages, judgement)
    if facts:
        messages[-1]["content"] = f"{facts_block(facts)}\n\n{messages[-1]['content']}"
    # 场景切换排在事实和判定之上、时间跳跃之下：它定的是「这一幕发生在哪儿、
    # 上一幕断没断」，比本轮的事实更靠上一层，但没有「什么时候」那一层高
    break_block = scene_break_block(sess)
    if break_block:
        messages[-1]["content"] = f"{break_block}\n\n{messages[-1]['content']}"
    # 时间跳跃最后注入，于是排在最前面：它定的是「这一幕发生在什么时候」，
    # 比本轮的事实和判定更靠上一层，冲突时先按它算
    jump_block = time_jump_block(sess, action_time)
    if jump_block:
        messages[-1]["content"] = f"{jump_block}\n\n{messages[-1]['content']}"

    diag = {
        "system_tokens": estimate_tokens(system_content),
        "state_tokens": estimate_tokens(state_block),
        "catalog_tokens": estimate_tokens(catalog),
        "meaning_tokens": estimate_tokens(meaning_block),
        "npc_tokens": estimate_tokens(npc_block),
        # 【关系的转折】那一段。它每轮都在、大小只跟攒了多少条里程碑有关，
        # 调 MILESTONE_TOKEN_BUDGET 时看这个数
        "milestone_tokens": estimate_tokens(milestones),
        "roster_tokens": estimate_tokens(roster),
        "chronicle_tokens": estimate_tokens(chronicle_block),
        # 【场面】那一段的字数。它不再随「进没进私聊线」跳变——线没了，
        # 它每轮都在，大小只跟地点描述写多长有关
        "scene_tokens": estimate_tokens(scene),
        "history_count": len(window),
        "mode": mode,
        "private_with": private_with if mode == PRIVATE_MODE else None,
        # 时钟走到哪了。前端那一行诊断读这几个字段
        "slot": str(getattr(sess, "slot", "") or ""),
        "day": max(1, int(getattr(sess, "day", 1) or 1)),
        "triggered": [
            {
                "id": e.id,
                "keywords": e.keywords,
                "constant": bool(e.constant),
                "depth": int(e.depth or 0),
            }
            for e in hits
        ],
        "npcs_onstage": [{"id": n.id, "name": n.name} for n in context_npcs],
        "npcs_here": [{"id": n.id, "name": n.name} for n in here],
        "intent_used": intent,
        # 裁决点名了谁。这几个名字是「字面没提到也发卡」的唯一来源，
        # 排查「该给卡的人没给」时先看这里是不是空的
        "refs_used": refs,
        # 这一轮实际注入了写作规则没有，方便核对勾选是否生效
        "rules_used": bool(rules_block),
    }
    return messages, diag
