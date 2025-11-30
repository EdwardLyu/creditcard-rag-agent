import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import AzureOpenAI
from openai.types.chat import ChatCompletionMessageParam
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession

# ------------------------------------------
# TODO 請新增能長期儲存 User info 的機制，包括但不限於使用者年齡、持有卡別、卡片額度等等
# ------------------------------------------

# ==========================================
# 1. 環境設定與初始化
# ==========================================
load_dotenv()

# 檢查必要的 Azure OpenAI 環境變數
required_vars = ["AOAI_KEY", "AOAI_URL", "AOAI_MODEL_VERSION"]
if not all(k in os.environ for k in required_vars):
    print(f"❌ 錯誤：缺少必要的環境變數: {required_vars}")
    sys.exit(1)

# 初始化 Azure OpenAI Client (這是 Client 端的 Router 大腦)
client = AzureOpenAI(
    api_key=os.getenv("AOAI_KEY"),
    azure_endpoint=os.getenv("AOAI_URL"),
    api_version=os.getenv("AOAI_MODEL_VERSION"),
)

# ==========================================
# 2. 定義各個 Agent 的連線參數 (Server Parameters)
# ==========================================

# A. 產品專家 Agent 
PRODUCT_SERVER_PARAMS = StdioServerParameters(
    command="python",
    args=["agent_product.py"], 
    env=os.environ.copy()
)

# B. 比較/推薦專家 Agent 
ADVISOR_SERVER_PARAMS = StdioServerParameters(
    command="python",
    args=["agent_comparing.py"],
    env=os.environ.copy()
)

# ==========================================
# 3. 定義 Tool Schemas (高層次菜單)
# ==========================================

# ------------------------------------------
# TODO 若需要改變每個agent功能的敘述，或是呼叫各個agnent所需的參數，請在此修改
# ------------------------------------------

tool_schemas = [
    {
        "type": "function",
        "function": {
            "name": "product_agent",  
            "description": "【產品專家】負責 1.提供卡片固定資訊與條款內容2.計算回饋與列出附加權益（動態資訊）",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_query": {
                        "type": "string",
                        "description": "使用者的完整原始問題 (例如：「CUBE卡年費多少？」)"
                    }
                },
                "required": ["user_query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "comparing_agent", 
            "description": "【比較與推薦專家】負責「多張卡片比較」或「推薦卡片」。當使用者詢問「哪張卡比較好？」、「兩張卡比一比」或「請推薦適合學生的卡」時使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_query": {
                        "type": "string",
                        "description": "使用者的完整原始問題"
                    },
                    "user_profile": {
                        "type": "string",
                        "description": "使用者背景資訊摘要 (例如：學生、月消費5000、常去全聯)。若未知則不填。"
                    }
                },
                "required": ["user_query"]
            }
        }
    }
]

# ==========================================
# 4. 定義 System Prompt (派單員邏輯)
# ==========================================

# ------------------------------------------
# TODO 務必修改 system prompt 以符合你的需求我們的專案要求，包括但不限於 :
# 1.使用者資訊檢查：根據使用者的問題回答還需要哪些資訊，例如：使用者想了解某筆交易所能獲得的回饋，就請他提供金額、日期、發票開立公司名稱等等 
# 2.專家 Agent 的職責與分工：請明確定義每個 Agent 的專長與適用情境，避免重疊或模糊不清
# 下面的範例為gemini所生成僅供參考
# ------------------------------------------

SYSTEM_PROMPT = """
你是一個專業的信用卡服務總管 (Main Dispatcher)。
你的職責不是直接回答問題，而是**分析使用者的意圖**，並指揮手下的「專家 Agent」來完成任務。

# 👑 你的核心原則
1. **精準分派**：不要自己瞎掰答案，所有資訊都必須來自專家 Agent。
2. **多工處理**：如果問題需要查證單一卡片細節，又要進行比較，請**同時呼叫**兩個 Agent。
3. **資訊完整**：傳遞給 Agent 的 `user_query` 必須包含完整的上下文。

# 🕵️‍♂️ 專家 Agent 介紹與使用時機

請根據使用者的問題類型，選擇最適合的 Agent：

### 1. 💳 產品專家 (product_agent)
- **專長**：單一卡片的客觀數據、官方條款、硬性規定。
- **適用問題**：
    - 「CUBE卡年費多少？」
    - 「世界卡海外消費回饋幾趴？」
    - 「申請資格是什麼？」

### 2. ⚖️ 比較與推薦專家 (comparing_agent)
- **專長**：多卡比較分析、決策建議、推薦。
- **適用問題**：
    - 「我有學生身分，推薦哪張卡？」
    - 「CUBE卡 跟 Rose卡 哪張比較好？」
    - 「我去日本玩要刷哪張？」

# 🚦 決策邏輯 (Routing Logic)

**步驟 1：檢查資訊是否充足**
- 如果使用者想求推薦（如「推薦我一張卡」），但**未提供**職業、年齡或消費習慣：
- ⛔ **禁止呼叫 Agent**。
- 💬 **直接反問使用者**：「為了精準推薦，請問您的職業是學生還是上班族？平常主要的消費通路為何？」

**步驟 2：判斷路由**
- **查詢單一卡片**：問年費、權益 -> 呼叫 `product_agent`。
- **比較或推薦**：問哪張好、求推薦 -> 呼叫 `comparing_agent`。
- **混合情境**：如果使用者問「CUBE卡年費多少？跟 Rose 卡比起來哪張好？」 -> **同時產生** `product_agent` (查CUBE年費) 與 `comparing_agent` (進行比較) 的 tool calls。

**步驟 3：整合回答 (Synthesize)**
- 當你收到 Agent 回傳的資料後，請將其轉化為通順、有條理的中文回答。
"""

# ==========================================
# 5. 主程式：聊天迴圈與連線管理
# ==========================================

async def chat() -> None:
    print("\n💬 歡迎使用 信用卡多重代理人系統 (Client Dispatcher)")
    print("=" * 60)
    print("正在啟動並連接所有 Agent，請稍候...")

    messages: List[ChatCompletionMessageParam] = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]

    # 使用 AsyncExitStack 來同時管理多個 Context Manager
    async with AsyncExitStack() as stack:
        try:
            # --- A. 建立多重連線 ---
            
            # 1. 連線到 Product Agent
            r_prod, w_prod = await stack.enter_async_context(stdio_client(PRODUCT_SERVER_PARAMS))
            sess_prod = await stack.enter_async_context(ClientSession(r_prod, w_prod))
            await sess_prod.initialize()
            print("✅ [System] Product Agent 已連線")

            # 2. 連線到 Comparing/Advisor Agent
            r_adv, w_adv = await stack.enter_async_context(stdio_client(ADVISOR_SERVER_PARAMS))
            sess_adv = await stack.enter_async_context(ClientSession(r_adv, w_adv))
            await sess_adv.initialize()
            print("✅ [System] Comparing Agent 已連線")

            print("🚀 系統準備就緒！(輸入 'q' 離開)")

            # --- B. 建立路由對照表 (Tool Name -> Session) ---
            # 這裡將新的工具名稱對應到連線 Session
            SESSION_MAP = {
                "product_agent": sess_prod,     # 對應 product_agent
                "comparing_agent": sess_adv     # 對應 comparing_agent
            }

            # --- C. 對話主迴圈 ---
            while True:
                try:
                    user_input = input("\n👤 (你): ").strip()
                    if user_input.lower() in ['quit', 'exit', 'q']:
                        print("👋 再見！")
                        break
                    if not user_input:
                        continue

                    # 加入使用者訊息
                    messages.append({"role": "user", "content": user_input})

                    # 1. Router 思考 (決定要找誰)
                    print("🤔 [Router] 正在分析意圖...", end="\r")
                    response = client.chat.completions.create(
                        model=os.getenv("AOAI_MODEL_VERSION"),
                        messages=messages,
                        tools=tool_schemas,
                        tool_choice="auto",
                    )
                    msg = response.choices[0].message
                    messages.append(msg)

                    # 2. 處理 Tool Calls (並行分派任務)
                    if msg.tool_calls:
                        print(f"⚡ [Router] 偵測到 {len(msg.tool_calls)} 個分派任務：")
                        
                        tasks = []      
                        tool_outputs = []

                        for tool_call in msg.tool_calls:
                            name = tool_call.function.name
                            args = json.loads(tool_call.function.arguments)
                            
                            # 查表找 Session
                            target_sess = SESSION_MAP.get(name)
                            
                            if target_sess:
                                print(f"   -> 派單給: {name}")
                                # 建立 Task 但不馬上 await (為了並行)
                                task = target_sess.call_tool(name, arguments=args)
                                tasks.append((tool_call, task))
                            else:
                                print(f"   ❌ 錯誤: 找不到 {name} 對應的連線")
                                tool_outputs.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "name": name,
                                    "content": json.dumps({"error": "Agent connection not found"})
                                })

                        # 3. 並行執行所有 Agent 任務
                        if tasks:
                            print("⏳ [System] 等待 Agents 回覆中...")
                            mcp_results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
                            
                            for i, mcp_res in enumerate(mcp_results):
                                original_tool_call = tasks[i][0]
                                tool_name = original_tool_call.function.name
                                
                                if isinstance(mcp_res, Exception):
                                    content_str = json.dumps({"error": str(mcp_res)})
                                    print(f"   ❌ {tool_name} 執行失敗: {mcp_res}")
                                else:
                                    if mcp_res.content and hasattr(mcp_res.content[0], 'text'):
                                        content_str = mcp_res.content[0].text
                                    else:
                                        content_str = str(mcp_res)
                                    print(f"   ✅ {tool_name} 回覆完成")

                                tool_outputs.append({
                                    "role": "tool",
                                    "tool_call_id": original_tool_call.id,
                                    "name": tool_name,
                                    "content": content_str
                                })

                        # 4. 整合回答
                        messages.extend(tool_outputs)
                        
                        print("📝 [Router] 正在整合資訊...")
                        final_response = client.chat.completions.create(
                            model=os.getenv("AOAI_MODEL_VERSION"),
                            messages=messages
                        )
                        final_answer = final_response.choices[0].message.content
                        print(f"\n💬 (總管): {final_answer}")
                        messages.append(final_response.choices[0].message)

                    else:
                        # 沒有呼叫工具
                        print(f"\n💬 (總管): {msg.content}")

                except Exception as e:
                    print(f"\n❌ [Error] 發生未預期錯誤: {e}")
                    continue

        except Exception as e:
            print(f"❌ [System] 連線建立失敗: {e}")
            print("請檢查 agent_product.py 與 agent_comparing.py 是否存在。")

if __name__ == "__main__":
    try:
        if sys.platform.startswith('win'):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(chat())
    except KeyboardInterrupt:
        print("\n程式手動中斷")