# eligibility_agent.py
import os
import sys
import json
import asyncio
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from openai import OpenAI
from rag_search import search_chunks
import logging   
from dotenv import load_dotenv

# === 讀取 Gemini 設定（取代原本 Azure OpenAI） ===
# 1. 初始化環境
from pathlib import Path

# 在這個檔案所在的資料夾，往上找 .env
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# === 讀取 Gemini 設定（取代原本 Azure OpenAI） ===
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/"
)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

try:
    llm_client = OpenAI(
        api_key=GEMINI_API_KEY,
        base_url=GEMINI_BASE_URL,
    )
except Exception as e:
    print(f"❌ Gemini Client 初始化失敗: {e}", file=sys.stderr)
    llm_client = None
    
mcp = FastMCP("eligibility-agent")


# ==========================================
# 2. 輕量版：五張卡的申辦規則表
#   
# ==========================================

async def tool_check_eligibility(user_profile_json: str) -> dict:
    """
    使用 LLM + RAG 內容判斷 eligibility。
    ✅ 不再強制 LLM 輸出 JSON，因此不會再出現「無法解析」。
    """
    user = json.loads(user_profile_json)
    
    metadata = {
         "doc_type": "credit_card_profile"
    }
    
    # 1) 從 RAG 搜尋該卡片相關內容
    try:
        rag_results = search_chunks(
            query="信用卡申辦資格條件",
            metadata_filter=metadata,
            top_k=20
        )
    except Exception as e:
        rag_results = []
    print(rag_results)
    # 2) 讓 LLM 根據 RAG 內容做 eligibility 推論（用自然語言即可）
    prompt = f"""
你是一位信用卡申辦資格分析專家。請你根據數張信用卡的申辦資訊判斷使用

使用者資料（JSON）：
{json.dumps(user, ensure_ascii=False)}


以下是從 RAG 搜尋到的卡片內容（可能包含回饋、優惠、條款、資格等）：
{json.dumps(rag_results, ensure_ascii=False)}

請用繁體中文回答每張卡片：
1) 申請人的年齡/收入/學生身分是否有達到明確門檻？（若沒有寫就說「資料不足」）
2) 以此使用者條件，給與每張卡「建議申辦 / 不建議 / 資訊不足」其一
3) 2～4 點條列理由

直接輸出文字，不要 JSON。
"""

    resp = llm_client.chat.completions.create(
        model=GEMINI_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )

    explanation = (resp.choices[0].message.content or "").strip()

    # 3) 我們自己包成 dict 回去（避免解析）
    return explanation 


# ==========================================
# 3. 工具 Schema 與 System Prompt
# ==========================================

INTERNAL_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "tool_check_eligibility",
            "description": "根據使用者條件，檢查指定信用卡是否符合申辦門檻。",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_profile_json": {
                        "type": "string",
                        "description": "使用者資料的 JSON 字串，例如 {\"age\":23,\"annual_income\":450000,\"is_student\":false}"
                    }
                },
                "required": ["user_profile_json"]
            }
        }
    }
]

ELIGIBILITY_SYSTEM_PROMPT = """
你是「信用卡申辦資格專家」，負責判斷使用者是否適合申辦特定信用卡。

### 工具使用規則
- 任何需要判斷「可不可以辦」、「過件機率高不高」、「哪張比較容易申辦」的問題，
  都必須呼叫 `tool_check_eligibility`，取得每張卡的機械式判斷結果與原因。

### 回答原則
1. **先看結構化結果，再補充說明**：
   - 先依照工具回傳的 status（✅/❌）做整理。
   - 再用條列式說明理由，例如年齡、年收、學生身分等。
2. **不要亂猜銀行內規**：
   - 工具沒有提供的資料，就說「此部分仍以銀行實際審核為準」。
3. **輸出格式建議**：
   - 先給一個總結：比如「整體來說，你最適合 A、B 卡」。
   - 再列出每張卡：卡名 / 建議 / 原因（條列）。
4. **user_profile 來源**：
   - 你會收到一個 `user_profile` 字串參數，可直接當作 JSON，
     也可以依使用者在對話中補充的資訊做口頭解釋。

請使用繁體中文回答。
"""

# ==========================================
# 4. REACT LOOP
# ==========================================

async def _generate_response(user_query: str, user_profile: str = "") -> str:

    messages = [
        {"role": "system", "content": ELIGIBILITY_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"使用者資料(user_profile JSON)：{user_profile}\n"
                f"使用者問題：{user_query}"
            ) if user_profile else user_query
        },
    ]

    MAX_TURNS = 5
    turn = 0

    try:
        while turn < MAX_TURNS:
            turn += 1

            resp = llm_client.chat.completions.create(
                model=GEMINI_MODEL,
                messages=messages,
                tools=INTERNAL_TOOLS_SCHEMA,
                tool_choice="auto",
            )

            msg = resp.choices[0].message
            messages.append(msg)

            # 沒有再呼叫工具 → 直接回覆
            if not msg.tool_calls:
                return msg.content

            # 執行工具
            for tool_call in msg.tool_calls:
                fname = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                if fname == "tool_check_eligibility":
                    tool_result = await tool_check_eligibility(**args)
                else:
                    tool_result = json.dumps(
                        {"error": f"Unknown tool: {fname}"},
                        ensure_ascii=False
                    )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": fname,
                    "content": tool_result,
                })

        return "⚠️ 超過思考次數上限，無法取得完整資訊。"

    except Exception as e:
        return f"❌ Agent 執行發生錯誤: {e}"

# ==========================================
# 5. MCP Tool Entry
# ==========================================

@mcp.tool()
async def eligibility_agent(user_query: str, user_profile: str = "") -> str:
    """
    主要進入點：檢查指定卡片的申辦資格。
    - user_query: 使用者自然語言問題
    - user_profile: 建議傳 JSON 字串，例如 {"age":23,"annual_income":450000,"is_student":false}
    """
    print(f"🪪 [Eligibility Agent] 收到請求 | Query={user_query}", file=sys.stderr)
    return await _generate_response(user_query, user_profile)


# ==========================================
# 6. Local 測試模式
# ==========================================

async def local_chat_loop():
    print("\n🪪 --- Eligibility Agent Local Mode ---")
    print("輸入 'q' 離開")

    profile = input("請輸入 user_profile JSON (可留空): ").strip()
    if not profile:
        # 給一個示範用 profile
        profile = json.dumps(
            {"age": 23, "annual_income": 450000, "is_student": False},
            ensure_ascii=False,
        )
        print(f"👉 使用預設 profile：{profile}")

    while True:
        user_input = input("\n👤 User: ").strip()
        if user_input.lower() in ("q", "quit", "exit"):
            break

        reply = await _generate_response(user_input, profile)
        print(f"🪪 Agent: {reply}")

    print("Bye!")

if __name__ == "__main__":
    if "--local" in sys.argv:
        if sys.platform.startswith("win"):
            asyncio.set_event_loop_policy(
                asyncio.WindowsSelectorEventLoopPolicy()
            )
        asyncio.run(local_chat_loop())
    else:
        print("🪪 Eligibility Agent Server starting...", file=sys.stderr)
        mcp.run()
