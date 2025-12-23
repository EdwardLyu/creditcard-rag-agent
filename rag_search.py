import json
from typing import List, Dict, Any, Optional

# --- 1. LangChain / BGE 相關套件 ---
from langchain_community.embeddings import HuggingFaceBgeEmbeddings
from langchain_community.vectorstores import FAISS

# --- 2. 設定與路徑 ---
FAISS_INDEX_PATH = "cards_rag_faiss_index" # 假設 FAISS 索引已存在並預先建立
BGE_MODEL_NAME = "BAAI/bge-m3"

# --- 3. 全域變數 ---
_faiss_db: Optional[FAISS] = None
# 固定 top_k = 5
DEFAULT_TOP_K = 5 

# --- 4. 初始化 Embedding 模型 ---
_embeddings_model: HuggingFaceBgeEmbeddings = HuggingFaceBgeEmbeddings(
    model_name=BGE_MODEL_NAME,
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True},
)


def load_index():
    """載入 RAG index 到記憶體，只做一次 (使用 FAISS 向量庫)"""
    global _faiss_db
    if _faiss_db is not None:
        return

    try:
        # 載入預先建立好的 FAISS 索引和資料
        _faiss_db = FAISS.load_local(
            folder_path=FAISS_INDEX_PATH, 
            embeddings=_embeddings_model, 
            allow_dangerous_deserialization=True
        )
        print(f"✅ RAG FAISS index loaded from {FAISS_INDEX_PATH}")

    except Exception as e:
        print(f"❌ 載入 FAISS 索引失敗，請確保 '{FAISS_INDEX_PATH}' 存在並包含有效索引。錯誤: {e}")
        _faiss_db = None


def search_chunks(
    query: str,
    top_k: int = DEFAULT_TOP_K, 
    metadata_filter: Dict[str, Any] | None = None, # ✅ 改成接收一個字典
) -> List[Dict[str, Any]]:
    """
    Args:
        query: 使用者問題
        top_k: 回傳筆數
        metadata_filter: 過濾條件字典，例如 {"card_name": "國泰CUBE卡", "doc_type": "benefit_scheme"}
                         只要索引中有該欄位，就可以作為過濾條件。
    """
    load_index()
    
    if _faiss_db is None:
        return []

    # 1. 處理過濾條件
    final_filter = {}
    if metadata_filter:
        for k, v in metadata_filter.items():
            if v is not None:
                if isinstance(v, str):
                    final_filter[k] = v.strip()
                else:
                    final_filter[k] = v

    faiss_filter = final_filter if final_filter else None

    # 2. 執行 FAISS 檢索
    try:
        results = _faiss_db.similarity_search(
            query, 
            k=top_k,
            filter=faiss_filter # ✅ 直接傳入處理好的字典
        )
    except Exception as e:
        print(f"❌ FAISS 檢索失敗: {e}")
        return []

    formatted_chunks = []
    print(results)
    for i, doc in enumerate(results, 1):
        meta = doc.metadata
        content = doc.page_content

        # 1. 提取關鍵欄位 (如果沒有則留空或顯示預設值)
        card_name = meta.get("card_name", "未知卡片")
        scheme_name = meta.get("scheme_name")
        doc_type = meta.get("doc_type", "一般資訊")
        valid_period = meta.get("valid_period", "未指定")
        
        # 2. 處理 title，讓 LLM 一眼知道這段是在講什麼
        if scheme_name:
            title = f"{card_name} - {scheme_name} ({doc_type})"
        else:
            title = f"{card_name} ({doc_type})"

        # 3. 處理指定通路列表 (channels_flat)
        # 這對回答「麥當勞有沒有回饋」這類問題至關重要
        channels_flat = meta.get("channels_flat", [])
        channels_str = ""
        if channels_flat and isinstance(channels_flat, list):
            # 將列表轉為逗號分隔字串，節省 token 但保持語意
            channels_str = f"\n- **包含通路關鍵字**: {', '.join(channels_flat)}"

        # 4. 組裝單個 Chunk 的文本
        # 使用 Markdown 格式，讓 LLM 容易區分不同區塊
        chunk_text = (
            f"### 資料來源 {i}: {title}\n"
            f"- **適用期間**: {valid_period}\n"
            f"- **內容詳情**: {content}"
            f"{channels_str}"
        )
        
        formatted_chunks.append(chunk_text)

    # 5. 將所有 chunks 用分隔線接起來
    return "\n\n---\n\n".join(formatted_chunks)



def rag_search(query: str, top_k: int = DEFAULT_TOP_K) -> List[Dict[str, Any]]:
    """
    簡單封裝：如果不需要卡片/文件類型過濾，就直接用這個。
    """
    return search_chunks(query, top_k=top_k)