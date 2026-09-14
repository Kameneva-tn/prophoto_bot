# -*- coding: utf-8 -*-
"""
PROPHOTO Telegram bot — приймає замовлення на рілз-обкладинку або карусель.

Flow:
/start → рілз / карусель → вибір шаблону (для каруселі — «розгорнути» показує слайди)
→ скріншот Instagram для рекомендації (або «пропустити»)
→ структуровані дані (заголовок → саблайн → тексти екранів → фото)
   або чернетка → Claude структурує → підтвердження / правки
→ бриф збережено в orders/<id>/, для шаблонів 7/8 одразу рендер слайдів.
"""
import os, io, json, time, glob, logging, subprocess, shutil
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ReplyKeyboardRemove)
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler, MessageHandler,
                          ConversationHandler, ContextTypes, filters)
try:
    import ai
except Exception:
    ai = None

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("prophoto")

HERE = os.path.dirname(os.path.abspath(__file__))
PREV = os.path.join(HERE, "previews")
ORDERS = os.path.join(HERE, "orders")
TEMPLATES = json.load(open(os.path.join(HERE, "templates.json"), encoding="utf-8"))
CLIENTS_PATH = os.path.join(HERE, "clients.json")
CLIENTS = json.load(open(CLIENTS_PATH)) if os.path.exists(CLIENTS_PATH) else {}
def remember_client(u):
    if not u: return
    cid = str(u.id)
    rec = {"name": u.full_name, "username": u.username}
    if CLIENTS.get(cid) != rec:
        CLIENTS[cid] = rec
        try: json.dump(CLIENTS, open(CLIENTS_PATH, "w"), ensure_ascii=False, indent=1)
        except Exception: pass
LAYOUTS = json.load(open(os.path.join(HERE, "layouts.json"), encoding="utf-8"))
LAYOUT_DIR = os.path.join(HERE, "layouts")
ADMIN_CHAT = os.getenv("ADMIN_CHAT_ID")  # chat id to notify about new orders (you)
AI_ENABLED = bool(os.getenv("ANTHROPIC_API_KEY")) and os.getenv("AI_ENABLED", "1") != "0"
try:
    import drive_sa
    DRIVE_ENABLED = drive_sa.enabled()
except Exception:
    DRIVE_ENABLED = False
try:
    import cc_builder
    FIGMA_ENABLED = os.getenv("FIGMA_VIA_CLAUDE_CODE", "1") != "0" and cc_builder.available()
except Exception:
    FIGMA_ENABLED = False

(TYPE, TEMPLATE, LAYOUT, SCREENSHOT, MODE, TITLE, SUBLINE, SCREENS, PHOTOS, DRAFT, DRAFT_PHOTOS, CONFIRM, REVISE) = range(13)

# ----------------------------------------------------------------------------- helpers
def kb(rows):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows])

def cover_path(t): return os.path.join(PREV, f"t{t}_s01.jpg")
def slide_paths(t): return sorted(glob.glob(os.path.join(PREV, f"t{t}_s*.jpg")))

# --- кеш file_id: кожне превʼю вивантажується в Telegram лише один раз
FID_PATH = os.path.join(HERE, "file_ids.json")
FIDS = json.load(open(FID_PATH)) if os.path.exists(FID_PATH) else {}
def _fid_save(): json.dump(FIDS, open(FID_PATH, "w"), indent=1)

async def send_photo_cached(chat, path, **kw):
    key = os.path.basename(path)
    for attempt in range(3):
        try:
            if key in FIDS:
                return await chat.send_photo(FIDS[key], **kw)
            msg = await chat.send_photo(open(path, "rb"), **kw)
            FIDS[key] = msg.photo[-1].file_id; _fid_save(); return msg
        except Exception as e:
            log.warning("send_photo %s attempt %s: %s", key, attempt + 1, e)
            if key in FIDS and "file" in str(e).lower(): FIDS.pop(key, None)
    raise RuntimeError("send failed " + key)

async def send_album_cached(chat, paths, captions=None):
    """Альбом з кешованих file_id; те, чого ще нема в кеші, спершу вивантажується по одному."""
    for p in paths:
        if os.path.basename(p) not in FIDS:
            m = await send_photo_cached(chat, p)            # перше вивантаження, повідомлення потім видаляємо
            try: await m.delete()
            except Exception: pass
    media = [InputMediaPhoto(FIDS[os.path.basename(p)], caption=(captions[i] if captions else None)) for i, p in enumerate(paths)]
    for i in range(0, len(media), 10):
        for attempt in range(3):
            try: await chat.send_media_group(media[i:i + 10]); break
            except Exception as e: log.warning("media_group attempt %s: %s", attempt + 1, e)

async def send_covers(update, ctx, post_type):
    """Одна картинка-сітка з 8 обкладинками (як у стрічці) + кнопки."""
    chat = update.effective_chat
    await send_photo_cached(chat, os.path.join(PREV, "grid_covers.jpg"),
                            caption="Варіанти оформлення. Номер на картинці = номер шаблону.")
    keys = list(TEMPLATES); chunks = [keys[i:i + 3] for i in range(0, len(keys), 3)]
    rows = [[(f"{t}", f"pick:{t}") for t in ch] for ch in chunks]
    if post_type == "carousel":
        rows += [[(f"🔍 {t}", f"expand:{t}") for t in ch] for ch in chunks]
        text = "Оберіть номер шаблону або натисніть 🔍, щоб побачити всі його слайди."
    else:
        text = "Оберіть номер обкладинки для рілзу."
    await chat.send_message(text, reply_markup=kb(rows))

# ----------------------------------------------------------------------------- flow
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
    who = update.effective_user.first_name if update.effective_user else ""
    await update.effective_chat.send_message(
        f"{who}, привіт! Я допоможу оформити публікацію у стилі PROPHOTO.\nЩо робимо?",
        reply_markup=kb([[("🎬 Рілз", "type:reels"), ("🖼 Карусель", "type:carousel")]]))
    return TYPE

async def on_type(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data["type"] = q.data.split(":")[1]
    await q.edit_message_text("Рілз — підбираємо обкладинку." if ctx.user_data["type"] == "reels" else "Карусель — підбираємо шаблон.")
    await send_covers(update, ctx, ctx.user_data["type"])
    return TEMPLATE

async def on_expand(update, ctx):
    q = update.callback_query; await q.answer()
    t = q.data.split(":")[1]
    await send_photo_cached(update.effective_chat, os.path.join(PREV, f"grid_t{t}.jpg"),
                            caption=f"Шаблон {t} — {TEMPLATES[t]['name']}: усі слайди по порядку.")
    await update.effective_chat.send_message(f"Це всі слайди шаблону {t}. Обрати його?",
                                             reply_markup=kb([[(f"✅ Обрати {t}", f"pick:{t}"), ("↩️ Інші варіанти", "back:covers")]]))
    return TEMPLATE

async def on_back(update, ctx):
    q = update.callback_query; await q.answer()
    await send_covers(update, ctx, ctx.user_data["type"])
    return TEMPLATE

async def on_pick(update, ctx):
    q = update.callback_query; await q.answer()
    t = q.data.split(":")[1]; ctx.user_data["template"] = t
    await q.edit_message_text(f"Обрано шаблон {t} — {TEMPLATES[t]['name']}.")
    await update.effective_chat.send_message(
        "Сумніваєтесь, чи це доречно саме зараз у вашій стрічці? Можу порадити: надішліть скріншот профілю (сітка з останніми постами), "
        "я звірю з планом стрічки й скажу, який тип обкладинки має йти наступним.",
        reply_markup=kb([[("💡 Порадьте мені", "advise:go")], [("⏭ Пропустити", "skip:shot")]]))
    return LAYOUT

async def on_advise(update, ctx):
    q = update.callback_query; await q.answer()
    await q.edit_message_text("Надішліть скріншот вашого Instagram-профілю.", reply_markup=kb([[("⏭ Пропустити", "skip:shot")]]))
    return SCREENSHOT

async def on_screenshot(update, ctx):
    photo = update.message.photo[-1] if update.message.photo else None
    doc = update.message.document
    if not photo and not (doc and doc.mime_type and doc.mime_type.startswith("image/")):
        await update.message.reply_text("Надішліть зображення або натисніть «Пропустити».",
                                        reply_markup=kb([[("⏭ Пропустити", "skip:shot")]]))
        return SCREENSHOT
    f = await (photo or doc).get_file()
    data = await f.download_as_bytearray()
    if not AI_ENABLED:
        ctx.user_data["screenshot"] = bytes(data); ctx.user_data["advice_requested"] = True
        await update.message.reply_text("Дякую! Скріншот піде разом із замовленням — порада щодо наступної обкладинки прийде сюди від менеджера.")
        return await ask_mode(update.effective_chat, ctx)
    await update.message.reply_text("Дивлюсь на стрічку…")
    try:
        types = LAYOUTS["types"]
        cls = ai.classify_feed(bytes(data), "image/jpeg" if photo else doc.mime_type, types)
        recent = [p for p in cls.get("posts", []) if p in types]
        res = ai.next_for(LAYOUTS["layouts"], types, recent, ctx.user_data["type"])
        nt, at, tmpl = res["next"], res["after_next"], types[res["next"]]["template"]
        seen = ", ".join(types[p]["label"] for p in recent[:3]) or "не розпізнано"
        what = "обкладинка рілзу" if ctx.user_data["type"] == "reels" else "обкладинка каруселі"
        txt = f"Бачу останні пости: {seen}.\nЗа планом стрічки наступна {what} — *{types[nt]['label']}*."
        if res["skipped"]:
            txt += f"\n(За планом перед нею ще мають бути {res['skipped']} пост(и) без тексту — чисте фото або продажний; для каруселі беру наступну текстову.)"
        rows = []
        if tmpl:
            txt += f"\n\nЦе шаблон {tmpl} — {TEMPLATES[tmpl]['name']}."
            rows.append([(f"✅ Взяти шаблон {tmpl}", f"pick2:{tmpl}")])
        else:
            txt += "\n\nТобто зараз доречніше чисте фото без тексту (для рілзу — кадр без напису)."
        rows.append([(f"Лишити мій вибір ({ctx.user_data['template']})", "pick2:" + ctx.user_data["template"])])
        if tmpl:
            await send_photo_cached(update.effective_chat, cover_path(tmpl), caption=txt, parse_mode="Markdown", reply_markup=kb(rows))
        else:
            await update.message.reply_text(txt, parse_mode="Markdown", reply_markup=kb(rows))
    except Exception:
        log.exception("recommend failed")
        await update.message.reply_text("Не вдалося проаналізувати скріншот, рухаємось далі з вашим вибором.")
        return await ask_mode(update.effective_chat, ctx)
    return SCREENSHOT

async def on_pick2(update, ctx):
    q = update.callback_query; await q.answer()
    ctx.user_data["template"] = q.data.split(":")[1]
    try: await q.edit_message_caption(caption=f"Працюємо з шаблоном {ctx.user_data['template']}.")
    except Exception: await q.edit_message_text(f"Працюємо з шаблоном {ctx.user_data['template']}.")
    return await ask_mode(update.effective_chat, ctx)

async def on_skip_shot(update, ctx):
    q = update.callback_query; await q.answer()
    await q.edit_message_text("Добре, без рекомендації.")
    return await ask_mode(update.effective_chat, ctx)

async def ask_mode(chat, ctx):
    await chat.send_message(
        "Тепер зміст. Є два шляхи:\n"
        "• У вас уже є заголовок, саблайн і тексти екранів — введемо по кроках.\n"
        "• Є лише чернетка/конспект — надішліть як є, я структурую і покажу на підтвердження.",
        reply_markup=kb([[("📋 Є структура", "mode:struct")], [("📝 Є чернетка", "mode:draft")]]))
    return MODE

async def on_mode(update, ctx):
    q = update.callback_query; await q.answer()
    mode = q.data.split(":")[1]; ctx.user_data["mode"] = mode
    if mode == "struct":
        await q.edit_message_text("Крок 1/4. Надішліть заголовок (2–5 слів).")
        return TITLE
    await q.edit_message_text("Надішліть чернетку одним повідомленням (текст, конспект, тези — як є). Можна переслати з нотаток.")
    return DRAFT

async def on_title(update, ctx):
    ctx.user_data["title"] = update.message.text.strip()
    await update.message.reply_text("Крок 2/4. Саблайн — одне коротке речення-уточнення (або «-», якщо без нього).")
    return SUBLINE

async def on_subline(update, ctx):
    s = update.message.text.strip(); ctx.user_data["subline"] = "" if s == "-" else s
    if ctx.user_data["type"] == "reels":
        ctx.user_data["slides"] = []
        await update.message.reply_text("Крок 3/3. Надішліть фото для обкладинки (1 або кілька, потім /done).")
        return PHOTOS
    await update.message.reply_text(
        "Крок 3/4. Тексти екранів одним повідомленням. Кожен екран — заголовок з нового рядка, пункти під ним, екрани розділяйте порожнім рядком.\n"
        "Приклад:\nЩО РОБИТИ\n1. видихніть — не тримайте живіт втягнутим\n2. опустіть плечі вниз\n\nЩО ЦЕ ДАЄ\n1. талія візуально тонша")
    return SCREENS

def parse_screens(text):
    slides = []
    for block in [b for b in text.strip().split("\n\n") if b.strip()]:
        lines = [l.strip() for l in block.strip().split("\n") if l.strip()]
        title, items = lines[0], []
        for l in lines[1:]:
            l = l.lstrip("-•*0123456789.) ").strip()
            if l: items.append(l)
        slides.append({"title": title, "items": items})
    return slides

async def on_screens(update, ctx):
    ctx.user_data["slides"] = parse_screens(update.message.text)
    n = len(ctx.user_data["slides"])
    await update.message.reply_text(f"Прийнято {n} екран(ів). Крок 4/4. Надішліть фото (по 3 на екран для каруселі; можна менше). Коли все — /done.")
    ctx.user_data["photos"] = []
    return PHOTOS

async def on_draft(update, ctx):
    text = update.message.text or update.message.caption or ""
    if update.message.document and update.message.document.mime_type == "text/plain":
        f = await update.message.document.get_file(); text = (await f.download_as_bytearray()).decode("utf-8", "ignore")
    if len(text) < 30:
        await update.message.reply_text("Замало тексту для структури. Надішліть чернетку повніше."); return DRAFT
    if not AI_ENABLED:
        ctx.user_data["draft"] = text; ctx.user_data["photos"] = []
        await update.message.reply_text("Прийнято. Структуру зробимо ми й надішлемо на погодження. Тепер фото, які хочете використати (потім /done).")
        return PHOTOS
    await update.message.reply_text("Структурую…")
    try:
        s = ai.structure_draft(text, TEMPLATES[ctx.user_data["template"]]["name"])
    except Exception:
        log.exception("structure failed"); await update.message.reply_text("Не вийшло. Спробуйте ще раз або оберіть «Є структура»."); return DRAFT
    ctx.user_data.update(title=s["title"], subline=s.get("subline", ""), cta=s.get("cta", ""), slides=s.get("slides", []))
    ctx.user_data["photos"] = []
    return await show_structure(update.effective_chat, ctx)

def fmt_structure(d):
    out = [f"*Заголовок:* {d['title']}", f"*Саблайн:* {d.get('subline') or '—'}"]
    if d.get("cta"): out.append(f"*CTA:* {d['cta']}")
    for i, s in enumerate(d.get("slides", []), 1):
        out.append(f"\n*Екран {i}. {s['title']}*")
        out += [f"{j}. {it.replace('**', '')}" for j, it in enumerate(s["items"], 1)]
    return "\n".join(out)

async def show_structure(chat, ctx):
    await chat.send_message(fmt_structure(ctx.user_data), parse_mode="Markdown",
                            reply_markup=kb([[("✅ Так, беремо", "conf:ok"), ("✏️ Правки", "conf:edit")]]))
    return CONFIRM

async def on_confirm(update, ctx):
    q = update.callback_query; await q.answer()
    if q.data == "conf:edit":
        await q.edit_message_reply_markup(None)
        await update.effective_chat.send_message("Напишіть, що змінити (наприклад: «екран 2 коротший, заголовок без слова “курс”»).")
        return REVISE
    await q.edit_message_reply_markup(None)
    if ctx.user_data.get("photos"):
        return await finish(update, ctx)
    await update.effective_chat.send_message("Тепер фото: надішліть кадри, які хочете використати (потім /done).")
    return PHOTOS

async def on_revise(update, ctx):
    await update.message.reply_text("Правлю…")
    try:
        cur = {k: ctx.user_data.get(k) for k in ("title", "subline", "cta", "slides")}
        s = ai.revise_structure(cur, update.message.text)
        ctx.user_data.update(title=s["title"], subline=s.get("subline", ""), cta=s.get("cta", ""), slides=s.get("slides", []))
    except Exception:
        log.exception("revise failed"); await update.message.reply_text("Не вийшло застосувати правки, спробуйте сформулювати інакше."); return REVISE
    return await show_structure(update.effective_chat, ctx)

async def on_photo(update, ctx):
    ctx.user_data.setdefault("photos", [])
    src = update.message.photo[-1] if update.message.photo else update.message.document
    if not src: return PHOTOS
    f = await src.get_file(); data = await f.download_as_bytearray()
    ctx.user_data["photos"].append(bytes(data))
    n = len(ctx.user_data["photos"])
    await update.message.reply_text(f"Фото {n} збережено. Ще — або /done.")
    return PHOTOS

async def on_done(update, ctx):
    if AI_ENABLED and ctx.user_data.get("mode") == "struct" and ctx.user_data.get("type") == "carousel" and "slides" in ctx.user_data and not ctx.user_data.get("confirmed"):
        ctx.user_data["confirmed"] = True
        return await show_structure(update.effective_chat, ctx)
    return await finish(update, ctx)

# ----------------------------------------------------------------------------- finish
def save_order(user, ctx):
    oid = time.strftime("%Y%m%d_%H%M%S") + f"_{user.id}"
    d = os.path.join(ORDERS, oid); os.makedirs(os.path.join(d, "photos"), exist_ok=True)
    photos = []
    for i, b in enumerate(ctx.user_data.get("photos", []), 1):
        p = os.path.join(d, "photos", f"photo_{i:02d}.jpg"); open(p, "wb").write(b); photos.append(os.path.basename(p))
    if ctx.user_data.get("screenshot"):
        open(os.path.join(d, "instagram_screenshot.jpg"), "wb").write(ctx.user_data["screenshot"])
    brief = {"order_id": oid, "user": {"id": user.id, "name": user.full_name, "username": user.username},
             "advice_requested": bool(ctx.user_data.get("advice_requested")), "draft": ctx.user_data.get("draft"),
             "type": ctx.user_data["type"], "template": ctx.user_data["template"],
             "title": ctx.user_data.get("title"), "subline": ctx.user_data.get("subline"), "cta": ctx.user_data.get("cta"),
             "slides": ctx.user_data.get("slides", []), "photos": photos}
    json.dump(brief, open(os.path.join(d, "brief.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return d, brief

def brief_to_post_txt(brief, photos):
    lines = [f"# {brief['title']}"]
    if brief.get("subline"): lines.append(f"> {brief['subline']}")
    if brief.get("cta"): lines.append(f"cta: {brief['cta']}")
    if photos: lines.append("photos: " + ", ".join(photos[:3]))
    k = 3
    for s in brief.get("slides", []):
        lines += ["", f"## {s['title']}"]
        if photos: lines.append("photos: " + ", ".join(photos[k:k + 3] or photos[:3])); k += 3
        lines += [f"{i}. {it}" for i, it in enumerate(s["items"], 1)]
    return "\n".join(lines) + "\n"

def render(order_dir, brief):
    """Рендер шаблонів 7/8 генератором carousel.py; повертає список файлів."""
    gen = os.path.join(HERE, "generator", "carousel.py")
    post = os.path.join(order_dir, "post.txt")
    open(post, "w", encoding="utf-8").write(brief_to_post_txt(brief, brief["photos"]))
    out = os.path.join(order_dir, "out")
    subprocess.run(["python3", gen, post, "--photos", os.path.join(order_dir, "photos"), "--out", out, "--jpg", "--preview"], check=True, timeout=300)
    return sorted(glob.glob(os.path.join(out, "slide_*.jpg"))), os.path.join(out, "preview.jpg")

def order_text(brief):
    lines = [f"Замовлення #{brief['order_id']}",
             f"Назва для готового файлу: {brief['order_id']}__{brief['user']['id']} -- підпис.jpg", f"Клієнт: {brief['user']['name']} @{brief['user']['username']}",
             f"Тип: {'рілз' if brief['type']=='reels' else 'карусель'} · шаблон {brief['template']} — {TEMPLATES[brief['template']]['name']}",
             f"Фото: {len(brief['photos'])}" + (" · є скріншот профілю, просить пораду" if brief.get("advice_requested") else "")]
    if brief.get("draft"):
        lines += ["", "ЧЕРНЕТКА (структурувати):", brief["draft"]]
    else:
        lines += ["", fmt_structure(brief).replace("*", "")]
    return "\n".join(lines)

async def finish(update, ctx):
    chat = update.effective_chat; user = update.effective_user
    d, brief = save_order(user, ctx)
    t = brief["template"]
    open(os.path.join(d, "brief.txt"), "w", encoding="utf-8").write(order_text(brief))
    await chat.send_message(f"Дякую! Замовлення #{brief['order_id']} прийнято.\nШаблон {t} — {TEMPLATES[t]['name']}, фото: {len(brief['photos'])}.\n"
                            "Ми зберемо макет і надішлемо сюди на погодження.")
    link = None
    figma_url = None
    if FIGMA_ENABLED and (brief["type"] == "reels" or brief.get("slides")) and not brief.get("draft"):
        await chat.send_message("Збираю макет у Figma… це займе 2–4 хвилини.")
        try:
            import asyncio
            photos = [os.path.join(d, "photos", p) for p in brief["photos"]]
            res = await asyncio.to_thread(cc_builder.build_order, brief, photos, os.path.join(d, "out"))
            figma_url = res["figma_url"]
            files = res["exported"]
            for i in range(0, len(files), 10):
                await chat.send_media_group([InputMediaPhoto(open(p, "rb")) for p in files[i:i + 10]])
            note = "" if res["complete"] else "\n(Для цього шаблону автоматично зібрано обкладинку; внутрішні слайди доверстає дизайнер.)"
            await chat.send_message("Ось макет. Якщо потрібні правки — напишіть, що змінити, менеджер внесе." + note)
        except Exception:
            log.exception("figma build failed")
            await chat.send_message("Автозбірка не спрацювала — макет зберемо вручну й надішлемо сюди.")
    elif TEMPLATES[t]["auto_render"] and brief["type"] == "carousel" and brief.get("slides") and not brief.get("draft"):
        try:
            files, preview = render(d, brief)
            await chat.send_photo(open(preview, "rb"), caption="Попереднє превʼю (чорновий автозбір) — фінальну версію надішле менеджер.")
        except Exception:
            log.exception("render failed")
    if ADMIN_CHAT:
        try:
            txt = order_text(brief) + (f"\n\n📁 Drive: {link}" if link else "\n\n(Drive не налаштовано — фото лише в orders/ на сервері)") + (f"\nFigma: {figma_url}" if figma_url else "")
            await ctx.bot.send_message(ADMIN_CHAT, txt[:4000], disable_web_page_preview=True)
        except Exception:
            log.exception("admin notify failed")
    ctx.user_data.clear()
    return ConversationHandler.END

async def nudge(update, ctx):
    """Будь-яке повідомлення поза діалогом → пропонуємо почати."""
    await update.effective_chat.send_message("Щоб оформити публікацію, натисніть кнопку:", reply_markup=kb([[("▶️ Почати", "go:start")]]))

async def post_init(app):
    from telegram import BotCommand
    await app.bot.set_my_commands([BotCommand("start", "Нове замовлення"), BotCommand("cancel", "Скасувати")])

async def cancel(update, ctx):
    ctx.user_data.clear()
    await update.message.reply_text("Скасовано. /start — почати знову.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ----------------------------------------------------------------------------- main
async def deliver_ready(context):
    """Файли з Drive «ГОТОВО» → замовнику. Назва: <номер_замовлення>__<id_замовника>[ -- підпис].ext
    Бот бере id замовника прямо з назви (усі дані в одному місці). Копія — у робочий чат ADMIN_CHAT."""
    if not (DRIVE_ENABLED and drive_sa.delivery_enabled()): return
    try:
        import asyncio, tempfile
        files = await asyncio.to_thread(drive_sa.list_ready)
        for f in files:
            raw = f["name"]; name = raw; target = None; order = None
            head = raw.split(" -- ", 1)[0]
            caption = None
            if " -- " in raw:
                caption = os.path.splitext(raw.split(" -- ", 1)[1])[0]
            if "__" in head:
                order, cid = head.rsplit("__", 1)
                cid = os.path.splitext(cid)[0].strip()
                if cid.isdigit(): target = cid
            if not target:
                # адресата в назві немає — кладемо в робочий чат і позначаємо
                target = ADMIN_CHAT; caption = (caption or "") + "\n⚠️ у назві файлу немає <номер>__<id> — надсилаю в робочий чат"
            path = os.path.join(tempfile.gettempdir(), f["id"] + "_" + raw)
            await asyncio.to_thread(drive_sa.download, f["id"], path)
            sent_ok = False
            try:
                await context.bot.send_document(target, open(path, "rb"), caption=caption, filename=name)
                sent_ok = True
            except Exception:
                log.exception("send to %s failed", target)
            who = CLIENTS.get(str(target), {}).get("name") or target
            if ADMIN_CHAT and str(target) != str(ADMIN_CHAT):
                try:
                    tag = f"↑ надіслано замовнику: {who}" + (f" · {order}" if order else "")
                    await context.bot.send_document(ADMIN_CHAT, open(path, "rb"), caption=tag, filename=name)
                except Exception: log.exception("admin copy failed")
            if sent_ok:
                await asyncio.to_thread(drive_sa.mark_sent, f["id"])
            try: os.remove(path)
            except Exception: pass
            log.info("delivered %s -> %s", name, target)
    except Exception:
        log.exception("deliver_ready failed")

def start_health_server():
    """Крихітний HTTP-відгук для хостингів типу Render Web Service (потрібен відкритий порт)."""
    port = os.getenv("PORT")
    if not port: return
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers(); self.wfile.write(b"prophoto bot ok")
        def do_HEAD(self):
            self.send_response(200); self.end_headers()
        def log_message(self, *a): pass
    threading.Thread(target=HTTPServer(("0.0.0.0", int(port)), H).serve_forever, daemon=True).start()
    log.info("health server on port %s", port)

def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    start_health_server()
    os.makedirs(ORDERS, exist_ok=True)
    app = (Application.builder().token(token).post_init(post_init)
           .connect_timeout(20).read_timeout(30).write_timeout(30).pool_timeout(30).media_write_timeout(120)
           .build())
    async def on_error(update, context):
        log.exception("update failed", exc_info=context.error)
        try:
            if update and update.effective_chat:
                await update.effective_chat.send_message("Щось пішло не так із мережею. Натисніть кнопку ще раз або /start.")
        except Exception: pass
    app.add_error_handler(on_error)
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start), CallbackQueryHandler(start, pattern=r"^go:start$")],
        states={
            TYPE: [CallbackQueryHandler(on_type, pattern=r"^type:")],
            TEMPLATE: [CallbackQueryHandler(on_expand, pattern=r"^expand:"), CallbackQueryHandler(on_pick, pattern=r"^pick:"),
                       CallbackQueryHandler(on_back, pattern=r"^back:")],
            LAYOUT: [CallbackQueryHandler(on_advise, pattern=r"^advise:"), CallbackQueryHandler(on_skip_shot, pattern=r"^skip:")],
            SCREENSHOT: [CallbackQueryHandler(on_skip_shot, pattern=r"^skip:"), CallbackQueryHandler(on_pick2, pattern=r"^pick2:"),
                         MessageHandler(filters.PHOTO | filters.Document.IMAGE, on_screenshot)],
            MODE: [CallbackQueryHandler(on_mode, pattern=r"^mode:")],
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_title)],
            SUBLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_subline)],
            SCREENS: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_screens)],
            DRAFT: [MessageHandler((filters.TEXT | filters.Document.TEXT) & ~filters.COMMAND, on_draft)],
            PHOTOS: [MessageHandler(filters.PHOTO | filters.Document.IMAGE, on_photo), CommandHandler("done", on_done)],
            CONFIRM: [CallbackQueryHandler(on_confirm, pattern=r"^conf:")],
            REVISE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_revise)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
        allow_reentry=True,
    )
    async def trace(update, context):
        u = update.effective_user
        try:
            if update.effective_chat and update.effective_chat.type == "private":
                remember_client(u)
        except Exception: pass
        log.info("UPDATE from %s (%s): %s", u.id if u else "?", u.username if u else "?",
                 (update.message.text if update.message and update.message.text else "") or (update.callback_query.data if update.callback_query else "<other>"))
    app.add_handler(MessageHandler(filters.ALL, trace), group=-1)
    app.add_handler(CallbackQueryHandler(trace), group=-1)
    app.add_handler(conv)
    if DRIVE_ENABLED and drive_sa.delivery_enabled():
        app.job_queue.run_repeating(deliver_ready, interval=60, first=10)
        log.info("delivery watcher on")
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, nudge))
    app.add_handler(CallbackQueryHandler(start, pattern=r"^go:start$"))
    log.info("bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
