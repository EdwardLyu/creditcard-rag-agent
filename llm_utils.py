"""
LLM 相關工具函式
包含 Azure OpenAI 的 embedding 和聊天功能
"""
import os
from datetime import datetime, timezone, timedelta
from openai import AzureOpenAI
from pandas.core.arrays import boolean
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# 從環境變數中獲取配置
aoai_key = os.getenv("AOAI_KEY")
aoai_url = os.getenv("AOAI_URL")
aoai_model_version = os.getenv("AOAI_MODEL_VERSION")
embedding_api_key = os.getenv("EMBEDDING_API_KEY")
embedding_url = os.getenv("EMBEDDING_URL")


def query_aoai_embedding(question):
    """
    使用 Azure OpenAI 取得文字的 embedding 向量

    Args:
        question: 要轉換為 embedding 的文字

    Returns:
        list: embedding 向量，失敗時返回空列表
    """
    try_cnt = 2
    while try_cnt > 0:
        try_cnt -= 1
        api_key = embedding_api_key
        api_base = embedding_url
        try:
            client = AzureOpenAI(
                api_key=api_key,
                api_version=aoai_model_version,
                azure_endpoint=api_base,
            )
            embedding = client.embeddings.create(
                input=question,
                model="text-embedding-ada-002",
            )
            return embedding.data[0].embedding
        except Exception as e:
            print(f"get_embedding_resource error | err_msg={e}")

    return []

def chat_with_aoai_gpt(messages: list[dict], use_json_format: boolean = False) -> tuple[str, int, int]:
    """
    與 Azure OpenAI 服務互動的核心函數

    Args:
        messages: 包含對話歷史的列表，每個元素是包含 role 和 content 的字典
        use_json_format: 是否使用 JSON 格式（保留參數，目前未使用）

    Returns:
        tuple: 包含三個元素：
            - AI的回應內容 (str)
            - 輸入消息的 token 數量 (int)
            - 輸出回應的 token 數量 (int)
    """
    error_time = 0     # 記錄重試次數
    temperature = 0.7  # 控制回應的創造性/隨機性，0為最保守，1為最創造性

    while error_time <= 2:  # 最多重試3次
        error_time += 1
        try:
            # 初始化 Azure OpenAI 客戶端
            client = AzureOpenAI(
                api_key=aoai_key,
                azure_endpoint=aoai_url,
            )

            # 發送請求到 Azure OpenAI 服務
            aoai_response = client.chat.completions.create(
                model=aoai_model_version,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"} if use_json_format else None,
            )

            # 提取 AI 的回應
            assistant_message = aoai_response.choices[0].message.content

            # 返回 AI 回應及相關的 token 使用統計
            return (
                assistant_message
            )
        except Exception as e:
            print(f"錯誤：{str(e)}")
            return "", 0, 0  # 發生錯誤時返回空值

