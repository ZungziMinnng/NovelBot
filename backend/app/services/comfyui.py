"""调本地 ComfyUI 出图（RPG NPC 立绘）。

工作流不内置：ComfyUI 的 /prompt 只吃 API 格式，而界面里保存的是 UI 格式，
两者不通用。用户需在 ComfyUI 里「工作流 → 导出（API）」，把正向提示词那段
文字整体换成 %PROMPT%，存到 data/comfy_workflows/ 下。除了 LoRA 开关那一节，
本模块对工作流内容一无所知，只认占位符约定，所以换工作流不用改代码。
"""

import asyncio
import copy
import json
import logging
import random
import re
import time
import uuid
from pathlib import Path
from typing import Any

from app.config import settings
from app.services import llm_client

logger = logging.getLogger(__name__)

PROMPT_PH = "%PROMPT%"
_SEED_PH = "%SEED%"
_SEED_KEYS = {"seed", "noise_seed"}
# 底模认这两个键名：ckpt_name 是各家加载器的通用叫法（含 easy-use 的 fullLoader），
# hires_ckpt_name 是 HighRes-Fix 脚本里高清修复阶段用的那个
_CKPT_KEYS = {"ckpt_name", "hires_ckpt_name"}
_POLL_INTERVAL = 1.0
# LoRA 开关认这两种形状，别的加载器（LoraTagLoader 等）一律不管，扫不到就当没有
_LORA_NODES = {"LoraLoader", "LoraLoaderModelOnly"}
_POWER_LORA = "Power Lora Loader"
_POWER_KEY = re.compile(r"^lora_\d+$")
# 2^50，跟 ComfyUI 前端的「随机」按钮对齐。它那边是：
#   max = Math.min(1125899906842624, max)   // limit to something that javascript can handle
#   value = Math.floor(Math.random() * range) * step + min
# 种子控件是 min=0 step=1，所以实际范围就是 [0, 2^50-1]。节点自己声明到 2^64-1
# 也会被那行 Math.min 夹住（JS 的 number 撑不住更大的整数），所以别照节点上限写
_MAX_SEED = 2**50 - 1


class ComfyError(Exception):
    """带用户可读中文说明的失败，路由层直接拿 str(e) 当 detail。"""


def random_seed() -> int:
    """摇一个种子，取值域和 ComfyUI 的随机按钮逐一对应（闭区间 [0, 2^50-1]）。"""
    return random.randint(0, _MAX_SEED)


def _workflow_dir() -> Path:
    return Path(settings.data_dir) / "comfy_workflows"


# ── 加载 ──────────────────────────────────────────────────────────────────

def list_workflows() -> list[str]:
    """目录下有哪些工作流，返回去掉 .json 的文件名。

    目录不存在就返回空——设置页那段说明已经告诉用户文件该放哪，这里不用抛错。
    """
    d = _workflow_dir()
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def load_workflow(name: str = "npc_portrait") -> dict:
    # name 来自模组的 image_config，是用户可编辑的 JSON，所以只认单层文件名，
    # 不让 ../ 顺着走出 comfy_workflows
    path = _workflow_dir() / f"{Path(name).name}.json"
    if not path.exists():
        raise ComfyError(
            f"找不到工作流文件：{path}\n"
            "请在 ComfyUI 界面打开一个工作流，用「工作流 → 导出（API）」存成 API 格式，"
            f"把正向提示词那段文字整体替换成 {PROMPT_PH}，再保存到这个路径。"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ComfyError(f"工作流文件不是合法 JSON：{e}")
    # UI 格式带 nodes/links 数组，API 格式是 {节点id: {class_type, inputs}}
    if not isinstance(data, dict) or not data or not all(
        isinstance(v, dict) and "class_type" in v for v in data.values()
    ):
        raise ComfyError(
            "这是界面格式的工作流，API 提交不认。"
            "请在 ComfyUI 里用「工作流 → 导出（API）」重新导出。"
        )
    return data


# ── 占位符填充 ────────────────────────────────────────────────────────────

def _subst(value: Any, repl: dict) -> Any:
    """递归替换。整段等于占位符时换成原始类型（int），否则做字符串内替换。
    节点间的连线是 ["6", 0] 这种列表，键不匹配所以原样穿过。"""
    if isinstance(value, str):
        if value in repl:
            return repl[value]
        for k, v in repl.items():
            if isinstance(v, str) and k in value:
                value = value.replace(k, v)
        return value
    if isinstance(value, list):
        return [_subst(x, repl) for x in value]
    if isinstance(value, dict):
        return {k: _subst(v, repl) for k, v in value.items()}
    return value


def _describe_text_nodes(wf: dict) -> str:
    """列出所有文本编码节点，告诉用户该把哪一段换成占位符。"""
    hits = []
    for nid, node in wf.items():
        if "TextEncode" not in str(node.get("class_type", "")):
            continue
        text = (node.get("inputs") or {}).get("text")
        if isinstance(text, str) and text.strip():
            hits.append(f"  #{nid} {node['class_type']}：{text[:50]}…")
    return "\n".join(hits) or "  （这个工作流里没找到任何文本编码节点）"


def fill(
    wf: dict, prompt: str, width: int = 0, height: int = 0, seed: int | None = None,
) -> dict:
    wf = copy.deepcopy(wf)
    raw = json.dumps(wf, ensure_ascii=False)

    if PROMPT_PH not in raw:
        raise ComfyError(
            f"工作流里没有 {PROMPT_PH} 占位符，不知道该把提示词放进哪个节点。\n"
            f"请把下面某一个节点的文本整体替换成 {PROMPT_PH}：\n"
            + _describe_text_nodes(wf)
        )

    if seed is None:
        seed = random_seed()

    repl: dict[str, Any] = {PROMPT_PH: prompt}
    if width:
        repl["%WIDTH%"] = width
    if height:
        repl["%HEIGHT%"] = height
    has_seed_ph = _SEED_PH in raw
    if has_seed_ph:
        repl[_SEED_PH] = seed

    for node in wf.values():
        node["inputs"] = _subst(node.get("inputs") or {}, repl)

    if not has_seed_ph:
        # 导出的工作流种子多半锁成 fixed，此时 ComfyUI 会命中缓存直接返回上一张图。
        # 全部写成同一个 seed 而不是各摇一个：工作流里可能有好几个采样器
        # （npc_portrait 就有两个），各摇一个的话「这张图是哪个种子出的」没有
        # 唯一答案，把种子填回来也复现不出同一张图
        for node in wf.values():
            for key, val in (node.get("inputs") or {}).items():
                if key in _SEED_KEYS and isinstance(val, int) and not isinstance(val, bool):
                    node["inputs"][key] = seed

    return wf


# ── LoRA 开关 / 底模覆写 ──────────────────────────────────────────────────
# 这两块是本模块读懂工作流内容的地方。用占位符做不到：前端得先知道有哪些
# LoRA 才能画开关，而占位符要用户手改 JSON 才有。覆写只在提交前打补丁，
# 磁盘上那份工作流不动——在 ComfyUI 界面里打开还是用户自己存的样子


def _lora_slots(wf: dict):
    """遍历出每条 LoRA 的 (所在 inputs, 存放的 key, 文件名)。

    认两种形状：原生 LoraLoader 一个节点挂一条（key 为 None），rgthree 的
    Power Lora Loader 一个节点里 lora_1/lora_2… 挂好几条。别的加载器
    （LoraTagLoader 之类）扫不到，就当这份工作流没有 LoRA。
    """
    for node in wf.values():
        ct = str(node.get("class_type", ""))
        inputs = node.get("inputs") or {}
        if ct in _LORA_NODES:
            name = inputs.get("lora_name")
            if isinstance(name, str) and name:
                yield inputs, None, name
        elif ct.startswith(_POWER_LORA):
            for key, val in inputs.items():
                if _POWER_KEY.match(key) and isinstance(val, dict):
                    name = val.get("lora")
                    if isinstance(name, str) and name:
                        yield inputs, key, name


def _num(val, default: float) -> float:
    # isinstance(True, int) 是 True，布尔得单独挡掉
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    return default


def inspect_loras(name: str = "npc_portrait") -> list[dict]:
    """这份工作流里有哪些 LoRA、现在开没开、强度多少，给前端画开关用。

    返回的是工作流文件里的原始状态，不含模组覆写——覆写存在 image_config 里，
    由前端自己叠上去。同一个文件在图里出现两次只报一条。
    """
    out: list[dict] = []
    seen: set[str] = set()
    for inputs, key, lora in _lora_slots(load_workflow(name)):
        if lora in seen:
            continue
        seen.add(lora)
        if key is None:
            # 原生加载器没有开关字段，强度 0 就是关
            strength = _num(inputs.get("strength_model"), 1.0)
            on = strength != 0
        else:
            strength = _num(inputs[key].get("strength"), 1.0)
            on = bool(inputs[key].get("on", True))
        # 导出的文件里常是 1.0000000000000002 这种浮点噪声，直接进滑块很难看
        out.append({"lora": lora, "on": on, "strength": round(strength, 3)})
    return out


def apply_loras(wf: dict, overrides: dict) -> dict:
    """把前端存的覆写打进工作流。原地改，调用方保证 wf 已是副本。

    覆写按 **文件名** 索引而不是节点 id：用户重新导出一次工作流，节点 id 就
    可能全变，文件名不会。同一个文件出现在两处的话两处一起改。
    """
    if not overrides:
        return wf
    for inputs, key, lora in _lora_slots(wf):
        ov = overrides.get(lora)
        if not isinstance(ov, dict):
            continue
        on = bool(ov.get("on", True))
        strength = _num(ov.get("strength"), 1.0)
        if key is None:
            # 原生加载器没有开关字段，靠写 0 来关。ComfyUI 的 load_lora 里那句
            # 提前返回是 `strength_model == 0 and strength_clip == 0`——**两个都得是
            # 0** 才会原样返回模型、连 safetensors 都不读。所以 strength_clip 也得
            # 一起清掉，只清 model 那个的话文件照读、CLIP 侧照打补丁
            inputs["strength_model"] = strength if on else 0.0
            if not on and "strength_clip" in inputs:
                inputs["strength_clip"] = 0.0
            # 开着的时候故意不动 strength_clip：工作流可能特意把 model 和 clip
            # 调成不一样（0.8 / 0.5），拿 model 那个值盖过去等于悄悄改了配方。
            # 关掉时写的那个 0 也不会留下——补丁打在每次现读的副本上，不落盘
        else:
            inputs[key]["on"] = on
            inputs[key]["strength"] = strength
    return wf


# ── 底模覆写 ──────────────────────────────────────────────────────────────


def _ckpt_slots(wf: dict):
    """遍历出每处写死的底模：(节点 id, 节点, 所在 inputs, 键名, 当前值)。

    按键名认，不按节点 class_type——同一个底模常被好几个加载器各写一遍
    （草稿 / 上色 / 面部细化各一个），高清修复脚本里还另有一个
    `hires_ckpt_name`。只要键名对得上就都算一处，覆盖时一处都不能落下。
    """
    for nid, node in wf.items():
        inputs = node.get("inputs") or {}
        for key in _CKPT_KEYS:
            val = inputs.get(key)
            if isinstance(val, str) and val:
                yield nid, node, inputs, key, val


def inspect_ckpts(name: str = "npc_portrait") -> list[dict]:
    """这份工作流在哪些地方写死了底模、分别是哪个，给前端画下拉用。

    返回的是工作流文件里的原始值，不含覆写——覆写存在 image_config 里，由
    前端自己叠上去。空列表表示这份工作流不认底模（例如走 UNETLoader 单文件
    的那种），前端据此不画控件，免得出现一个填了没反应的死下拉。
    """
    return [
        {
            "node": nid,
            "class": str(node.get("class_type", "")),
            "key": key,
            "name": val,
        }
        for nid, node, _inputs, key, val in _ckpt_slots(load_workflow(name))
    ]


def apply_ckpt(wf: dict, name: str) -> dict:
    """把用户选的底模打进工作流。原地改，调用方保证 wf 已是副本。

    一处不落地改：工作流里写死的底模往往有好几处，只改第一处就是「主模型
    换了、高清修复还在用旧的」——高清是同一个 latent 接着去噪（denoise 一般
    0.4 上下），中途换模型会风格漂移。扫不到任何一处就原样返回、不报错：
    工作流本来就不认底模时（UNETLoader 那种）用户填了也只是没效果，该由
    前端说明，不该在出图时炸。
    """
    if not name:
        return wf
    for _nid, _node, inputs, key, _val in _ckpt_slots(wf):
        inputs[key] = name
    return wf


# ── 结果与错误提取 ────────────────────────────────────────────────────────

def _first_image(outputs: dict) -> dict | None:
    """扫出图，兼容 SaveImage / PreviewImage 和用户自换的工作流。

    **优先 SaveImage 那张**：多阶段工作流（草稿→上色→面部细化）里每个阶段都挂
    PreviewImage，光扫「第一个有图的节点」会抓到草稿阶段那张。ComfyUI 里
    PreviewImage 存临时目录、`type` 是 `temp`，SaveImage 存输出目录、`type` 是
    `output`——挑 `output` 的就拿到最终那张。工作流只有 PreviewImage 时
    （没接 SaveImage）就落回第一张，不至于什么都返回不了。
    """
    fallback = None
    for node_out in outputs.values():
        for img in (node_out or {}).get("images") or []:
            pick = {
                "filename": img.get("filename", ""),
                "subfolder": img.get("subfolder", ""),
                "type": img.get("type", "output"),
            }
            if pick["type"] == "output":
                return pick
            if fallback is None:
                fallback = pick
    return fallback


def _format_submit_error(resp) -> str:
    """/prompt 的 400 里藏着节点校验详情（模型文件名对不上等都走这条）。"""
    try:
        body = resp.json()
    except Exception:
        return f"ComfyUI 拒绝了任务（HTTP {resp.status_code}）"
    parts = []
    msg = (body.get("error") or {}).get("message")
    if msg:
        parts.append(str(msg))
    for nid, ne in (body.get("node_errors") or {}).items():
        for e in (ne or {}).get("errors") or []:
            field = (e.get("extra_info") or {}).get("input_name") or ""
            parts.append(
                f"节点 #{nid} {ne.get('class_type', '')} "
                f"{field}：{e.get('message', '')}".strip()
            )
    return "ComfyUI 拒绝了任务 — " + ("；".join(parts) or f"HTTP {resp.status_code}")


def _format_exec_error(entry: dict) -> str:
    msgs = []
    for item in ((entry.get("status") or {}).get("messages") or []):
        if isinstance(item, list) and len(item) >= 2 and item[0] == "execution_error":
            d = item[1] or {}
            msgs.append(
                f"节点 #{d.get('node_id')} {d.get('node_type', '')}："
                f"{d.get('exception_message', '')}"
            )
    return "；".join(msgs) or "未知错误，去 ComfyUI 控制台看日志"


# ── 主流程 ────────────────────────────────────────────────────────────────

async def generate(
    prompt: str, width: int = 0, height: int = 0, timeout: float = 300.0,
    workflow: str = "npc_portrait", seed: int | None = None,
    loras: dict | None = None, ckpt: str | None = None,
) -> bytes:
    """提交工作流并等出图，返回图片字节。失败一律抛 ComfyError。

    seed 为 None 时自己摇一个。想把种子记下来的调用方自己先 random_seed()
    再传进来——这样返回值仍然只是图片字节，调用契约不变。

    loras 是 {文件名: {"on": bool, "strength": float}}，形状见 apply_loras。
    ckpt 是要覆盖的底模文件名，空 / None 表示用工作流里写死那个，见 apply_ckpt。
    """
    wf = fill(load_workflow(workflow), prompt, width, height, seed)
    apply_loras(wf, loras or {})
    apply_ckpt(wf, ckpt or "")
    base = settings.comfyui_base_url.rstrip("/")

    # use_proxy=False 是必须的：ComfyUI 在 127.0.0.1，而 httpx 的 mounts 没有
    # no_proxy 语义，用默认参数会把本地请求也送进用户配的代理
    async with llm_client._build_httpx_client(use_proxy=False) as client:
        try:
            resp = await client.post(
                f"{base}/prompt",
                json={"prompt": wf, "client_id": uuid.uuid4().hex},
                timeout=30,
            )
        except Exception as e:
            raise ComfyError(
                f"连不上 ComfyUI（{base}）：{type(e).__name__}。"
                "确认它已启动，地址可在设置页修改。"
            )
        if resp.status_code != 200:
            raise ComfyError(_format_submit_error(resp))
        prompt_id = resp.json().get("prompt_id")
        if not prompt_id:
            raise ComfyError("ComfyUI 没有返回 prompt_id")

        logger.info("ComfyUI 已接单 %s，等待出图……", prompt_id)
        deadline = time.monotonic() + timeout
        image = None
        while image is None:
            if time.monotonic() > deadline:
                raise ComfyError(
                    f"生成超时（{timeout:.0f} 秒）。工作流可能挂了重型节点（如超分），"
                    "或显存不足正在换页。"
                )
            await asyncio.sleep(_POLL_INTERVAL)
            try:
                h = await client.get(f"{base}/history/{prompt_id}", timeout=20)
            except Exception as e:
                raise ComfyError(f"查询生成进度失败：{type(e).__name__}")
            if h.status_code != 200:
                continue
            entry = (h.json() or {}).get(prompt_id)
            if not entry:
                continue
            if ((entry.get("status") or {}).get("status_str")) == "error":
                raise ComfyError("ComfyUI 执行失败 — " + _format_exec_error(entry))
            image = _first_image(entry.get("outputs") or {})

        try:
            v = await client.get(f"{base}/view", params=image, timeout=60)
            v.raise_for_status()
        except Exception as e:
            raise ComfyError(f"取图失败：{type(e).__name__}")
        if not v.content:
            raise ComfyError("ComfyUI 返回了空图片")
        return v.content


async def ping() -> tuple[bool, str]:
    """设置页「测试连接」用。"""
    base = settings.comfyui_base_url.rstrip("/")
    try:
        async with llm_client._build_httpx_client(use_proxy=False) as client:
            r = await client.get(f"{base}/system_stats", timeout=5)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        ver = ((r.json() or {}).get("system") or {}).get("comfyui_version") or ""
        return True, f"已连接{'（ComfyUI ' + ver + '）' if ver else ''}"
    except Exception as e:
        return False, f"连不上：{type(e).__name__}"


async def list_checkpoints() -> list[str]:
    """问 ComfyUI 有哪些底模可选，给前端画下拉用。

    走 /object_info 而不是自己去列磁盘目录：checkpoint 具体放在哪由 ComfyUI
    那边的 extra_model_paths 决定，NovelBot 不该假定一个路径。问
    CheckpointLoaderSimple 就够了——它和 easy-use 的 fullLoader 取的是同一份
    文件名列表。连不上抛 ComfyError 让路由转 502；能连上但拿不到列表返回空。
    """
    base = settings.comfyui_base_url.rstrip("/")
    try:
        async with llm_client._build_httpx_client(use_proxy=False) as client:
            r = await client.get(f"{base}/object_info/CheckpointLoaderSimple", timeout=15)
    except Exception as e:
        raise ComfyError(
            f"连不上 ComfyUI（{base}）：{type(e).__name__}。"
            "确认它已启动，地址可在设置页修改。"
        )
    if r.status_code != 200:
        raise ComfyError(f"ComfyUI 没给出底模列表（HTTP {r.status_code}）")
    required = (
        (((r.json() or {}).get("CheckpointLoaderSimple") or {}).get("input") or {})
        .get("required") or {}
    ).get("ckpt_name") or []
    options = required[0] if required else []
    return [str(x) for x in options] if isinstance(options, list) else []
