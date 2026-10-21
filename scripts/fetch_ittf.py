"""
Автоматический парсер расписания и результатов Чемпионата Азии (Ташкент 2026)
с официального портала ITTF: https://results.ittf.com/ittf-web-results/html/TTE3474/results.html

Почему раньше не обновлялся счёт матчей и как это исправлено:
1. На портале ITTF используется hash-роутинг (#/results/2026-10-21). Открытие базового URL
   показывало только первый день (19 октября). Теперь скрипт явно переходит по маршрутам
   #/results/2026-10-19 ... #/results/2026-10-25 и #/live.
2. В data.json команды и игроки записаны на русском языке с флагами и 3-буквенными кодами
   стран, например: «🇹🇼 Китайский Тайбэй (TPE)», а на сайте ITTF — на английском
   («Chinese Taipei», «Hong Kong, China»). Теперь сопоставление идёт по (разряд, дата+время, стол)
   и по 3-буквенным кодам стран (TPE, HKG, KOR, IND, KAZ и т.д.), а также автоматически
   синхронизируется верхняя сетка плей-офф (brackets: qf, sf, final).
"""
import json
import os
import re
from datetime import datetime, timezone
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

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

COUNTRY_MAP = {
    "CHINA": ("CHN", "🇨🇳 Китай (CHN)"),
    "PEOPLE'S REPUBLIC OF CHINA": ("CHN", "🇨🇳 Китай (CHN)"),
    "JAPAN": ("JPN", "🇯🇵 Япония (JPN)"),
    "REPUBLIC OF KOREA": ("KOR", "🇰🇷 Республика Корея (KOR)"),
    "KOREA": ("KOR", "🇰🇷 Республика Корея (KOR)"),
    "CHINESE TAIPEI": ("TPE", "🇹🇼 Китайский Тайбэй (TPE)"),
    "HONG KONG, CHINA": ("HKG", "🇭🇰 Гонконг, Китай (HKG)"),
    "HONG KONG": ("HKG", "🇭🇰 Гонконг, Китай (HKG)"),
    "INDIA": ("IND", "🇮🇳 Индия (IND)"),
    "SINGAPORE": ("SGP", "🇸🇬 Сингапур (SGP)"),
    "ISLAMIC REP. OF IRAN": ("IRI", "🇮🇷 Иран (IRI)"),
    "IRAN": ("IRI", "🇮🇷 Иран (IRI)"),
    "KAZAKHSTAN": ("KAZ", "🇰🇿 Казахстан (KAZ)"),
    "UZBEKISTAN": ("UZB", "🇺🇿 Узбекистан (UZB)"),
    "THAILAND": ("THA", "🇹🇭 Таиланд (THA)"),
    "MALAYSIA": ("MAS", "🇲🇾 Малайзия (MAS)"),
    "INDONESIA": ("INA", "🇮🇩 Индонезия (INA)"),
    "IRAQ": ("IRQ", "🇮🇶 Ирак (IRQ)"),
    "SAUDI ARABIA": ("KSA", "🇸🇦 Саудовская Аравия (KSA)"),
    "BAHRAIN": ("BRN", "🇧🇭 Бахрейн (BRN)"),
    "JORDAN": ("JOR", "🇯🇴 Иордания (JOR)"),
    "MACAO, CHINA": ("MAC", "🇲🇴 Макао, Китай (MAC)"),
    "MACAO": ("MAC", "🇲🇴 Макао, Китай (MAC)"),
    "PHILIPPINES": ("PHI", "🇵🇭 Филиппины (PHI)"),
    "KYRGYZSTAN": ("KGZ", "🇰🇬 Кыргызстан (KGZ)"),
    "TURKMENISTAN": ("TKM", "🇹🇲 Туркменистан (TKM)"),
    "TAJIKISTAN": ("TJK", "🇹🇯 Таджикистан (TJK)"),
    "SRI LANKA": ("SRI", "🇱🇰 Шри-Ланка (SRI)"),
    "MONGOLIA": ("MGL", "🇲🇳 Монголия (MGL)"),
    "MALDIVES": ("MDV", "🇲🇻 Мальдивы (MDV)"),
    "QATAR": ("QAT", "🇶🇦 Катар (QAT)"),
    "KUWAIT": ("KUW", "🇰🇼 Кувейт (KUW)"),
    "OMAN": ("OMA", "🇴🇲 Оман (OMA)"),
    "UNITED ARAB EMIRATES": ("UAE", "🇦🇪 ОАЭ (UAE)"),
    "BANGLADESH": ("BAN", "🇧🇩 Бангладеш (BAN)"),
    "YEMEN": ("YEM", "🇾🇪 Йемен (YEM)"),
    "DPR KOREA": ("PRK", "🇰🇵 КНДР (PRK)"),
}

FLAG_BY_CODE = {code: label.split(" ")[0] for _, (code, label) in COUNTRY_MAP.items()}

STAGE_RU = [
    ("Round of 128", "1/64 финала (Round of 128"),
    ("Round of 64", "1/32 финала (Round of 64"),
    ("Round of 32", "1/16 финала (Round of 32"),
    ("Round of 16", "1/8 финала (Round of 16"),
    ("Quarterfinals", "1/4 финала"),
    ("Quarter-finals", "1/4 финала"),
    ("Semifinals", "1/2 финала"),
    ("Semi-finals", "1/2 финала"),
    ("Preliminary Round 3", "Предварительный раунд 3"),
    ("Preliminary Round 2", "Предварительный раунд 2"),
    ("Preliminary Round 1", "Предварительный раунд 1"),
    ("Group", "Групповой этап"),
    ("Final", "Финал"),
]


def load_existing():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"updatedAt": "", "brackets": {}, "matches": []}


def detect_event_code(header_line):
    t = (header_line or "").upper()
    if "WOMEN'S TEAMS" in t:
        return "WT"
    if "MEN'S TEAMS" in t:
        return "MT"
    if "WOMEN'S SINGLES" in t:
        return "WS"
    if "MEN'S SINGLES" in t:
        return "MS"
    if "WOMEN'S DOUBLES" in t:
        return "WD"
    if "MEN'S DOUBLES" in t:
        return "MD"
    if "MIXED DOUBLES" in t:
        return "XD"
    return None


def detect_stage_ru(header_line, day_num):
    for eng, ru in STAGE_RU:
        if eng.lower() in (header_line or "").lower():
            if "Round of" in ru:
                return f"{ru} • {day_num} октября)"
            return f"{ru} ({day_num} октября)"
    return f"Матчи ({day_num} октября)"


def resolve_team_code_and_ru(eng_name):
    clean = (eng_name or "").strip()
    upper = clean.upper()
    if upper in COUNTRY_MAP:
        return COUNTRY_MAP[upper]
    for k, val in COUNTRY_MAP.items():
        if k in upper or upper in k:
            return val
    return (upper[:3], clean)


def format_player_or_pair_ru(lines_with_code):
    """Форматирует имя игрока или пары с флагом и кодом страны (например: '🇮🇷 SHAHSAVARI Neda / YARISERAJI Fatemeh (IRI)')."""
    names = []
    code = ""
    for line in lines_with_code:
        m = re.match(r"^(?:WIN\s+)?(.+?)\s+([A-Z]{3})$", line.strip())
        if m:
            names.append(m.group(1).strip())
            code = m.group(2).strip()
        else:
            names.append(line.replace("WIN ", "").strip())
    flag = FLAG_BY_CODE.get(code, "🏓")
    joined = " / ".join(names)
    return code, f"{flag} {joined} ({code})" if code else joined


def parse_match_blocks_from_text(page_text):
    """
    Разбирает текстовое содержимое страницы результатов ITTF на отдельные карточки матчей.
    Поддерживает как командные матчи (Men's Teams / Women's Teams), так и одиночные/парные разряды.
    """
    lines = [ln.strip() for ln in (page_text or "").splitlines() if ln.strip()]
    header_pattern = re.compile(
        r"^(Men's Teams|Women's Teams|Men's Singles|Women's Singles|Men's Doubles|Women's Doubles|Mixed Doubles)\s*-\s*(.+)$",
        re.IGNORECASE,
    )
    time_pattern = re.compile(r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2}),\s*(\d{1,2}:\d{2})$", re.IGNORECASE)
    table_pattern = re.compile(r"^Table\s+(\d+)$", re.IGNORECASE)
    team_score_pattern = re.compile(r"^(.+?)\s+(\d+)\s+(\d+)\s+(.+?)$")

    parsed_matches = []
    i = 0
    n = len(lines)

    while i < n:
        hm = header_pattern.match(lines[i])
        if not hm:
            i += 1
            continue

        header_line = lines[i]
        ev_code = detect_event_code(header_line)
        i += 1

        # Собираем строки до следующего заголовка матча
        block = []
        while i < n and not header_pattern.match(lines[i]):
            block.append(lines[i])
            i += 1

        if not ev_code or not block:
            continue

        day_num = "21"
        time_str = "TBD"
        table_ru = "Олимп. городок"
        content_lines = []

        for bl in block:
            tm = time_pattern.match(bl)
            if tm:
                day_num = tm.group(1).zfill(2)
                time_str = f"{day_num}.10 • {tm.group(2)}"
                continue
            tbm = table_pattern.match(bl)
            if tbm:
                table_ru = f"Стол {tbm.group(1)}"
                continue
            if bl in ("Olympic Town, Tashkent", "Stats >", "Stats", "Official"):
                continue
            content_lines.append(bl)

        stage_ru = detect_stage_ru(header_line, int(day_num))

        # Вариант 1: Командный матч в одну строку: "Chinese Taipei 2 0 Hong Kong, China"
        if ev_code in ("MT", "WT"):
            for cl in content_lines:
                tsm = team_score_pattern.match(cl)
                if tsm:
                    team1_eng, s1, s2, team2_eng = tsm.group(1), int(tsm.group(2)), int(tsm.group(3)), tsm.group(4)
                    code1, ru1 = resolve_team_code_and_ru(team1_eng)
                    code2, ru2 = resolve_team_code_and_ru(team2_eng)
                    done = (s1 >= 3 or s2 >= 3)
                    parsed_matches.append({
                        "ev": ev_code,
                        "header": header_line,
                        "stage": stage_ru,
                        "time": time_str,
                        "table": table_ru,
                        "codeA": code1,
                        "codeB": code2,
                        "a": ru1,
                        "b": ru2,
                        "scoreA": s1,
                        "scoreB": s2,
                        "done": done,
                    })
                    break
            continue

        # Вариант 2: Одиночный или парный матч (игроки + строка очков по партиям, где последнее число — выигранные сеты)
        # Пример:
        # WIN SHAHSAVARI Neda IRI
        # YARISERAJI Fatemeh IRI
        # 8 11 6 11 11 3
        # CHONG Lok Teng MAC
        # LEONG I Nam MAC
        # 11 5 11 2 0 2
        sides = []
        curr_players = []
        has_win_marker = False
        for cl in content_lines:
            if re.match(r"^(?:WIN\s+)?[A-Za-z\s\-'.()]+\s+[A-Z]{3}$", cl):
                if cl.startswith("WIN "):
                    has_win_marker = True
                curr_players.append(cl)
            elif re.match(r"^(?:\d+\s+)*\d+$", cl) and curr_players:
                nums = [int(x) for x in cl.split()]
                games_won = nums[-1] if nums else 0
                sides.append((list(curr_players), games_won))
                curr_players = []
            elif cl.upper() in ("WO", "W/O") and curr_players:
                sides.append((list(curr_players), 0))
                curr_players = []

        if len(sides) == 2:
            (p1_lines, s1), (p2_lines, s2) = sides[0], sides[1]
            code1, ru1 = format_player_or_pair_ru(p1_lines)
            code2, ru2 = format_player_or_pair_ru(p2_lines)
            done = has_win_marker or s1 >= 3 or s2 >= 3
            parsed_matches.append({
                "ev": ev_code,
                "header": header_line,
                "stage": stage_ru,
                "time": time_str,
                "table": table_ru,
                "codeA": code1,
                "codeB": code2,
                "a": ru1,
                "b": ru2,
                "scoreA": s1,
                "scoreB": s2,
                "done": done,
            })

    return parsed_matches


def extract_code(text):
    m = re.search(r"\(([A-Z]{3})\)", text or "")
    return m.group(1) if m else ""


def apply_scraped_matches(payload, scraped_matches):
    matches = payload.get("matches", [])
    brackets = payload.get("brackets", {})
    updated_count = 0

    for sm in scraped_matches:
        ev = sm["ev"]
        time_str = sm["time"]
        table_ru = sm["table"]
        sA, sB = sm["scoreA"], sm["scoreB"]
        done = sm["done"]
        codeA, codeB = sm["codeA"], sm["codeB"]

        # 1. Ищем существующий матч в списке matches:
        # Сначала по точному совпадению (ev, time, table)
        target = None
        for m in matches:
            if m.get("ev") == ev and m.get("time") == time_str and m.get("table") == table_ru:
                target = m
                break

        # Если время или стол изменились, ищем по (ev, коды стран) в той же стадии
        if not target and codeA and codeB:
            stage_prefix = sm["stage"].split("(")[0].strip()
            for m in matches:
                if m.get("ev") != ev or stage_prefix not in m.get("stage", ""):
                    continue
                m_cA = extract_code(m.get("a", ""))
                m_cB = extract_code(m.get("b", ""))
                if {m_cA, m_cB} == {codeA, codeB}:
                    target = m
                    break

        if target:
            m_cA = extract_code(target.get("a", ""))
            m_cB = extract_code(target.get("b", ""))
            # Проверяем, не стоят ли стороны в обратном порядке
            if m_cA == codeB and m_cB == codeA and codeA != codeB:
                final_sA, final_sB = sB, sA
            else:
                final_sA, final_sB = sA, sB
                # Если в target были плейсхолдеры "Победитель...", заменяем на реальные имена
                if "Победитель" in target.get("a", "") or "Сетка" in target.get("a", ""):
                    target["a"] = sm["a"]
                if "Победитель" in target.get("b", "") or "Сетка" in target.get("b", ""):
                    target["b"] = sm["b"]

            live_suffix = " (LIVE)" if (not done and (final_sA > 0 or final_sB > 0)) else ""
            target["score"] = f"{final_sA} : {final_sB}{live_suffix}"
            target["done"] = done
            updated_count += 1
        else:
            # Новый матч, которого ещё не было в списке
            live_suffix = " (LIVE)" if (not done and (sA > 0 or sB > 0)) else ""
            matches.insert(0, {
                "ev": ev,
                "stage": sm["stage"],
                "time": time_str,
                "table": table_ru,
                "a": sm["a"],
                "b": sm["b"],
                "score": f"{sA} : {sB}{live_suffix}",
                "done": done,
            })
            updated_count += 1

        # 2. Если это 1/4 финала, 1/2 финала или Финал — обновляем верхнюю сетку BRACKETS[ev]
        if ev in brackets:
            b_ev = brackets[ev]
            hdr_lower = sm["header"].lower()
            b_list = None
            if "quarterfinal" in hdr_lower:
                b_list = b_ev.get("qf", [])
            elif "semifinal" in hdr_lower:
                b_list = b_ev.get("sf", [])
            elif "final" in hdr_lower and "quarter" not in hdr_lower and "semi" not in hdr_lower:
                b_list = b_ev.get("final", [])

            if b_list:
                time_part = time_str.split("•")[-1].strip()
                for node in b_list:
                    lbl = node.get("label", "")
                    n_cA = extract_code(node.get("a", ""))
                    n_cB = extract_code(node.get("b", ""))
                    matched_node = (
                        (time_part in lbl and table_ru in lbl)
                        or (codeA and codeB and {n_cA, n_cB} == {codeA, codeB})
                    )
                    if matched_node:
                        if n_cA == codeB and n_cB == codeA and codeA != codeB:
                            node["scoreA"] = str(sB)
                            node["scoreB"] = str(sA)
                        else:
                            node["scoreA"] = str(sA)
                            node["scoreB"] = str(sB)
                            if "Победитель" in node.get("a", "") or "Четвертьфинал" in node.get("a", ""):
                                node["a"] = sm["a"]
                            if "Победитель" in node.get("b", "") or "Четвертьфинал" in node.get("b", ""):
                                node["b"] = sm["b"]
                        break

    return updated_count


def scrape_all_days_with_playwright():
    all_scraped = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Обходим дни с 20 по 25 октября + вкладку #/live
        routes = [f"#/results/{d}" for d in TOURNAMENT_DATES[1:]] + ["#/live"]
        for route in routes:
            url = f"{ITTF_HTML_URL}{route}"
            try:
                page.goto(url, wait_until="networkidle", timeout=45000)
                page.wait_for_timeout(2500)
                body_text = page.evaluate("() => document.body.innerText")
                parsed = parse_match_blocks_from_text(body_text)
                all_scraped.extend(parsed)
            except Exception as e:
                print(f"Warning on route {route}: {e}")

        browser.close()
    return all_scraped


def main():
    payload = load_existing()
    scraped_matches = scrape_all_days_with_playwright()
    updated_count = apply_scraped_matches(payload, scraped_matches)

    payload["updatedAt"] = datetime.now(timezone.utc).isoformat()
    payload["lastScrapedMatchesCount"] = len(scraped_matches)
    payload["lastUpdatedMatchesCount"] = updated_count

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(
        f"Updated {DATA_FILE} at {payload['updatedAt']} "
        f"(scraped: {len(scraped_matches)}, updated: {updated_count}, total: {len(payload.get('matches', []))})"
    )


if __name__ == "__main__":
    main()
