import json
import os

INPUT_FILE = "cards_rag.jsonl"          # 您的原始機器用檔案
OUTPUT_FILE = "cards_rag_view.json"     # 給人類看的排版檔案

def convert_to_pretty():
    if not os.path.exists(INPUT_FILE):
        print(f"❌ 找不到檔案: {INPUT_FILE}")
        return

    print(f"🚀 正在讀取 {INPUT_FILE} ...")
    
    data_list = []
    
    # 1. 讀取 JSONL (一行一行讀)
    try:
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    data_list.append(obj)
                except json.JSONDecodeError:
                    print(f"⚠️ 第 {line_num} 行格式錯誤，已跳過。")
    except Exception as e:
        print(f"❌ 讀取錯誤: {e}")
        return

    print(f"📊 共讀取 {len(data_list)} 筆資料，正在進行排版...")

    # 2. 寫入標準 JSON (indent=4 會自動換行跟縮排)
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            # ensure_ascii=False: 顯示中文
            # indent=4: 設定縮排 4 格 (這就是您要的換行排版效果)
            json.dump(data_list, f, ensure_ascii=False, indent=4)
            
        print(f"✅ 轉換成功！")
        print(f"📄 請打開這個檔案查看: {OUTPUT_FILE}")
        
    except Exception as e:
        print(f"❌ 寫入錯誤: {e}")

if __name__ == "__main__":
    convert_to_pretty()