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

mcp = FastMCP("product-expert-agent")

# ==========================================
# 2. 定義內部工具 (Internal Tools)
# ==========================================

async def tool_query_annual_fee(card_name: str) -> str:
    """模擬查詢：取得信用卡年費資訊"""
    print(f"   ⚙️ [Internal Tool] 執行 tool_query_annual_fee (查年費) | 參數: {card_name}", file=sys.stderr)
    # 模擬資料庫
    cn = card_name.upper()
    if "CUBE" in cn:
        return json.dumps({"card": "CUBE卡", "fee": "首年免年費，次年NT$1,800", "condition": "申辦電子帳單享免年費"})
    elif "世界" in cn or "WORLD" in cn:
        return json.dumps({"card": "世界卡", "fee": "NT$20,000", "condition": "無減免優惠"})
    else:
        return json.dumps({"error": "查無此卡片年費資料"})

async def tool_query_benefits(card_name: str) -> str:
    """模擬查詢：取得信用卡主要權益"""
    print(f"   ⚙️ [Internal Tool] 執行 tool_query_benefits (查權益) | 參數: {card_name}", file=sys.stderr)
    cn = card_name.upper()
    if "CUBE" in cn:
        return "CUBE卡權益：提供四大權益方案天天切換，指定消費享 3% 小樹點回饋無上限。"
    elif "COSTCO" in cn:
        return "Costco聯名卡權益：Costco店內消費 2% 柏克金幣，店外 1%。"
    else:
        return "查無此卡片權益資料。"

async def tool_calculate_installment(amount: int, months: int) -> str:
    """模擬計算：分期付款試算 (不含利息簡單除法)"""
    print(f"   ⚙️ [Internal Tool] 執行 tool_calculate_installment (算分期) | 參數: {amount} / {months}", file=sys.stderr)
    if months <= 0:
        return json.dumps({"error": "期數必須大於0"})
    
    per_month = int(amount / months)
    return json.dumps({
        "total_amount": amount,
        "months": months,
        "payment_per_month": per_month,
        "note": "此為預估值，實際金額以帳單為準"
    })

# ==========================================
# 3. 定義工具清單 (JSON Schema)
# ==========================================
INTERNAL_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "tool_query_annual_fee",
            "description": "查詢特定信用卡的年費與免年費條件。",
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
            "name": "tool_query_benefits",
            "description": "查詢信用卡的權益內容與回饋資訊。",
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
            "name": "tool_calculate_installment",
            "description": "計算分期付款每期應繳金額。",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "integer", "description": "總金額"},
                    "months": {"type": "integer", "description": "分期期數"}
                },
                "required": ["amount", "months"]
            }
        }
    }
]

PRODUCT_SYSTEM_PROMPT = """
你是國泰世華銀行的「信用卡產品專家」。
你的任務是提供精確的產品數據與試算服務。

# 可用工具：
- `tool_query_annual_fee`: 查年費。
- `tool_query_benefits`: 查權益。
- `tool_calculate_installment`: 幫客戶算分期金額。

# 規則：
- 遇到數字或規定問題，請務必呼叫工具查詢，嚴禁憑空捏造。
- 回答時請保持專業、客觀。
"""

# ==========================================
# 4. 核心邏輯層 (ReAct Loop)
# ==========================================
async def _generate_response(user_query: str) -> str:
    if not aoai_client:
        return "❌ 系統錯誤：Agent 腦部連線失敗。"

    messages = [
        {"role": "system", "content": PRODUCT_SYSTEM_PROMPT},
        {"role": "user", "content": user_query}
    ]

    MAX_TURNS = 5
    current_turn = 0

    try:
        while current_turn < MAX_TURNS:
            current_turn += 1
            
            # 1. 呼叫 LLM
            response = aoai_client.chat.completions.create(
                model=os.getenv("AOAI_MODEL_VERSION"),
                messages=messages,
                tools=INTERNAL_TOOLS_SCHEMA,
                tool_choice="auto"
            )
            msg = response.choices[0].message
            messages.append(msg)

            # 2. 判斷是否結束
            if not msg.tool_calls:
                return msg.content

            # 3. 執行工具
            for tool_call in msg.tool_calls:
                func_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                
                result_content = ""
                
                if func_name == "tool_query_annual_fee":
                    result_content = await tool_query_annual_fee(**args)
                elif func_name == "tool_query_benefits":
                    result_content = await tool_query_benefits(**args)
                elif func_name == "tool_calculate_installment":
                    result_content = await tool_calculate_installment(**args)
                else:
                    result_content = json.dumps({"error": "Unknown tool"})

                # 4. 加入工具結果
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": func_name,
                    "content": str(result_content)
                })
            
        return "思考次數過多，無法產生完整回答。"

    except Exception as e:
        return f"Agent 執行發生錯誤: {str(e)}"

# ==========================================
# MCP 介面層
# ==========================================
@mcp.tool()
async def product_agent(user_query: str) -> str:
    """【產品專家入口】接收使用者的問題，透過 LLM 與內部工具生成產品資訊。"""
    print(f"💳 [Product Agent] 收到請求 (MCP) | Query: {user_query}", file=sys.stderr)
    return await _generate_response(user_query)

# ==========================================
# Local 測試層
# ==========================================
async def local_chat_loop():
    print("\n💳 --- 產品專家 Agent (本地測試模式) ---")
    print("輸入 'q' 離開。")
    print("(測試提示：試著問 'CUBE卡年費多少?' 或 '買iPhone 3萬分12期要繳多少?')")
    
    while True:
        try:
            user_input = input("\n👤 (User): ").strip()
            if user_input.lower() in ['q', 'quit', 'exit']:
                break
            if not user_input:
                continue
            
            print("💳 (Agent): 思考中...", end="\r")
            reply = await _generate_response(user_input)
            print(f"💳 (Agent): {reply}")
            
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
        print("💳 Product Agent Server starting...", file=sys.stderr)
        mcp.run()