# ADR 0001 — انتخاب PostgreSQL به‌عنوان دیتابیس اصلی

| Field | Value |
| --- | --- |
| **Status** | Accepted |
| **Date** | 2026-11-08 |
| **Scope** | لایه داده و زیرساخت دیتابیس پروژه Lurnian Backend |
| **Related** | [`README.md`](../../README.md) — بخش Database |

---

## Context

Lurnian Backend یک **modular monolith** مبتنی بر FastAPI است که روی **Python 3.14** اجرا می‌شود. ساختار فعلی پروژه شامل `core/` (تنظیمات، لاگ، زیرساخت مشترک) و `modules/` (هر domain یک ماژول مستقل با router و schemas) است. مسیر request به‌صورت async است و کیفیت کد با `ruff` و تست‌ها با `pytest` + `httpx` کنترل می‌شود.

نیازهای داده‌ای پروژه:

- داده رابطه‌ای با **integrity بالا** (کاربر، محتوای آموزشی، پیشرفت، تاریخچه مرور).
- کوئری‌های **تحلیلی و ترکیبی** روی حجم رو به رشد داده (آمار پیشرفت، صف مرور، برنامه‌ریزی تکرار).
- مسیر request کاملاً **async**، بدون بلاک شدن event loop.
- **Schema تحت کنترل نسخه** با migrationهای قابل بازبینی در PR.
- تراکنش‌های قابل ردیابی با مرز مشخص، به‌طوری که atomicity هر use case صریح باشد.
- امکان رشد تدریجی بدون تعویض دیتابیس.

محدودیت‌های اعلام‌شده برای این مرحله:

- استفاده از نسخه Beta/Alpha/RC ممنوع است.
- PgBouncer، `pg_trgm` و `pgvector` فعلاً وارد dependencies یا زیرساخت نمی‌شوند.
- انتخاب Production provider و برنامه ارتقا به PostgreSQL 19 به آینده موکول شده است.
- در این مرحله هیچ مدل، جدول یا migration طراحی نمی‌شود.

---

## Decision

### خلاصه تصمیمات (D-01 تا D-18)

| ID | موضوع | تصمیم |
| --- | --- | --- |
| **D-01** | DBMS | **PostgreSQL** تنها دیتابیس اصلی پروژه؛ هیچ دیتابیس جایگزینی در نظر گرفته نمی‌شود. |
| **D-02** | Major Version | **PostgreSQL 18**؛ استفاده از Beta/Alpha/RC ممنوع. |
| **D-03** | Minor Version | همیشه **آخرین minor همان major** نصب/اجرا می‌شود (در زمان ثبت: `18.6`). به‌روزرسانی minor یک **سیاست نگهداری** است، نه تصمیم جداگانه. |
| **D-04** | ORM | **SQLAlchemy 2.1.x** به‌صورت async (`AsyncSession`, `create_async_engine`). |
| **D-05** | Driver | **psycopg 3.3.x** به‌عنوان driver اصلی، با dialect `postgresql+psycopg`. |
| **D-06** | Migration | **Alembic 1.20.x** با قالب async. |
| **D-07** | Connection Pool | **فقط pool داخلی SQLAlchemy**؛ `psycopg_pool` نصب یا پیکربندی نمی‌شود. |
| **D-08** | Session scope | `AsyncSession` در سطح **Request** (از طریق dependency). |
| **D-09** | Transaction scope | Transaction در سطح **Use Case / Service**؛ `commit` در Router و Repository **ممنوع**. |
| **D-10** | Isolation | `READ COMMITTED` پیش‌فرض؛ `SERIALIZABLE` پیش‌فرض نیست. |
| **D-11** | FSRS Concurrency | ترتیب بررسی: **Idempotency → Optimistic Concurrency → Targeted Locking**؛ `SERIALIZABLE` آخرین گزینه. |
| **D-12** | شناسه‌ها | `uuidv7()` فعلاً **فقط یک گزینه پیشنهادی** است؛ برای هیچ Entity اجباری نیست. تصمیم در مرحله طراحی مدل‌ها. |
| **D-13** | Health | دو endpoint مستقل: `GET /health` (Liveness، بدون DB) و `GET /ready` (Readiness، با بررسی DB). قطع DB مانع Startup اجباری نمی‌شود. |
| **D-14** | Dev infra | **Docker Compose + PostgreSQL 18**. |
| **D-15** | CI infra | **PostgreSQL واقعی در container مستقل** برای تست. |
| **D-16** | خارج از Scope | **PgBouncer، `pg_trgm`، `pgvector`** نه در dependencies و نه در زیرساخت. |
| **D-17** | Production | انتخاب Production provider و برنامه ارتقا به PostgreSQL 19 به **مراحل آینده** موکول شد. |
| **D-18** | مستندات | این ADR + خلاصه کوتاه در `README.md` به‌عنوان مرجع تصمیمات دیتابیس. |

### جزئیات تصمیمات

#### نسخه PostgreSQL (D-02, D-03)

- **Major** روی ۱۸ تثبیت شده است: GA در ۲۵ سپتامبر ۲۰۲۵، پشتیبانی رسمی تا ۱۴ نوامبر ۲۰۳۰.
- **Minor** در زمان نصب/استقرار همیشه آخرین نسخه موجود است، نه نسخه ثابت‌شده در تاریخ این سند. در زمان ثبت، `18.6` (۱۳ اوت ۲۰۲۶) منتشر شده و minor بعدی طبق roadmap در **۱۲ نوامبر ۲۰۲۶** برنامه‌ریزی شده است.
- هیچ minor در `pyproject.toml` یا manifestها pin نمی‌شود؛ tag تصویر dev برابر `18` است (نه `18.6`) تا همیشه آخرین patch همان major بالا بیاید.
- در محیط‌های managed، فعال بودن **auto minor upgrade** یک الزام عملیاتی است و در مرحله انتخاب provider بررسی می‌شود.
- **PostgreSQL 19 در این مرحله مجاز نیست**: در ۱۵ اکتبر ۲۰۲۶ وارد RC1 شده و GA آن ۱۹ نوامبر ۲۰۲۶ برنامه‌ریزی شده است؛ طبق D-02 نسخه RC قابل انتخاب نیست (به D-17 مراجعه شود).
- نسخه‌های ۱۴ و پایین‌تر (۱۴ در ۱۲ نوامبر ۲۰۲۶ EOL می‌شود) و ۱۵/۱۶/۱۷ به‌عنوان major انتخابی در نظر گرفته نشدند؛ ۱۸ هم جدیدترین نسخه پایدار و هم طولانی‌ترین پنجره پشتیبانی در میان گزینه‌های مجاز را دارد.

#### Stack (D-04, D-05, D-06)

- **ORM:** SQLAlchemy 2.1.x؛ `sqlalchemy[asyncio]` الزامی است، چون از نسخه ۲.۱ وابستگی `greenlet` دیگر به‌صورت پیش‌فرض نصب نمی‌شود و بدون extra، import کردن `sqlalchemy.ext.asyncio` خطا می‌دهد.
- **Driver:** psycopg 3.3.x با dialect `postgresql+psycopg`. یک driver برای **هر سه مصرف**: اپلیکیشن async، Alembic، و scriptهای maintenance/seed. `asyncpg` به‌عنوان driver اصلی انتخاب نشد (به بخش Alternatives مراجعه شود).
- **Migration:** Alembic 1.20.x با قالب async (`async_engine_from_config` + `connection.run_sync(do_run_migrations)`).
- **منبع حقیقت URL:** فقط `DATABASE_URL` در `Settings`؛ `alembic.ini` هیچ `sqlalchemy.url` ندارد و Alembic همان تنظیمات اپ را import می‌کند.
- **پیش‌نیاز سازگاری:** psycopg 3 از Python 3.10–3.14 و PostgreSQL 10–18 پشتیبانی می‌کند و SQLAlchemy 2.1 روی Python 3.11+ (شامل 3.14) تست شده است. پروژه روی CPython 3.14 استاندارد است، نه free-threaded (`cp314t`).

#### Connection Pooling (D-07)

- تنها منبع اتصال: **pool داخلی SQLAlchemy** (`AsyncAdaptedQueuePool` از طریق `create_async_engine`).
- `psycopg_pool` **نصب یا پیکربندی نمی‌شود**؛ هیچ pool دومی ساخته نمی‌شود تا دو منبع اتصال موازی و سقف‌های ناهم‌خوان وجود نداشته باشد.
- پارامترها فقط از `Settings` خوانده می‌شوند: `pool_size`، `max_overflow`، `pool_timeout`، `pool_recycle`، و `pool_pre_ping=True`.
- `pool_pre_ping=True` الزامی است (تشخیص اتصال مرده قبل از استفاده، مخصوصاً پس از restart دیتابیس یا قطعی شبکه).
- سقف ظرفیت: `replicas × (pool_size + max_overflow) < max_connections` سرور، با احتساب سهم Alembic و ابزارهای عملیاتی.
- **Alembic** با `poolclass=NullPool` (کلاس خود SQLAlchemy، نه `psycopg_pool`) و engine موقت اجرا می‌شود تا هرگز از pool اپ استفاده نکند.
- اگر در آینده pooler خارجی اضافه شود، این تصمیم باید در یک ADR جدید بازبینی شود (NullPool + تنظیم prepared statement در psycopg). این بازبینی بخشی از تصمیم فعلی نیست.

#### Session و Transaction (D-08, D-09)

`AsyncSession` در سطح request ساخته و بسته می‌شود، اما **مرز تراکنش** در لایه service است:

| لایه | مسئولیت | مجاز / ممنوع |
| --- | --- | --- |
| **Request (dependency)** | ساخت `AsyncSession` از `async_sessionmaker`، `yield`، و `close()` در پایان | فقط ساخت/بستن؛ در صورت exception منتشرشده `rollback()` به‌عنوان **شبکه ایمنی** |
| **Service / Use Case** | مالک atomicity و منطق کسب‌وکار | `commit()` در مسیر موفق، `rollback()` در مسیر خطا، تعیین مرز تراکنش |
| **Repository** | فقط دسترسی به داده | `add` / `execute` / `flush`؛ **هیچ** `commit` / `rollback` / `begin` |
| **Router** | HTTP، validation، mapping پاسخ | **هیچ** عملیات تراکنشی؛ session فقط به service داده می‌شود |

نکات الزامی:

- `async_sessionmaker(expire_on_commit=False)` تا اشیاء پس از commit در ساخت پاسخ قابل استفاده باشند.
- یک request می‌تواند چند use case را فراخوانی کند و هر use case تراکنش مستقل خودش را داشته باشد.
- عملیات غیرقابل بازگشت یا خارجی (ارسال ایمیل، فراخوانی API بیرونی، enqueue job) هرگز داخل تراکنش باز انجام نمی‌شود.
- `lazy="raise"` برای relationshipها به‌صورت پیش‌فرض، برای جلوگیری از بارگذاری ناخواسته در async؛ بارگذاری صریح با `selectinload` / `joinedload`.
- `MetaData(naming_convention=...)` از ابتدا، برای نام‌گذاری پایدار constraintها و جلوگیری از migrationهای پرنویز.
- `Base.metadata.create_all()` در هیچ محیطی استفاده نمی‌شود؛ schema فقط با Alembic مدیریت می‌شود.

#### هم‌زمانی FSRS (D-10, D-11)

`READ COMMITTED` پیش‌فرض است و `SERIALIZABLE` پیش‌فرض نیست. برای عملیات هم‌زمان FSRS، ترتیب بررسی راهکارها:

1. **Idempotency** — هر ثبت مرور یک کلید یکتا دارد (از سمت کلاینت یا مشتق از `(user_id, card_id, review_session_id)`). ارسال دوباره همان درخواست همان اثر را دارد و نتیجه قبلی برگردانده می‌شود. این راهکار اولویت اول است، چون تا حد زیادی نیاز به قفل را حذف می‌کند.
2. **Optimistic Concurrency** — یک ستون نسخه (`version` / `updated_at`) و شرط اتمیک `UPDATE ... WHERE version = :expected`؛ اگر صفر ردیف به‌روزرسانی شد ⇒ `409 Conflict` و کلاینت وضعیت تازه را می‌گیرد. گزینه طبیعی برای وضعیت کارت FSRS که یک ردیف per card است.
3. **Targeted Locking** — فقط در صورت نیاز: `SELECT ... FOR UPDATE` روی همان ردیف، یا advisory lock برای عملیات سطح کاربر (مثل reset یک deck). دامنه قفل حداقلی و کوتاه.
4. **`SERIALIZABLE`** — تنها برای عملیات چندردیفی که سه راهکار بالا کافی نبودند، با retry صریح روی `40001`. افزودن آن یک تصمیم مستند و موردی است.

قاعده: هر راهکار هم‌زمانی باید با تست هم‌زمانی واقعی (دو session موازی روی PostgreSQL واقعی) تأیید شود، نه با فرض.

#### شناسه‌ها (D-12)

- `uuidv7()` فقط یک **گزینه پیشنهادی** در toolbox طراحی است و برای هیچ Entity اجباری نیست.
- تصمیم نهایی برای هر Entity (نوع شناسه، تولید سمت DB یا اپ، `bigint identity` در برابر UUID) در **مرحله طراحی مدل‌ها** و بر اساس حجم نوشتن، نیاز به ترتیب زمانی، عمومی بودن شناسه و هزینه ایندکس گرفته می‌شود.
- دو قاعده از همین حالا قطعی است: (۱) هیچ شناسه قابل حدس با شمارش برای منابع عمومی استفاده نشود؛ (۲) تولید شناسه در یک لایه متمرکز باشد (DB یا اپ)، نه هر دو.

#### Health و Startup (D-13)

- `GET /health` → **Liveness**: هیچ تماس دیتابیسی ندارد؛ فقط وضعیت فرآیند و metadata سرویس. پاسخ فعلی endpoint حفظ می‌شود.
- `GET /ready` → **Readiness**: یک `SELECT 1` سبک با timeout کوتاه روی session؛ در صورت عدم دسترسی به DB پاسخ `503` برمی‌گرداند تا load balancer ترافیک را قطع کند.
- **Startup fail-fast وجود ندارد**: قطع بودن DB هنگام startup باعث توقف فرآیند نمی‌شود؛ فقط یک `warning` ساختاریافته لاگ می‌شود و سرویس بالا می‌آید و `not ready` می‌ماند (جلوگیری از crash loop در محیط container/cloud).
- در shutdown، `engine.dispose()` فراخوانی می‌شود.
- `/ready` هرگز خطای خام دیتابیس را به کلاینت برنمی‌گرداند؛ جزئیات فقط در لاگ سرور با `request_id` ثبت می‌شود.
- این تغییرات با افزودن route و schema به ماژول `health` موجود انجام می‌شود و ساختار ماژولار را تغییر نمی‌دهد.

#### زیرساخت Development و CI (D-14, D-15)

| محیط | تصمیم |
| --- | --- |
| **Development** | Docker Compose با image `postgres:18-alpine`، volume پایدار، پورت فقط روی loopback، healthcheck داخلی، متغیرهای `POSTGRES_*` از `.env` (که commit نمی‌شود). بدون pooler و بدون extension اضافه. |
| **CI** | PostgreSQL واقعی در **container مستقل** per job/run؛ دیتابیس مجزا برای تست‌ها؛ `alembic upgrade head` قبل از اجرای تست‌ها؛ استفاده از دیتابیس اختصاصی CI، نه دیتابیس توسعه. |
| **Production** | در این مرحله تصمیمی گرفته نمی‌شود (D-17). الزام آینده: هر provider انتخاب‌شده باید PG 18، PITR و auto minor upgrade را پوشش بدهد. |

`DATABASE_URL` تنها منبع حقیقت اتصال است (DSN کامل، پوشیده از لاگ در `Settings`) و هم اپلیکیشن و هم Alembic از همان می‌خوانند. برای محیط‌های غیرمحلی `sslmode` برابر `require` یا `verify-full` است.

#### موارد خارج از Scope (D-16)

PgBouncer، `pg_trgm` و `pgvector` — نه نصب، نه پیکربندی، نه ورود به dependencies. اگر روزی نیاز شوند (جستجوی fuzzy یا embedding)، هر یک با ADR جداگانه و تأیید مستقل بررسی می‌شود.

#### موکول‌شده به آینده (D-17)

1. **انتخاب Production provider** — مقایسه سرویس‌های managed PostgreSQL (Neon / Supabase / RDS / Cloud SQL / DigitalOcean / self-hosted) با معیارهای region، هزینه، PITR، پشتیبانی PG 18 و امکان branching برای preview.
2. **ارتقا به PostgreSQL 19** — پس از GA (۱۹ نوامبر ۲۰۲۶) و پخته شدن چند minor؛ مسیر ارتقا (`pg_upgrade` یا logical replication) در همان زمان بررسی می‌شود.
3. **بازبینی pooler** — هر تغییری که نیاز به pooler خارجی داشته باشد و D-07 را تحت تأثیر قرار دهد.

### اصول مهندسی پذیرفته‌شده

این اصول بخشی از تصمیمات تأییدشده همین مرحله‌اند و در مرحله پیاده‌سازی رعایت می‌شوند (بدون تصمیم جدید):

| ID | اصل | جزئیات |
| --- | --- | --- |
| **P-01** | Timezone | همه timestampها `TIMESTAMPTZ` در **UTC**؛ `TIMESTAMP` بدون timezone ممنوع؛ زمان‌ها در اپ همیشه timezone-aware؛ `TimeZone` سرور `UTC`؛ تبدیل به timezone کاربر فقط در لایه presentation. داده‌های «روز تقویمی» به‌صورت `DATE` + timezone کاربر. |
| **P-02** | Migration workflow | Alembic به‌عنوان گام **release** قبل از استقرار کد اجرا می‌شود، نه در `lifespan`. گراف خطی، یک migration per PR، بازبینی دستی فایل autogenerate، `compare_type` و `compare_server_default` فعال، import صریح مدل‌ها در `env.py`. `downgrade` الزام محیط توسعه است، نه رویه production. |
| **P-03** | Schema evolution | الگوی **expand/contract** برای تغییرات شکستنی: افزودن ستون nullable → backfill → استقرار کد جدید → حذف/سخت‌تر کردن. |
| **P-04** | Credentials | نقش اپ با حداقل دسترسی (بدون `SUPERUSER` / `CREATEDB` / `CREATEROLE`)، رمز فقط در secret store محیط، rotation دوره‌ای، هیچ رمزی در repo، لاگ یا خروجی ابزار. |
| **P-05** | Environment variables | فقط `DATABASE_URL` به‌عنوان DSN کامل، در `Settings` پوشیده از `repr`/لاگ؛ پارامترهای pool و timeout نیز تنظیمات `Settings` با پیش‌فرض امن، نه hardcode. `.env` هرگز commit نمی‌شود. |
| **P-06** | Backup | Development: بدون backup (داده seed بازتولیدپذیر). Production: **PITR** + snapshot دوره‌ای + **restore drill** دوره‌ای؛ backup بدون تست restore معتبر نیست. جزئیات retention همراه با انتخاب provider. |
| **P-07** | خطای اتصال | `pool_pre_ping=True`؛ retry با backoff فقط برای خطاهای گذرا (`OperationalError`، `DisconnectionError`، `40001`، `40P01`) و فقط روی عملیات idempotent؛ بدون retry کورکورانه روی commit نامشخص؛ timeouts اجباری: `connect_timeout`، `statement_timeout`، `lock_timeout`، `pool_timeout`؛ `idle_in_transaction_session_timeout` روی نقش/سرور. |
| **P-08** | Indexing | ایندکس روی هر FK (PostgreSQL خودکار نمی‌سازد)؛ unique index برای کلیدهای طبیعی؛ partial index برای زیرمجموعه‌های پرتکرار؛ ایندکس ترکیبی با ترتیب `(owner_id, created_at DESC)`؛ توجیه هر ایندکس با `EXPLAIN (ANALYZE, BUFFERS)`؛ نام‌گذاری صریح ایندکس‌ها. |
| **P-09** | کنترل drift | CI علاوه بر `alembic upgrade head`، `alembic check` را برای تشخیص اختلاف metadata و schema اجرا می‌کند. |

---

## Consequences

### پیامدهای مثبت

- **یک driver برای همه مصرف‌ها**: psycopg 3 هم اپلیکیشن async و هم Alembic و هم scriptها را پوشش می‌دهد؛ نگهداری ساده‌تر و رفتار یکسان در همه مسیرها.
- **مرز تراکنش قابل ردیابی**: با تمرکز commit در service، atomicity هر use case صریح و قابل تست است و اشتباهات رایج (commit در repository یا در router) از ساختار کد قابل تشخیص است.
- **نبود وابستگی اضافی**: حذف `psycopg_pool` و نبود pooler، تعداد اجزای عملیاتی و حالت‌های شکست را کاهش می‌دهد.
- **پایداری در قطعی دیتابیس**: تفکیک liveness و readiness و نبود fail-fast، از crash loop جلوگیری می‌کند.
- **سازگاری کامل با Python 3.14 و FastAPI** و مسیر ارتقای روشن (SQLAlchemy 2.1 روی Python 3.11+ و psycopg روی 3.10–3.14).
- **دسترسی به ویژگی‌های PG 18** که مستقیم به workload این پروژه مربوط‌اند: `uuidv7()` (به‌عنوان گزینه)، AIO، B-tree skip scan، virtual generated columns، `RETURNING OLD/NEW`.
- **تکرارپذیری محیط**: dev و CI هر دو روی PG 18 واقعی اجرا می‌شوند، بدون mock کردن دیتابیس.

### پیامدهای منفی و هزینه‌ها

- **Discipline لازم است**: مدل session/transaction فقط با انضباط تیمی حفظ می‌شود؛ هر commit در repository یا router یک نقض قابل بازبینی است.
- **سقف اتصال به replicas گره خورده است**: بدون pooler خارجی، افزایش تعداد instanceهای اپ مستقیماً فشار روی `max_connections` می‌آورد و نیازمند محاسبه ظرفیت است.
- **منحنی یادگیری**: SQLAlchemy 2.1 async (شامل ممنوعیت lazy loading و نیاز به eager loading صریح) برای اعضای جدید تیم هزینه یادگیری دارد.
- **وابستگی به Alembic برای هر تغییر schema**: هیچ مسیر «خودکار» وجود ندارد و autogenerate همیشه نیازمند بازبینی انسانی است.
- **`sqlalchemy[asyncio]` و `greenlet`**: از ۲.۱، این وابستگی صریحاً باید نصب شود؛ فراموش کردن extra یک خطای محیطی رایج است.
- **بدون PgBouncer، عملیات failover/restart دیتابیس** با خطاهای کوتاه اتصال دیده می‌شود؛ کاهش اثر آن به `pool_pre_ping` و retry محدود وابسته است.

### ریسک‌ها و کاهش آن‌ها

| ریسک | کاهش |
| --- | --- |
| N+1 و `MissingGreenlet` در async | `lazy="raise"` + بارگذاری صریح + تست‌های مسیرهای پرترافیک |
| تراکنش‌های آویزان | `idle_in_transaction_session_timeout` + مرز کوتاه تراکنش در service |
| از دست رفتن داده در migration اشتباه | بازبینی اجباری فایل، expand/contract، backup/PITR در production |
| اتمام اتصال‌ها زیر بار | محاسبه `replicas × (pool_size + max_overflow)` و پایش مصرف pool |
| drift بین مدل‌ها و schema | `alembic check` در CI (P-09) |
| تأخیر در دریافت patch امنیتی | سیاست D-03 (همیشه آخرین minor) و auto minor upgrade در provider |

---

## Alternatives

### SQLModel — رد شد

مزیت واقعی داشت: کاهش تکرار بین مدل جدول و schema API. اما برای پروژه‌ای با چندین domain و کوئری‌های تحلیلی:

- نسخه‌گذاری `0.0.x` و API ناپایدار برای یک پروژه بلندمدت.
- لایه نازک روی SQLAlchemy است؛ برای relationshipها و کوئری‌های پیچیده باید به SQLAlchemy خام برگشت — یعنی هر دو را داری، نه یکی.
- وابستگی به زمان‌بندی release یک کتابخانه میانی برای سازگاری با SQLAlchemy (تا نسخه 2.1، SQLAlchemy در `<2.1` pin شده بود؛ سازگاری در `0.0.48` اضافه شد).
- Alembic را حذف نمی‌کند، پس بخشی از ساده‌سازی وعده‌داده‌شده محقق نمی‌شود.

### asyncpg به‌عنوان driver اصلی — رد شد

سریع‌ترین گزینه در throughput خام است، اما:

- فقط async است؛ Alembic، scriptهای maintenance و ابزارهای ops به یک driver دوم (sync) نیاز پیدا می‌کنند.
- dialect `postgresql+asyncpg` در برخی type و رفتار prepared statement تفاوت دارد.
- برای محیط‌هایی که در آینده ممکن است pooler در حالت transaction داشته باشند، انعطاف کمتری نسبت به psycopg دارد.

`asyncpg` حذف نشده است؛ به‌عنوان گزینه پشتیبان/بنچمارک در دسترس می‌ماند، اما بخشی از stack فعلی نیست.

### PostgreSQL 19 — فعلاً رد شد

در تاریخ ثبت این ADR در **RC1** (از ۱۵ اکتبر ۲۰۲۶) است و GA آن ۱۹ نوامبر ۲۰۲۶ برنامه‌ریزی شده؛ طبق D-02 نسخه RC قابل انتخاب نیست. ارتقا به D-17 موکول شد.

### PgBouncer — موکول شد

با یک فرآیند اپ و pool داخلی SQLAlchemy، pooler خارجی پیچیدگی اضافی و ریسک prepared statement دارد. اگر تعداد instanceها یا الگوی اتصال تغییر کرد، در ADR جداگانه بررسی می‌شود (D-16, D-17).

### `psycopg_pool` — رد شد

داشتن دو pool موازی (SQLAlchemy و psycopg) سقف اتصال و رفتار timeout را دوپاره می‌کند. pool داخلی SQLAlchemy کافی است (D-07).

### majorهای قدیمی‌تر (17/16/15/14) — رد شد

پنجره پشتیبانی کوتاه‌تر (۱۴ در ۱۲ نوامبر ۲۰۲۶ EOL می‌شود) و نبود ویژگی‌های PG 18 که به workload این پروژه مربوط‌اند.

---

## Deferred Decisions

### موکول‌شده به مراحل بعد (با مرجع)

| موضوع | مرجع | مرحله تصمیم |
| --- | --- | --- |
| انتخاب Production provider (Neon / Supabase / RDS / Cloud SQL / DigitalOcean / self-hosted) | D-17 | مرحله زیرساخت production |
| برنامه و مسیر ارتقا به PostgreSQL 19 | D-17 | پس از GA و پخته شدن چند minor |
| بازبینی نیاز به pooler خارجی و اثر آن بر D-07 | D-07, D-17 | همراه با انتخاب provider |
| استراتژی شناسه‌ها (`uuidv7` در برابر `bigint`، محل تولید) برای هر Entity | D-12 | مرحله طراحی مدل‌ها |
| تفکیک نقش migration از نقش runtime اپ | P-04 | مرحله production / استقرار |
| نام و شکل دقیق کلیدهای `Settings` (URL، pool، timeout) | P-05 | مرحله پیاده‌سازی زیرساخت |
| آستانه‌ها و قالب payload پاسخ `/ready` | D-13 | مرحله پیاده‌سازی health |
| سیاست retention بکاپ | P-06 | همراه با انتخاب provider |

### موارد حل‌نشده (Open Items)

1. **تفکیک نقش‌ها** — پیشنهاد جدا کردن نقش migration (مالک DDL) از نقش runtime (فقط DML/SELECT) باقی است، اما به provider و رویه deploy وابسته است؛ تا آن زمان یک نقش با حداقل دسترسی کافی است.
2. **سیاست retention و RPO/RTO** — بدون انتخاب provider قابل تثبیت نیست.
3. **نیاز آینده به extensionها** (`pg_trgm` برای جستجوی fuzzy، `pgvector` برای embedding) — امروز خارج از scope (D-16)؛ در صورت نیاز، ADR جداگانه.
4. **معیارهای ظرفیت** (`pool_size`، تعداد replicas، `max_connections`) — پس از مشخص شدن topology استقرار.

### صریحاً خارج از Scope این ADR

- طراحی جدول، Entity، relationship یا migration.
- انتخاب Production provider و اجرای آن.
- نصب یا پیکربندی PgBouncer، `pg_trgm`، `pgvector`، `psycopg_pool`.
- جایگزین کردن یا ارزیابی دیتابیس‌های غیر PostgreSQL.
- تغییر ساختار ماژولار موجود پروژه (`core/` و `modules/`).
