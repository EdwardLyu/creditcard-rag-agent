import asyncio
import json
import logging
import sys
import os

# 引入 MCP 相關套件
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource

# 引入寫好的 LLM 工具 (確保 llm_utils.py 在同一個資料夾)
from llm_utils import chat_with_aoai_gpt

# 設定 Log (輸出到 stderr 以免干擾 MCP 通訊)
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("agent_demand")

# 建立 MCP Server
app = Server("agent_demand")

@app.list_tools()
async def list_tools() -> list[Tool]:
    """定義這個 Agent 能做什麼"""
    return [
        Tool(
            name="analyze_user_needs",
            description="分析使用者背景資訊（年齡、職業、收入、消費習慣）。當使用者提及個人狀況時務必使用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_input": {
                        "type": "string",
                        "description": "使用者的自我介紹或需求描述 (例如: 我是大學生，月打工賺2萬)"
                    }
                },
                "required": ["user_input"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent | ImageContent | EmbeddedResource]:
    """當 Router 呼叫此工具時的執行入口"""
    if name == "analyze_user_needs":
        user_input = arguments.get("user_input", "")
        logger.info(f"收到分析請求: {user_input}")
        
        # 執行分析邏輯
        result_json = await analyze_logic(user_input)
        
        # 回傳 JSON 字串給 Router
        return [TextContent(type="text", text=json.dumps(result_json, ensure_ascii=False))]
    
    raise ValueError(f"Unknown tool: {name}")

async def analyze_logic(user_input: str) -> dict:
    """
    核心邏輯：LLM 提取 + Rule-Based 資格審查
    """
    
    # --- 1. LLM Prompt：提取關鍵欄位 ---
    system_prompt = """
    你是國泰世華銀行的「需求分析專家」。
    請從使用者輸入中提取以下資訊，並輸出純 JSON 格式：

    1. age (int, 未知填 null)
    2. occupation (str, 未知填 "未知")
    3. annual_income (int, 單位:新台幣元, 請自動將"月薪4萬"轉換為480000, 未知填 null)
    4. identity_type (str, 選填: "學生", "上班族", "家管", "退休", "未知")
    5. spending_habits (List[str], 消費關鍵字 e.g. ["網購", "旅遊", "蝦皮", "百貨", "加油"])
    6. purpose (str, 辦卡目的 e.g. "脫白", "哩程", "現金回饋", "首刷禮")

    **重要判斷規則**：
    - 若提及「還在唸書」、「大學生」、「打工」，identity_type 必為 "學生"。
    - 若提及「剛畢業」、「第一份工作」，identity_type 為 "社會新鮮人"。
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input}
    ]

    # 呼叫 Gemini (使用 llm_utils)
    try:
        response_text = chat_with_aoai_gpt(messages, use_json_format=True)
        profile = json.loads(response_text)
    except Exception as e:
        logger.error(f"LLM 解析失敗: {e}")
        # 發生錯誤時的回底
        profile = {
            "error": "Parsing failed", 
            "raw": str(e),
            "age": None,
            "identity_type": "未知",
            "annual_income": None
        }

    # --- 2. Rule Engine：國泰世華信用卡資格審查 ---
    risk_flags = []
    recommended_tags = [] # 用來給推薦 Agent 的暗示
    
    # 取得欄位
    age = profile.get("age")
    income = profile.get("annual_income")
    identity = profile.get("identity_type")
    habits = profile.get("spending_habits", [])

    # === 規則 A: 身分與年齡限制 ===
    if identity == "學生":
        risk_flags.append("【學生身分限制】額度上限約 2 萬元，需照會父母，無法申辦無限卡/世界卡。")
        if age and age < 20:
             risk_flags.append("【未成年】未滿 20 歲學生需法定代理人簽名同意。")
        # 學生推薦
        recommended_tags.append("推薦：CUBE卡(門檻低/回饋靈活)、蝦皮聯名卡(網購)")

    elif age and age < 20:
        risk_flags.append("【未成年】未滿 20 歲須由法定代理人同意，或僅能申辦附卡。")

    if identity == "社會新鮮人":
        recommended_tags.append("推薦：CUBE卡(適合新鮮人/首張卡)")

    # === 規則 B: 年收入門檻 (Income Thresholds) ===
    if income:
        # < 20 萬
        if income < 200000 and identity != "學生":
            risk_flags.append("【財力提醒】年收未達 20 萬，可能未達多數信用卡(CUBE/蝦皮)最低申請門檻。")
        
        # 20萬 ~ 60萬 (普卡/白金/御璽等級)
        elif 200000 <= income < 600000:
            recommended_tags.append("資格符合：CUBE卡、蝦皮聯名卡、長榮航空御璽卡、亞洲萬里通里享卡")
            
        # 60萬 ~ 200萬 (無限/鈦金商務等級)
        elif 600000 <= income < 2000000:
            recommended_tags.append("資格符合：長榮航空無限卡(需年收60萬)、亞洲萬里通鈦金商務卡")
            if "旅遊" in habits or "出國" in habits:
                 recommended_tags.append("推薦：長榮航空聯名卡(適合常出國)")

        # > 200萬 (頂級卡/世界卡等級)
        elif income >= 2000000:
            recommended_tags.append("【高資產客群】符合「世界卡」、「長榮航空極致無限卡」申請資格")
            recommended_tags.append("尊榮禮遇：機場接送、貴賓室、頂級餐廳優惠")

    # === 規則 C: 消費習慣對應 (Habits) ===
    if habits:
        if "蝦皮" in habits or "網購" in habits:
            recommended_tags.append("推薦：國泰蝦皮購物聯名卡(站內最高10%)、CUBE卡(玩數位方案)")
        if "旅遊" in habits or "日本" in habits:
            recommended_tags.append("推薦：CUBE卡(趣旅行方案)、長榮/亞萬聯名卡")
        if "全聯" in habits or "超商" in habits:
            recommended_tags.append("推薦：CUBE卡(集精選方案)")

    # 寫回結果
    profile["risk_flags"] = risk_flags
    profile["system_tags"] = recommended_tags

    return profile

async def main():
    # 啟動 MCP Server (標準輸入輸出模式)
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    print("正在啟動 Demand Agent...", file=sys.stderr)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass