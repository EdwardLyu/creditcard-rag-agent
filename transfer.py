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


# 轉換 credit_card_profile → chunk
def profile_to_chunk(profile: dict, source_file: str) -> dict:
    card_name = profile.get("card_name", "")
    issuer = profile.get("issuer", "")
    doc_type = profile.get("doc_type", "credit_card_profile")

    # ===== 1) 年費字串 =====
    annual_fee = profile.get("annual_fee")
    annual_fee_waiver = profile.get("annual_fee_waiver")  # raw 裡常有

    if isinstance(annual_fee, dict):
        annual_fee_str = f"正卡年費 {annual_fee.get('primary', '')}，附卡{annual_fee.get('supplementary', '')}。"
        waiver = annual_fee.get("waiver") or annual_fee_waiver
        if waiver:
            annual_fee_str += f"年費減免條件：{waiver}。"
    else:
        if annual_fee:
            annual_fee_str = f"{annual_fee}。"
            if annual_fee_waiver:
                annual_fee_str += f"年費減免條件：{annual_fee_waiver}。"
        else:
            annual_fee_str = "年費依銀行公告。"

    # ===== 2) 申辦資格 =====
    eligibility = profile.get("eligibility") or {}
    income_req = eligibility.get("income_requirement") or profile.get("income_requirement", "")
    age = eligibility.get("age", "")
    employment = eligibility.get("employment", "")

    conds = [age, employment, income_req]
    clean_conds = []
    for c in conds:
        if not c:
            continue
        clean_conds.append(str(c).rstrip("。"))

    # ===== 3) 其他 raw 資訊（你想補進 text 的重點）=====
    base_reward = profile.get("base_reward")  # 回饋概述
    reward_unit = profile.get("reward_unit")
    reward_type_raw = profile.get("reward_type")  # 例：點數回饋/哩程/現金回饋

    interest_and_fees = profile.get("interest_and_fees") or {}
    revolving_rate = interest_and_fees.get("revolving_rate")
    cash_advance_fee = interest_and_fees.get("cash_advance_fee")

    supp_card_info = profile.get("supp_card_info")
    best_for = profile.get("best_for") or []
    segments = profile.get("target_users") or profile.get("user_segments") or []

    positioning = profile.get("positioning")

    # ===== 4) 組 text =====
    text_parts = [f"{issuer}發行的「{card_name}」基本資料：", annual_fee_str]

    if clean_conds:
        text_parts.append("申辦資格包含：" + "、".join(clean_conds) + "。")

    # 回饋摘要
    if base_reward:
        if reward_unit:
            text_parts.append(f"回饋概述：{base_reward}（回饋單位：{reward_unit}）。")
        else:
            text_parts.append(f"回饋概述：{base_reward}。")

    # raw reward_type（點數/哩程/現金回饋）也可以補一句
    if reward_type_raw:
        text_parts.append(f"回饋類型：{reward_type_raw}。")

    # 利率/手續費
    fee_parts = []
    if revolving_rate:
        fee_parts.append(f"循環利率：{revolving_rate}")
    if cash_advance_fee:
        fee_parts.append(f"預借現金手續費：{cash_advance_fee}")
    if fee_parts:
        text_parts.append("費用資訊：" + "；".join(fee_parts) + "。")

    if supp_card_info:
        text_parts.append(f"附卡資訊：{supp_card_info.rstrip('。')}。")

    if segments:
        text_parts.append("適合族群例如：" + "；".join(map(str, segments)) + "。")

    if best_for:
        text_parts.append("適用情境：" + "；".join(map(str, best_for)) + "。")

    if positioning:
        text_parts.append(f"卡片定位：{positioning.rstrip('。')}。")

    text = "".join(text_parts)


    metadata = {
        "card_family": profile.get("family") or profile.get("card_family") or card_name,
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
        text_parts = [f"{scheme_card_name}權益方案「{scheme_name}」：{surface_desc}"]

        if valid_period_str:
            text_parts.append(f"（適用期間：{valid_period_str}）")
        elif valid_period:
            text_parts.append(f"（適用期間：{valid_period}）")

        # ✅ NEW：把 reward_levels 寫進 text（RAG 很常靠這段回答）
        reward_levels = s.get("reward_levels")
        if isinstance(reward_levels, dict) and reward_levels:
            # 例：L1 2%、L2 3%、L3 3.3%
            lv_text = "、".join([f"{k} {v}%" for k, v in reward_levels.items()])
            text_parts.append(f"回饋分級：{lv_text}。")

        # ✅ NEW：把 channel_groups 攤平到文字裡
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

                if isinstance(shops, list):
                    for shop in shops:
                        channels_flat.append(f"{group_name}-{shop}")
                else:
                    channels_flat.append(f"{group_name}-{shops}")

            text_parts.append("指定通路包含：" + "；".join(group_texts) + "。")
        else:
            channels_flat = []

        # ✅ NEW：把 notes 補進 text（notes 可能是字串或 list）
        notes = s.get("notes")
        if notes:
            if isinstance(notes, list):
                notes_str = "；".join([str(x).rstrip("。") for x in notes if x])
            else:
                notes_str = str(notes).rstrip("。")
            if notes_str:
                text_parts.append(f"注意事項：{notes_str}。")

        text = "".join(text_parts)

        # -------- metadata --------
        metadata = {
            "card_family": family,
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
            "metadata": metadata,
        }
        chunks.append(chunk)

    return chunks

# 轉換 benefit_rule → chunks（簡化版模板）
def flatten_to_text(data, prefix="", bullet="；", level=0):
    """
    把任意結構(dict/list/primitive)遞迴展開成可讀字串。
    - dict: key：value
    - list: 用 bullet 串起來
    """
    if data is None:
        return ""

    # 基本型別
    if isinstance(data, (str, int, float, bool)):
        return str(data)

    # list
    if isinstance(data, list):
        parts = []
        for item in data:
            item_txt = flatten_to_text(item, prefix=prefix, bullet=bullet, level=level + 1)
            if item_txt:
                parts.append(item_txt)
        return bullet.join(parts)

    # dict
    if isinstance(data, dict):
        parts = []
        for k, v in data.items():
            v_txt = flatten_to_text(v, prefix=prefix, bullet=bullet, level=level + 1)
            if v_txt == "":
                continue
            # dict value 若本身很長，可以用 "k：v"；若是巢狀 dict/list 也照樣串起來
            parts.append(f"{k}：{v_txt}")
        return bullet.join(parts)

    # 其他型別（保底）
    return str(data)

def strip_keys(data, exclude_keys: set):
    """
    遞迴移除 dict 中指定 key；list 會逐項處理；其他型別原樣回傳。
    會把巢狀結構裡同名 key 也一併移除。
    """
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if k in exclude_keys:
                continue
            out[k] = strip_keys(v, exclude_keys)
        return out
    if isinstance(data, list):
        return [strip_keys(x, exclude_keys) for x in data]
    return data


def rule_to_chunks(rules: list, card_name: str, issuer: str, source_file: str) -> list:
    chunks = []

    EXCLUDE_FROM_TEXT = {
        "doc_type", "card_name", "scheme_id", "rule_type",
        "source", "card_family", "issuer", "bank", "family"
    }

    for i, r in enumerate(rules):
        doc_type = r.get("doc_type", "benefit_rule")
        scheme_id = r.get("scheme_id")
        scheme_name = r.get("scheme_name")  # 有些檔案是用 scheme_name
        rule_type = r.get("rule_type")
        channel_group = r.get("channel_group")

        # --- 先做一個 header（與你 .jsonl 格式接近）---
        header_parts = [f"{card_name}"]
        if card_name != "國泰CUBE卡":
            header_parts.append(f"{rule_type}：")

        header = "".join(header_parts)

        # --- 特例敘述（可選）：做成「附加描述」而不是覆蓋 text ---
        special_desc = ""

        # 1) Shopee「回饋分級」專用敘述（避免覆蓋外層 rules 變數）
        if r.get("rule_type") == "回饋分級" and isinstance(r.get("rules"), dict):
            rules_obj = r["rules"]
            bank = rules_obj.get("bank_provided", {}) if isinstance(rules_obj.get("bank_provided"), dict) else {}
            shopee = rules_obj.get("shopee_provided", {}) if isinstance(rules_obj.get("shopee_provided"), dict) else {}
            special = rules_obj.get("special_period_bonus", {}) if isinstance(rules_obj.get("special_period_bonus"), dict) else {}

            tiered = bank.get("tiered", [])
            tier1 = tiered[0].get("reward") if len(tiered) > 0 and isinstance(tiered[0], dict) else None
            tier2 = tiered[1].get("reward") if len(tiered) > 1 and isinstance(tiered[1], dict) else None

            promo_days = special.get("promo_days", [])
            promo_days_txt = "、".join(promo_days) if isinstance(promo_days, list) and promo_days else ""

            special_desc = (
                f"蝦皮全站回饋分級摘要："
                f"銀行端站外一般消費回饋 {bank.get('base_reward', '0.5%')}，"
                f"蝦皮全站依門檻可能為 {tier1 or '—'} / {tier2 or '—'}；"
                f"平台端蝦幣：非商城 {shopee.get('non_mall', '—')}、商城 {shopee.get('mall', '—')}。"
            )
            if promo_days_txt or special.get("max_combined_reward"):
                special_desc += (
                    f"活動檔期（如超級品牌日"
                    f"{('、' + promo_days_txt) if promo_days_txt else ''}）"
                    f"合計最高回饋可達 {special.get('max_combined_reward', '—')}。"
                )

        # 2) 世界卡「通用使用規則」專用敘述
        if r.get("rule_type") == "通用使用規則":
            special_desc = (
                f"通用使用規則摘要："
                f"{r.get('usage_limit', '')}"
                f"{'；' if r.get('usage_limit') else ''}"
                f"{r.get('service_charge', '')}"
                f"{('；' + r.get('reservation')) if r.get('reservation') else ''}"
                f"{('；' + r.get('blackout')) if r.get('blackout') else ''}"
                f"{('；' + r.get('stacking')) if r.get('stacking') else ''}"
                f"{('；' + r.get('note')) if r.get('note') else ''}"
            ).strip("；")

        # --- 把「raw」展開塞進 text ---
        r_for_text = strip_keys(r, EXCLUDE_FROM_TEXT)
        raw_all_text = flatten_to_text(r_for_text)

        # --- 組合最終 text：header + special + raw 全展開 ---
        text_parts = [header]
        if special_desc:
            text_parts.append(special_desc)
        # raw 全資訊
        if raw_all_text:
            text_parts.append(f"{raw_all_text}")

        text = " ".join([p for p in text_parts if p])

        metadata = {
            "card_family": r.get("card_family") or card_name,
            "valid_period": r.get("valid_period"),
            "source": r.get("source"),
            "source_file": source_file,
            "source_path": ["benefit_rule", i],
            "raw": r,
        }

        chunk = {
            "id": make_id(card_name, "rule", scheme_name or scheme_id, f"idx{i}"),
            "text": text,
            "card_name": card_name,
            "issuer": issuer,
            "doc_type": doc_type,
            "scheme_name": (scheme_name if card_name == "國泰CUBE卡" else rule_type),
            "metadata": metadata,
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
    將 global_rule 區塊轉成 chunk，並「保證」把 raw(r) 裡所有資訊都加進 text。
    做法：正常人類可讀敘述 + raw 全展開（含巢狀 dict/list）
    """
    chunks: list[dict] = []

    # 攤平成單一 list
    flat_rules: list[dict] = []
    if isinstance(global_rules, dict):
        flat_rules = [global_rules]
    elif isinstance(global_rules, list):
        for item in global_rules:
            if isinstance(item, list):
                flat_rules.extend([x for x in item if isinstance(x, dict)])
            elif isinstance(item, dict):
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

        # ---- 人類可讀主敘述 ----
        text_parts = []
        if card_name:
            text_parts.append(f"{card_name}")
        if rule_name:
            text_parts.append(f"「{rule_name}」：")
        if rule_text:
            text_parts.append(rule_text)

        # conditions（保留你原本的易讀摘要）
        if isinstance(conditions, dict) and conditions:
            cond_lines = []
            for _, v in conditions.items():
                if v is not None and v != "":
                    cond_lines.append(str(v))
            if cond_lines:
                text_parts.append(" 條件包含：" + "；".join(cond_lines) + "。")

        if valid_period:
            text_parts.append(f"（適用期間：{valid_period}）")
        if note:
            text_parts.append(f" 備註：{note}")

        # ---- 關鍵：raw 全資訊展開，確保不漏欄位 ----
        # 這裡直接展開 r（也就是你 metadata.raw 會存的那包）
        raw_all = flatten_to_text(r)
        # raw展開
        if raw_all:
            text_parts.append(f"{raw_all}")

        text = "".join(text_parts)

        metadata = {
            "card_family": card_name,
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
            "metadata": metadata,
        }
        chunks.append(chunk)

    return chunks


# welcome_offer → chunks
def welcome_to_chunks(welcome, card_name: str, issuer: str, source_file: str) -> list:
    """
    welcome 可能是 dict（蝦皮、世界卡、CUBE）也可能是 list（亞洲萬里通）
    統一轉成 list 處理
    並「保證」把 raw(w) 內所有資訊都加進 text（raw展開）
    """
    chunks = []
    welcome_list = [welcome] if isinstance(welcome, dict) else (welcome or [])

    for i, w in enumerate(welcome_list):
        if not isinstance(w, dict):
            continue

        offer_name = w.get("offer_name", "新戶禮")
        period = w.get("valid_period")
        # 四張卡片出現過的欄位：conditions / requirements / tasks
        conditions = w.get("conditions") or w.get("requirements") or []
        tasks = w.get("tasks") or []
        reward = w.get("reward") or w.get("max_reward")
        channel_group = w.get("channel_group")
        note = w.get("note")

        text_parts = [f"{card_name} {offer_name}："]

        # conditions / requirements（字串陣列）
        if isinstance(conditions, list) and conditions:
            text_parts.append("達成條件：" + "；".join(map(str, conditions)) + "。")

        # tasks（像 CUBE 那種任務制）
        if isinstance(tasks, list) and tasks:
            task_lines = []
            for t in tasks:
                if isinstance(t, dict):
                    tn = t.get("task_name")
                    desc = t.get("description")
                    tr = t.get("reward")
                    # 任務一：...；回饋...
                    line = " ".join([x for x in [
                        f"{tn}" if tn else "",
                        f"{desc}" if desc else "",
                        f"回饋：{tr}" if tr else ""
                    ] if x])
                    if line:
                        task_lines.append(line)
                else:
                    task_lines.append(str(t))
            if task_lines:
                text_parts.append("任務/門檻：" + "；".join(task_lines) + "。")

        # reward（可能是 dict 或字串）
        if isinstance(reward, dict) and reward:
            text_parts.append("回饋內容：" + "、".join([f"{k}: {v}" for k, v in reward.items()]) + "。")
        elif reward:
            text_parts.append(f"回饋內容：{reward}。")

        if period:
            text_parts.append(f"活動期間：{period}。")

        if note:
            text_parts.append(f"備註：{note}")

        # ---- 關鍵：把 raw(w) 全展開加進 text，確保不漏欄位 ----
        raw_all = flatten_to_text(w)
        # raw展開
        if raw_all:
            text_parts.append(f"{raw_all}")

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
            "raw": w,
        }

        chunk = {
            "id": make_id(card_name, "welcome", i),
            "text": text,
            "card_name": card_name,
            "issuer": issuer,
            "doc_type": "welcome_offer",
            "scheme_name": None,
            "metadata": metadata,
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

        if "welcome_offer" in data:
            chunks += welcome_to_chunks(data["welcome_offer"], card_name, issuer, source_file)

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
        profiles = data.get("credit_card_profile")

        if isinstance(profiles, dict):
            profiles = [profiles]

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


