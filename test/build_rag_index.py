# build_rag_index.py
# 使用 llm_utils.query_ai_embedding（目前是本地 BGE-M3）
# 把 cards_rag.jsonl 每一行加上 embedding 欄位，輸出 cards_rag_embedded.jsonl

import json

from llm_utils import query_ai_embedding

INPUT_PATH = "cards_rag.jsonl"
OUTPUT_PATH = "cards_rag_embedded.jsonl"

def main():
    total = 0
    with open(INPUT_PATH, "r", encoding="utf-8") as fin, \
         open(OUTPUT_PATH, "w", encoding="utf-8") as fout:

        for idx, line in enumerate(fin, start=1):
            line = line.strip()
            if not line:
                continue

            chunk = json.loads(line)
            text = chunk.get("text", "")

            # 呼叫目前改成用 BGE-M3 的 query_ai_embedding
            emb = query_ai_embedding(text)

            if not emb:
                # 如果 embedding 失敗，就寫空陣列，但至少不會整個程式炸掉
                print(f"⚠️ 第 {idx} 行 embedding 失敗，先寫入空陣列")
                emb = []

            chunk["embedding"] = emb
            fout.write(json.dumps(chunk, ensure_ascii=False) + "\n")
            total += 1

    print(f"✅ 完成：共處理 {total} 筆；已輸出帶 embedding 的 {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
