# -*- coding: utf-8 -*-
"""Claude API helpers for the PROPHOTO bot."""
import os, json, base64, re
import anthropic

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")
_client = None

def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    return _client

def _text(resp):
    """Збираємо лише текстові блоки відповіді (модель може повертати ще й блоки роздумів)."""
    return "\n".join(b.text for b in resp.content if getattr(b, "type", "") == "text")

def _json(resp):
    text = _text(resp) if not isinstance(resp, str) else resp
    text = re.sub(r"```json|```", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)

STRUCTURE_SYSTEM = """Ти редактор Instagram-каруселей студії PROPHOTO (українська мова).
З чернетки клієнта зроби структуру каруселі. Правила:
- title: 2–5 слів, UPPERCASE не потрібен (це зробить шаблон), без крапки в кінці.
- subline: одне речення-уточнення, до 8 слів.
- cta: 3–6 слів заклик для обкладинки (наприклад «збережіть і спробуйте на зйомці»).
- slides: 2–6 слайдів. Кожен має "title" (2–6 слів; перше слово — головне, воно стане великим), "tags" — 2 короткі факти-теги по 1–4 слова (число, назва, параметр) і "items" — 2–4 пункти по 6–20 слів.
- У кожному пункті ключову фразу (дія, параметр, обладнання, число) обгорни у **подвійні зірочки** — це буде жирним; пояснення лишай без зірочок.
- Якщо шаблон — «Програма по тижнях», tags[0] кожного слайда = "Тиждень N" (N — номер слайда), а title — назва теми тижня.
- Не вигадуй фактів, яких немає в чернетці. Прибирай емодзі.
Відповідай ТІЛЬКИ валідним JSON без пояснень:
{"title": "...", "subline": "...", "cta": "...", "slides": [{"title": "...", "tags": ["...", "..."], "items": ["...", "..."]}]}"""

def structure_draft(draft_text: str, template_name: str) -> dict:
    last = None
    for attempt in range(2):
        r = client().messages.create(
            model=MODEL, max_tokens=8000, system=STRUCTURE_SYSTEM,
            messages=[{"role": "user", "content": f"Шаблон: {template_name}.\n\nЧернетка:\n{draft_text[:12000]}"
                       + ("\n\nВАЖЛИВО: відповідь має бути коротким валідним JSON, не більше 6 слайдів." if attempt else "")}],
        )
        try:
            return _json(r)
        except Exception as e:
            last = e
    raise last

def revise_structure(current: dict, request: str) -> dict:
    r = client().messages.create(
        model=MODEL, max_tokens=8000, system=STRUCTURE_SYSTEM,
        messages=[{"role": "user", "content":
                   f"Ось поточна структура:\n{json.dumps(current, ensure_ascii=False)}\n\nВнеси правки: {request}\nПоверни повний оновлений JSON."}],
    )
    return _json(r)

CLASSIFY_SYSTEM = """Ти дивишся на скріншот Instagram-профілю (сітка 3 колонки; найновіший пост — зліва вгорі).
Класифікуй ПЕРШІ ПОСТИ у порядку читання (зліва направо, зверху вниз, до 6 штук) за типами обкладинок:
{types}
Відповідай ТІЛЬКИ JSON: {{"posts": ["<type>", "<type>", ...], "notes": "1 речення про стиль стрічки"}}
Використовуй лише ключі типів зі списку. Якщо пост не схожий на жоден — "photo"."""

def classify_feed(image_bytes: bytes, media_type: str, types: dict) -> dict:
    tlist = "\n".join(f"- {k}: {v['label']}" for k, v in types.items())
    r = client().messages.create(
        model=MODEL, max_tokens=400, system=CLASSIFY_SYSTEM.format(types=tlist),
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                         "data": base64.b64encode(image_bytes).decode()}},
            {"type": "text", "text": "Класифікуй перші пости."},
        ]}],
    )
    return _json(r)

def match_layout(layouts: dict, recent: list) -> tuple:
    """Обираємо розкладку, яка найкраще пояснює останні пости клієнта."""
    best = None
    for key, lay in layouts.items():
        r = next_by_layout(lay["cells"], recent)
        if best is None or r["match_score"] > best[1]["match_score"]:
            best = (key, r)
    return best

def next_for(layouts: dict, types: dict, recent: list, post_type: str) -> dict:
    """Наступна клітинка плану з урахуванням типу публікації: для каруселі пропускаємо клітинки,
    які не є обкладинкою з текстом (чисте фото / продажний пост)."""
    key, r = match_layout(layouts, recent)
    cells = layouts[key]["cells"]; n = len(cells); i = r["matched_index"]
    steps = 1; nxt = cells[(i - steps) % n]
    if post_type == "carousel":
        while types[nxt]["template"] is None and steps < n:
            steps += 1; nxt = cells[(i - steps) % n]
    return {"layout": key, "next": nxt, "after_next": cells[(i - steps - 1) % n], "skipped": steps - 1, "score": r["match_score"]}

def next_by_layout(layout_cells: list, recent: list) -> dict:
    """Розкладка задана у порядку читання (як виглядатиме стрічка в кінці), тобто пости публікуються
    з кінця списку до початку. Знаходимо, де в плані стоїть найновіший пост клієнта, і повертаємо
    попередню клітинку плану — це і є наступний пост. Якщо збігу немає — шукаємо за 2-3 постами."""
    n = len(layout_cells)
    best = None
    for i in range(n):
        score = 0
        for k, t in enumerate(recent[:3]):
            if i + k < n and layout_cells[i + k] == t: score += 3 - k
        if best is None or score > best[0]: best = (score, i)
    score, i = best
    nxt = layout_cells[(i - 1) % n]
    return {"matched_index": i, "match_score": score, "next": nxt, "after_next": layout_cells[(i - 2) % n]}
