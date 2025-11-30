import psycopg2

def _connect_db(connection_string):
    """連接到 PostgreSQL 數據庫，失敗時自動重試直到成功"""
    try:
        conn = psycopg2.connect(connection_string)
        return conn
    except Exception as e:
        print(f"資料庫連接失敗: {e}")
        return None

# 查詢 新聞資料表 (ntn001rtnews)
# def query_news(connection_string, company_id, company_name, embedded_query):
    # search_count=15     # 取出的資料數
    # days=30             # 最早的資料時間
    # max_retries = 3     # 最大重試次數
    
    # for attempt in range(max_retries):
    #     conn = None
    #     cursor = None
    #     try:
    #         # 嘗試建立資料庫連線
    #         conn = _connect_db(connection_string)
    #         if conn is None:
    #             continue  # 如果連線失敗，進入下一次重試

    #         # 創建 cursor
    #         cursor = conn.cursor()

    #         # 根據條件生成 SQL 查詢語句
    #         and_date = f" AND datetime >= NOW() - INTERVAL '{days} DAYS' "
    #         embedded_query_pg = "[" + ",".join(map(str, embedded_query)) + "]"
    #         query_sql = ""

    #         if (
    #         company_id
    #         and company_name
    #         and len(company_id) > 0
    #         and len(company_name) > 0
    #         ):
    #         # 簡化一下 只拿 Story 讓學生自己拿 個股
    #             query_sql = f"""
    #                 SELECT headline, story
    #                 FROM ntn001rtnews
    #                 WHERE stock_code LIKE '%{company_id}%' {and_date}
    #                 ORDER BY story_vector <-> '{embedded_query_pg}'::VECTOR(1536)
    #                 LIMIT {search_count};
    #             """
    #         else:
    #             query_sql = f"""
    #                 SELECT headline, story                    
    #                 FROM ntn001rtnews
    #                 WHERE datetime >= NOW() - INTERVAL '{days} DAYS'
    #                 ORDER BY story_vector <-> '{embedded_query_pg}'::VECTOR(1536)
    #                 LIMIT {search_count};
    #             """
    #         # 如果查詢語句為空，返回空列表
    #         if len(query_sql) == 0:
    #             return []
    #         else:
    #             # 執行查詢
    #             cursor.execute(query_sql)
    #             data = cursor.fetchall()
    #             column_names = [desc[0] for desc in cursor.description]
    #             final_rows = [dict(zip(column_names, row)) for row in data]
    #             return final_rows  # 成功查詢，返回結果
    #     except (psycopg2.OperationalError, psycopg2.errors.QueryCanceled) as e:

    #         # 捕獲 timeout 相關異常，記錄日誌
    #         print(f"Timeout error on attempt {attempt + 1}: {e}")
    #         if attempt == max_retries - 1:  # 如果是最後一次重試，拋出異常
    #             raise
    #         # 否則繼續下一次重試
    #     finally:
    #         # 確保資源被釋放
    #         if cursor:
    #             cursor.close()
    #         if conn:
    #             conn.close()


    # max_retries = 3  # 最大重試次數
    # for attempt in range(max_retries):
    #     conn = None
    #     cursor = None
    #     try:
    #         # 嘗試建立資料庫連線
    #         conn = _connect_db(connection_string)
    #         if conn is None:
    #             continue  # 如果連線失敗，進入下一次重試

    #         # 創建 cursor
    #         cursor = conn.cursor()

    #         # 根據條件生成 SQL 查詢語句
    #         embedded_query_pg = "[" + ",".join(map(str, embedded_query)) + "]"
    #         query_sql = ""

    #         if (
    #             company_id
    #             and company_name
    #             and len(company_id) > 0
    #             and len(company_name) > 0
    #         ):
    #         # 簡化一下 只拿 Story 讓學生自己拿 個股
    #             query_sql = f"""
    #                 SELECT key1, pagehtml, l2_distance(pagehtml_vector,'{embedded_query_pg}'::VECTOR(1536)) AS similarity, updat
    #                 FROM atimwjsonx
    #                 WHERE key1 = '{company_id}' AND pagehtml LIKE '%{company_name}%' AND latest = 1
    #                 ORDER BY pagehtml_vector <-> '{embedded_query_pg}'::VECTOR(1536)
    #                 LIMIT 1;
    #             """
    #         # 如果查詢語句為空，返回空列表
    #         if len(query_sql) == 0:
    #             return []
    #         else:
    #             # 執行查詢
    #             cursor.execute(query_sql)
    #             data = cursor.fetchall()
    #             column_names = [desc[0] for desc in cursor.description]
    #             final_rows = [dict(zip(column_names, row)) for row in data]
    #             return final_rows  # 成功查詢，返回結果

    #     except (psycopg2.OperationalError, psycopg2.errors.QueryCanceled) as e:
    #         # 捕獲 timeout 相關異常，記錄日誌
    #         print(f"Timeout error on attempt {attempt + 1}: {e}")
    #         if attempt == max_retries - 1:  # 如果是最後一次重試，拋出異常
    #             raise
    #         # 否則繼續下一次重試

    #     finally:
    #         # 確保資源被釋放
    #         if cursor:
    #             cursor.close()
    #         if conn:
    #             conn.close()