# رادار گیت‌هاب — خبرخوان هوش مصنوعی و تکنولوژی

وب‌اپ فارسی و RTL که هر چند ساعت یک‌بار گیت‌هاب و چند منبع تکنولوژی را می‌خواند، تکراری‌ها را حذف می‌کند و برای آیتم‌های مهم با یک مدل زبانی (LLM) **خلاصهٔ فارسی، دسته‌بندی، امتیاز اهمیت و «با این چی می‌شه ساخت؟»** تولید می‌کند.

<p align="center">
  <img src="app/web/static/img/icon.svg" width="72" alt="">
</p>

## چه چیزهایی جمع می‌کند؟

| منبع | روش | یادداشت |
|---|---|---|
| GitHub Trending روزانه/هفتگی/ماهانه | HTML صفحهٔ `github.com/trending` به تفکیک زبان | «N stars today» و رتبه ذخیره می‌شود |
| GitHub Search | Search API با `topic:llm`، `topic:ai-agents`، `topic:rag`، `topic:mcp`، `claude`، `openai` … | دو حالت: ریپوهای **تازه** (`created:>`) و **فعال** (`pushed:>` + ستارهٔ بالا) |
| ریلیزها | `/repos/{o}/{r}/releases` برای فهرست watch (قابل ویرایش در پنل) | با ETag؛ پیش‌انتشارها برچسب می‌خورند |
| ردیاب ستاره | GraphQL دسته‌ای (۸۰ ریپو در هر درخواست) برای همهٔ ریپوهای ۳۰ روز اخیر | تاریخچه در `star_snapshots`؛ **جهش ستاره** (+۳۰۰ و +۲۵٪ در ۷ روز) پرچم می‌خورد؛ نمودار ستاره در صفحهٔ هر ریپو |
| Hacker News | API رسمی Firebase (top + best)؛ اگر فیلتر بود، خودکار به HTML سایت HN و سپس HNPWA می‌رود | حداقل امتیاز قابل تنظیم؛ آیتم‌های AI پرچم می‌گیرند |
| Hugging Face | مدل‌های ترند + Daily Papers | مقاله‌هایی که ریپوی گیت‌هاب دارند به همان ریپو وصل می‌شوند |
| RSS/Atom | ۲۲ فید پیش‌فرض (فیدهای Reddit به‌خاطر فیلترینگ روی سرورهای ایران پیش‌فرض خاموش‌اند) (TechCrunch AI، The Verge AI، HF Blog، OpenAI، Anthropic، Google AI/DeepMind، arXiv cs.AI/CL/LG، Simon Willison، GitHub Blog، Reddit r/LocalLLaMA، .NET Blog، …) | هر فید یک منبع جداست؛ در پنل اضافه/حذف/خاموش می‌شود |

**اتصال بین منابع:** هر خبر HN، مقاله یا paper که به `github.com/owner/repo` اشاره کند، زیر صفحهٔ همان ریپو در بخش «بحث‌ها و پوشش خبری» دیده می‌شود.

## لایهٔ هوش مصنوعی

- ماژول provider‑agnostic: **Anthropic** (SDK رسمی، با structured output و prompt caching) و **OpenAI‑compatible** (OpenAI، OpenRouter، Groq، DeepSeek، Together، Ollama/LM Studio محلی، LiteLLM…). ترتیب ارائه‌دهنده‌ها = اولویت و fallback.
- برای هر آیتم: `title_fa`، `summary_fa`، `readme_summary_fa`، `category` (۱۲ دسته)، `tags`، `importance` ۱ تا ۱۰ و ۲ تا ۴ `ideas` با استک پیشنهادی برای توسعه‌دهندهٔ ایرانی.
- **سرمقالهٔ روز:** یک درخواست LLM از روی مهم‌ترین آیتم‌های ۲۴ ساعت، در بالای صفحهٔ اصلی و در خلاصهٔ روزانهٔ بله.
- **کنترل هزینه:** امتیاز اولیهٔ اکتشافی (prescore) تعیین می‌کند چه چیزی به LLM برود؛ batch چند آیتم در یک درخواست؛ سقف روزانهٔ آیتم و توکن؛ کش نتیجه در پایگاه داده؛ گزارش مصرف و هزینهٔ تقریبی در پنل.
- بدون کلید هم کار می‌کند: متن اصلی با برچسب «ترجمه نشده» نمایش داده می‌شود.

> مدل پیش‌فرض `claude-opus-5-5` است. برای ترجمهٔ انبوه، `claude-haiku-5-5` حدود ۴۰ برابر ارزان‌تر است و `claude-sonnet-5-5` حد وسط؛ از پنل یا `.env` تغییر دهید. با سقف پیش‌فرض ۱۵۰ آیتم در روز و effort=low، هزینهٔ Opus حدود ۳ تا ۵ دلار در روز و Haiku چند سنت است.

## وب‌اپ

- صفحهٔ اصلی با کارت‌ها (نام، ستاره و رشد، زبان، خلاصهٔ فارسی، تگ، اهمیت)، فیلتر بازهٔ زمانی/نوع/دسته/زبان، جست‌وجو، مرتب‌سازی، «فقط ترجمه‌شده»
- صفحهٔ هر آیتم: خلاصه، ایده‌ها، خلاصهٔ README، نمودار ستاره، متن اصلی، آیتم‌های مرتبط و بحث‌های مربوط به همان ریپو
- صفحه‌های **ترند** (روز/هفته/ماه + جدول جهش‌ها)، **ریلیزها**، **ایده‌های امروز**، **نشان‌شده‌ها** (localStorage + خروجی JSON)
- حالت تیره/روشن، موبایل‌پسند، فونت Vazirmatn (self-hosted)، PWA (manifest + service worker)، اعداد فارسی و تاریخ شمسی
- خروجی **RSS فارسی** (`/feed.xml`، با همان فیلترهای صفحهٔ اصلی) و **JSON API** (`/api/items`، `/api/items/{id}`، `/api/trending`، `/api/releases`، `/api/ideas`، `/api/spikes`، `/api/categories`، `/api/stats`؛ مستندات در `/api/docs`)
- **پنل مدیریت** `/admin`: روشن/خاموش کردن منابع، ویرایش فهرست ریپوهای watch و کوئری‌ها، افزودن فید، اجرای دستی هر کار، لاگ اجرا و صف دستورها، مصرف توکن/هزینه، تنظیم کلیدها (ذخیره در DB با اولویت بر `.env`)، تست LLM و اعلان، پنهان کردن/ترجمهٔ مجدد آیتم، خروجی JSON

## اعلان (اختیاری)

خلاصهٔ روزانه (سرمقاله + ۱۰ آیتم برتر) به **بله** یا **تلگرام** با Bot API؛ به‌علاوه **هشدار فوری** برای آیتم‌هایی با اهمیت ≥ ۹ (قابل تنظیم/خاموش). توکن و chat_id را در `.env` یا پنل بگذارید و با «تست اعلان» بسنجید.

## معماری

```
┌──────────────┐    ┌──────────────────────────────┐    ┌──────────────┐
│  web (FastAPI│◄──►│  PostgreSQL 16               │◄──►│ worker       │
│  + Jinja2)   │    │  items, sources, snapshots,  │    │ APScheduler  │
│  :8000→4200  │    │  llm_usage, run_logs,        │    │ + صف دستورها │
└──────────────┘    │  commands, editorials, …     │    └──────┬───────┘
       ▲            └──────────────────────────────┘           │
       │ nginx (میزبان)                       ┌───────────────┼──────────────┐
   کاربر/RSS/API                           collectors      llm/enrich     notify
                                       (trending, search,  (anthropic,   (bale/
                                        releases, stars,    openai-compat) telegram)
                                        hn, hf, rss)
┌──────────────┐
│ backup       │  pg_dump فشرده هر شب ۰۳:۳۰، نگهداری ۷ نسخه در ./backups
└──────────────┘
```

- `app/collectors/` — هر منبع یک ماژول با خروجی `RawItem`؛ `base.ingest()` dedupe بر اساس `external_id` (مثل `gh:owner/repo`، `rel:owner/repo@tag`، `hn:123`، `rss:<sha1 لینک نرمال‌شده>`، `hf:org/model`، `hfp:arxiv-id`)، ادغام فیلدها، snapshot ستاره، لینک به ریپو.
- `app/collectors/prescore.py` — امتیاز اولیهٔ ۰ تا ۱۰۰ از ستاره/رشد/ترند/جهش/امتیاز HN/کلیدواژه‌های AI/وزن منبع.
- `app/llm/` — `base.py` (interface + جدول قیمت)، `anthropic_provider.py`، `openai_compat.py`، `prompts.py`، `enrich.py` (انتخاب، batch، بودجه، ذخیره)، `editorial.py`.
- `app/worker/` — زمان‌بندی (`__main__.py`) و کارها (`jobs.py`)؛ پنل با جدول `commands` به worker دستور می‌دهد.
- `app/web/` — صفحه‌ها (`routes_public.py`)، API/RSS (`routes_api.py`)، پنل (`routes_admin.py`)، کوئری‌های مشترک (`queries.py`)، قالب‌ها و استاتیک.
- تنظیمات: `.env` (pydantic-settings) + جدول `settings` برای مقادیر قابل‌تغییر از پنل (`settings_store.py`).

### زمان‌بندی پیش‌فرض (قابل تغییر در `.env`)

| کار | زمان |
|---|---|
| ترند + جست‌وجوی گیت‌هاب | هر ۶ ساعت |
| ریلیزها | هر ۳ ساعت |
| Hacker News / Hugging Face / RSS | هر ۲ ساعت |
| خلاصه‌سازی LLM | هر ۲۰ دقیقه (فقط آیتم‌های جدیدِ بالای آستانه، تا سقف روزانه) |
| ردیاب ستاره + تشخیص جهش | ۰۲:۱۵ هر شب (+ جهش هر ۶ ساعت) |
| سرمقاله | ۰۸:۳۰ |
| خلاصهٔ روزانهٔ بله | ۰۹:۰۰ |
| پاک‌سازی (آیتم‌های قدیمی‌تر از ۱۸۰ روز) | ۰۴:۲۰ |

در اولین اجرا با پایگاه خالی، worker یک «دور کامل» را خودکار در صف می‌گذارد.

## اجرا در محیط توسعه (بدون Docker)

```bash
python -m venv .venv && . .venv/Scripts/activate   # ویندوز؛ در لینوکس: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # و DATABASE_URL=sqlite:///./data/dev.db را فعال کنید
uvicorn app.main:app --reload --port 4200
python -m app.worker            # در ترمینال دوم
pytest -q
```

## استقرار با Docker Compose

```bash
git clone https://github.com/alirezzazm/ai-github-news.git /opt/ai-github-news
cd /opt/ai-github-news
cp .env.example .env
nano .env     # POSTGRES_PASSWORD, SECRET_KEY, ADMIN_PASSWORD, SITE_URL و در صورت داشتن: GITHUB_TOKEN, ANTHROPIC_API_KEY, NOTIFY_*
docker compose up -d --build
docker compose ps
curl -s http://127.0.0.1:4200/healthz
```

سرویس‌ها: `db` (Postgres 16)، `web` (uvicorn روی `127.0.0.1:4200`)، `worker`، `backup`. همه با `restart: unless-stopped` برمی‌گردند.

### nginx میزبان

تا زمانی که دامنه نداریم، `deploy/nginx-temp.conf` را در `/etc/nginx/sites-available/ai-github-news` بگذارید و لینک کنید (روی IP سرور با HTTP جواب می‌دهد). وقتی دامنه آماده شد:

```bash
sed 's/DOMAIN/news.example.ir/' deploy/nginx-domain.conf > /etc/nginx/sites-available/ai-github-news
nginx -t && systemctl reload nginx
certbot --nginx -d news.example.ir
# سپس SITE_URL را در .env به https://news.example.ir تغییر دهید و: docker compose up -d
```

هر دو فایل `snippets/deny-probes.conf` را include می‌کنند.

### به‌روزرسانی

```bash
./deploy/deploy.sh      # git pull + build + up -d + health
```

### پشتیبان و بازگردانی

کانتینر `backup` هر شب ساعت ۰۳:۳۰ (به وقت تهران) `pg_dump -Fc | gzip` را در `./backups/` می‌نویسد و فقط ۷ نسخهٔ آخر را نگه می‌دارد. بازگردانی:

```bash
./scripts/restore.sh backups/aignews-20261024-0330.dump.gz
```

## متغیرهای مهم `.env`

| متغیر | توضیح |
|---|---|
| `POSTGRES_PASSWORD`, `SECRET_KEY`, `ADMIN_USER`, `ADMIN_PASSWORD` | الزامی |
| `SITE_URL` | آدرس عمومی برای RSS و اعلان |
| `GITHUB_TOKEN` | PAT فقط‌خواندنی؛ بدون آن ۶۰ درخواست در ساعت دارید و ردیاب ستاره به حالت محدود REST می‌رود |
| `LLM_PROVIDERS` | مثلاً `anthropic,openai`؛ خالی = بدون LLM |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_EFFORT` | کلید و مدل Anthropic |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` | هر endpoint سازگار با OpenAI (برای Ollama کلید لازم نیست) |
| `LLM_DAILY_ITEM_LIMIT`, `LLM_DAILY_TOKEN_LIMIT`, `LLM_BATCH_SIZE`, `LLM_MIN_PRESCORE` | کنترل هزینه |
| `NOTIFY_PROVIDER`, `NOTIFY_BOT_TOKEN`, `NOTIFY_CHAT_ID`, `DIGEST_HOUR`, `ALERT_MIN_IMPORTANCE` | اعلان |
| `COLLECT_*_EVERY_MIN`, `ENRICH_EVERY_MIN`, `HN_MIN_POINTS` | زمان‌بندی |

همهٔ کلیدها را می‌توان بعداً از `/admin/settings` هم وارد کرد (در پایگاه داده ذخیره می‌شود و بر `.env` اولویت دارد).

## تست‌ها

`pytest` روی SQLite اجرا می‌شود: پارسر ترند (با فیکسچر واقعی)، dedupe و ادغام، تشخیص جهش، پارس RSS/HN/HF، استخراج JSON از پاسخ LLM، prescore، و تست‌های HTTP صفحه‌ها/API/RSS/پنل.

## مجوز

MIT. فونت Vazirmatn تحت OFL.
