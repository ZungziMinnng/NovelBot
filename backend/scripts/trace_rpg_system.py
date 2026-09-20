"""拆解 RPG 某一局发给叙事模型的 system：按段报字数、token 和占比。

**只读**：不写库、不调 LLM。做法是把 build_rpg_messages 真跑一遍，同时在每个
拼段函数上挂一个记录器，再按真实拼接顺序把记录对齐回各段。对齐结果会和真实
拼接逐字比对，对不上会打 ❌ —— 那说明 build_rpg_messages 的拼段顺序或函数名
改了，回来同步 HOOKS 和 INLINE 两张表。

用法（在 backend 目录下）：
    python -m scripts.trace_rpg_system --session 11
    python -m scripts.trace_rpg_system --session 11 --mode private --with 3
"""
import argparse
import asyncio
import inspect
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.rpg import RpgMessage, RpgModule, RpgSession
from app.services import rpg_context as C
from app.services.context_budget import estimate_tokens

# 挂记录器的拼段函数 → 段落名。顺序无关，对齐靠调用顺序
HOOKS = [
    ("render", "GM 抬头"),
    ("style_block", "玩法规则"),
    ("_meaning_block", "数值的含义"),
    ("_state_block", "你（状态）"),
    ("catalog_block", "道具与技能"),
    ("roster_block", "角色总表"),
    ("_npc_block", "在场角色卡"),
    ("scene_block", "场面"),
    ("event_memory", "长期回忆"),
    ("summary_block", "概要"),
    ("resolve_rules", "写作规则"),
    ("truncate_to_token_budget", "TRUNC"),  # 逐块截断 + 最后一次整体截断，靠内容区分
    ("current_scene_block", "SCENE_ANCHOR"),
]

# 代码里 append 前做过 .strip() 的段。漏了会让重建比真实多几个字
STRIPPED = {"GM 抬头"}

# 逐块截断那两块的抬头 → 段落名
TRUNC_PREFIXES = [("【外场】", "外场"), ("【世界设定】", "世界设定")]


def _install_readonly_guards() -> None:
    """把一切写库动作拦死。这是真实库，跑分析绝不允许落任何一笔。"""
    async def _noop(*a, **k):
        return None

    def _blocked(*a, **k):
        raise RuntimeError("只读模式：禁止写库")

    AsyncSession.commit = _noop
    AsyncSession.flush = _noop
    AsyncSession.add = _blocked
    AsyncSession.delete = _blocked


def _make_recorder(orig, label, sink):
    """包一层记录器。必须用工厂函数传参，循环里直接闭包会全捕获成最后一个函数。"""
    if inspect.iscoroutinefunction(orig):
        async def wrapper(*a, **k):
            result = await orig(*a, **k)
            if isinstance(result, str):
                sink.append((label, result, a))
            return result
    else:
        def wrapper(*a, **k):
            result = orig(*a, **k)
            if isinstance(result, str):
                sink.append((label, result, a))
            return result
    return wrapper


async def _run(session_id: int, mode: str, private_with: int | None):
    recorded: list[tuple[str, str, tuple]] = []
    for name, label in HOOKS:
        setattr(C, name, _make_recorder(getattr(C, name), label, recorded))

    async with AsyncSessionLocal() as db:
        sess = await db.get(RpgSession, session_id)
        if sess is None:
            sys.exit(f"没有 id={session_id} 这一局")
        module = await db.get(RpgModule, sess.module_id)
        msgs = list((await db.execute(
            select(RpgMessage).where(RpgMessage.session_id == session_id).order_by(RpgMessage.id)
        )).scalars().all())

        # 对准最近一次真实调用：最后一条玩家输入就是那一轮的 new_input，
        # 它之前的消息就是那一轮的 history（刚落库的那句会被代码排掉）
        last_user = max((i for i, m in enumerate(msgs) if m.role == "user"), default=None)
        history = msgs[:last_user] if last_user is not None else msgs
        new_input = msgs[last_user].content if last_user is not None else ""

        messages, diag = await C.build_rpg_messages(
            db, module, sess, history, new_input, None, None, mode, private_with,
        )
    return module, sess, messages, diag, recorded, history, new_input


def _assemble(recorded, module):
    """把记录对齐回真实拼接：剔掉内部重复的截断记录，剩下按抬头认段落。"""
    truncs = [r for r in recorded if r[0] == "TRUNC" and r[2]]
    # 整体截断是 build_rpg_messages 里最后一次 truncate 调用（拼完 sections、
    # 算完场面锚之后）。按「最长输入」猜不可靠：概要正文没截断前可能比它还长
    final_input = truncs[-1][2][0] if truncs else None
    # 拼段函数内部自己也会调 truncate：数值的含义/场面跟外层一模一样，概要是
    # 外层的子串（外层多一句抬头）。凡是和正式段落互相包含的记录，都是重复
    labeled = [t for lb, t, _ in recorded if lb not in ("TRUNC", "SCENE_ANCHOR") and t]

    sections, skipped, anchor = [], [], ""
    for label, text, args in recorded:
        if label == "SCENE_ANCHOR":
            anchor = text
            continue
        if label == "TRUNC":
            if args and (args[0] == final_input
                         or any(text in t or t in text for t in labeled)):
                continue  # 整体拼接本身，或上面那条重复记录
            for prefix, name in TRUNC_PREFIXES:
                if text.startswith(prefix):
                    label = name
                    break
        text = text.strip() if label in STRIPPED else text
        # 真实代码里每一块都带 if 判空，空块不会 append（空串也不会多出分隔符）
        if text:
            sections.append((label, text))
        else:
            skipped.append(label)

    # 两处没有独立函数、直接拼进去的段，按代码里的位置插回去
    def insert_after(name, items):
        idx = next((i for i, (lb, _) in enumerate(sections) if lb == name), None)
        if idx is not None:
            for offset, item in enumerate(items):
                sections.insert(idx + 1 + offset, item)

    instruction = (module.system_instruction or "").strip()
    worldview = (module.worldview or "").strip()
    sample = (module.narration_sample or "").strip()
    insert_after("玩法规则", [
        ("GM 指令", instruction),
        ("世界观", "【世界观】\n" + worldview if worldview else ""),
    ])
    # 叙事样例紧跟在【世界设定】后面；没命中世界书时它前面就是【场面】
    tail = "世界设定" if any(lb == "世界设定" for lb, _ in sections) else "场面"
    insert_after(tail, [("叙事样例", "【叙事样例】\n" + sample if sample else "")])
    sections = [(lb, tx) for lb, tx in sections if tx]

    return sections, skipped, anchor, final_input


def _report(module, sess, messages, diag, sections, skipped, anchor, final_input, history, new_input):
    joined = "\n\n".join(t for _, t in sections)
    print(f"模组: id={module.id} {module.name!r} 类型={module.genre!r} 玩法={module.play_style!r}")
    print(f"局: id={sess.id} 角色={sess.char_name!r} 回合数={sess.turn_count} "
          f"时段={sess.slot} 地点={sess.location!r}")
    print(f"这一轮: history {len(history)} 条 + 输入 {len(new_input)} 字（{new_input!r}）\n")

    if joined == final_input:
        print("对齐校验: ✅ 与真实拼接逐字一致")
    else:
        i = 0
        while i < min(len(joined), len(final_input)) and joined[i] == final_input[i]:
            i += 1
        print(f"对齐校验: ❌ 重建 {len(joined)} vs 实际 {len(final_input)}，首个差异在第 {i} 字")
        print("  重建:", repr(joined[max(0, i - 45):i + 45]))
        print("  实际:", repr(final_input[max(0, i - 45):i + 45]))
        print("  → 拼段顺序或函数名改过了，回来同步 HOOKS / TRUNC_PREFIXES")

    print(f"\n{'段落':<12}{'字数':>8}{'≈token':>9}{'占比':>8}")
    print("-" * 37)
    total = len(joined) or 1
    for label, text in sections:
        print(f"{label:<12}{len(text):>8}{estimate_tokens(text):>9}{len(text) / total * 100:>7.1f}%")
    print("-" * 37)
    print(f"{'合计':<12}{len(joined):>8}{estimate_tokens(joined):>9}")
    print(f"{'【场面锚】':<12}{len(anchor):>8}{estimate_tokens(anchor):>9}  (截断后追加，不吃预算)")

    system = messages[0]["content"]
    truncated = len(system) < len(joined) + len(anchor) + 2
    print(f"\n预算 {C.SYSTEM_TOKEN_BUDGET} token｜整条 system ≈{estimate_tokens(system)} token "
          f"/ {len(system)} 字｜占用约 {estimate_tokens(system) / C.SYSTEM_TOKEN_BUDGET * 100:.0f}%")
    print("尾部截断:", "⚠️ 触发了，尾巴上的段被砍" if truncated else "没触发")
    if skipped:
        print("这轮没注入:", "、".join(skipped))
    print(f"历史窗口 {len(messages) - 2} 条｜写作规则已注入: {diag.get('rules_used')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="拆解 RPG 一局的 system 各段字数（只读）")
    parser.add_argument("--session", type=int, required=True, help="存档局 id")
    parser.add_argument("--mode", default=C.GROUP_MODE, choices=sorted(C.TURN_MODES),
                        help="复刻哪一轮的模式，默认群聊")
    parser.add_argument("--with", dest="private_with", type=int, default=None, help="私聊对象 NPC id")
    args = parser.parse_args()

    _install_readonly_guards()
    module, sess, messages, diag, recorded, history, new_input = asyncio.run(
        _run(args.session, args.mode, args.private_with)
    )
    sections, skipped, anchor, final_input = _assemble(recorded, module)
    _report(module, sess, messages, diag, sections, skipped, anchor, final_input, history, new_input)


if __name__ == "__main__":
    main()
