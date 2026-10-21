"""
Автоматический парсер расписания и результатов Чемпионата Азии (Ташкент 2026)
с официального портала ITTF: https://results.ittf.com/ittf-web-results/html/TTE3474/results.html

Ключевые исправления для командных разрядов (MT и WT):
1. Нормализация табуляций (\t): в DOM портала ITTF карточки командных матчей склеивают
   заголовок и город ("Men's Teams - Quarterfinals - Match 2\tOlympic Town, Tashkent"),
   время и стол ("Wed 21, 10:00\tTable 1"), а также команды и счёт ("Chinese Taipei\t3\t0\tHong Kong, China")
   через символ табуляции \t. Теперь скрипт разбивает \t на отдельные строки перед разбором.
2. Привязка сетки плей-офф (1/4 и 1/2 финала) строго по номеру матча ("Quarterfinals - Match 1..4" -> qf[0..3],
   "Semifinals - Match 1..2" -> sf[0..1]), а не только по номеру стола (так как Match 1 и Match 4 или Match 2 и Match 3
   часто меняются столами).
3. Принудительное обновление участников матча (a и b) по данным протокола ITTF даже в том случае,
   если в data.json ранее стояла другая пара команд после предварительной жеребьёвки.
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
    ("Preliminary Round 3", "Предварительный раунд 3 — за выход в 1/4 финала"),
    ("Preliminary Round 2", "Предварительный раунд 2"),
    ("Preliminary Round 1", "Предварительный раунд 1"),
    ("Positional 5-8", "Матчи за 5–8 места"),
    ("Positions 5-8", "Матчи за 5–8 места"),
    ("Position 5-8", "Матчи за 5–8 места"),
    ("Positional 9-12", "Матчи за 9–12 места"),
    ("Positions 9-12", "Матчи за 9–12 места"),
    ("Positional 13-16", "Матчи за 13–16 места"),
    ("Positions 13-16", "Матчи за 13–16 места"),
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


def extract_match_number(header_line):
    """Извлекает номер матча из заголовка, например 'Men's Teams - Quarterfinals - Match 2' -> 2."""
    m = re.search(r"Match\s+(\d+)", header_line or "", flags=re.IGNORECASE)
    return int(m.group(1)) if m else None


def resolve_team_code_and_ru(eng_name):
    clean = re.sub(r"^WIN\s+", "", (eng_name or "").strip(), flags=re.IGNORECASE).strip()
    upper = clean.upper()
    if upper in COUNTRY_MAP:
        return COUNTRY_MAP[upper]
    for k, val in COUNTRY_MAP.items():
        if k in upper or upper in k:
            return val
    return (upper[:3], clean)


def format_player_or_pair_ru(lines_with_code):
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


def parse_team_content_lines(content_lines):
    """
    Разбирает строки командного матча как в многострочном формате:
        Chinese Taipei
        3
        0
        Hong Kong, China
    так и в однострочном формате (включая табуляции):
        Chinese Taipei 3 0 Hong Kong, China
    """
    cleaned = [
        re.sub(r"^WIN\s+", "", ln, flags=re.IGNORECASE).strip()
        for ln in content_lines
        if ln.strip() and ln.strip() not in ("WIN", "Official", "Stats", "Stats >", "v", "⌄", "›")
    ]
    if not cleaned:
        return None

    # Вариант А: Многострочный формат (команда 1, счёт 1, счёт 2, команда 2 в первых 4 строках)
    if len(cleaned) >= 4 and cleaned[1].isdigit() and cleaned[2].isdigit():
        t1, s1, s2, t2 = cleaned[0], int(cleaned[1]), int(cleaned[2]), cleaned[3]
        return t1, s1, s2, t2

    # Вариант Б: Команда 1 на первой строке, "3 0" на второй, Команда 2 на третьей
    if len(cleaned) >= 3 and re.match(r"^\d+\s+\d+$", cleaned[1]):
        parts = cleaned[1].split()
        return cleaned[0], int(parts[0]), int(parts[1]), cleaned[2]

    # Вариант В: Однострочный формат в любой из строк или при склейке первых 4 элементов
    single_line_re = re.compile(r"^([A-Za-z.,'\-\s()]+?)\s+(\d+)\s+(\d+)\s+([A-Za-z.,'\-\s()]+?)$")
    for cl in cleaned[:3]:
        m = single_line_re.match(cl)
        if m:
            return m.group(1).strip(), int(m.group(2)), int(m.group(3)), m.group(4).strip()

    joined_top = " ".join(cleaned[:4])
    m = single_line_re.match(joined_top)
    if m:
        return m.group(1).strip(), int(m.group(2)), int(m.group(3)), m.group(4).strip()

    return None


def normalize_ittf_text(page_text):
    """
    В Chromium innerText карточки ITTF разделяют элементы одной строки символом табуляции (\t):
      "Men's Teams - Quarterfinals - Match 2\tOlympic Town, Tashkent"
      "Wed 21, 10:00\tTable 1"
      "Chinese Taipei\t3\t0\tHong Kong, China"
    Превращаем табуляции перед 'Olympic Town' и 'Table N' в переносы строк, а остальные \t — в пробелы.
    """
    text = page_text or ""
    text = re.sub(r"\t+(?=Olympic Town|Table\s+\d+)", "\n", text, flags=re.IGNORECASE)
    text = text.replace("\t", " ")
    return text


def parse_match_blocks_from_text(page_text):
    """
    Разбирает текстовое содержимое страницы результатов ITTF на отдельные карточки матчей.
    """
    norm_text = normalize_ittf_text(page_text)
    lines = [ln.strip() for ln in norm_text.splitlines() if ln.strip()]
    header_pattern = re.compile(
        r"^(Men's Teams|Women's Teams|Men's Singles|Women's Singles|Men's Doubles|Women's Doubles|Mixed Doubles)\s*-\s*(.+)$",
        re.IGNORECASE,
    )
    time_pattern = re.compile(
        r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2})(?:,\s*(\d{1,2}:\d{2}))?$",
        re.IGNORECASE,
    )
    table_pattern = re.compile(r"^Table\s+(\d+)$", re.IGNORECASE)
    player_line_pattern = re.compile(r"^(?:WIN\s+)?[A-Za-z\s\-'.()]+\s+[A-Z]{3}$")
    numbers_line_pattern = re.compile(r"^(?:\d+\s*)+$")

    parsed_matches = []
    i = 0
    n = len(lines)

    while i < n:
        hm = header_pattern.match(lines[i])
        if not hm:
            i += 1
            continue

        header_line = re.sub(r"\s+Olympic Town.*$", "", lines[i], flags=re.IGNORECASE).strip()
        ev_code = detect_event_code(header_line)
        match_num = extract_match_number(header_line)
        i += 1

        block = []
        while i < n and not header_pattern.match(lines[i]):
            block.append(lines[i])
            i += 1

        if not ev_code or not block:
            continue

        day_num = "21"
        day_abbr_ru = "Ср"
        time_only = "TBD"
        time_str = "TBD"
        table_ru = "Олимп. городок"
        content_lines = []

        day_map_ru = {
            "MON": "Пн", "TUE": "Вт", "WED": "Ср", "THU": "Чт",
            "FRI": "Пт", "SAT": "Сб", "SUN": "Вс"
        }

        for bl in block:
            tm = time_pattern.match(bl)
            if tm:
                day_abbr_ru = day_map_ru.get(tm.group(1).upper(), "")
                day_num = tm.group(2).zfill(2)
                time_only = tm.group(3) or "TBD"
                time_str = f"{day_num}.10 • {time_only}"
                continue
            tbm = table_pattern.match(bl)
            if tbm:
                table_ru = f"Стол {tbm.group(1)}"
                continue
            if bl in ("Olympic Town, Tashkent", "Stats >", "Stats", "Official"):
                continue
            content_lines.append(bl)

        stage_ru = detect_stage_ru(header_line, int(day_num))

        # 1. Командные разряды (MT / WT)
        if ev_code in ("MT", "WT"):
            team_parsed = parse_team_content_lines(content_lines)
            if team_parsed:
                team1_eng, s1, s2, team2_eng = team_parsed
                code1, ru1 = resolve_team_code_and_ru(team1_eng)
                code2, ru2 = resolve_team_code_and_ru(team2_eng)
                done = (s1 >= 3 or s2 >= 3)
                parsed_matches.append({
                    "ev": ev_code,
                    "header": header_line,
                    "matchNum": match_num,
                    "stage": stage_ru,
                    "dayAbbrRu": day_abbr_ru,
                    "dayNum": day_num,
                    "timeOnly": time_only,
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
            continue

        # 2. Одиночные и парные разряды (MS, WS, MD, WD, XD)
        expected_players_per_side = 2 if ev_code in ("MD", "WD", "XD") else 1
        sides = []
        curr_players = []
        curr_nums = []
        has_win_marker = False
        is_wo = False

        for cl in content_lines:
            if cl == "WIN":
                has_win_marker = True
                continue
            if player_line_pattern.match(cl):
                if cl.startswith("WIN "):
                    has_win_marker = True
                if len(curr_players) >= expected_players_per_side and (curr_nums or len(sides) == 0):
                    if curr_nums or len(curr_players) == expected_players_per_side:
                        games_won = curr_nums[-1] if curr_nums else 0
                        sides.append((list(curr_players), games_won))
                        curr_players = []
                        curr_nums = []
                curr_players.append(cl)
            elif numbers_line_pattern.match(cl) and curr_players:
                curr_nums.extend(int(x) for x in cl.split())
            elif cl.upper() in ("WO", "W/O") and curr_players:
                is_wo = True
                curr_nums.append(0)

        if curr_players:
            games_won = curr_nums[-1] if curr_nums else 0
            sides.append((list(curr_players), games_won))

        if len(sides) >= 2:
            (p1_lines, s1), (p2_lines, s2) = sides[0], sides[1]
            code1, ru1 = format_player_or_pair_ru(p1_lines)
            code2, ru2 = format_player_or_pair_ru(p2_lines)
            done = has_win_marker or is_wo or s1 >= 3 or s2 >= 3
            parsed_matches.append({
                "ev": ev_code,
                "header": header_line,
                "matchNum": match_num,
                "stage": stage_ru,
                "dayAbbrRu": day_abbr_ru,
                "dayNum": day_num,
                "timeOnly": time_only,
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


def promote_winner_in_placeholders(payload, ev, codeA, codeB, winner_code, winner_ru):
    """Заменяет плейсхолдеры вида 'Победитель IRI / SGP' или 'Победитель ЧФ 2 (HKG / TPE)' на реального победителя."""
    if not codeA or not codeB or not winner_ru:
        return

    def update_val(val):
        if "Победитель" not in val:
            return val
        codes = set(re.findall(r"\b[A-Z]{3}\b", val))
        if codes == {codeA, codeB}:
            return winner_ru
        if {codeA, codeB}.issubset(codes):
            val = re.sub(rf"\b{codeA}\s*/\s*{codeB}\b", winner_code, val)
            val = re.sub(rf"\b{codeB}\s*/\s*{codeA}\b", winner_code, val)
        return val

    for m in payload.get("matches", []):
        if m.get("ev") != ev:
            continue
        for side_key in ("a", "b"):
            m[side_key] = update_val(m.get(side_key, ""))

    b_ev = payload.get("brackets", {}).get(ev, {})
    for stage_key in ("qf", "sf", "final"):
        for node in b_ev.get(stage_key, []):
            for side_key in ("a", "b"):
                node[side_key] = update_val(node.get(side_key, ""))


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

        # 1. Ищем существующий матч в списке matches по (ev, time, table)
        target = None
        for m in matches:
            if m.get("ev") == ev and m.get("time") == time_str and m.get("table") == table_ru:
                target = m
                break

        # Запасной поиск по (ev, стадия, коды стран)
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
            if ev in ("MT", "WT"):
                # Для командных разрядов всегда синхронизируем названия команд и порядок с официальным протоколом ITTF
                target["a"] = sm["a"]
                target["b"] = sm["b"]
                target["time"] = time_str
                target["table"] = table_ru
                final_sA, final_sB = sA, sB
            elif m_cA == codeB and m_cB == codeA and codeA != codeB:
                final_sA, final_sB = sB, sA
            else:
                final_sA, final_sB = sA, sB
                if "Победитель" in target.get("a", "") or "Сетка" in target.get("a", ""):
                    target["a"] = sm["a"]
                if "Победитель" in target.get("b", "") or "Сетка" in target.get("b", ""):
                    target["b"] = sm["b"]

            live_suffix = " (LIVE)" if (not done and (final_sA > 0 or final_sB > 0)) else ""
            target["score"] = f"{final_sA} : {final_sB}{live_suffix}"
            target["done"] = done
            updated_count += 1
        else:
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

        # 2. Если матч завершён, продвигаем победителя в следующие стадии (вместо "Победитель ...")
        if done and (sA > sB or sB > sA):
            winner_ru = sm["a"] if sA > sB else sm["b"]
            winner_code = codeA if sA > sB else codeB
            promote_winner_in_placeholders(payload, ev, codeA, codeB, winner_code, winner_ru)

        # 3. Если это 1/4 финала, 1/2 финала или Финал — обновляем верхнюю сетку BRACKETS[ev]
        if ev in brackets:
            b_ev = brackets[ev]
            hdr_lower = sm["header"].lower()
            stage_label_prefix = None
            b_list = None
            if "quarterfinal" in hdr_lower:
                b_list = b_ev.get("qf", [])
                stage_label_prefix = "1/4 финала"
            elif "semifinal" in hdr_lower:
                b_list = b_ev.get("sf", [])
                stage_label_prefix = "1/2 финала"
            elif "final" in hdr_lower and "quarter" not in hdr_lower and "semi" not in hdr_lower:
                b_list = b_ev.get("final", [])
                stage_label_prefix = "🥇 ФИНАЛ"

            if b_list:
                m_num = sm.get("matchNum")
                target_node = None
                # Приоритет 1: Точный номер матча в сетке (Match 1 -> индекс 0, Match 2 -> индекс 1 и т.д.)
                if m_num is not None and 1 <= m_num <= len(b_list):
                    target_node = b_list[m_num - 1]
                else:
                    # Приоритет 2: Совпадение по времени и столу или кодам стран
                    time_part = sm.get("timeOnly", "")
                    for node in b_list:
                        lbl = node.get("label", "")
                        n_cA = extract_code(node.get("a", ""))
                        n_cB = extract_code(node.get("b", ""))
                        if (time_part and time_part in lbl and table_ru in lbl) or (
                            codeA and codeB and {n_cA, n_cB} == {codeA, codeB}
                        ):
                            target_node = node
                            break

                if target_node is not None:
                    if ev in ("MT", "WT"):
                        target_node["a"] = sm["a"]
                        target_node["b"] = sm["b"]
                        target_node["scoreA"] = str(sA)
                        target_node["scoreB"] = str(sB)
                        if stage_label_prefix and sm.get("dayNum"):
                            day_prefix = f"{sm['dayAbbrRu']} " if sm.get("dayAbbrRu") else ""
                            target_node["label"] = (
                                f"{stage_label_prefix} • {day_prefix}{sm['dayNum']}.10, {sm['timeOnly']} • {table_ru}"
                            )
                    else:
                        n_cA = extract_code(target_node.get("a", ""))
                        n_cB = extract_code(target_node.get("b", ""))
                        if n_cA == codeB and n_cB == codeA and codeA != codeB:
                            target_node["scoreA"] = str(sB)
                            target_node["scoreB"] = str(sA)
                        else:
                            target_node["scoreA"] = str(sA)
                            target_node["scoreB"] = str(sB)
                            if "Победитель" in target_node.get("a", "") or "Четвертьфинал" in target_node.get("a", ""):
                                target_node["a"] = sm["a"]
                            if "Победитель" in target_node.get("b", "") or "Четвертьфинал" in target_node.get("b", ""):
                                target_node["b"] = sm["b"]

                    # Для завершённых четвертьфиналов команд сразу записываем победителя в соответствующий слот 1/2 финала
                    if ev in ("MT", "WT") and "quarterfinal" in hdr_lower and done and m_num in (1, 2, 3, 4):
                        sf_list = b_ev.get("sf", [])
                        winner_ru = sm["a"] if sA > sB else sm["b"]
                        if m_num == 1 and len(sf_list) >= 1:
                            sf_list[0]["a"] = winner_ru
                        elif m_num == 2 and len(sf_list) >= 1:
                            sf_list[0]["b"] = winner_ru
                        elif m_num == 3 and len(sf_list) >= 2:
                            sf_list[1]["a"] = winner_ru
                        elif m_num == 4 and len(sf_list) >= 2:
                            sf_list[1]["b"] = winner_ru

                    # Для завершённых полуфиналов команд сразу записываем победителя в Финал
                    if ev in ("MT", "WT") and "semifinal" in hdr_lower and done and m_num in (1, 2):
                        fin_list = b_ev.get("final", [])
                        winner_ru = sm["a"] if sA > sB else sm["b"]
                        if m_num == 1 and len(fin_list) >= 1:
                            fin_list[0]["a"] = winner_ru
                        elif m_num == 2 and len(fin_list) >= 1:
                            fin_list[0]["b"] = winner_ru

    return updated_count


def scrape_all_days_with_playwright():
    if sync_playwright is None:
        raise RuntimeError("Playwright is not installed")
    all_scraped = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

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
