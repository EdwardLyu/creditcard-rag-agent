import json
import csv
import os

# 設定檔案名稱
INPUT_FILE = "cards_rag.jsonl"
OUTPUT_FILE = "cards_rag.csv"

def convert_jsonl_to_csv():
    if not os.path.exists(INPUT_FILE):
        print(f"❌ 找不到輸入檔案: {INPUT_FILE}")
        return

    print(f"🚀 開始讀取 {INPUT_FILE} ...")

    processed_rows = []
    all_headers = set()

    # 1. 讀取並處理每一行資料
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            
            try:
                # 解析 JSON
                data = json.loads(line)
                
                # 取出 metadata (如果有的話)
                metadata = data.pop("metadata", {})
                
                # --- 核心邏輯：合併資料 (Flatten) ---
                # 將原本的 data 與 metadata 合併成同一層
                # 注意：如果 metadata 裡有跟外層一樣的 key，這裡 metadata 會覆蓋外層
                flat_row = {**data, **metadata}

                # --- 處理非純文字的欄位 (List 或 Dict) ---
                # CSV 一個格子只能存字串，所以遇到 list 或 dict 要轉成 JSON 字串
                for k, v in flat_row.items():
                    if isinstance(v, (list, dict)):
                        # ensure_ascii=False 確保中文不會變亂碼
                        flat_row[k] = json.dumps(v, ensure_ascii=False)
                    elif v is None:
                        flat_row[k] = ""
                
                # 收集所有出現過的欄位名稱 (為了製作 CSV Header)
                all_headers.update(flat_row.keys())
                
                processed_rows.append(flat_row)

            except json.JSONDecodeError:
                print(f"⚠️ 跳過格式錯誤的第 {line_num} 行")
                continue

    # 2. 決定欄位順序 (讓 id, card_name 這種重要欄位排前面)
    # 先轉成 list 方便排序
    sorted_headers = list(all_headers)
    
    # 定義我們希望排在最前面的欄位順序
    priority_order = [
        "id", "card_name", "doc_type", "scheme_name", "rule_type", "text", 
        "card_family", "tier", "reward_type", "valid_period", "channels_flat"
    ]
    
    # 自定義排序邏輯
    def header_sort_key(header):
        if header in priority_order:
            return priority_order.index(header)
        return len(priority_order) + 1  # 其他欄位排在後面

    # 執行排序 (優先欄位在前，剩下的依字母順序)
    sorted_headers.sort(key=lambda x: (header_sort_key(x), x))

    print(f"📊 共處理 {len(processed_rows)} 筆資料，欄位包含: {sorted_headers}")

    # 3. 寫入 CSV
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8-sig", newline="") as f:
            # encoding="utf-8-sig" 是為了讓 Excel 開啟時不會亂碼 (加上 BOM)
            writer = csv.DictWriter(f, fieldnames=sorted_headers)
            
            writer.writeheader()
            writer.writerows(processed_rows)
            
        print(f"✅ 轉換成功！已輸出至: {OUTPUT_FILE}")
        print("👉 提示：'channels_flat' 或 'raw' 等欄位內容較長，Excel 中可能需要拉寬欄位查看。")

    except Exception as e:
        print(f"❌ 寫入 CSV 時發生錯誤: {e}")

if __name__ == "__main__":
    convert_jsonl_to_csv()