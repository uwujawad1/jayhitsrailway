import sys
import json
import os
import re

sys.path.insert(0, os.path.dirname(__file__))

from tools import cc_gen, checkLuhn
import requests


def generate_cards(bin_code, amount=10, month="xx", year="xx", cvv="xxx"):
    clean_bin = bin_code.replace("x", "")
    if not (6 <= len(clean_bin) <= 16):
        return {"error": "Invalid BIN format. Provide 6-16 digits."}

    amount = min(max(int(amount), 1), 100)

    try:
        req = requests.get(f"https://bins.antipublic.cc/bins/{clean_bin[:6]}", timeout=5).json()
        bin_info = {
            "brand": req.get("brand", "------"),
            "country": req.get("country", "------"),
            "flag": req.get("flag", ""),
            "bank": req.get("bank", "------"),
            "level": req.get("level", "------"),
            "type": req.get("type", "------"),
        }
    except Exception:
        bin_info = {"brand": "------", "country": "------", "flag": "", "bank": "------", "level": "------", "type": "------"}

    cards = cc_gen(bin_code, amount, month, year, cvv)
    return {"cards": cards, "bin_info": bin_info, "count": len(cards)}


def _lookup_bin(bin6):
    try:
        req = requests.get(f"https://bins.antipublic.cc/bins/{bin6}", timeout=5).json()
        country_name = req.get("country_name", "") or req.get("country", "Unknown")
        flag = req.get("country_flag", "") or req.get("flag", "")
        return {
            "country": country_name.title() if country_name.isupper() and len(country_name) > 2 else country_name,
            "country_code": req.get("country", ""),
            "flag": flag,
            "bank": req.get("bank", "Unknown"),
            "brand": req.get("brand", "Unknown"),
            "type": req.get("type", "Unknown"),
            "level": req.get("level", "Unknown"),
        }
    except Exception:
        return {"country": "Unknown", "country_code": "", "flag": "", "bank": "Unknown", "brand": "Unknown", "type": "Unknown", "level": "Unknown"}


def filter_cards(cards_text):
    cc_re = re.compile(r"^(\d{12,19})[|/;:,\s]+(\d{1,2})[|/;:,\s]+(\d{2,4})[|/;:,\s]+(\d{3,4})")
    cards = []
    by_bin = {}
    by_type = {}

    for line in cards_text.strip().splitlines():
        m = cc_re.match(line.strip())
        if m:
            cc_num, mm, yy, cvv_val = m.group(1), m.group(2).zfill(2), m.group(3), m.group(4)
            if len(yy) == 4:
                yy = yy[2:]
            card_str = f"{cc_num}|{mm}|{yy}|{cvv_val}"
            cards.append(card_str)
            b6 = cc_num[:6]
            by_bin.setdefault(b6, []).append(card_str)
            brand = _detect_brand(cc_num)
            by_type.setdefault(brand, []).append(card_str)

    bin_summary = {k: len(v) for k, v in sorted(by_bin.items(), key=lambda x: -len(x[1]))}
    type_summary = {k: len(v) for k, v in sorted(by_type.items(), key=lambda x: -len(x[1]))}

    bin_info = {}
    by_country = {}
    unique_bins = list(by_bin.keys())
    for b6 in unique_bins[:50]:
        info = _lookup_bin(b6)
        bin_info[b6] = info
        country = info.get("country", "Unknown")
        if country:
            by_country.setdefault(country, []).extend(by_bin[b6])
    for b6 in unique_bins[50:]:
        bin_info[b6] = {"country": "Unknown", "country_code": "", "flag": "", "bank": "Unknown", "brand": "Unknown", "type": "Unknown", "level": "Unknown"}
        by_country.setdefault("Unknown", []).extend(by_bin[b6])

    country_summary = {k: len(v) for k, v in sorted(by_country.items(), key=lambda x: -len(x[1]))}

    return {
        "total": len(cards),
        "unique_bins": len(by_bin),
        "by_bin": bin_summary,
        "by_type": type_summary,
        "by_country": country_summary,
        "cards": cards,
        "bins": {k: v for k, v in by_bin.items()},
        "types": {k: v for k, v in by_type.items()},
        "countries": by_country,
        "bin_info": bin_info,
    }


def _detect_brand(cc):
    if cc.startswith("4"):
        return "Visa"
    elif cc[:2] in ["51", "52", "53", "54", "55"] or (2221 <= int(cc[:4]) <= 2720):
        return "Mastercard"
    elif cc[:2] in ["34", "37"]:
        return "Amex"
    elif cc[:4] in ["6011"] or cc[:2] == "65" or cc[:6][:3] in ["644", "645", "646", "647", "648", "649"]:
        return "Discover"
    elif cc[:4] in ["3528", "3529"] or cc[:2] in ["35"]:
        return "JCB"
    else:
        return "Other"


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""

    if action == "gen":
        bin_code = sys.argv[2] if len(sys.argv) > 2 else ""
        amount = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        month = sys.argv[4] if len(sys.argv) > 4 else "xx"
        year = sys.argv[5] if len(sys.argv) > 5 else "xx"
        cvv = sys.argv[6] if len(sys.argv) > 6 else "xxx"
        result = generate_cards(bin_code, amount, month, year, cvv)
        print(json.dumps(result))

    elif action == "filter":
        cards_text = sys.stdin.read()
        result = filter_cards(cards_text)
        print(json.dumps(result))

    else:
        print(json.dumps({"error": "Unknown action. Use: gen, filter"}))
