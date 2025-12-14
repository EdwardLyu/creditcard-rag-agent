# agent_client.py (V2 - 支援連續對話版)
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI  # 改用 OpenAI client
from openai.types.chat import ChatCompletionMessageParam
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession
from pathlib import Path

# ==========================================
# 1. 環境設定與初始化
# ==========================================

# 在這個檔案所在的資料夾，往上找 .env
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# 檢查 Gemini 相關環境變數
required_vars = ["GEMINI_API_KEY"]
missing = [k for k in required_vars if k not in os.environ or not os.environ[k].strip()]
if missing:
    print(f"❌ 錯誤：缺少必要的環境變數: {missing}")
    sys.exit(1)

# 讀取 Gemini 相關設定
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/",
)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# 初始化 OpenAI Client
client = OpenAI(
    api_key=GEMINI_API_KEY,
    base_url=GEMINI_BASE_URL,
)

# ==========================================
# 2. 定義各個 Agent 的連線參數
# ==========================================

# A. 產品專家 Agent 
PRODUCT_SERVER_PARAMS = StdioServerParameters(
    command="python", args=["agent_product.py"], env=os.environ.copy()
)

# B. 比較/推薦專家 Agent 
ADVISOR_SERVER_PARAMS = StdioServerParameters(
    command="python", args=["agent_comparing.py"], env=os.environ.copy()
)

# C. 需求分析 Agent 
DEMAND_SERVER_PARAMS = StdioServerParameters(
    command="python", args=["agent_demand.py"], env=os.environ.copy()
)
# D. 申辦資格 Agent
ELIGIBILITY_SERVER_PARAMS = StdioServerParameters(
    command="python", args=["eligibility_agent.py"], env=os.environ.copy()
)

# ==========================================
# 3. 定義 Tool Schemas
# ==========================================

tool_schemas = [
    {
        "type": "function",
        "function": {
            "name": "product_agent",  
            "description": "【產品專家】負責 1.提供卡片固定資訊與條款內容 2.計算回饋與列出附加權益。",
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
            "description": "【比較與推薦專家】負責「多張卡片比較」或「推薦卡片」。當使用者詢問「哪張卡比較好？」或「請推薦適合學生的卡」時使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_query": {
                        "type": "string",
                        "description": "使用者的完整原始問題"
                    },
                    "user_profile": {
                        "type": "string",
                        "description": "使用者背景資訊 JSON (由 demand_agent 分析得知)。若未知則不填。"
                    }
                },
                "required": ["user_query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "demand_agent",  
            "description": "【需求分析專家】負責分析使用者背景（年齡、職業、年收）。當使用者提供個人資訊，或詢問「我可以辦什麼卡」時，請優先呼叫此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_input": {
                        "type": "string",
                        "description": "使用者的自我介紹或需求描述"
                    }
                },
                "required": ["user_input"]
            }
        }
    },
        {
        "type": "function",
        "function": {
            "name": "eligibility_agent",
            "description": "【申辦資格 / 適格性】判斷使用者是否符合某張卡的申辦門檻/財力條件/學生或新鮮人限制等，並說明原因與需要補什麼資料。",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_query": {
                        "type": "string",
                        "description": "使用者的完整原始問題（例如：『我月薪 4 萬可以辦 CUBE 嗎？』）"
                    },
                    "user_profile": {
                        "type": "string",
                        "description": "使用者背景資訊 JSON 字串（若 demand_agent 已分析出來可提供；未知可不填）"
                    }
                },
                "required": ["user_query"]
            }
        }
    }

    
]

# ==========================================
# 4. System Prompt
# ==========================================

SYSTEM_PROMPT = """
你是一個專業的信用卡服務總管 (Main Dispatcher)。
你的任務是協調 Agent 回答問題。

# ⚠️ 最高指導原則 (防止鬼打牆)
1. **禁止重複呼叫**：在同一次回答中，**絕對禁止**連續呼叫同一個 Agent 兩次。
2. **狀態檢查**：
   - 每次決定行動前，請先檢查「對話歷史 (Context)」。
   - 如果你看到歷史紀錄中 `demand_agent` **剛剛已經**回傳了 JSON 結果，**請勿**再次呼叫它。
   - 承上，拿到 JSON 後，你的下一步**必須**是呼叫 `comparing_agent`，並把 JSON 填入 `user_profile`。

# 專家 Agent 介紹
1. **demand_agent**: 分析使用者背景 (年齡/職業/收入)。
2. **comparing_agent**: 推薦卡片。需提供 `user_profile`。
3. **product_agent**: 查詢卡片回饋資訊。
4. **eligibility_agent: 判斷申辦門檻/資格與缺少資料

# 標準作業流程 (SOP)

**情境：使用者求推薦 (例如: "我是學生，想辦卡")**
STEP 1: 呼叫 `demand_agent` 分析背景。
STEP 2: (收到 demand_agent 回覆後) -> **立刻停止思考背景**，轉而呼叫 `comparing_agent`。
   - 參數 `user_query`: 使用者的原始問題
   - 參數 `user_profile`: 剛剛 `demand_agent` 回傳的 JSON 字串
STEP 3: (收到 comparing_agent 回覆後) -> 整合資訊，回答使用者。

**錯誤示範 (絕對禁止)**
❌ 使用者說「我是學生」 -> 呼叫 `demand_agent` -> 收到結果 -> 又看到「我是學生」 -> 又呼叫 `demand_agent` (無限迴圈)。
"""

# ==========================================
# 5. 主程式：聊天迴圈與連線管理
# ==========================================

async def chat() -> None:
    print("\n💬 歡迎使用 信用卡多重代理人系統 (Client Dispatcher V2)")
    print("============================================================")
    print("正在啟動並連接所有 Agent，請稍候...")

    messages: List[ChatCompletionMessageParam] = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]

    async with AsyncExitStack() as stack:
        try:
            # --- A. 建立多重連線 ---
            
            # 1. Product Agent
            r_prod, w_prod = await stack.enter_async_context(stdio_client(PRODUCT_SERVER_PARAMS))
            sess_prod = await stack.enter_async_context(ClientSession(r_prod, w_prod))
            await sess_prod.initialize()
            print("✅ [System] Product Agent 已連線")

            # 2. Comparing Agent
            r_adv, w_adv = await stack.enter_async_context(stdio_client(ADVISOR_SERVER_PARAMS))
            sess_adv = await stack.enter_async_context(ClientSession(r_adv, w_adv))
            await sess_adv.initialize()
            print("✅ [System] Comparing Agent 已連線")
            
            # 3. Demand Agent
            r_dem, w_dem = await stack.enter_async_context(stdio_client(DEMAND_SERVER_PARAMS))
            sess_dem = await stack.enter_async_context(ClientSession(r_dem, w_dem))
            await sess_dem.initialize()
            print("✅ [System] Demand Agent 已連線")
             # 4. Eligibility Agent
            r_eli, w_eli = await stack.enter_async_context(stdio_client(ELIGIBILITY_SERVER_PARAMS))
            sess_eli = await stack.enter_async_context(ClientSession(r_eli, w_eli))
            await sess_eli.initialize()
            print("✅ [System] Eligibility Agent 已連線")
            print("🚀 系統準備就緒！(輸入 'q' 離開)")

            # --- B. 建立路由對照表 ---
            SESSION_MAP = {
                "product_agent": sess_prod,
                "comparing_agent": sess_adv,
                "demand_agent": sess_dem,
                "eligibility_agent": sess_eli
            }

            # --- C. 對話主迴圈 (User Loop) ---
            while True:
                user_input = input("\n👤 (你): ").strip()
                if user_input.lower() in ['quit', 'exit', 'q']:
                    print("👋 再見！")
                    break
                if not user_input:
                    continue

                messages.append({"role": "user", "content": user_input})

                # === D. 內部派單迴圈 (Agent Loop) ===
                # 這裡使用了 while True，讓 Router 可以連續呼叫多次工具
                while True:
                    print("🤔 [Router] 思考下一步...", end="\r")
                    
                    try:
                        response = client.chat.completions.create(
                            model=GEMINI_MODEL,
                            messages=messages,
                            tools=tool_schemas,
                            tool_choice="auto",
                        )
                    except Exception as e:
                        print(f"\n❌ LLM 呼叫錯誤: {e}")
                        break

                    msg = response.choices[0].message
                    messages.append(msg) # 將模型的決策加入歷史紀錄

                    # 1. 如果模型回傳了文字 (Content)，代表它想說話了 -> 顯示並跳出內部迴圈
                    if msg.content:
                        print(f"\n💬 (總管): {msg.content}")
                        break 

                    # 2. 如果模型想呼叫工具 (Tool Calls)
                    if msg.tool_calls:
                        print(f"\n⚡ [Router] 偵測到 {len(msg.tool_calls)} 個分派任務：")
                        
                        tasks = []       
                        tool_outputs = []

                        for tool_call in msg.tool_calls:
                            name = tool_call.function.name
                            args = json.loads(tool_call.function.arguments)
                            
                            target_sess = SESSION_MAP.get(name)
                            
                            if target_sess:
                                print(f"   -> 派單給: {name}")
                                # 呼叫 MCP Agent
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

                        # 並行執行所有任務
                        if tasks:
                            print("⏳ [System] 等待 Agents 回覆中...")
                            mcp_results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
                            
                            for i, mcp_res in enumerate(mcp_results):
                                original_tool_call = tasks[i][0]
                                tool_name = original_tool_call.function.name
                                
                                content_str = ""
                                if isinstance(mcp_res, Exception):
                                    content_str = json.dumps({"error": str(mcp_res)})
                                    print(f"   ❌ {tool_name} 執行失敗: {mcp_res}")
                                else:
                                    # 兼容 TextContent 或直接字串
                                    if hasattr(mcp_res, 'content') and mcp_res.content and hasattr(mcp_res.content[0], 'text'):
                                        content_str = mcp_res.content[0].text
                                    else:
                                        content_str = str(mcp_res)
                                    print(f"   ✅ {tool_name} 回覆完成")

                                # 將結果存入列表
                                tool_outputs.append({
                                    "role": "tool",
                                    "tool_call_id": original_tool_call.id,
                                    "name": tool_name,
                                    "content": content_str
                                })

                        # 將 Tool Outputs 塞回 messages，讓迴圈跑下一輪，模型會看到結果並決定下一步
                        messages.extend(tool_outputs)

        except Exception as e:
            print(f"❌ [System] 連線建立失敗: {e}")
            print("請檢查所有 Agent 檔案是否存在且正確。")

if __name__ == "__main__":
    try:
        if sys.platform.startswith('win'):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(chat())
    except KeyboardInterrupt:
        print("\n程式手動中斷")