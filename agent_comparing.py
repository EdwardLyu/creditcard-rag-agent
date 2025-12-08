# comparing_agent.py
import os
import sys
import json
import asyncio
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
from openai import OpenAI  # ✅ 改成使用 OpenAI client（指向 Gemini API）

# 1. 初始化環境
from pathlib import Path

# 在這個檔案所在的資料夾，往上找 .env
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# === 讀取 Gemini 設定 ===
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/"
)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# 建立 Gemini-compatible client
try:
    llm_client = OpenAI(
        api_key=GEMINI_API_KEY,
        base_url=GEMINI_BASE_URL,
    )
except Exception as e:
    print(f"❌ Gemini Client 初始化失敗: {e}", file=sys.stderr)
    llm_client = None

mcp = FastMCP("comparing-expert-agent")

# ==========================================
# 2. 內部工具 (Internal Tools)
# ==========================================

async def tool_example_1(card_name: str) -> str:
    print(f"   ⚙️ [Internal Tool] 查回饋 | card={card_name}", file=sys.stderr)
    if "CUBE" in card_name.upper():
        return json.dumps({"card": "CUBE卡", "reward_rate": "3%", "note": "需切換權益"})
    elif "ROSE" in card_name.upper():
        return json.dumps({"card": "Rose Giving卡", "reward_rate": "3%", "note": "節假日限定"})
    else:
        return json.dumps({"error": "查無此卡資料"})

async def tool_example_2(score_a: int, score_b: int) -> str:
    print(f"   ⚙️ [Internal Tool] 比分數 | {score_a} vs {score_b}", file=sys.stderr)
    diff = score_a - score_b
    if diff > 0:
        return f"A比B高 {diff} 分"
    elif diff < 0:
        return f"B比A高 {abs(diff)} 分"
    else:
        return "兩者分數相同"

async def tool_example_3(user_type: str) -> str:
    print(f"   ⚙️ [Internal Tool] 推薦卡片 | 使用者={user_type}", file=sys.stderr)
    if "學生" in user_type:
        return "推薦: CUBE卡 (門檻低)"
    elif "富豪" in user_type:
        return "推薦: 世界卡 (權益多)"
    else:
        return "推薦: 現金回饋御璽卡 (通用)"

# ==========================================
# 3. 工具 Schemas
# ==========================================

INTERNAL_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "tool_example_1",
            "description": "查詢卡片基礎回饋率。",
            "parameters": {
                "type": "object",
                "properties": {
                    "card_name": {"type": "string"}
                },
                "required": ["card_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_example_2",
            "description": "比較兩個分數差異。",
            "parameters": {
                "type": "object",
                "properties": {
                    "score_a": {"type": "integer"},
                    "score_b": {"type": "integer"}
                },
                "required": ["score_a", "score_b"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_example_3",
            "description": "依使用者身分推薦卡片。",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_type": {"type": "string"}
                },
                "required": ["user_type"]
            }
        }
    }
]

COMPARING_SYSTEM_PROMPT = """
你是國泰世華銀行的「信用卡比較與推薦顧問」。
你的任務是回答使用者的比較問題或推薦請求。

可用工具：
- tool_example_1：查回饋率
- tool_example_2：比分數
- tool_example_3：依身分推薦卡片

原則：
- 優先使用工具來獲得資料
- 結果需整理成清楚、親切的建議
"""

# ==========================================
# 4. REACT LOOP（核心邏輯）
# ==========================================

async def _generate_response(user_query: str, user_profile: str = "") -> str:
    if not llm_client:
        return "❌ 系統錯誤：LLM client 未初始化"

    # 將背景資料一起加入 prompt
    full_content = f"使用者問題：{user_query}"
    if user_profile:
        full_content += f"\n使用者背景：{user_profile}"

    messages = [
        {"role": "system", "content": COMPARING_SYSTEM_PROMPT},
        {"role": "user", "content": full_content}
    ]

    MAX_TURNS = 5
    turn = 0

    try:
        while turn < MAX_TURNS:
            turn += 1

            # === 呼叫 Gemini ===
            response = llm_client.chat.completions.create(
                model=GEMINI_MODEL,
                messages=messages,
                tools=INTERNAL_TOOLS_SCHEMA,
                tool_choice="auto",
            )

            msg = response.choices[0].message
            messages.append(msg)

            # 若模型直接給答案 → 結束
            if not msg.tool_calls:
                return msg.content

            # === 執行工具 ===
            for tool_call in msg.tool_calls:
                fname = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                if fname == "tool_example_1":
                    result = await tool_example_1(**args)
                elif fname == "tool_example_2":
                    result = await tool_example_2(**args)
                elif fname == "tool_example_3":
                    result = await tool_example_3(**args)
                else:
                    result = json.dumps({"error": "Unknown internal tool"})

                # 回傳給 LLM
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": fname,
                    "content": result
                })

        return "⚠️ 思考次數過多（超過 MAX_TURNS），未能完成回答。"

    except Exception as e:
        return f"❌ Agent 執行錯誤：{e}"

# ==========================================
# 5. MCP Tool Entry
# ==========================================

@mcp.tool()
async def comparing_agent(user_query: str, user_profile: str = "") -> str:
    print(f"⚖️ [Comparing Agent] 收到請求 | Query={user_query}", file=sys.stderr)
    return await _generate_response(user_query, user_profile)

# ==========================================
# Local 測試
# ==========================================

async def local_chat_loop():
    print("\n⚖️ --- Comparing Agent Local Mode ---")
    print("輸入 'q' 離開")

    profile = input("設定 user_profile (可留空): ").strip()

    while True:
        user_input = input("\n👤 User: ").strip()
        if user_input.lower() in ("q", "quit", "exit"):
            break

        reply = await _generate_response(user_input, profile)
        print(f"⚖️ Agent: {reply}")

    print("Bye!")

# ==========================================
# 伺服器入口
# ==========================================

if __name__ == "__main__":
    if "--local" in sys.argv:
        if sys.platform.startswith("win"):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(local_chat_loop())
    else:
        print("⚖️ Comparing Agent Server starting...", file=sys.stderr)
        mcp.run()
