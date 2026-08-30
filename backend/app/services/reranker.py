"""本地交叉编码重排：对 RRF 融合后的候选按 (query, 摘要原文) 成对精读打分。

模型/依赖不可用时静默降级为原顺序，绝不阻断生成。首次失败后记住不可用状态，
避免每章都重试慢加载。
"""
import logging
import threading

logger = logging.getLogger(__name__)

MODEL_NAME = "BAAI/bge-reranker-v2-m3"
# 只精排融合结果的头部：候选池本就由两路 OVERFETCH 撑宽，20 条足够覆盖
CANDIDATE_K = 20

_lock = threading.Lock()
_model = None
_unavailable = False


def _get_model():
    global _model, _unavailable
    if _model is not None or _unavailable:
        return _model
    with _lock:
        if _model is None and not _unavailable:
            try:
                import torch
                from sentence_transformers import CrossEncoder

                device = "cuda" if torch.cuda.is_available() else "cpu"
                logger.info("加载重排模型 %s（%s）……", MODEL_NAME, device)
                # local_files_only：模型已预下载到本地缓存，禁止加载时联网检查更新
                # ——本机系统代理是 socks4，HF 的联网检查会直接报错
                _model = CrossEncoder(MODEL_NAME, device=device, local_files_only=True)
                logger.info("重排模型加载完成")
            except Exception as exc:
                logger.warning("重排模型不可用，回退 RRF 排序：%s", exc)
                _unavailable = True
    return _model


def rerank_hits(query: str, hits: list[dict], candidate_k: int = CANDIDATE_K) -> tuple[list[dict], bool]:
    """对前 candidate_k 条命中按交叉编码分数重排，尾部保持原序拼回。

    返回 (重排后的列表, 是否实际重排)。同步阻塞（GPU 约百毫秒、CPU 秒级），
    调用方应放线程池执行。
    """
    if not query or len(hits) < 2:
        return hits, False
    model = _get_model()
    if model is None:
        return hits, False
    head = hits[:candidate_k]
    tail = hits[candidate_k:]
    try:
        scores = model.predict([(query, h.get("text") or "") for h in head])
    except Exception as exc:
        logger.warning("重排打分失败，回退 RRF 排序：%s", exc)
        return hits, False
    order = sorted(range(len(head)), key=lambda i: float(scores[i]), reverse=True)
    return [head[i] for i in order] + tail, True
