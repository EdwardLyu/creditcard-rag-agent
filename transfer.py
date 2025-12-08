# 將 creditcard 中的 .json 轉換成 credit_rag.jsonl
import json, os
from pathlib import Path

# 基本工具：產生 ID
def make_id(*parts):
    """
    把多個字串組成一個乾淨的 id：小寫、底線、移除空白
    """
    cleaned = []
    for p in parts:
        if p is None:
            continue
        s = str(p).strip().replace(" ", "").replace("：", "_").replace(":", "_")
        cleaned.append(s.lower())
    return "_".join(cleaned)

def detect_reward_type(card_name: str | None = None,
                       family: str | None = None,
                       raw: dict | None = None) -> str:
    text = (card_name or "") + " " + (family or "")
    raw_text = ""
    if raw:
        try:
            import json
            raw_text = json.dumps(raw, ensure_ascii=False)
        except Exception:
            raw_text = str(raw)
    full = text + " " + raw_text

    # 1) 亞洲萬里通 / 里程卡 / miles
    mile_keywords = ["亞洲萬里通", "哩程", "里數", "mile", "miles"]
    if any(k in full for k in mile_keywords):
        return "miles"

    # 2) 蝦皮（混合回饋：現金 + 蝦幣）
    shopee_keywords = ["蝦幣", "免運"]
    if any(k in full for k in shopee_keywords):
        return "mixed"

    # 3) 點數（銀行紅利點數、旅遊積分等）
    point_keywords = ["點", "points", "小樹點"]
    if any(k in full for k in point_keywords):
        return "points"

    return "other"


# 轉換 credit_card_profile → chunk
def profile_to_chunk(profile: dict, source_file: str) -> dict:
    card_name = profile.get("card_name", "")
    issuer = profile.get("issuer", "")
    doc_type = profile.get("doc_type", "credit_card_profile")

    # 1. 組 text（可以自己調整模板，下面是簡單示範）
    annual_fee = profile.get("annual_fee")
    if isinstance(annual_fee, dict):
        annual_fee_str = f"正卡年費 {annual_fee.get('primary', '')}，附卡{annual_fee.get('supplementary', '')}。"
        if annual_fee.get("waiver"):
            annual_fee_str += f"年費減免條件：{annual_fee['waiver']}。"
    else:
        if annual_fee:
            annual_fee_str = f"{annual_fee}。"
        else:
            annual_fee_str = "年費依銀行公告。"

    eligibility = profile.get("eligibility") or {}
    income_req = eligibility.get("income_requirement") or profile.get("income_requirement", "")
    age = eligibility.get("age", "")
    employment = eligibility.get("employment", "")

    conds = [age, employment, income_req]
    clean_conds = []
    for c in conds:
        if not c:
            continue
        c = c.rstrip("。")
        clean_conds.append(c)

    segments = profile.get("target_users") or profile.get("user_segments") or []

    text_parts = [
        f"{issuer}發行的「{card_name}」基本資料：",
        annual_fee_str,
    ]

    if clean_conds:
        text_parts.append("申辦資格包含：" + "、".join(clean_conds) + "。")

    if segments:
        text_parts.append("適合族群例如：" + "；".join(segments) + "。")

    positioning = profile.get("positioning")
    if positioning:
        text_parts.append(f"卡片定位：{positioning}")

    text = "".join(text_parts)

    family = profile.get("family") or profile.get("card_family")
    reward_type = detect_reward_type(card_name, family, profile)
    
    # 如果卡名含「蝦皮」，就硬改成 mixed
    if "蝦皮" in card_name:
        reward_type = "mixed"
    # 世界卡：以禮遇為主
    elif "世界卡" in card_name and "亞洲萬里通" not in card_name:
        reward_type = "privilege"

    # 2. 組 metadata
    metadata = {
        "card_family": profile.get("family") or profile.get("card_family") or card_name,
        "tier": profile.get("tier"),
        "reward_type": reward_type,
        "main_tags": ["profile"],
        "channel_tags": [],
        "source": profile.get("source"),
        "source_file": source_file,
        "source_path": ["credit_card_profile"],
        "raw": profile
    }

    chunk = {
        "id": make_id(card_name, "profile"),
        "text": text,
        "card_name": card_name,
        "issuer": issuer,
        "doc_type": doc_type,
        "scheme_name": None,
        "rule_type": None,
        "metadata": metadata
    }
    return chunk

# 轉換 benefit_scheme → chunks
def scheme_to_chunks(schemes: list[dict], card_name: str, issuer: str, source_file: str) -> list[dict]:
    chunks: list[dict] = []

    for i, s in enumerate(schemes):
        # 有些 scheme 裡會自己帶 card_name / card_family，用它優先，沒有再用參數帶進來的 card_name
        scheme_card_name = s.get("card_name") or card_name
        family = s.get("card_family") or scheme_card_name

        scheme_name = s.get("scheme_name", "")
        surface_desc = s.get("surface_desc", "")
        valid_period = s.get("valid_period")

        # 用共用的偵測函式來決定 reward_type（會抓 "亞洲萬里通" / "哩程" 等關鍵字）
        reward_type = detect_reward_type(scheme_card_name, family, s)

        # -------- valid_period 組人類可讀字串（特別處理 asiamiles 那種 dict） --------
        valid_period_str = None
        if isinstance(valid_period, dict):
            # 專門給 asiamiles 用的人類可讀字串
            gp = valid_period.get("general_spending")
            acc = valid_period.get("accelerator")
            parts = []
            if gp:
                parts.append(f"一般消費里程累積期間：{gp}")
            if acc:
                parts.append(f"哩程加速器指定通路期間：{acc}")
            valid_period_str = "；".join(parts)
        else:
            valid_period_str = valid_period

        # -------- text --------
        text = f"{scheme_card_name}權益方案「{scheme_name}」：{surface_desc}"
        if valid_period_str:
            text += f"（適用期間：{valid_period_str}）"
        elif valid_period:
            # 保險一層，如果上面沒轉出來就用原始的
            text += f"（適用期間：{valid_period}）"

        # ✅ NEW：把 channel_groups 攤平到文字裡，讓 RAG 搜得到通路名稱
        channel_groups = s.get("channel_groups") or {}
        channels_flat = []
        if isinstance(channel_groups, dict) and channel_groups:
            group_texts = []
            for group_name, shops in channel_groups.items():
                if isinstance(shops, list):
                    shop_list = "、".join(shops)
                else:
                    shop_list = str(shops)
                group_texts.append(f"{group_name}：{shop_list}")
                # 順便做一個扁平清單，放到 metadata 讓你 debug / 過濾
                if isinstance(shops, list):
                    for shop in shops:
                        channels_flat.append(f"{group_name}-{shop}")
                else:
                    channels_flat.append(f"{group_name}-{shops}")
            text += " 指定通路包含：" + "；".join(group_texts) + "。"
        else:
            channels_flat = []

        # -------- metadata --------
        metadata = {
            "card_family": family,
            "tier": s.get("tier"),
            "reward_type": reward_type,  # ✅ 用偵測出來的 reward_type
            "main_tags": ["benefit_scheme"],
            "channel_tags": [],          # 之後如果要加 channel_tag mapping 也可以在這裡接
            "channels_flat": channels_flat,
            "valid_period": valid_period_str or valid_period,
            "source": s.get("source"),
            "source_file": source_file,
            "source_path": ["benefit_scheme", i],
            "raw": s,
        }

        chunk = {
            "id": make_id(scheme_card_name, "scheme", scheme_name or i),
            "text": text,
            "card_name": scheme_card_name,
            "issuer": issuer,
            "doc_type": s.get("doc_type", "benefit_scheme"),
            "scheme_name": scheme_name,
            "rule_type": None,
            "metadata": metadata,
        }
        chunks.append(chunk)

    return chunks

# 轉換 benefit_rule → chunks（簡化版模板）
def rule_to_chunks(rules: list, card_name: str, issuer: str, source_file: str) -> list:
    chunks = []
    for i, r in enumerate(rules):
        doc_type = r.get("doc_type", "benefit_rule")
        scheme_id = r.get("scheme_id")
        scheme_name = r.get("scheme_name")  # 有些檔案是用 scheme_name
        rule_type = r.get("rule_type")
        family = r.get("card_family") or card_name
        reward_type = detect_reward_type(card_name, family, r)

        # 1) Shopee「回饋分級」專用敘述
        if r.get("rule_type") == "回饋分級" and r.get("rules"):
            rules = r["rules"]
            bank = rules.get("bank_provided", {})
            shopee = rules.get("shopee_provided", {})
            special = rules.get("special_period_bonus", {})

            text = (
                f"{card_name}蝦皮全站回饋分級規則："
                f"銀行端站外一般消費回饋 {bank.get('base_reward', '0.5%')}，"
                f"於蝦皮全站消費可依當月門檻享 {bank.get('tiered', [{}])[0].get('reward', '1%')} "
                f"或 {bank.get('tiered', [{}, {}])[1].get('reward', '2%')} 回饋；"
                f"蝦皮平台另提供非商城 {shopee.get('non_mall', '1%')}、"
                f"商城 {shopee.get('mall', '2%')} 的蝦幣回饋。"
                f"指定活動期間如超級品牌日與 {','.join(special.get('promo_days', []))} 等檔期，"
                f"合計最高回饋可達 {special.get('max_combined_reward', '最高 10%')}。"
            )

        # 2) 世界卡「通用使用規則」專用敘述
        if r.get("rule_type") == "通用使用規則":
            text = (
                f"{card_name}頂級美饌通用使用規則："
                f"{r.get('usage_limit', '')}"
                f"{'；' if r.get('usage_limit') else ''}"
                f"{r.get('service_charge', '')}"
                f"；{r.get('reservation', '')}"
                f"；{r.get('blackout', '')}"
                f"；{r.get('stacking', '')}"
                f"；{r.get('note', '')}"
            )



        channel_group = r.get("channel_group")

        # 1. 粗暴做法：把重要欄位串成文字（你可以慢慢優化）
        text_parts = [f"{card_name}"]
        if scheme_name:
            text_parts.append(f"「{scheme_name}」")
        elif scheme_id:
            text_parts.append(f"（方案ID：{scheme_id}）")
        if rule_type:
            text_parts.append(f"{rule_type}：")

        # 嘗試把常見欄位加入文字
        for key in ["include", "exclude", "conditions", "benefits",
                    "lounges", "sharing_rule", "how_to_use", "offers"]:
            val = r.get(key)
            if val:
                if isinstance(val, list):
                    text_parts.append(f"{key} 包含：" + "；".join(map(str, val)) + "。")
                else:
                    text_parts.append(f"{key}：{val}。")

        # 如果有 tiers / restaurants / rules 這種複雜結構，可以先簡單描述
        if r.get("tiers"):
            text_parts.append("此規則依不同卡別有分級差異。")
        if r.get("restaurants"):
            text_parts.append("此規則適用於多家指定餐廳。")
        if r.get("rules"):
            text_parts.append("詳細回饋與門檻依複雜分級規則計算。")

        text = "".join(text_parts)

        metadata = {
            "card_family": r.get("card_family") or card_name,
            "tier": None,
            "reward_type": reward_type,
            "main_tags": ["benefit_rule"],
            # "channel_tags": [],
            "channel_tags": map_channel_tag(channel_group),
            "valid_period": r.get("valid_period"),
            "source": r.get("source"),
            "source_file": source_file,
            "source_path": ["benefit_rule", i],
            "raw": r
        }

        chunk = {
            "id": make_id(card_name, "rule", scheme_name or scheme_id, f"idx{i}"),
            "text": text,
            "card_name": card_name,
            "issuer": issuer,
            "doc_type": doc_type,
            "scheme_name": scheme_name,
            "rule_type": rule_type,
            "metadata": metadata
        }
        chunks.append(chunk)
    return chunks

# channel_group 自動填 channel_tags
def map_channel_tag(channel_group: str | None) -> list[str]:
    if not channel_group:
        return []
    mapping = {
        # 玩數位
        "數位串流平台": ["digital", "entertainment"],
        "AI工具": ["digital", "software"],
        "網購平台": ["online_shopping"],
        "國際電商": ["online_shopping", "overseas"],

        # 樂饗購
        "國內指定百貨": ["department_store", "shopping_mall"],
        "國內餐飲": ["dining"],
        "國內外送平台": ["dining", "delivery"],
        "國內藥妝": ["drugstore", "beauty"],

        # 趣旅行
        "指定海外消費": ["overseas", "travel", "shopping"],
        "日本指定遊樂園": ["travel", "entertainment", "theme_park"],
        "指定國內外交通": ["transportation", "travel"],
        "指定航空公司": ["airline", "travel"],
        "指定飯店住宿": ["hotel", "travel"],
        "指定旅遊/訂房平台": ["travel", "online_booking"],
        "指定旅行社": ["travel_agency", "travel"],

        # 集精選
        "量販超市": ["grocery", "hypermarket"],
        "指定加油": ["gas"],
        "指定超商": ["convenience_store"],
        "生活家居": ["home", "furniture", "lifestyle"],

        # 蝦皮聯名卡
        "蝦皮購物": ["online_shopping", "platform"]
    }
    return mapping.get(channel_group, [])

def global_rule_to_chunks(global_rules, card_name: str, issuer: str, source_file: str) -> list[dict]:
    """
    將 global_rule 區塊轉成 chunk
    會把像「權益方案切換與生效日」「權益適用期間與方案切換」這種規則寫成一段文字，
    讓 RAG 可以抓到「一天最多切換一次」、「當日零時起生效」這類資訊。
    """
    chunks: list[dict] = []

    # 有些檔案（像 cube_structured.json）裡的 global_rule 會有「list 裡面又包 list」，
    # 這裡先攤平成單一 list
    flat_rules: list[dict] = []
    if isinstance(global_rules, dict):
        flat_rules = [global_rules]
    elif isinstance(global_rules, list):
        for item in global_rules:
            if isinstance(item, list):
                flat_rules.extend(item)
            else:
                flat_rules.append(item)

    for i, r in enumerate(flat_rules):
        if not isinstance(r, dict):
            continue

        doc_type = r.get("doc_type", "global_rule")
        rule_name = r.get("rule_name", "")
        rule_text = r.get("rule_text", "")
        valid_period = r.get("valid_period")
        conditions = r.get("conditions") or {}
        note = r.get("note")

        # ---- 組文字 ----
        # 主幹：卡名 + 規則名稱 + 規則說明
        text_parts = []
        if card_name:
            text_parts.append(f"{card_name}")
        if rule_name:
            text_parts.append(f"「{rule_name}」：")
        text_parts.append(rule_text)

        # 把 conditions 攤成人類好讀的一小段
        # 例如：
        # - 每位正卡持卡人每日最多可變更方案1次
        # - 變更當日零時起之消費依新方案計算回饋
        if isinstance(conditions, dict) and conditions:
            cond_lines = []
            for k, v in conditions.items():
                cond_lines.append(f"{v}")
            if cond_lines:
                text_parts.append(" 條件包含：" + "；".join(cond_lines) + "。")

        # 有效期間
        if valid_period:
            text_parts.append(f"（適用期間：{valid_period}）")

        if note:
            text_parts.append(f" 備註：{note}")

        text = "".join(text_parts)

        metadata = {
            "card_family": card_name,
            "tier": None,
            "reward_type": "other",
            "main_tags": ["global_rule"],
            "channel_tags": [],
            "valid_period": valid_period,
            "source": r.get("source"),
            "source_file": source_file,
            "source_path": ["global_rule", i],
            "raw": r,
        }

        chunk = {
            "id": make_id(card_name, "global_rule", rule_name or f"idx{i}"),
            "text": text,
            "card_name": card_name,
            "issuer": issuer,
            "doc_type": doc_type,
            "scheme_name": None,
            "rule_type": None,
            "metadata": metadata,
        }
        chunks.append(chunk)

    return chunks


# welcome_offer → chunks
def welcome_to_chunks(welcome, card_name: str, issuer: str, source_file: str) -> list:
    """
    welcome 可能是 dict（蝦皮、世界卡）也可能是 list（亞洲萬里通）
    統一轉成 list 處理
    """
    chunks = []
    if isinstance(welcome, dict):
        welcome_list = [welcome]
    else:
        welcome_list = welcome

    for i, w in enumerate(welcome_list):
        offer_name = w.get("offer_name", "新戶禮")
        period = w.get("valid_period")
        conditions = w.get("conditions") or w.get("requirements") or []
        reward = w.get("reward")
        channel_group = w.get("channel_group")

        text_parts = [
            f"{card_name} {offer_name}：",
        ]
        if conditions:
            text_parts.append("達成條件：" + "；".join(conditions) + "。")
        if isinstance(reward, dict):
            text_parts.append("回饋內容：" + "、".join([f"{k}: {v}" for k, v in reward.items()]) + "。")
        elif reward:
            text_parts.append(f"回饋內容：{reward}。")
        if period:
            text_parts.append(f"活動期間：{period}。")

        text = "".join(text_parts)

        metadata = {
            "card_family": w.get("family"),
            "tier": None,
            "reward_type": "mixed",
            "main_tags": ["welcome_offer"],
            "channel_tags": map_channel_tag(channel_group),
            "valid_period": period,
            "source": w.get("source"),
            "source_file": source_file,
            "source_path": ["welcome_offer", i],
            "raw": w
        }

        chunk = {
            "id": make_id(card_name, "welcome", i),
            "text": text,
            "card_name": card_name,
            "issuer": issuer,
            "doc_type": "welcome_offer",
            "scheme_name": None,
            "rule_type": None,
            "metadata": metadata
        }
        chunks.append(chunk)
    return chunks

# 把 4 份 JSON 檔各自轉成 chunk list
def convert_file(path: str) -> list:
    path_obj = Path(path)
    with open(path_obj, "r", encoding="utf-8") as f:
        data = json.load(f)

    source_file = path_obj.name
    chunks = []

    # 情況一：像 shopee.json / worldcard_structured.json（最外層有 card_name）
    if isinstance(data, dict) and "card_name" in data:
        card_name = data.get("card_name")
        issuer = data.get("issuer", "國泰世華銀行")

        profile = data.get("credit_card_profile")
        if isinstance(profile, dict):
            chunks.append(profile_to_chunk(profile, source_file))
        elif isinstance(profile, list):
            for p in profile:
                chunks.append(profile_to_chunk(p, source_file))

        if "benefit_scheme" in data:
            chunks += scheme_to_chunks(data["benefit_scheme"], card_name, issuer, source_file)

        if "benefit_rule" in data:
            chunks += rule_to_chunks(data["benefit_rule"], card_name, issuer, source_file)

        if "welcome_offer" in data:  # shopee / worldcard 是 welcome_offer（單數）
            chunks += welcome_to_chunks(data["welcome_offer"], card_name, issuer, source_file)

                # 🔹 新增：處理 global_rule（像 CUBE 的切換規則、權益分級等）
        if "global_rule" in data:
            chunks += global_rule_to_chunks(data["global_rule"], card_name=card_name, issuer=issuer, source_file=source_file)


    # 情況二：像 colab.json（最外層有 card_family + 多張 card）
    elif isinstance(data, dict) and "credit_card_profile" in data and "card_family" in data:
        issuer = data.get("issuer", "國泰世華銀行")
        card_family = data.get("card_family")

        for p in data["credit_card_profile"]:
            chunks.append(profile_to_chunk(p, source_file))

        if "benefit_scheme" in data:
            chunks += scheme_to_chunks(
                data["benefit_scheme"],
                card_name=card_family,
                issuer=issuer,
                source_file=source_file
            )

        if "benefit_rule" in data:
            chunks += rule_to_chunks(
                data["benefit_rule"],
                card_name=card_family,
                issuer=issuer,
                source_file=source_file
            )

        if "welcome_offer" in data:
            for w in data["welcome_offer"]:
                chunks += welcome_to_chunks(
                    welcome=w,
                    card_name=w.get("card_name", card_family),
                    issuer=issuer,
                    source_file=source_file
                )

        if "global_rule" in data:
            chunks += global_rule_to_chunks(
                data["global_rule"],
                card_name=card_family,
                issuer=issuer,
                source_file=source_file
            )

    # ✅ 情況三：像 cube_structured.json（有 credit_card_profile，但沒有 card_name / card_family）
    elif isinstance(data, dict) and "credit_card_profile" in data:
        profiles = data.get("credit_card_profile") or []
        # CUBE 的 profile 是 list
        if isinstance(profiles, list) and profiles:
            # 用第一個 profile 當共用 card_name / issuer
            first = profiles[0]
            card_name = first.get("card_name", path_obj.stem)
            issuer = first.get("issuer", "國泰世華銀行")

            for p in profiles:
                chunks.append(profile_to_chunk(p, source_file))

            if "benefit_scheme" in data:
                chunks += scheme_to_chunks(data["benefit_scheme"], card_name, issuer, source_file)

            if "benefit_rule" in data:
                chunks += rule_to_chunks(data["benefit_rule"], card_name, issuer, source_file)

            # ⚠ cube_structured.json 的 key 叫 welcome_offers（複數）
            if "welcome_offers" in data:
                chunks += welcome_to_chunks(data["welcome_offers"], card_name, issuer, source_file)

            if "global_rule" in data:
                chunks += global_rule_to_chunks(data["global_rule"], card_name=card_name, issuer=issuer, source_file=source_file)

    return chunks


# 寫成 JSONL 檔案
def main():
    base_dir = "creditcard_json"
    
    input_files = [
        "cube_structured.json",
        "shopee.json",
        "worldcard_structured.json",
        "colab.json"
    ]
    input_paths = [os.path.join(base_dir, f) for f in input_files]

    all_chunks = []
    for path in input_paths:
        file_chunks = convert_file(path)
        print(path, "產生 chunk 數量：", len(file_chunks))
        all_chunks.extend(file_chunks)

    print("總共 chunk 數量：", len(all_chunks))
    
    output_path = os.path.join(os.path.dirname(base_dir), "cards_rag.jsonl")
    
    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()


