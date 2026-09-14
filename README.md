# PROPHOTO Telegram-бот замовлень

Бот приймає замовлення на рілз-обкладинки та каруселі у стилі PROPHOTO, структурує чернетку через Claude, збирає бриф і фото,
а за потреби верстає макет у Figma через Claude Code (затверджений клієнт Figma MCP).

> Секрети (`.env`, токени Figma/Google) у репозиторій не потрапляють — див. `.gitignore`. Перед першим запуском скопіюйте `.env.example` → `.env`.

Бот проводить клієнта від «що хочете» до готового брифу (і для шаблонів 7/8 — до готових слайдів).

## Сценарій
1. `/start` → **Рілз** або **Карусель**.
2. Альбом із 8 обкладинок. Для каруселі кнопка 🔍 показує всі слайди шаблону.
3. Кнопка «💡 Порадьте мені» → скріншот профілю → Claude лише класифікує останні пости за типами обкладинок; далі код сам зіставляє їх з обома розкладками з Figma (A і B), обирає ту, що краще збігається, і бере наступну клітинку плану (для каруселі — наступну текстову). Кнопка «Пропустити».
4. Зміст: «📋 Є структура» (заголовок → саблайн → тексти екранів → фото) або «📝 Є чернетка» (Claude структурує, показує на підтвердження, приймає правки словами).
5. Фото: надсилати по одному або альбомом, завершити `/done`.
6. Бриф зберігається в `orders/<дата_час_userid>/brief.json` + `photos/`. Для шаблонів 7 і 8 бот одразу рендерить слайди (`generator/carousel.py`) і надсилає превʼю та JPG. Інші шаблони — «верстає дизайнер» (бриф надходить у ADMIN_CHAT_ID).

## Тестовий режим (без ШІ, зараз)
У `.env` лишіть `ANTHROPIC_API_KEY` порожнім (або `AI_ENABLED=0`). Тоді бот:
- проводить клієнта тим самим сценарієм, але без Claude: «Порадьте мені» лише збирає скріншот, «Є чернетка» зберігає текст як є;
- складає замовлення в `orders/<id>/` (brief.txt, brief.json, photos/, instagram_screenshot.jpg);
- надсилає все вам у Telegram (`ADMIN_CHAT_ID`): текст брифу, фото альбомом, скріншот, brief.json;
- якщо налаштовано `drive_sa.py` — дублює папку замовлення в Google Drive «ЗАМОВЛЕННЯ» і дає лінк.
Далі ви передаєте замовлення Клоду в чаті (лінк на папку Drive або пересланий бриф + фото) — і макет збирається у Figma.

## Figma напряму з бота — через Claude Code
Figma пускає до свого MCP лише затверджених клієнтів; Claude Code — один із них. Бот викликає його у фоні
з жорсткою інструкцією «виконай build.js через use_figma, підстав фото, зроби експорт». Один раз на Mac:
```bash
npm install -g @anthropic-ai/claude-code      # якщо нема npm: brew install node
claude                                        # увійти своїм акаунтом Claude (Pro/Max) → вийти: /exit
claude mcp add --transport http figma https://mcp.figma.com/mcp
claude                                        # у чаті набрати /mcp → figma → Authenticate → у браузері Allow → /exit
python3 cc_builder.py test                    # має вивести ваш Figma-акаунт
```
Далі `./run.sh` — бот після `/done` збирає макет у файлі PROPHOTO STUDIO (сторінка AUTO POSTS, секція з номером замовлення),
експортує слайди й надсилає клієнту та вам. Рілз-обкладинки — усі 8 шаблонів; каруселі повністю — 3, 5, 7, 8 (1, 2, 4, 6 — обкладинка, решту доверстовує дизайнер).
Кожна збірка — один виклик Claude Code (кілька центів). Вимкнути: `FIGMA_VIA_CLAUDE_CODE=0` у .env.
Файли: `builder.py` — генерує детермінований build.js; `cc_builder.py` — запускає Claude Code; `figma_mcp.py` — лише константа FILE_KEY (прямий OAuth Figma закрила, файл лишено для довідки).

## Встановлення
```bash
pip3 install -r requirements.txt
cp .env.example .env      # вписати токени
./run.sh
```
Токени: `TELEGRAM_BOT_TOKEN` — @BotFather → /newbot. `ANTHROPIC_API_KEY` — platform.claude.com (потрібен баланс).
`ADMIN_CHAT_ID` — напишіть боту @userinfobot, він покаже ваш id.

## Render (без сервера і терміналу)
Репозиторій на GitHub → render.com → New → **Web Service** → підключити репозиторій `prophoto-bot`.
Render сам підхопить `render.yaml`. У розділі Environment вписати `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`, `ADMIN_CHAT_ID`.
Тариф — **Starter** (free засинає, бот замовкає). Логи — вкладка Logs. Кожен push у GitHub автоматично перерозгортає бота.
Обмеження: без Claude Code/Figma-автозбірки; папка orders стирається при перезапуску — замовлення живуть у Telegram-групі (та в Drive, якщо налаштовано drive_sa.py).

## VPS (сервер 24/7)
1. Hetzner Cloud (або DigitalOcean): сервер Ubuntu 24.04, найменший тариф (~€4–6/міс). Отримати IP і root-пароль.
2. З Mac: `scp -r ~/Downloads/bot root@IP:/root/bot` (папка з готовим .env).
3. На сервері: `ssh root@IP`, потім `bash /root/bot/deploy/setup_server.sh` — ставить Python, Node, Claude Code, сервіс.
4. Доступи Claude Code + Figma робляться на Mac (claude → вхід; claude mcp add … figma; /mcp → Authenticate), а потім переносяться:
   на Mac `bash ~/Downloads/bot/deploy/export_claude_creds.sh root@IP`.
5. На сервері: `cd /root/bot && python3 cc_builder.py test` (має показати Figma-акаунт) → `systemctl start prophoto-bot`.
Логи: `journalctl -u prophoto-bot -f`. Перезапуск після змін: `systemctl restart prophoto-bot`. Оновити код: скопіювати файли scp і перезапустити.

## Хостинг
- Тест: запустити `./run.sh` на Mac — бот працює, поки відкритий термінал.
- Постійно: будь-який VPS (Ubuntu) — `nohup ./run.sh &` або systemd-сервіс; або Railway/Render (Procfile: `python3 bot.py`).

## Файли
```
bot.py            — сценарій (python-telegram-bot, ConversationHandler)
ai.py             — Claude: структурування чернетки, правки, класифікація постів на скріншоті; next_by_layout — правило розкладки
templates.json    — каталог шаблонів (назви, описи для ШІ, чи рендеримо автоматично)
previews/         — 44 превʼю: t<шаблон>_s<слайд>.jpg (t1_s01 … t8_s06)
generator/        — рендер шаблонів 7/8 (carousel.py + шрифти + графіка)
orders/           — замовлення (створюється автоматично)
```

## Що доробити далі
- Рендер шаблонів 1–6 (зараз вони йдуть дизайнеру як бриф).
- Автозаливка результату в Google Drive (`generator/drive_upload.py` вже є, треба підключити в `finish()`).
- Кнопка «замінити фото N» після превʼю.
layouts.json      — плани розкладок A і B (типи обкладинок → шаблони); layouts/ — картинки планів
