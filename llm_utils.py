"""
LLM 相關工具函式

包含：
- 本地 BGE-M3 embedding
- Gemini（透過 OpenAI 相容 API）的聊天功能
"""
import os
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from openai import OpenAI  # 改成使用 OpenAI client（指向 Gemini 相容端點）

# 載入環境變數
from pathlib import Path

# 在這個檔案所在的資料夾，往上找 .env
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# ====== Gemini Chat 設定（取代原本的 Azure OpenAI） ======
gemini_api_key = os.getenv("GEMINI_API_KEY")
gemini_base_url = os.getenv("GEMINI_BASE_URL")
gemini_model = os.getenv("GEMINI_MODEL")

# 建立全域的 Gemini/OpenAI client
_gemini_client: OpenAI | None = None
if gemini_api_key:
    try:
        _gemini_client = OpenAI(
            api_key=gemini_api_key,
            base_url=gemini_base_url,
        )
    except Exception as e:
        print(f"初始化 Gemini OpenAI client 失敗：{e}")
        _gemini_client = None
else:
    print("警告：未設定 GEMINI_API_KEY，chat_with_aoai_gpt 將無法使用。")

# ====== BGE-M3 Embedding（保留原本本地 embedding 設計） ======
_bge_model = SentenceTransformer("BAAI/bge-m3")


def query_ai_embedding(text: str):
    """
    使用本地 BGE-M3 (BAAI/bge-m3) 取得文字 embedding 向量
    回傳: list[float]

    ※ 名稱維持 query_ai_embedding，實際上已經是本地模型，
      這樣可以避免其他檔案大改動。
    """
    try:
        emb = _bge_model.encode(text, normalize_embeddings=True)
        return emb.tolist()
    except Exception as e:
        print(f"local embedding error (bge-m3): {e}")
        return []


def chat_with_aoai_gpt(messages: list[dict], use_json_format: bool = False) -> str:
    """
    與 LLM 互動的核心函數（現在改為呼叫 Gemini 的 OpenAI 相容 API）

    Args:
        messages: 對話歷史列表，每個元素是 {"role": "...", "content": "..."} 的 dict
        use_json_format: 是否要求模型回傳 JSON 格式（會設定 response_format）

    Returns:
        str: 模型的回應內容，失敗時回傳空字串 ""
    """
    temperature = 0.7  # 控制回應的創造性/隨機性

    if _gemini_client is None:
        print("錯誤：Gemini client 尚未初始化成功或缺少 GEMINI_API_KEY。")
        return ""

    try:
        response = _gemini_client.chat.completions.create(
            model=gemini_model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"} if use_json_format else None,
        )

        assistant_message = response.choices[0].message.content
        return assistant_message or ""

    except Exception as e:
        print(f"錯誤：{str(e)}")
        return ""