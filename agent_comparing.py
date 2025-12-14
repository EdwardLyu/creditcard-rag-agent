# agent_comparing.py
import os
import sys
import json
import asyncio
from pathlib import Path

# 3rd party imports
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
from openai import OpenAI

# === [重要] 導入你的 RAG 搜尋工具 ===
# 確保 rag_search.py, llm_utils.py 和 cards_rag_embedded.jsonl 在同一目錄下
try:
    from rag_search import search_chunks, load_index
except ImportError:
    print("❌ 找不到 rag_search.py，請確認檔案位置。", file=sys.stderr)
    sys.exit(1)

# ==========================================
# 1. 初始化環境與設定
# ==========================================

# 載入 .env
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/"
)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp") 

# 初始化 Gemini Client
try:
    llm_client = OpenAI(
        api_key=GEMINI_API_KEY,
        base_url=GEMINI_BASE_URL,
    )
except Exception as e:
    print(f"❌ Gemini Client 初始化失敗: {e}", file=sys.stderr)
    llm_client = None

# [重要] 預先載入 RAG 資料庫
# 這會觸發 llm_utils 載入 Embedding 模型 (BGE-M3)，確保後續搜尋速度
print("📚 正在初始化 RAG 知識庫...", file=sys.stderr)
try:
    load_index()
    print("✅ RAG 知識庫載入完成！", file=sys.stderr)
except Exception as e:
    print(f"❌ RAG 載入失敗: {e}", file=sys.stderr)

# 建立 MCP Server
mcp = FastMCP("comparing-expert-agent")

# ==========================================
# 2. 定義真實工具 (Real Tools)
# ==========================================

async def tool_search_bank_info(query: str, card_filter: str = None) -> str:
    """
    搜尋銀行產品、權益或信用卡相關資訊。
    這是 Agent 唯一獲取外部知識的管道。
    """
    print(f"    🔎 [RAG Search] 搜尋: {query} | 過濾卡片: {card_filter}", file=sys.stderr)
    
    # [關鍵優化]
    # search_chunks 內部會執行 Embedding 運算 (CPU/GPU 密集)
    # 必須使用 asyncio.to_thread 放到背景執行，否則會卡死整個 Agent
    try:
        results = await asyncio.to_thread(
            search_chunks, 
            query=query, 
            card_filter=card_filter, 
            top_k=5  # 取前 5 筆最相關
        )
        
        if not results:
            return json.dumps({"result": "查無相關資料，請嘗試更換關鍵字。"})

        # 整理回傳結果 (精簡化以節省 Token)
        simplified_results = []
        for r in results:
            simplified_results.append({
                "card": r.get("card_name", "未知卡片"),
                "type": r.get("doc_type", "一般資訊"),
                "content": r.get("text", "")
            })
            
        return json.dumps(simplified_results, ensure_ascii=False)

    except Exception as e:
        error_msg = f"搜尋執行錯誤: {str(e)}"
        print(f"❌ {error_msg}", file=sys.stderr)
        return json.dumps({"error": error_msg})

# ==========================================
# 3. 工具 Schemas 與 System Prompt
# ==========================================

INTERNAL_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "tool_search_bank_info",
            "description": "搜尋信用卡權益、回饋規則、年費等資訊。回答使用者關於產品的具體問題時必須使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜尋關鍵字，例如 'CUBE卡日本回饋' 或 '世界卡年費'"
                    },
                    "card_filter": {
                        "type": "string",
                        "description": "若問題明確針對某張卡，可填入卡片名稱以精準過濾 (如 'CUBE卡')"
                    }
                },
                "required": ["query"]
            }
        }
    }
]

COMPARING_SYSTEM_PROMPT = """
你是國泰世華銀行的「資深信用卡產品顧問」。
你的知識來源是內部的 RAG 資料庫，除此之外你不知道其他即時資訊。

### 回答原則：
1. **依據事實**：當使用者詢問權益、數字、規則時，**必須**使用 `tool_search_bank_info` 查詢。
2. **誠實告知**：如果搜尋結果中沒有資料，請直接說「資料庫中目前沒有相關資訊」，不要編造。
3. **結構化回答**：請消化搜尋到的內容，用條列式或表格整理給使用者，不要只貼原文。
4. **比較情境**：若使用者問「A卡跟B卡哪個好？」，請分別搜尋兩張卡的資料，再進行綜合比較。

### 思考流程：
- 收到問題 -> 分析關鍵字 -> 呼叫搜尋工具 -> 閱讀結果 -> 整理並回答。
"""

# ==========================================
# 4. REACT LOOP (核心邏輯)
# ==========================================

async def _generate_response(user_query: str, user_profile: str = "") -> str:
    if not llm_client:
        return "❌ 系統錯誤：LLM client 未初始化"

    # 建構對話歷史
    full_query = user_query
    if user_profile:
        full_query = f"使用者背景：{user_profile}\n使用者問題：{user_query}"

    messages = [
        {"role": "system", "content": COMPARING_SYSTEM_PROMPT},
        {"role": "user", "content": full_query}
    ]

    MAX_TURNS = 5
    turn = 0

    try:
        while turn < MAX_TURNS:
            turn += 1

            # 1. 呼叫 LLM
            response = llm_client.chat.completions.create(
                model=GEMINI_MODEL,
                messages=messages,
                tools=INTERNAL_TOOLS_SCHEMA,
                tool_choice="auto",
            )

            msg = response.choices[0].message
            messages.append(msg)

            # 2. 若沒有要呼叫工具，直接回傳答案
            if not msg.tool_calls:
                return msg.content

            # 3. 執行工具
            for tool_call in msg.tool_calls:
                fname = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                
                tool_result = ""
                if fname == "tool_search_bank_info":
                    tool_result = await tool_search_bank_info(**args)
                else:
                    tool_result = json.dumps({"error": "Unknown tool"})

                # 將工具結果回傳給 LLM
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": fname,
                    "content": tool_result
                })

        return "⚠️ 抱歉，我思考太久了，無法提供完整答案。"

    except Exception as e:
        return f"❌ Agent 執行發生錯誤: {e}"

# ==========================================
# 5. MCP Tool Entry & Local Test
# ==========================================

@mcp.tool()
async def comparing_agent(user_query: str, user_profile: str = "") -> str:
    """主要進入點：接收使用者問題，回傳比較或推薦結果"""
    print(f"⚖️ [Comparing Agent] 收到請求 | Query={user_query}", file=sys.stderr)
    return await _generate_response(user_query, user_profile)

async def local_chat_loop():
    print("\n⚖️ --- Comparing Agent Local Mode (RAG Enabled) ---")
    print("提示：輸入 'q' 離開")
    
    if not os.path.exists("cards_rag_embedded.jsonl"):
        print("⚠️ 警告：找不到 cards_rag_embedded.jsonl，搜尋功能將失效。")

    profile = input("設定 user_profile (例如 '學生', '常出國', 可留空): ").strip()

    while True:
        user_input = input("\n👤 User: ").strip()
        if user_input.lower() in ("q", "quit", "exit"):
            break
        
        reply = await _generate_response(user_input, profile)
        print(f"⚖️ Agent: {reply}")

    print("Bye!")

if __name__ == "__main__":
    # 支援 Windows 的 asyncio loop 策略
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    if "--local" in sys.argv:
        asyncio.run(local_chat_loop())
    else:
        print("⚖️ Comparing Agent Server starting...", file=sys.stderr)
        mcp.run()