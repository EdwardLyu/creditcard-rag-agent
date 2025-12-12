import os
import sys
import json
import asyncio
from rag_search import search_chunks
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
from openai import OpenAI  # ✅ 改成使用 OpenAI client（指向 Gemini 相容端點）
from rag_search import search_chunks 

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

mcp = FastMCP("product-expert-agent")

# ==========================================
# 2. 定義內部工具 (Internal Tools)
# ==========================================
async def tool_rag_search_product(
    user_query: str,
    card_name: str | None = None,
    top_k: int = 5
) -> str:
    """
    用 RAG 查詢信用卡產品資訊，回傳相關 chunks。
    """
    print(
        f"   ⚙️ [Internal Tool] RAG search | q={user_query}, card={card_name}",
        file=sys.stderr
    )

    # 🔎 根據問題內容，調整查詢策略
    # 如果是在問「回饋 / 權益 / 通路」，優先抓 benefit_scheme，top_k 開大一點
    lower_q = user_query.lower()
    is_benefit_query = any(
        kw in user_query for kw in ["回饋", "權益", "通路", "方案"]
    )

    if is_benefit_query:
        effective_top_k = max(top_k, 20)
        doc_type = "benefit_scheme"
    else:
        effective_top_k = top_k
        doc_type = None
        
    my_metadata = {
    "card_name": card_name,
    "doc_type": doc_type
}
     # 確保用的是你現在有 card_filter 的版本

    results = search_chunks(
        query=user_query,
        top_k=effective_top_k,
        metadata_filter=my_metadata
    )

    print(results)
    return results 


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
            "name": "tool_rag_search_product",
            "description": "用 RAG 查詢信用卡產品資訊，從 chunks 中找年費、權益、資格等內容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_query": {
                        "type": "string",
                        "description": "使用者問題原文，例如：'國泰世華世界卡機場接送資格是什麼？'"
                    },
                    "card_name": {
                        "type": "string",
                        "description": "若已知要查的卡片名稱就填，否則可留空，可能的卡片名稱有：國泰CUBE卡, 國泰世華世界卡, 國泰蝦皮購物聯名卡及國泰亞洲萬里通聯名卡四個可能",
                        "nullable": True
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "要取回最相關的幾筆資料",
                        "default": 5
                    }
                },
                "required": ["user_query"]
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
- `tool_rag_search_product`: 從內部 RAG 資料庫查詢信用卡產品資訊
  （包含年費、哩程/點數回饋、申辦資格、首刷禮、機場接送、貴賓室、海外漫遊等）。
- `tool_calculate_installment`: 幫客戶算分期金額。

# 使用原則：
- 只要是「固定規則」或「數字型資訊」（年費、門檻、回饋倍率、次數）都應優先用 RAG 工具查詢，
  嚴禁憑空捏造。
- 回答時請整理查回來的內容，以條列說明，讓使用者易讀。
- 如果 RAG 查不到資料，要明確說「目前資料庫沒有這張卡的資訊」。

- ⚠ 特別注意：
  若同一張卡有多個權益方案（例如依類別分成不同方案），
  當使用者詢問「這張卡的回饋 / 權益有哪些？」時，
  請盡量完整列出所有主要方案，而不是只選其中一、兩個。
"""

# ==========================================
# 4. 核心邏輯層 (ReAct Loop)
# ==========================================
async def _generate_response(user_query: str) -> str:
    if not llm_client:
        return "❌ 系統錯誤：LLM client 未初始化。"

    messages = [
        {"role": "system", "content": PRODUCT_SYSTEM_PROMPT},
        {"role": "user", "content": user_query + "我是國泰cube卡的二級用戶"}
    ]

    MAX_TURNS = 5
    current_turn = 0

    try:
        while current_turn < MAX_TURNS:
            current_turn += 1
            
            # 1. 呼叫 LLM（Gemini OpenAI-compatible）
            response = llm_client.chat.completions.create(
                model=GEMINI_MODEL,
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
                
                if func_name == "tool_rag_search_product":
                    result_content = await tool_rag_search_product(**args)
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