# 信用卡多重代理人系統 (Credit Card Multi-Agent System)

這是一個基於 **MCP (Model Context Protocol)** 架構開發的多重代理人系統。系統包含一個核心的 **Client (派單員/Dispatcher)** 以及多個獨立的 **Server (專家 Agent)**，透過標準化的協定進行溝通與協作。

## 📂 專案結構

- **📁 `creditcard_json/`**:
  放原始整理好的信用卡 JSON 資料：

  - `cube_structured.json`：CUBE 卡
  - `shopee.json`：蝦皮聯名卡
  - `worldcard_structured.json`：國泰世華世界卡
  - `colab.json`：國泰世華亞洲萬里通聯名卡

這些檔案不直接給 RAG 用，要先經過 `transfer.py` 轉成統一格式。

---

- **`agent_client.py`**: Client 端主程式。負責接收使用者輸入、決策分派任務 (Router)，並整合各 Agent 的回覆。
- **`agent_product.py`**: Server 端 - 產品專家 Agent。負責回答單一卡片的客觀資訊 (如年費、權益)。
- **`agent_comparing.py`**: Server 端 - 比較與推薦專家 Agent。負責多卡比較與個人化推薦。
- **`agent_demand.py`**: Server 端 - 需求分析專家 Agent。負責從使用者口語對話中提取背景資訊（年齡、職業、年收、消費習慣）。
- **`connect_database.py`**: 資料庫連線模組 (供各 Agent 使用，目前沒有用到)。
- **`build_rag_index.py`**: 將 credit_rag.jsonl 轉換成 credit_rag_embedding.jsonl。
- **`rag_search.py`**: 向量查詢方式

## 🚀 快速開始

### 1. 建立並啟用虛擬環境 (推薦)

建議使用 Python 3.10 以上版本。

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 2. 安裝相依套件

```bash
pip install -r requirements.txt
```

### 3. 啟動系統（擇一）

1. **跑主程式**

```bash
python agent_client.py
```

2. **測試 agent_product.py**

```bash
python agent_product.py --local
```

3. **測試 agent_comparing.py**

```bash
python agent_comparing.py --local
```
4. **測試 agent_demand.py**

```bash
python agent_demand.py --local
```

## 🚀 補充資訊（想到什麼補什麼）

# 連接到地端的 postgresql

1. **設定資料庫伺服器位置**
   **env 中的** `DB_CONNECTION_STRING = "postgresql://user:password@localhost:5432/dbname"`

**user** ：使用者名稱 (Username)。
**password**：密碼 (Password)。
**localhost:5432**：伺服器位置與連接埠 (Host:Port)。
**dbname**：資料庫名稱 (Database Name)

2. **實際編寫資料庫查詢的函數**
   **connect_database.py** 裡面寫了怎麼實際去資料庫伺服器撈資料，想了解詳情可以參考 `query_news` 函數

# llm_utils.py 定義怎麼使用 llm api 並回答

**query_ai_embedding** ：示範怎麼將文字向量化（暫時沒用到）
**chat_with_aoai_gpt** ： 實際呼叫 llm 回答的函數

輸入歷史資料，如：

```bash
messages_normal = [
        {"role": "system", "content": "你是一個幽默的繁體中文助手。"},
        {"role": "user", "content": "請用一句話解釋什麼是遞迴 (Recursion)。"},
        {"role": "assistant", "content":"遞迴就像是一個自言自語的魔術師，透過不斷重複自己來解決問題，直到遇到一個簡單的情況停下來為止！"},
        {"role": "system", "content": "你是一個幽默的繁體中文助手。"},
        {"role": "user", "content": "你還記得我們在討論什麼主題嗎"},
    ]
```

輸出會是回應的字串
