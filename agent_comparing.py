import os
import sys
import json
import asyncio
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
from openai import AzureOpenAI

# 1. 初始化環境
load_dotenv()

try:
    aoai_client = AzureOpenAI(
        api_key=os.getenv("AOAI_KEY"),
        azure_endpoint=os.getenv("AOAI_URL"),
        api_version=os.getenv("AOAI_MODEL_VERSION"),
    )
except Exception as e:
    print(f"❌ AOAI Client 初始化失敗: {e}", file=sys.stderr)
    aoai_client = None

mcp = FastMCP("comparing-expert-agent")

# ==========================================
# 2. 定義內部工具 (Internal Tools) - 廚房裡的工具
# ==========================================
# 這些工具只在 Server 內部運作，Client 端(rag_mcp_client.py) 完全不知道它們的存在

async def tool_example_1(card_name: str) -> str:
    """模擬查詢資料庫：取得卡片基礎回饋率"""
    print(f"   ⚙️ [Internal Tool] 執行 tool_example_1 (查回饋) | 參數: {card_name}", file=sys.stderr)
    # 模擬資料庫回傳
    if "CUBE" in card_name.upper():
        return json.dumps({"card": "CUBE卡", "reward_rate": "3%", "note": "需切換權益"})
    elif "ROSE" in card_name.upper():
        return json.dumps({"card": "Rose Giving卡", "reward_rate": "3%", "note": "節假日限定"})
    else:
        return json.dumps({"error": "查無此卡片資料"})

async def tool_example_2(score_a: int, score_b: int) -> str:
    """模擬計算工具：比較兩個分數的差距"""
    print(f"   ⚙️ [Internal Tool] 執行 tool_example_2 (比分數) | 參數: {score_a} vs {score_b}", file=sys.stderr)
    diff = score_a - score_b
    if diff > 0:
        return f"A比B高 {diff} 分"
    elif diff < 0:
        return f"B比A高 {abs(diff)} 分"
    else:
        return "兩者分數相同"

async def tool_example_3(user_type: str) -> str:
    """模擬推薦系統：根據使用者類型推薦卡片"""
    print(f"   ⚙️ [Internal Tool] 執行 tool_example_3 (找推薦) | 參數: {user_type}", file=sys.stderr)
    if "學生" in user_type:
        return "推薦: CUBE卡 (門檻低)"
    elif "富豪" in user_type:
        return "推薦: 世界卡 (權益多)"
    else:
        return "推薦: 現金回饋御璽卡 (通用)"

# ==========================================
# 3. 定義工具清單 (JSON Schema) - 給 LLM 看的菜單
# ==========================================
INTERNAL_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "tool_example_1",
            "description": "查詢特定信用卡的基礎回饋率資料。",
            "parameters": {
                "type": "object",
                "properties": {
                    "card_name": {"type": "string", "description": "卡片名稱"}
                },
                "required": ["card_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_example_2",
            "description": "比較兩個數值或權益分數的差異。",
            "parameters": {
                "type": "object",
                "properties": {
                    "score_a": {"type": "integer", "description": "第一張卡的分數"},
                    "score_b": {"type": "integer", "description": "第二張卡的分數"}
                },
                "required": ["score_a", "score_b"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_example_3",
            "description": "根據使用者身分(如學生、富豪)獲取系統推薦的卡片。",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_type": {"type": "string", "description": "使用者類型"}
                },
                "required": ["user_type"]
            }
        }
    }
]

COMPARING_SYSTEM_PROMPT = """
你是國泰世華銀行的「信用卡比較與推薦顧問」。
你的任務是回答使用者的比較問題或推薦請求。

# 可用工具：
- `tool_example_1`: 查詢卡片回饋率。
- `tool_example_2`: 比較兩個分數差異。
- `tool_example_3`: 根據身分推薦卡片。

# 規則：
- 盡量使用工具來獲取確切資訊，而不是憑空猜測。
- 收到工具結果後，請整合成親切的顧問口吻回覆使用者。
"""

# ==========================================
# 4. 核心邏輯層 (ReAct Loop)
# ==========================================
async def _generate_response(user_query: str, user_profile: str = "") -> str:
    if not aoai_client:
        return "❌ 系統錯誤：Agent 腦部連線失敗。"

    # 準備初始對話歷史
    full_content = f"使用者問題：{user_query}"
    if user_profile:
        full_content += f"\n使用者背景：{user_profile}"

    messages = [
        {"role": "system", "content": COMPARING_SYSTEM_PROMPT},
        {"role": "user", "content": full_content}
    ]

    # 設定最大思考次數 (避免無窮迴圈)
    MAX_TURNS = 5
    current_turn = 0

    try:
        while current_turn < MAX_TURNS:
            current_turn += 1
            
            # 1. 呼叫 LLM (思考)
            response = aoai_client.chat.completions.create(
                model=os.getenv("AOAI_MODEL_VERSION"),
                messages=messages,
                tools=INTERNAL_TOOLS_SCHEMA, # 給它看內部工具
                tool_choice="auto"
            )
            msg = response.choices[0].message
            messages.append(msg) # 將 LLM 的回應加入歷史

            # 2. 判斷是否需要呼叫工具
            if not msg.tool_calls:
                # LLM 認為不需要呼叫工具，直接生成了回答 -> 任務結束
                return msg.content

            # 3. 執行工具 (行動)
            for tool_call in msg.tool_calls:
                func_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                
                result_content = ""
                
                # 簡單的工具路由
                if func_name == "tool_example_1":
                    result_content = await tool_example_1(**args)
                elif func_name == "tool_example_2":
                    result_content = await tool_example_2(**args)
                elif func_name == "tool_example_3":
                    result_content = await tool_example_3(**args)
                else:
                    result_content = json.dumps({"error": "Unknown tool"})

                # 4. 將工具結果加入歷史 (觀察)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": func_name,
                    "content": str(result_content)
                })
            
            # 迴圈繼續，LLM 會在下一輪看到工具結果並進行整合...

        return "思考次數過多，無法產生完整回答。"

    except Exception as e:
        return f"Agent 執行發生錯誤: {str(e)}"

# ==========================================
# MCP 介面層
# ==========================================
@mcp.tool()
async def comparing_agent(user_query: str, user_profile: str = "") -> str:
    """【比較與推薦專家入口】接收使用者問題與背景，透過 LLM 與內部工具生成建議。"""
    print(f"⚖️ [Comparing Agent] 收到請求 (MCP) | Query: {user_query}", file=sys.stderr)
    return await _generate_response(user_query, user_profile)

# ==========================================
# Local 測試層
# ==========================================
async def local_chat_loop():
    print("\n⚖️ --- 比較與推薦 Agent (本地測試模式) ---")
    print("輸入 'q' 離開。")
    print("(測試提示：試著問 'CUBE卡回饋多少?' 或 '我是學生推薦哪張?' 或 '比較 100 和 80')")
    
    profile = input("設定測試用 User Profile (按 Enter 跳過): ").strip()
    
    while True:
        try:
            user_input = input("\n👤 (User): ").strip()
            if user_input.lower() in ['q', 'quit', 'exit']:
                break
            if not user_input:
                continue
            
            print("⚖️ (Agent): 思考中...", end="\r")
            reply = await _generate_response(user_input, profile)
            print(f"⚖️ (Agent): {reply}")
            
        except KeyboardInterrupt:
            break
    print("\nBye!")

# ==========================================
# 主程式入口
# ==========================================
if __name__ == "__main__":
    if "--local" in sys.argv:
        if sys.platform.startswith('win'):
             asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(local_chat_loop())
    else:
        print("⚖️ Comparing Agent Server starting...", file=sys.stderr)
        mcp.run()