import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from webdriver_manager.chrome import ChromeDriverManager

TARGET_URL = "https://www.cathay-cube.com.tw/cathaybk/personal/product/credit-card/cards/cube-list"
OUTPUT_FILE = "cube_card_benefits_div_structure.md"

def setup_driver():
    options = Options()
    # options.add_argument("--headless") # 建議開啟視窗觀察
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1440,900")
    options.add_argument("--no-sandbox")
    options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def scrape_specific_div():
    driver = setup_driver()
    driver.implicitly_wait(10)
    
    md_output = f"# CUBE 卡結構化權益資料 (特定 DIV 鎖定版)\n\n來源: {TARGET_URL}\n---\n"
    
    try:
        print("🚀 啟動瀏覽器...")
        driver.get(TARGET_URL)
        time.sleep(8) # 等待網頁完全載入

        # 1. 鎖定特定的父容器
        # class="aem-container aem-Grid aem-Grid--12 aem-Grid--default--12 overflow-clip mb-20"
        print("🔍 正在搜尋指定的父容器 (overflow-clip mb-20)...")
        
        # 使用 CSS Selector 精準定位該 class 組合
        # 注意：class 順序在 CSS selector 不重要，只要都包含即可
        parent_selector = "div.aem-container.aem-Grid.aem-Grid--12.aem-Grid--default--12.overflow-clip.mb-20"
        
        try:
            parent_div = driver.find_element(By.CSS_SELECTOR, parent_selector)
            print("✅ 成功鎖定父容器！")
        except Exception as e:
            print(f"❌ 找不到父容器，請檢查 class 是否變更。錯誤: {e}")
            return

        # 2. 在父容器內，抓取所有指定的子區塊
        # class="aem-GridColumn aem-GridColumn--default--12"
        # 使用 ./div 代表只找直接子層或內層
        child_selector = "./div[contains(@class, 'aem-GridColumn') and contains(@class, 'aem-GridColumn--default--12')]"
        children_divs = parent_div.find_elements(By.XPATH, child_selector)
        
        print(f"📦 在父容器內共找到 {len(children_divs)} 個權益區塊 (預期約 9 個)")

        for idx, div in enumerate(children_divs):
            # 捲動到該區塊，確保元素被渲染
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", div)
            time.sleep(0.5)

            # --- 3. 爬取表層文字 ---
            surface_text = div.text.strip()
            
            # 過濾掉完全空白的區塊
            if not surface_text:
                continue

            print(f"   ⚡ 正在處理第 {idx+1} 個區塊...")
            
            md_output += f"\n## 權益區塊 {idx+1}\n"
            md_output += "### 📄 表層資訊\n"
            md_output += f"```text\n{surface_text}\n```\n\n"

            # --- 4. 爬取 Info Icon 資訊 ---
            # 只在當前 div 內找 icon
            icons = div.find_elements(By.CSS_SELECTOR, ".icon-line-info")
            
            if icons:
                print(f"      ℹ️ 發現 {len(icons)} 個彈窗按鈕，準備抓取...")
                md_output += f"### ℹ️ 內層注意事項 (共 {len(icons)} 則)\n"
                
                for i, icon in enumerate(icons):
                    try:
                        if not icon.is_displayed():
                            continue

                        # --- A. 開啟彈窗 ---
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", icon)
                        time.sleep(0.5)
                        driver.execute_script("arguments[0].click();", icon)
                        time.sleep(1.5) # 等待彈窗

                        # --- B. 抓取彈窗內容 ---
                        # 抓取頁面上最新出現的 fixed 彈窗
                        popup_content = driver.execute_script("""
                            let popups = document.querySelectorAll('div[class*="fixed"]');
                            // 倒序尋找
                            for(let i=popups.length-1; i>=0; i--) {
                                let p = popups[i];
                                if(p.offsetWidth > 0 && p.offsetHeight > 0 && p.innerText.length > 5) {
                                    return p.innerText;
                                }
                            }
                            return null;
                        """)

                        if popup_content:
                            clean_text = popup_content.replace("關閉", "").strip()
                            formatted_text = "\n".join([f"> {line}" for line in clean_text.splitlines() if line.strip()])
                            md_output += f"**項目 {i+1} 詳情**:\n{formatted_text}\n\n"
                        
                        # --- C. 關閉彈窗 ---
                        # 1. JS 點擊關閉鈕
                        driver.execute_script("""
                            let popups = document.querySelectorAll('div[class*="fixed"]');
                            for(let i=popups.length-1; i>=0; i--) {
                                let p = popups[i];
                                if(p.offsetWidth > 0 && p.offsetHeight > 0) {
                                    let btns = p.querySelectorAll('button');
                                    for(let btn of btns) { btn.click(); }
                                }
                            }
                        """)
                        # 2. ESC 鍵
                        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                        time.sleep(1)

                    except Exception as e:
                        print(f"      ⚠️ Icon {i+1} 失敗: {e}")
                        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                        continue
            else:
                md_output += "(此區塊無詳細資訊按鈕)\n\n"
            
            md_output += "---\n"

        # 寫入檔案
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(md_output)
        print(f"\n✅ 抓取完成！檔案已儲存至: {OUTPUT_FILE}")

    except Exception as e:
        print(f"❌ 發生錯誤: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    scrape_specific_div()