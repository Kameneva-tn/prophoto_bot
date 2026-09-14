# -*- coding: utf-8 -*-
"""
cc_builder.py — збірка макета у Figma через Claude Code (затверджений клієнт Figma MCP).

Одноразове налаштування на Mac (див. README, розділ «Claude Code»):
  npm install -g @anthropic-ai/claude-code
  claude                       # увійти своїм акаунтом Claude
  claude mcp add --transport http figma https://mcp.figma.com/mcp
  claude  →  /mcp  →  figma → Authenticate (браузер → Allow)
  python3 cc_builder.py test   # має вивести ваш Figma-акаунт

Бот пише build.js (детермінований скрипт з builder.py) і просить Claude Code ЛИШЕ виконати
кроки: use_figma(build.js) → upload_assets + curl фото → get_screenshot + curl експорт.
"""
import os, sys, json, glob, shlex, subprocess
import builder
from figma_mcp import FILE_KEY

HERE = os.path.dirname(os.path.abspath(__file__))
CLAUDE = os.getenv("CLAUDE_BIN", "claude")
CC_MODEL = os.getenv("CC_MODEL", "sonnet")   # детермінована збірка — дешевша модель
TOOLS = "mcp__figma__use_figma,mcp__figma__upload_assets,mcp__figma__get_screenshot,mcp__figma__whoami,Read,Bash(curl:*),Bash(mkdir:*)"

def available():
    try:
        return subprocess.run([CLAUDE, "--version"], capture_output=True, text=True, timeout=20).returncode == 0
    except Exception:
        return False

def _run(prompt, cwd, max_turns=40, timeout=900):
    cmd = [CLAUDE, "-p", prompt, "--output-format", "json", "--allowedTools", TOOLS, "--model", CC_MODEL,
           "--max-turns", str(max_turns), "--permission-mode", "acceptEdits"]
    # Claude Code має працювати під вашим логіном (Max), а не під API-ключем бота:
    # інакше він не бачить Figma-підключення, авторизоване в інтерактивній сесії.
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    if r.returncode != 0 and not r.stdout.strip():
        raise RuntimeError(f"claude exited {r.returncode}: {r.stderr[-800:]}")
    try:
        j = json.loads(r.stdout)
        if j.get("is_error"): raise RuntimeError("claude error: " + str(j.get("result"))[:800])
        return j.get("result", ""), j
    except json.JSONDecodeError:
        return r.stdout, {}

def build_order(brief, photo_paths, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    order_dir = os.path.dirname(out_dir)
    js_path = os.path.join(order_dir, "build.js")
    open(js_path, "w", encoding="utf-8").write(builder._js(brief))
    photos_abs = [os.path.abspath(p) for p in photo_paths]
    prompt = f"""Ти виконуєш ДЕТЕРМІНОВАНУ збірку макета у Figma. Роби рівно ці кроки, нічого не вигадуй, не змінюй код, не додавай пояснень.

КРОК 1. Прочитай файл {js_path} інструментом Read. Виклич MCP-інструмент figma use_figma з параметрами:
  fileKey = "{FILE_KEY}", description = "order {brief['order_id']}", code = ПОВНИЙ вміст файлу build.js без жодних змін.
Він поверне JSON виду {{"section":"...","made":[...],"imgs":[...]}}. Запам'ятай його.

КРОК 2. Якщо масив imgs не порожній: виклич figma upload_assets з fileKey="{FILE_KEY}", count = довжина imgs, nodeIds = imgs, scaleMode="FILL".
У відповіді буде список uploads з submitUrl у тому ж порядку. Список фото клієнта (використовуй по колу, якщо фото менше, ніж слотів):
{json.dumps(photos_abs, ensure_ascii=False)}
Для кожного i (0..len(imgs)-1) виконай Bash:
  curl -s -F "file=@<photo[i mod len(photos)]>;type=image/jpeg" "<submitUrl_i>"
Якщо фото немає взагалі — пропусти крок 2.

КРОК 3. Для кожного id у масиві made (по порядку, k = 1,2,3…): виклич figma get_screenshot з fileKey="{FILE_KEY}", nodeId=id, maxDimension=4050,
візьми з відповіді image_url і виконай Bash:
  curl -sL -o "{os.path.abspath(out_dir)}/slide_0k.png" "<image_url>"   (k з двома цифрами: 01, 02, …)

КРОК 4. В самому кінці виведи ТІЛЬКИ такий JSON без іншого тексту:
{{"section":"<section з кроку 1>","made":<масив made>,"slides":<кількість збережених файлів>}}"""
    text, meta = _run(prompt, cwd=HERE)   # Figma MCP додано для папки бота — запускаємо звідти
    m = None
    try:
        s = text[text.rindex("{"):text.rindex("}") + 1]
        # take the last JSON object in the text
        for cand in [text[text.index("{"):]] + [s]:
            try: m = json.loads(cand); break
            except Exception: continue
    except Exception:
        pass
    pngs = sorted(glob.glob(os.path.join(out_dir, "slide_*.png")))
    if not pngs:
        raise RuntimeError("Claude Code не зберіг жодного слайда. Відповідь: " + text[-600:])
    exported = []
    try:
        from PIL import Image
        for p in pngs:
            jp = p[:-4] + ".jpg"; Image.open(p).convert("RGB").save(jp, quality=95); os.remove(p); exported.append(jp)
    except Exception:
        exported = pngs
    section = (m or {}).get("section", "")
    url = f"https://www.figma.com/design/{FILE_KEY}/PROPHOTO-STUDIO" + (f"?node-id={section.replace(':', '-')}" if section else "")
    full = brief["type"] == "reels" or brief["template"] in ("3", "5", "7", "8")
    return {"section": section, "frames": (m or {}).get("made", []), "figma_url": url, "exported": exported,
            "complete": full, "cost_usd": meta.get("total_cost_usd")}

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        text, meta = _run("Виклич MCP-інструмент figma whoami і виведи відповідь як є.", cwd=HERE, max_turns=3)
        print(text); print("cost:", meta.get("total_cost_usd"))
    elif len(sys.argv) > 1 and sys.argv[1] == "rebuild":
        # python3 cc_builder.py rebuild orders/<order_id>   → повторна збірка збереженого замовлення
        d = os.path.abspath(sys.argv[2]); brief = json.load(open(os.path.join(d, "brief.json"), encoding="utf-8"))
        photos = sorted(glob.glob(os.path.join(d, "photos", "*")))
        print(json.dumps(build_order(brief, photos, os.path.join(d, "out")), ensure_ascii=False, indent=1))
    elif len(sys.argv) > 1:
        brief = json.load(open(sys.argv[1], encoding="utf-8")); d = os.path.dirname(os.path.abspath(sys.argv[1]))
        photos = sorted(glob.glob(os.path.join(d, "photos", "*")))
        print(json.dumps(build_order(brief, photos, os.path.join(d, "out")), ensure_ascii=False, indent=1))
    else:
        print(__doc__)
