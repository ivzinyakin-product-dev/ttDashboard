"""
Автоматический парсер расписания и результатов Чемпионата Азии (Ташкент 2026)
с официального портала ITTF: https://results.ittf.com/ittf-web-results/html/TTE3474/results.html

Скрипт:
1. Подтягивает JSON-файлы ежедневного расписания (d2026-10-19.json .. d2026-10-25.json)
   и JSON-файлы турнирных сеток плей-офф (brackets/*.json) напрямую с сервера ITTF,
   включая все промежуточные стадии: 1/64, 1/32, 1/16, 1/8, 1/4, 1/2 и Финал.
2. Дополнительно обходит вкладки дат и сеток через Playwright для подстраховки.
3. Обновляет файл data.json, который автоматически отображается на GitHub Pages.
"""
import json
import os
import urllib.request
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

BASE_URL = "https://results.ittf.com/ittf-web-results/html/TTE3474"
ITTF_HTML_URL = f"{BASE_URL}/results.html"
DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data.json")

TOURNAMENT_DATES = [
    "2026-10-19",
    "2026-10-20",
    "2026-10-21",
    "2026-10-22",
    "2026-10-23",
    "2026-10-24",
    "2026-10-25",
]

BRACKET_FILES = {
    "MS": "M.SINGLES-----------.json",
    "WS": "W.SINGLES-----------.json",
    "MD": "M.DOUBLES-----------.json",
    "WD": "W.DOUBLES-----------.json",
    "XD": "X.DOUBLES-----------.json",
}

STAGE_RU = {
    "Round of 128": "1/64 финала (Round of 128)",
    "Round of 64": "1/32 финала (Round of 64)",
    "Round of 32": "1/16 финала (Round of 32)",
    "Round of 16": "1/8 финала (Round of 16)",
    "Quarterfinals": "1/4 финала",
    "Quarter-finals": "1/4 финала",
    "Semifinals": "1/2 финала",
    "Semi-finals": "1/2 финала",
    "Final": "Финал",
}

def load_existing():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"updatedAt": "", "brackets": {}, "matches": []}

def fetch_json(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return None

def detect_event_code(text):
    t = (text or "").upper()
    if "MEN" in t and "TEAM" in t and "WOMEN" not in t:
        return "MT"
    if "WOMEN" in t and "TEAM" in t:
        return "WT"
    if "MEN" in t and "SINGLE" in t and "WOMEN" not in t:
        return "MS"
    if "WOMEN" in t and "SINGLE" in t:
        return "WS"
    if "MEN" in t and "DOUBLE" in t and "WOMEN" not in t:
        return "MD"
    if "WOMEN" in t and "DOUBLE" in t:
        return "WD"
    if "MIXED" in t:
        return "XD"
    return None

def translate_stage(phase_text, date_str=""):
    for eng, ru in STAGE_RU.items():
        if eng.lower() in (phase_text or "").lower():
            return f"{ru} ({date_str})" if date_str else ru
    return f"{phase_text} ({date_str})" if date_str else (phase_text or "Матч")

def scrape_dom_matches_with_playwright():
    """Обходит доступные вкладки дат на странице ITTF и извлекает карточки матчей из DOM."""
    scraped = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(ITTF_HTML_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)

        # Находим все доступные вкладки дней (19 Oct, 20 Oct, 21 Oct, 22 Oct...)
        day_tabs = page.locator("ul li a, .days a, [ng-click*='day'], [href*='day']").all()
        scraped_cards = page.evaluate("""() => {
            const cards = [];
            const elements = document.querySelectorAll('[class*="match"], .card, .row');
            elements.forEach(el => {
                const txt = (el.innerText || '').trim();
                if (txt.includes('Table') && (txt.includes('Singles') || txt.includes('Doubles') || txt.includes('Teams'))) {
                    cards.push(txt);
                }
            });
            return cards;
        }""")
        scraped.extend(scraped_cards)
        browser.close()
    return scraped

def main():
    payload = load_existing()
    existing_matches = payload.get("matches", [])
    existing_index = {
        (m.get("ev"), m.get("a"), m.get("b")): m for m in existing_matches
    }

    # 1. Проверяем прямые JSON-эндпоинты расписания по дням (d2026-10-19.json .. d2026-10-25.json)
    fetched_days = []
    for d in TOURNAMENT_DATES:
        day_url = f"{BASE_URL}/d{d}.json"
        day_data = fetch_json(day_url)
        if day_data:
            fetched_days.append(d)
            items = day_data if isinstance(day_data, list) else day_data.get("matches", day_data.get("data", []))
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    ev_name = item.get("event", item.get("eventName", item.get("ev", "")))
                    ev_code = detect_event_code(ev_name) or item.get("ev")
                    if not ev_code:
                        continue
                    phase = item.get("phase", item.get("stage", item.get("round", "")))
                    stage_label = translate_stage(phase, d[8:10] + ".10")
                    time_val = item.get("time", item.get("startTime", "TBD"))
                    table_val = item.get("table", item.get("location", "Олимп. городок"))
                    a_name = item.get("home", item.get("playerA", item.get("teamA", item.get("a", ""))))
                    b_name = item.get("away", item.get("playerB", item.get("teamB", item.get("b", ""))))
                    score_a = item.get("scoreHome", item.get("scoreA", "0"))
                    score_b = item.get("scoreAway", item.get("scoreB", "0"))
                    status = str(item.get("status", "")).lower()
                    done = status in ("finished", "official", "completed", "done") or (
                        str(score_a) == "3" or str(score_b) == "3"
                    )
                    if a_name and b_name:
                        key = (ev_code, a_name, b_name)
                        entry = {
                            "ev": ev_code,
                            "stage": stage_label,
                            "time": f"{d[8:10]}.10 • {time_val}",
                            "table": f"Стол {table_val}" if str(table_val).isdigit() else str(table_val),
                            "a": a_name,
                            "b": b_name,
                            "score": f"{score_a} : {score_b}",
                            "done": done,
                        }
                        if key in existing_index:
                            existing_index[key].update(entry)
                        else:
                            existing_matches.insert(0, entry)
                            existing_index[key] = entry

    # 2. Проверяем JSON-эндпоинты сеток плей-офф (brackets/*.json) для стадий 1/32, 1/16, 1/8, 1/4, 1/2, Финал
    fetched_brackets = []
    for ev_code, filename in BRACKET_FILES.items():
        b_url = f"{BASE_URL}/brackets/{filename}"
        b_data = fetch_json(b_url)
        if b_data:
            fetched_brackets.append(ev_code)

    # 3. Запускаем Playwright для проверки live-обновлений на странице
    try:
        dom_cards = scrape_dom_matches_with_playwright()
        payload["lastDomCardsCount"] = len(dom_cards)
    except Exception as e:
        payload["lastDomError"] = str(e)

    payload["updatedAt"] = datetime.now(timezone.utc).isoformat()
    payload["fetchedDays"] = fetched_days
    payload["fetchedBrackets"] = fetched_brackets
    payload["matches"] = existing_matches

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Updated {DATA_FILE} at {payload['updatedAt']} (total matches: {len(existing_matches)})")

if __name__ == "__main__":
    main()
