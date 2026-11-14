# Auth API — v1

ورود فقط با **شماره تلفن و کد پیامکی**؛ رمز و ایمیل در این نسخه وجود ندارد.
همه مسیرها زیر `/api/v1/auth` هستند.

## سیاست توکن

| توکن | عمر | ذخیره | نکته |
| --- | --- | --- | --- |
| access | ۳۰ دقیقه | ذخیره نمی‌شود (JWT بی‌حالت، HS256) | فقط `sub` و `sid` را دارد؛ ابطال با سشن انجام می‌شود |
| refresh | ۳۶۵ روز | فقط `sha256` آن در `refresh_tokens` | یک‌بارمصرف و چرخشی؛ استفاده دوباره کل خانواده + سشن را می‌بندد |
| سشن | حداکثر ۳۶۵ روز | `user_sessions` | خروج فوری، بدون انتظار برای انقضای توکن |

کد یکبارمصرف: ۶ رقم، اعتبار ۱۲۰ ثانیه، حداکثر ۵ تلاش، فاصله ارسال مجدد ۶۰ ثانیه.
کد به‌صورت HMAC-SHA256 با pepper ذخیره می‌شود، نه خام.

## مسیرها

| متد | مسیر | ورودی | خروجی | احراز هویت |
| --- | --- | --- | --- | --- |
| POST | `/otp/request` | `{phone}` | `202 {challenge_id, expires_in, resend_after, debug_code}` | — |
| POST | `/otp/verify` | `{challenge_id, code}` | `200 {user, tokens, is_new_user}` | — |
| POST | `/refresh` | `{refresh_token}` | `200 {access_token, refresh_token, expires_in, refresh_expires_in, session_id}` | — |
| POST | `/logout` | — | `204` | Bearer |
| GET | `/me` | — | `200 {id, phone, phone_verified_at, status, created_at}` | Bearer |
| GET | `/sessions` | — | `200 {sessions: [{id, current, auth_method, ip, user_agent, created_at, last_seen_at, expires_at}]}` | Bearer |
| DELETE | `/sessions/{id}` | — | `204` | Bearer |
| POST | `/sessions/revoke-all` | `{keep_current}` | `200 {revoked_count}` | Bearer |

### جریان ورود

1. `POST /otp/request` با `09121234567` یا `+989121234567`؛ هر دو به `+989121234567` نرمال می‌شوند.
2. پاسخ برای شماره جدید و قدیم یکسان است (جلوگیری از افشای وجود حساب).
3. `POST /otp/verify` با `challenge_id` و کد؛ اگر شماره جدید باشد، همین‌جا `users` + تنظیمات پیش‌فرض ساخته می‌شود.
4. پاسخ شامل خود کاربر است، پس اپ برای نمایش خانه به درخواست دوم نیاز ندارد.
5. پس از انقضای access، `POST /refresh` جفت جدید می‌دهد. ذخیره‌ی refresh قدیمی خطاست: با استفاده دوباره، آن سشن بسته می‌شود.

### مدیریت سشن

`GET /sessions` دستگاه‌های فعال را نشان می‌دهد و سشن فعلی را با `current: true` علامت می‌زند.
`DELETE /sessions/{id}` هر سشنِ همان کاربر را می‌بندد و `POST /sessions/revoke-all` بقیه را (با `keep_current=true` سشن فعلی باز می‌ماند).
بستن سشن یعنی `revoked_at` روی سشن و همه‌ی توکن‌های همان سشن؛ access تا ۳۰ دقیقه بعد از نظر امضایی معتبر است اما وابستگی احراز هویت سشن را چک می‌کند و ۴۰۱ می‌دهد.

## قالب خطا

همه خطاها یک شکل دارند و `request_id` همان مقدار هدر `X-Request-ID` است:

```json
{
  "error": {
    "code": "auth.invalid_code",
    "message": "Incorrect code",
    "request_id": "8f1c…",
    "details": { "attempts_left": 4 }
  }
}
```

| کد | وضعیت | معنا |
| --- | --- | --- |
| `invalid_phone` | 400 | شماره قابل نرمال‌سازی نیست |
| `validation_error` | 422 | بدنه/پارامتر نامعتبر؛ `details.fields` فهرست فیلدها |
| `unauthenticated` | 401 | توکن نبود/نامعتبر/منقضی یا سشن بسته شده |
| `auth.code_invalid` | 401 | کد ناموجود، مصرف‌شده یا باطل‌شده |
| `auth.code_expired` | 401 | کد منقضی شده |
| `auth.invalid_code` | 401 | کد اشتباه؛ `attempts_left` را ببین |
| `auth.refresh_invalid` | 401 | refresh ناشناخته |
| `auth.refresh_expired` | 401 | refresh منقضی/باطل |
| `auth.refresh_reused` | 401 | استفاده دوباره؛ خانواده توکن و سشن بسته شد |
| `auth.session_revoked` | 401 | سشن بسته یا منقضی |
| `auth.account_disabled` | 403 | حساب `active` نیست |
| `auth.account_missing` | 401 | کاربر حذف شده است |
| `auth.code_cooldown` | 429 | قبل از پایان ۶۰ ثانیه درخواست دوباره؛ هدر `Retry-After` |
| `auth.code_limit_reached` | 429 | سقف ساعتی: ۵ کد برای هر شماره، ۲۰ کد برای هر IP |
| `auth.too_many_attempts` | 429 | ۵ تلاش اشتباه روی همین کد |
| `auth.account_deleted` | 403 | حساب حذف نرم شده است |
| `not_found` | 404 | مسیر یا منبع وجود ندارد |
| `conflict` | 409 | تضاد با داده موجود |
| `internal_error` | 500 | خطای پیش‌بینی‌نشده (جزئیات فقط در لاگ) |

پاسخ‌های ۴۲۹ در صورت وجود مقدار `details.retry_after` هدر `Retry-After` هم دارند. همه پاسخ‌های `/auth` با `Cache-Control: no-store` برمی‌گردند تا توکن و شماره در کش مشترک ننشیند.

## اجرای محلی بدون سرویس پیامک

در `development` کد در لاگ و در صورت `OTP_EXPOSE_IN_RESPONSE=true` در فیلد `debug_code` برمی‌گردد.
در محیط واقعی `debug_code` همیشه `null` است و بدون ارائه‌دهنده پیامک، کد به کاربر نمی‌رسد (لاگ هشدار می‌دهد).
