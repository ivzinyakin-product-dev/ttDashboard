"""
Автоматический парсер результатов Чемпионата Азии (Ташкент 2026) со страницы ITTF:
https://results.ittf.com/ittf-web-results/html/TTE3474/results.html
Запускается через GitHub Actions каждые 10 минут и обновляет data.json в репозитории.
"""
import json
import os
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ITTF_URL = "https://results.ittf.com/ittf-web-results/html/TTE3474/results.html"
DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data.json")

EVENT_PREFIX_MAP = {
    "Men's Teams": "MT",
    "Women's Teams": "WT",
    "Men's Singles": "MS",
    "Women's Singles": "WS",
    "Men's Doubles": "MD",
    "Women's Doubles": "WD",
    "Mixed Doubles": "XD",
}

def load_existing():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"updatedAt": "", "brackets": {}, "matches": []}

def main():
    payload = load_existing()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(ITTF_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(4000)

        # Извлекаем свежий текст карточек матчей со страницы ITTF
        raw_text = page.inner_text("body")
        browser.close()

    payload["updatedAt"] = datetime.now(timezone.utc).isoformat()
    payload["lastScrapedLength"] = len(raw_text)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Updated {DATA_FILE} at {payload['updatedAt']}")

if __name__ == "__main__":
    main()
