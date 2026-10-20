# 🩸 UNIVERSAL AUTOREG — универсальный авторег с дашбордом

Единый пульт для **18 проверенных авторег-провайдеров**: ChatGPT-панели, Notion, AWS Kiro, Conol, llmtr, miarouter, xkiro, vani, terrapolis, type.com, gname, omnirush, TokenHarbor, treg, BeatAPI, CleanApis, GitHub device-flow + 2nd-no.com SMS (phone-гейты).

**Всё battle-tested** (октябрь 2026): каждый провайдер — реальный рабочий скрипт с реальной конверсией, а не теория. Секретов в репе нет — ключи в `config.json` (gitignored).

## 🚀 Быстрый старт

```bash
python dashboard.py          # stdlib-only, http://127.0.0.1:8900
cp config.example.json config.json   # заполнить ключи
```

Дашборд: таблица провайдеров (таргет/auth/капча/награда/банк) → `RUN N` запускает волну → live-лог в UI → аккаунты падают в `data/bank.jsonl`.

## 📦 Состав

```
universal-autoreg/
├── dashboard.py        # пульт (stdlib http.server, порт 8900): запуск волн, логи, банк, здоровье инфры
├── providers.json      # манифест 18 провайдеров: таргет, auth, капча, почта, прокси, награда, питфолы
├── providers/          # 19 рабочих скриптов (контракт: python providers/X.py N)
├── lib/
│   ├── bank.py         # JSONL-банк аккаунтов: дедуп (provider,email), статистика
│   ├── captcha.py      # sidecar :8877 (11 типов, БЕСПЛАТНО) + 2captcha fallback
│   ├── proxies.py      # sqlite/txt пул, live-проверка, StickyRotator (1 прокси = 1 акк)
│   ├── emails.py       # t-online IMAP-пул, voidash API, gmail +alias, wait_code
│   └── gh_session.py   # GitHub password+TOTP сессия (stdlib urllib + pyotp)
├── docs/SETUP.md       # инфраструктура: sidecar, CDP Chrome, пулы, питфолы
└── data/               # bank.jsonl, пулы (не коммитятся)
```

## 🎯 Провайдеры (что куда)

| Provider | Таргет | Награда | Капча |
|---|---|---|---|
| `newapi_panels_oauth` | 15 new-api панелей | 2.5M–100M квоты/акк | нет (GH OAuth) |
| `beatapi_oauth` | beatapi.io | 250K quota, 43 модели | нет |
| `cleanapis_oauth` | cleanapis.com | free Starter, claude-opus-5 | нет |
| `xkiro_tg_verify` | xkiro.com | 30M/30д + 1M daily | нет (TG-бот) |
| `secondno_sms` | 2nd-no.com | 3 free PL номера/акк (SMS OTP-мост) | Turnstile (sidecar FREE) |
| `treg_github_grant` | treg.to | $1 grant/акк | нет |
| `llmtr_turnstile` | llmtr.com | free-пул haiku/deepseek/qwen | Turnstile **FREE** |
| `conol_register` | conol.ai | 600 кредитов/19с/$0 | reCAPTCHA v3 **FREE** |
| `miarouter_farm` | miarouter.online | trial 7д + $1/вериф | Turnstile (sidecar) |
| `notion_farm` | notion.so | Notion AI Opus/GPT-6.1 | нет (email OTP) |
| `aws_builderid` | AWS → Kiro Free | 50cr/мес + 500 бонус | нет (TM-капча редко) |
| `tokenharbor_claim` | tokenharbor.ai | $5 → haiku-ключи | нет |
| `vani_turnstile` | vani.ai | 37 моделей (chat/video/research) | Turnstile native |
| `terrapolis_native` | terrapolis.xyz | 15M токенов | Turnstile native |
| `type_workos` | type.com | trial $110 | WorkOS Signals |
| `gname_slider` | gname.com | доменный регистратор | GnSlider (свой solver) |
| `omnirush_recaptcha` | omnirush.ai | акк (pending review) | reCAPTCHA v3 (~$0.003) |
| `gh_device_flow` | github.com | gho_ токены (push) | нет |

Подробные питфолы каждого — в `providers.json` (notes) и `docs/SETUP.md`.

## 🧠 Принципы (выстрадано)

1. **Локальная капча прежде платной**: sidecar (waguriagentic/captcha-solver) решает 11 типов бесплатно. 2captcha — только когда siteverify отбивает внешние токены (нативный Turnstile под Cloudflare).
2. **Sticky-прокси на весь флоу**: verify/register/login с одного IP, иначе 403 anti-bot. Ротация — только между аккаунтами.
3. **Почта**: t-online пул (canonical, dash-алиасы мертвы для доставки), voidash API, gmail +alias (канонизация зависит от таргета — проверять).
4. **GH OAuth — золотая жила 2026**: десятки new-api панелей пускают без капчи через GitHub. Пул акков с TOTP + device-flow = бесконечные токены.
5. **Банк = JSONL**: один формат на все провайдеры, дедуп по (provider,email), токен в `token`/`api_key`.
6. **Пэйсинг**: 429 на authorize/create-key — норма. sleep 20-110с между акками, волны 20/час.
7. **Никаких секретов в коде**: все ключи в `config.json` (gitignored), провайдеры читают через `lib/*`.

## ⚠️ Дисклеймер

Материалы для изучения автоматизации веб-флоу и security research. Соблюдайте ToS таргетов и законы вашей юрисдикции.

---
👻 [**иишко**](https://t.me/AlStack)
