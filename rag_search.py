# rag_search.py
import json
import math
from typing import List, Dict, Any

from llm_utils import query_ai_embedding

INDEX_PATH = "cards_rag_embedded.jsonl"

# 開機時讀進記憶體
_cards_index: List[Dict[str, Any]] = []


def load_index():
    """載入 RAG index 到記憶體，只做一次"""
    global _cards_index
    if _cards_index:
        return

    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            # 確保有 embedding
            if "embedding" in obj and obj["embedding"]:
                # 這裡 embedding 保持 list[float] 就好
                _cards_index.append(obj)
    print(f"✅ RAG index loaded, total chunks = {len(_cards_index)}")


def _cosine(a: List[float], b: List[float]) -> float:
    """超簡單版本的 cosine similarity"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def search_chunks(
    query: str,
    top_k: int = 5,
    card_filter: str | None = None,
    doc_type: str | None = None,
) -> List[Dict[str, Any]]:
    """
    依照 query 做 embedding，計算與所有 chunk 的 cosine 相似度，回傳前 top_k 筆。

    query: 使用者問題
    card_filter: 若只想查某張卡，例如 "國泰世華CUBE卡"
    doc_type: "credit_card_profile" / "benefit_scheme" / "benefit_rule" / "welcome_offer"
    """
    load_index()
    q_emb = query_ai_embedding(query)
    if not q_emb:
        return []

    def _search(apply_card_filter: bool) -> List[tuple[float, Dict[str, Any]]]:
        scored: List[tuple[float, Dict[str, Any]]] = []

        for ch in _cards_index:
            # 1) 卡片過濾（可選）
            if apply_card_filter and card_filter:
                card = (ch.get("card_name") or "").strip()
                cf = card_filter.strip()
                # 如果兩邊都完全沒包含對方，就當作不是這張卡
                if cf not in card and card not in cf:
                    continue

            # 2) doc_type 過濾（可選）
            if doc_type and ch.get("doc_type") != doc_type:
                continue

            emb = ch.get("embedding")
            if not emb:
                continue

            sim = _cosine(q_emb, emb)
            scored.append((sim, ch))

        return scored

    # 先嘗試有 card_filter 的狀態
    scored = _search(apply_card_filter=True)

    # 如果有指定 card_filter，但完全沒有命中，就退一步「不套 card_filter 再搜一次」
    if not scored and card_filter:
        scored = _search(apply_card_filter=False)

    # 如果依然沒有，就直接回空 list
    if not scored:
        return []

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_k]]


def rag_search(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    簡單封裝：如果不需要卡片/文件類型過濾，就直接用這個。
    """
    return search_chunks(query, top_k=top_k)