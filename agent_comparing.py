# comparing_agent.py
import os
import sys
import json
import asyncio
from pathlib import Path

# 3rd party imports
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
from openai import OpenAI

# === 導入你的 RAG 搜尋模組 ===
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

# 預先載入 RAG 資料庫 (加速第一次搜尋)
print("📚 正在初始化 RAG 知識庫 (載入 jsonl 與 embedding 模型)...", file=sys.stderr)
try:
    # 這會觸發 llm_utils 載入 BGE-M3 模型，第一次會比較久
    load_index()
    print("✅ RAG 知識庫載入完成！", file=sys.stderr)
except Exception as e:
    print(f"❌ RAG 載入失敗: {e}", file=sys.stderr)

mcp = FastMCP("comparing-expert-agent")

# ==========================================
# 2. 定義真實工具 (Real Tools)
# ==========================================

async def tool_search_bank_info(query: str, card_filter: str = None) -> str:
    """
    搜尋銀行產品、權益或信用卡相關資訊。
    """
    print(f"    🔎 [RAG Search] 搜尋: {query} | 過濾卡片: {card_filter}", file=sys.stderr)
    
    # search_chunks 內部會呼叫 llm_utils.query_ai_embedding (CPU 密集運算)
    # 使用 to_thread 把它丟到背景執行，避免卡住 async 事件迴圈
    try:
        results = await asyncio.to_thread(
            search_chunks, 
            query=query, 
            card_filter=card_filter, 
            top_k=5  # 取前 5 筆最相關
        )
        
        if not results:
            return json.dumps({"result": "查無相關資料，請嘗試換個關鍵字。"})

        # 整理回傳結果，節省 token 並讓 LLM 好讀
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
            "description": "搜尋信用卡權益、回饋規則、年費等銀行產品資訊。當使用者詢問具體卡片細節時必須使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜尋關鍵字或問題，例如 'CUBE卡日本回饋' 或 '世界卡年費'"
                    },
                    "card_filter": {
                        "type": "string",
                        "description": "若問題明確針對某張卡，可填入卡片名稱以過濾雜訊 (如 'CUBE卡')"
                    }
                },
                "required": ["query"]
            }
        }
    }
]

COMPARING_SYSTEM_PROMPT = """
你是國泰世華銀行的「資深信用卡產品顧問」。
你的資料來源是內部的 RAG 知識庫，請根據搜尋結果來回答使用者。

### 回答原則：
1. **證據說話**：使用者問具體權益（如回饋率、年費、規則）時，**必須**使用 `tool_search_bank_info` 查詢。
2. **誠實告知**：如果搜尋結果沒有提到，就說「資料庫中目前沒有相關資訊」，不要憑空捏造。
3. **友善專業**：回答時請整理重點（條列式），語氣親切。
4. **比較情境**：若使用者要比較兩張卡（如 A卡 vs B卡），請分別搜尋這兩張卡的資料，再綜合回答。

### 思考流程：
- 收到問題 -> 判斷關鍵字 -> 呼叫搜尋工具 -> 閱讀搜尋結果 -> 整理並回答。
"""

# ==========================================
# 4. REACT LOOP (核心邏輯)
# ==========================================

async def _generate_response(user_query: str, user_profile: str = "") -> str:
    if not llm_client:
        return "❌ 系統錯誤：LLM client 未初始化"

    # 建構對話歷史
    messages = [
        {"role": "system", "content": COMPARING_SYSTEM_PROMPT},
        {"role": "user", "content": f"使用者背景：{user_profile}\n使用者問題：{user_query}" if user_profile else user_query}
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

        return "⚠️ 超過思考次數上限，無法取得完整資訊。"

    except Exception as e:
        return f"❌ Agent 執行發生錯誤: {e}"

# ==========================================
# 5. MCP Tool Entry
# ==========================================

@mcp.tool()
async def comparing_agent(user_query: str, user_profile: str = "") -> str:
    """主要進入點：接收使用者問題，回傳比較或推薦結果"""
    print(f"⚖️ [Comparing Agent] 收到請求 | Query={user_query}", file=sys.stderr)
    return await _generate_response(user_query, user_profile)

# ==========================================
# Local 測試 Loop
# ==========================================

async def local_chat_loop():
    print("\n⚖️ --- Comparing Agent Local Mode (RAG Enabled) ---")
    print("輸入 'q' 離開")
    
    # 測試環境檢查
    if not os.path.exists("cards_rag_embedded.jsonl"):
        print("⚠️ 警告：找不到 cards_rag_embedded.jsonl，搜尋功能將失效。")

    profile = input("設定 user_profile (可留空): ").strip()

    while True:
        user_input = input("\n👤 User: ").strip()
        if user_input.lower() in ("q", "quit", "exit"):
            break
        
        reply = await _generate_response(user_input, profile)
        print(f"⚖️ Agent: {reply}")

    print("Bye!")

if __name__ == "__main__":
    if "--local" in sys.argv:
        if sys.platform.startswith("win"):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(local_chat_loop())
    else:
        print("⚖️ Comparing Agent Server starting...", file=sys.stderr)
        mcp.run()