# MVP 1 — موارد انجام‌شده و وضعیت تست

این فایل تنها مرجع «چه چیزی ساخته شده و چه چیزی هنوز تأیید نشده» است.
قاعده به‌روزرسانی: هر آیتم تا وقتی کاربر دستی تست نکرده **⏳ تست‌نشده** می‌ماند؛ بعد از تأیید او به **✅ تست‌شده** تغییر می‌کند و تاریخ می‌خورد.

آخرین به‌روزرسانی: ۱۴۰۵/۰۸/۲۳ (2026-11-14)

راهنما: ✅ پیاده‌شده/تأییدشده · ⏳ پیاده‌شده ولی دستی تست‌نشده · ⬜ هنوز پیاده نشده · 🧪 فقط تست خودکار دارد

---

## ۱. وضعیت کلی

| بخش | پیاده‌سازی | تست خودکار | تأیید دستی کاربر |
| --- | --- | --- | --- |
| مدل داده و migration | ✅ ۳۸ جدول | 🧪 | ⏳ |
| احراز هویت v1 (تلفن + OTP) | ✅ | 🧪 ۲۹ تست | ⏳ |
| سشن و توکن | ✅ | 🧪 | ⏳ |
| هندلر خطای سراسری | ✅ | 🧪 | ⏳ |
| ماژول Review (FSRS) | ✅ | 🧪 ۸ تست | ⏳ |
| Health / readiness | ✅ | 🧪 | ⏳ |
| اجرا روی PostgreSQL واقعی | — | ⬜ | ⬜ |
| ارائه‌دهنده پیامک واقعی | — | ⬜ | ⬜ |

---

## ۲. پایه و زیرساخت

| # | مورد | فایل | وضعیت |
| --- | --- | --- | --- |
| 1 | تنظیمات typed با pydantic-settings | `core/config.py` | ⏳ |
| 2 | موتور async + session factory + readiness | `core/database.py` | ⏳ |
| 3 | لاگ ساختاریافته | `core/logging.py` | ⏳ |
| 4 | Enumهای دامنه (۳۱ عدد) | `core/enums.py` | ✅ |
| 5 | UUIDv7 و mixinهای زمان | `core/types.py` | ✅ |
| 6 | Migration پایه: ۳۸ جدول + ۳۱ type | `alembic/versions/0001_initial_schema.py` | ⏳ |
| 7 | تجمیع مدل‌ها برای metadata | `models.py` | ✅ |

### ساختار پوشه‌ها (همان‌طور که الان هست)

```
src/lurnian/
  main.py                     نقطه ورود؛ فقط app می‌سازد
  api/
    router.py                 روتر v1 (auth + review)
    errors.py                 قالب خطا، request-id، هندلرهای ۴۰۰/۴۰۱/۴۰۴/۴۰۹/۴۲۲/۴۲۹/۵۰۰
  core/                       config, database, security, exceptions, enums, types, logging
  modules/
    auth/
      domain/                 phone.py, clock.py  (قواعد خالص، بدون I/O)
      application/            auth_service.py, session_service.py, ports.py, dto.py
      infrastructure/         identity_models.py, security_models.py, repositories.py,
                              tokens.py, sms.py, account_defaults.py
      presentation/           router.py, schemas.py, dependencies.py
    review/                   fsrs.py, service.py, router.py, schemas.py, models.py
    learning/                 models.py, service.py (کوئری‌های خواندنی)
    profile/                  models.py, service.py
    billing/ notification/ platform/ health/
tests/                        conftest + ۷ فایل تست
docs/
  architecture/               database-design.md, database-catalog.md, mvp-v1.md
  api/                        auth-v1.md
  mvp1/                       همین فایل
```

قواعد لایه‌ها: `presentation` فقط ورودی/خروجی؛ `application` منطق و تراکنش؛ `infrastructure` SQL و آداپتر؛ `domain` بدون وابستگی. `api/router.py` تنها جایی است که روترها به هم وصل می‌شوند.

---

## ۳. احراز هویت v1

سیاست توکن: access **۳۰ دقیقه** (بی‌حالت، HS256، ذخیره نمی‌شود) · refresh **۳۶۵ روز** (یک‌بارمصرف، چرخشی، فقط هش SHA-256) · سقف سشن **۳۶۵ روز**.

| # | قابلیت | جزئیات | وضعیت |
| --- | --- | --- | --- |
| 8 | نرمال‌سازی شماره | `0912…`, `+98…`, `0098…` → E.164 | ⏳ |
| 9 | `POST /auth/otp/request` | کد ۶ رقمی، HMAC با pepper، ۱۲۰ ثانیه، cooldown ۶۰ ثانیه | ⏳ |
| 10 | باطل‌کردن کد قبلی | کدهای pending همان شماره `invalidated_at` می‌گیرند | ⏳ |
| 11 | `POST /auth/otp/verify` | قفل ردیف، مصرف کد، سقف ۵ تلاش، شمارش تلاش | ⏳ |
| 12 | ساخت کاربر در اولین ورود | `users` + `user_settings` + `fsrs_settings` | ⏳ |
| 13 | ورود کاربر قدیمی | همان مسیر، بدون ساخت رکورد جدید | ⏳ |
| 14 | برگشت داده کاربر همراه توکن | پاسخ `/otp/verify`: `{user, tokens, is_new_user}` | ⏳ |
| 15 | `POST /auth/refresh` | چرخش توکن، همان `family_id`، `parent_id` زنجیره | ⏳ |
| 16 | تشخیص استفاده مجدد | توکن مصرف‌شده → بستن خانواده + سشن + کد `auth.refresh_reused` | ⏳ |
| 17 | `POST /auth/logout` | `revoked_at` روی سشن و همه توکن‌های همان سشن | ⏳ |
| 18 | `GET /auth/me` | کاربر جاری از روی access token | ⏳ |
| 19 | `GET /auth/sessions` | لیست سشن‌های فعال + پرچم `current` | ⏳ |
| 20 | `DELETE /auth/sessions/{id}` | بستن یک سشن دیگر (فقط مال خود کاربر) | ⏳ |
| 21 | `POST /auth/sessions/revoke-all` | بستن بقیه با `keep_current` | ⏳ |
| 22 | اعتبارسنجی سشن در هر درخواست | توکن بی‌حالت + چک `user_sessions` (ابطال فوری) | ⏳ |
| 23 | ارسال پیامک | آداپتر لاگ؛ کد در لاگ و در `debug_code` فقط در development | ⏳ |
| 24 | حساب غیرفعال | `403 auth.account_disabled` و سوزاندن کد | ⏳ |
| 25 | حذف مسیرهای ایمیل/رمز | `/auth/login` و `/auth/register` دیگر وجود ندارند | ⏳ |

متغیرهای `.env` که اضافه شدند: `ACCESS_TOKEN_TTL_MINUTES=30`, `REFRESH_TOKEN_TTL_DAYS=365`, `SESSION_ABSOLUTE_TTL_DAYS=365`, `DEFAULT_PHONE_COUNTRY_CODE=98`, `OTP_LENGTH=6`, `OTP_TTL_SECONDS=120`, `OTP_MAX_ATTEMPTS=5`, `OTP_RESEND_COOLDOWN_SECONDS=60`, `OTP_PEPPER` (مقدار تصادفی ساخته شد), `OTP_EXPOSE_IN_RESPONSE=true` (فقط توسعه).

---

## ۴. خطا و پاسخ

| # | مورد | جزئیات | وضعیت |
| --- | --- | --- | --- |
| 26 | قالب واحد خطا | `{"error": {code, message, request_id, details}}` | ⏳ |
| 27 | هندلر ۴۲۲ | فهرست فیلدهای نامعتبر در `details.fields` | ⏳ |
| 28 | هندلر ۴۰۴/۴۰۵/۴۰۱/۴۰۳ | همان قالب، کد قابل برنامه‌نویسی | ⏳ |
| 29 | هندلر ۴۰۹ | `IntegrityError` → `conflict` | ⏳ |
| 30 | هندلر ۵۰۰ | لاگ استک + پاسخ بی‌جزئیات | ⏳ |
| 31 | `X-Request-ID` | تولید/اکو در هدر و بدنه خطا | ⏳ |
| 32 | کدهای خطای auth | `auth.invalid_code`, `auth.code_expired`, `auth.code_cooldown`, `auth.too_many_attempts`, `auth.refresh_reused`, `auth.session_revoked`, … | ⏳ |

مستند کامل مسیرها و کدها: `docs/api/auth-v1.md`.

---

## ۵. Review (از مرحله قبل)

| # | مورد | وضعیت |
| --- | --- | --- |
| 33 | زمان‌بندی FSRS-5 (`fsrs.py`) | ✅ (۸ تست) |
| 34 | صف امروز با سقف جدید/مرور و منطقه زمانی کاربر | ⏳ |
| 35 | ثبت پاسخ با idempotency `(user_id, idempotency_key)` | ⏳ |
| 36 | optimistic concurrency با `row_version` (۴۰۹) | ⏳ |
| 37 | ثبت outbox event هنگام زمان‌بندی | ⏳ |

---

## ۶. تست‌ها و کیفیت

| # | مورد | وضعیت |
| --- | --- | --- |
| 38 | `pytest -q` → ۷۰ passed (شامل تست‌های بازبینی امنیتی) | 🧪 اجرا شده |
| 39 | تست قواعد خالص: شماره، OTP، عمر توکن‌ها، گارد production | 🧪 |
| 40 | تست use case با fake: کد اشتباه/منقضی/مصرف‌شده، cooldown، سقف تلاش و سقف ساعتی، حساب حذف‌شده، خطای پیامک، چرخش و reuse، revoke-all | 🧪 |
| 41 | تست HTTP: ۴۰۱، ۴۰۲ نبود مسیر قدیمی، ۴۰۰ شماره، ۴۲۲ کد، قالب خطا و `X-Request-ID` | 🧪 |
| 42 | `ruff check` و `ruff format --check` | ✅ |
| 43 | `alembic upgrade head --sql` (۳۹ CREATE TABLE) | ✅ |
| 44 | اجرای واقعی روی PostgreSQL و تست انتها-به-انتها | ⬜ |
| 45 | تست با پیامک واقعی | ⬜ |

---

## ۷. مستندات

| # | فایل | وضعیت |
| --- | --- | --- |
| 46 | `docs/architecture/database-design.md` | ✅ تأییدشده |
| 47 | `docs/architecture/database-catalog.md` (۳۸ جدول + توضیح و مثال) | ✅ تأییدشده |
| 48 | `docs/architecture/mvp-v1.md` (دامنه v1 + ۹ دیاگرام) | ✅ |
| 49 | `docs/api/auth-v1.md` | ⏳ |
| 50 | `docs/mvp1/mvp-1.md` (همین فایل) | ✅ |

---

## ۸. بازبینی امنیتی و کیفیت (۱۴۰۵/۰۸/۲۳)

ایرادهای پیدا‌شده و اصلاح‌شده:

| # | مشکل | شدت | اصلاح | وضعیت |
| --- | --- | --- | --- | --- |
| 1 | حساب حذف نرم‌شده می‌توانست با OTP وارد شود (شماره هنوز در unique index بود) | بالا | بررسی `deleted_at` و `403 auth.account_deleted` در verify | ⏳ تست‌نشده |
| 2 | با خطای ارسال پیامک، کد معتبر می‌ماند و cooldown ۶۰ ثانیه‌ای راه را می‌بست | متوسط | باطل‌کردن چالش و commit قبل از ۵۰۳ | ⏳ تست‌نشده |
| 3 | `request_id` در پاسخ ۵۰۰ گم می‌شد (ریست contextvar قبل از هندلر) | متوسط | contextvar دیگر ریست نمی‌شود | ⏳ تست‌نشده |
| 4 | هیچ سقفی برای حجم درخواست کد نبود (SMS bomb و هزینه) | بالا | سقف ساعتی ۵ برای شماره و ۲۰ برای IP | ⏳ تست‌نشده |
| 5 | اجرا در production با `JWT_SECRET` پیش‌فرض، دور زدن کامل احراز هویت بود | بحرانی | `validate_production_settings` و توقف startup | ⏳ تست‌نشده |
| 6 | هدر `Retry-After` برای ۴۲۹ نبود | کم | از `details.retry_after` ساخته می‌شود | ⏳ تست‌نشده |
| 7 | پاسخ‌های auth قابل کش‌شدن بودند | متوسط | `Cache-Control: no-store` روی مسیرهای auth | ⏳ تست‌نشده |
| 8 | لاگ `IntegrityError` متن خام درایور را چاپ می‌کرد (احتمال داده شخصی) | کم | فقط SQLSTATE و نوع خطا | ⏳ تست‌نشده |
| 9 | چرخه import بین auth و review شکننده بود | کم | `auth/__init__` بدون import روتر؛ روترها در `api` وصل می‌شوند | ⏳ تست‌نشده |
| 10 | `revoke-all` بدنه اجباری داشت و بدون body ۴۲۲ می‌داد | کم | بدنه اختیاری | ⏳ تست‌نشده |
| 11 | کد مرده‌ی هش رمز (بدون هیچ کاربردی در v1) | کم | حذف شد | ✅ |

ریسک‌های باقی‌مانده (تصمیم آگاهانه یا کار بعدی):

| # | ریسک | توضیح |
| --- | --- | --- |
| 1 | IP پشت پروکسی | `request.client.host` بدون `X-Forwarded-For` قابل اعتماد نیست؛ باید فقط از پروکسی شناخته‌شده خوانده شود |
| 2 | پیامک واقعی | در production بدون ارائه‌دهنده، کد به کاربر نمی‌رسد (لاگ هشدار می‌دهد) |
| 3 | `security_events` نوشته نمی‌شود | تلاش‌های ناموفق ورود در جدول امنیتی ثبت نمی‌شوند؛ برای هشدار و قفل‌شدن حساب لازم است |
| 4 | جدول‌های بی‌پایان | `verification_challenges` و `review_history` نیاز به job پاک‌سازی/پارتیشن دارند؛ هنوز worker وجود ندارد |
| 5 | مقیاس افقی | engine و pool درون‌فرآیندی است؛ چند instance بدون مشکل کار می‌کند چون حالت در DB است، اما rate limit دقیق‌تر به Redis/DB نیاز دارد |
| 6 | مشاهده‌پذیری | متریک و tracing نداریم؛ فقط لاگ و `X-Request-ID` |
| 7 | CORS | برای کلاینت وب لازم می‌شود؛ عمداً اضافه نشد چون دامنه هنوز مشخص نیست |
| 8 | صفحه‌بندی سشن‌ها | `GET /sessions` بدون limit است؛ تعداد سشن هر کاربر عملاً کم است |

## ۹. اجرا و زیرساخت (Docker)

| # | مورد | جزئیات | وضعیت |
| --- | --- | --- | --- |
| 51 | اصلاح والیوم PG18 | mount در `/var/lib/postgresql`، والیوم جدید `pgdata18` | ✅ اجرا شد (PostgreSQL 18.7 healthy) |
| 52 | Redis | `redis:8-alpine` با AOF، رمز، `maxmemory 256mb`، healthcheck | ✅ healthy |
| 53 | Object storage | SeaweedFS با S3 API روی ۸۳۳۳ (جای MinIO که ایمیج عمومی‌اش بسته شد) | ✅ healthy، `s3=200` |
| 54 | Mailpit | SMTP روی ۲۵۲۵ و UI روی ۸۰۲۶ (پورت ۱۰۲۵ در ویندوز رزرو بود) | ✅ healthy |
| 55 | Dockerfile | نصب پکیج، اجرای non-root، همان ایمیج برای api و migrate | ✅ build و اجرا شد |
| 56 | سرویس `migrate` | `alembic upgrade head` یک‌باره قبل از api | ✅ ۳۹ جدول ساخته شد |
| 57 | سرویس `api` | depends_on سالم + healthcheck روی `/health` | ✅ healthy، `/ready` = ok |
| 58 | `.dockerignore` | حذف `.env`، تست و کش از build context | ✅ |

نکته: کانتینر قدیمی `lurnian-db` که با کانفیگ قبلی مانده بود حذف شد؛ والیوم قدیمی `lurnian-backend_lurnian_pgdata` دست‌نخورده باقی است.

## ۱۰. قدم بعدی

⬜ وکب v1: جست‌وجو/افزودن کلمه، enroll، ساخت کارت
⬜ اجرا روی دیتابیس واقعی و تست جریان کامل ورود
⬜ اتصال ارائه‌دهنده پیامک
⬜ Authorization و نقش‌ها (بعد از تأیید auth)
