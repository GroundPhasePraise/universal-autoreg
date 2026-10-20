# SETUP — инфраструктура universal-autoreg

## 1. Captcha sidecar (БЕСПЛАТНО, 11 типов)

```bash
git clone https://github.com/waguriagentic/captcha-solver cs_sidecar
cd cs_sidecar && pip install -r requirements.txt
# env: PORT=8877, SOLVER_BIND_HOST=127.0.0.1, SOLVER_ALLOW_UNAUTHENTICATED=1, REAL_PAGE=1
python server.py
curl http://127.0.0.1:8877/health   # 200 + 11 типов
```

Питфолы:
- Версии после 14.10 ввели Bearer-auth — без `SOLVER_ALLOW_UNAUTHENTICATED=1` фермы ловят 401.
- Vision-модель для image-captcha: локальный OpenAI-compat endpoint (у нас qwen3-vl-plus).
- `real_page=1` повышает конверсию Turnstile (сайт-обёртка решает в живом браузере).
- Нативный Turnstile под siteverify (terrapolis, vani, rsiai) внешние токены ОТБИВАЕТ — только cloakbrowser/patchright с нативным решением.

## 2. CDP Chrome (для TM-капчи, th_tonline, 2no)

```bash
chrome.exe --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir=C:\chrome-cdp
```
БЕЗ `--remote-allow-origins=*` → Handshake 403. Один инстанс, проверять `/json/version`.

## 3. Python

- Провайдеры на Playwright/Camoufox: **Python 3.11** (3.14 несовместим — greenlet).
- Windows: запускать с `PYTHONPATH=""` — venv-загрязнение ломает camoufox/playwright.
- `playwright-stealth==1.0.6` (git+https://github.com/AtuboDad/playwright_stealth.git).
- Camoufox обязателен там, где Chromium=403 (abliteration-паттерн). После taskkill — удалять SkeletonUILock.

## 4. Почтовые пулы

- **t-online**: `data/working_mails.txt` (email:password, canonical только — dash-алиасы мертвы для доставки). IMAP secureimap.t-online.de:993. SEARCH по SUBJECT (ALL падает на ящиках 18K+). Первый ящик может не дать код — автоматом следующий.
- **voidash**: POST api.voidash.com/api/v1/inboxes {"domain":"voidash.bond"} → session_key → GET /messages (Bearer). Домены eu.cc/cyou заблокированы у Notion/Attio. Код Attio в теле после "valid for one hour.".
- **gmail +alias**: канонизация зависит от таргета (llmtr/ChatGPT канонизируют, GH-панели нет). Dot-трюк: treg уникален по inbox — доты мертвы.
- **ForwardEmail** (для type.com WorkOS): свой домен + TXT forward-email=user+tag@gmail.com → OTP читать с Gmail.

## 5. Прокси

- Пул: `data/proxies.db` (sqlite, table pool, alive=1) или `data/proxies.txt`.
- Live-тест ПЕРЕД волной: `python -c "from lib.proxies import live_pool; print(len(live_pool()))"` (~20с/250шт, ThreadPool 40, verify=True — SSL-MITM прокси убивают Firefox).
- Sticky: 1 прокси = 1 акк на весь флоу (`StickyRotator`).
- New-API панели банят прокси-IP (403) — панель напрямую, GH-часть через прокси.
- Free-пул (ProxyGrab/proxyscrape/TheSpeedX) протухает за часы; residential (1024proxy sticky region-de) — для notion/type.

## 6. GH-аккаунты (ядро OAuth-волн)

- Пул: `data/gh_accounts.json` (login/email/password/totp).
- Сессия: `lib/gh_session.py` (password+TOTP, curl_cffi chrome131).
- Device-flow токены: `providers/gh_device_flow.py <login>` → gho_ (scopes repo,read:org,gist).
- Питфолы: user-code ПОСИМВОЛЬНО включая дефис; consent authorize='1' обязателен; flagged-акк → redirect без code; 429 на OAuth authorize = лимит приложения/региона — пэйсинг 60с+, выход 7-15%/волна.
- Проверка email акка: `curl -H "Authorization: Bearer <gho_>" https://api.github.com/user/emails` → verified.

## 7. Банк

`data/bank.jsonl` — единый формат:
```json
{"provider":"beatapi_oauth","email":"...","password":"...","token":"***","uid":123,"ts":1760000000}
```
`python -m lib.bank` — статистика. Дашборд читает тот же файл.

## 8. SMS (когда нужен телефон)

- **2nd-no.com (2no.pl)**: JSON-RPC, x-auth-token из sessionStorage 2NR-TOKEN; /config = карта id (310 random, 301 reserve + turnstile token, 311 my numbers, 415 messages). 3 номера/акк/3дня. Turnstile sitekey → 2captcha (submit СТРОГО in.php). Прямой API снаружи = CF 403, только из browser-контекста. Бесплатный пул выжжен под Telegram-реги (BANNED_NUMBER).
- Для Telegram-реги: только платный SMS (5sim/sms-activate ~$0.05-0.2).
- WorkOS (type.com) SMS доходит на 2no (~30с, тема "Twój kod weryfikacyjny"), min_ts фильтр обязателен.

## 9. Дашборд

```bash
python dashboard.py   # http://127.0.0.1:8900
```
- RUN N → subprocess providers/X.py N, лог logs/X.log, live-tail в UI.
- Health: sidecar / прокси-пул / почтовый пул / 2captcha баланс / банк.
- STOP — terminate текущей волны.
- Порт: UA_PORT, python для волн: UA_PYTHON.

## 10. Анти-детект браузеры (когда headless палится)

Каталог-сравнение: pim97/anti-detect-browser-tools-tech-comparison (13.10.2026).
- **CloakBrowser** — WorkOS Signals, нативный Turnstile (vani/terrapolis/type).
- **Camoufox** — Firefox-антидетект (abliteration, conol), headless OK, headed ломался.
- **Patchright** — Chromium без CDP-флагов.
- Scrapling/Obscura — scraping-стек.


## 8. 2nd-no.com SMS (secondno_sms)

- Провайдер: providers/secondno_sms.py, пакет lib/secondno/ (client 2no.pl JSON-RPC + captcha).
- Data: SECONDNO_HOME (default <repo>/data/secondno) — state.json (акки+номера), captcha_keys.json.
- Ключ 2captcha: env TWOCAPTCHA_API_KEY или data/secondno/captcha_keys.json; при живом sidecar :8877 он приоритетен (FREE, real_page).
- Резерв номера может требовать Turnstile-токен (сайт 2nd-no.com за Cloudflare, sitekey 0x4AAAAAAAh6YYTPTzEcN3Ep; submit СТРОГО in.php для 2captcha).
- Логин-стена = React SPA: playwright (Python 3.11, PYTHONPATH="" на Windows).
- Режимы: N [--gmail] (рега акков), reserve <email> <pass> <reserve_file> <code_file> [timeout] [min_ts] (REUSE-FIRST OTP-мост для phone-гейтов других провайдеров), accounts (дамп).
- Лимит: 3 номера/акк/3 дня, продлеваются при получении SMS. Free-пул выжжен под TG — только веб-сервисы с мягким VOIP-фильтром.
