import os
import pandas as pd
from langchain_community.embeddings import HuggingFaceBgeEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

def main():
    # ==========================================
    # 1. 設定檔案路徑
    # ==========================================
    csv_file_path = "rag_clean.csv"  # 您的 CSV 檔案名稱
    output_faiss_folder = "cards_rag_faiss_index" # 輸出向量資料庫的資料夾名稱

    # 檢查 CSV 是否存在
    if not os.path.exists(csv_file_path):
        print(f"❌ 找不到檔案: {csv_file_path}")
        return

    # ==========================================
    # 2. 讀取 CSV 並轉換為 LangChain Documents
    # ==========================================
    print(f"🚀 開始讀取 CSV: {csv_file_path} ...")
    
    # 讀取 CSV，並將 NaN (空值) 填補為空字串，避免 Metadata 報錯
    df = pd.read_csv(csv_file_path)
    df = df.fillna("") 

    documents = []
    print("🔄 正在轉換為 LangChain Documents...")

    for index, row in df.iterrows():
        # 1. 取出主要文本 (Text) 用於向量化
        page_content = row.get("text", "")
        
        # 確保文本不是空的
        if not page_content:
            continue

        # 2. 將其餘欄位設為 Metadata
        # 將該列轉換為字典
        metadata = row.to_dict()
        
        # 從 metadata 中移除 'text'，因為它已經是 page_content 了，不需要重複存
        if "text" in metadata:
            del metadata["text"]
            
        # 3. 建立 Document 物件
        doc = Document(page_content=page_content, metadata=metadata)
        documents.append(doc)

    print(f"📊 總共建立 {len(documents)} 個文件 (Documents)")

    # ==========================================
    # 3. 初始化 Embedding 模型與建立索引
    # ==========================================
    print("🧠 初始化 Embedding 模型 (BAAI/bge-m3)...")
    # 使用與您原本相同的模型設定
    embeddings = HuggingFaceBgeEmbeddings(
        model_name="BAAI/bge-m3",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )

    print("⚡️ 開始建立 FAISS 索引 (這可能需要一點時間)...")
    vectorstore = FAISS.from_documents(documents, embeddings)

    # ==========================================
    # 4. 儲存結果
    # ==========================================
    print(f"💾 儲存索引至: {output_faiss_folder}/")
    vectorstore.save_local(output_faiss_folder)
    print("✅ 完成！向量資料庫已建立。")

if __name__ == "__main__":
    main()