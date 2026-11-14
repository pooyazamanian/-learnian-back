# Lurnian — نسخه اول (MVP v1)

این سند جواب یک سؤال است: **از ۳۸ جدول طراحی‌شده، برای نسخه اول کدام‌ها لازم‌اند و کاربر از کدام جدول به کدام جدول می‌رود؟**

طراحی کامل (`database-design.md`) برای «هیچ‌وقت گیر نکنیم» است، نه برای «همه را از روز اول بسازیم». v1 فقط ۱۵ جدول را لمس می‌کند؛ ۲۳ جدول بقیه بعداً و بدون تغییر ساختار اضافه می‌شوند.

---

## ۱. دامنه v1

**داخل v1:**

- ورود فقط با **شماره تلفن + کد پیامکی** (بدون رمز، بدون ایمیل).
- یک **سشن** با access token کوتاه + refresh token چرخشی.
- افزودن کلمه (از کاتالوگ یا کلمه شخصی)، معنی، مثال.
- ورود کلمه به برنامه مرور و ساخت کارت‌های تمرین.
- صف مرور امروز، ثبت پاسخ ۱..۴، زمان‌بندی FSRS.
- سقف روزانه و وضعیت known/ignored.

**بیرون v1:** پرداخت و اشتراک، نقش و پنل ادمین، OAuth، رمز/TOTP، اعلان push، دک و اشتراک‌گذاری دک، آپلود صدا، import، آمار پیشرفته.

---

## ۲. جدول‌هایی که v1 استفاده می‌کند

### احراز هویت (۴ جدول)

| جدول | چرا لازم است | در v1 چه چیزی داخلش می‌رود |
| --- | --- | --- |
| `users` | تنها جدولی که «کاربر وجود دارد» را تعریف می‌کند | یک ردیف با `phone_e164`، `phone_verified_at`، `status='active'` |
| `verification_challenges` | کد پیامکی یکبارمصرف، قبل از اینکه کاربر وجود داشته باشد | `channel='sms'`, `purpose='login'`, `destination=+98…`, `code_hash`, `expires_at`, `attempts` |
| `user_sessions` | واحد «خروج از حساب»؛ access token بی‌حالت است و جای ذخیره ندارد | `auth_method='sms_otp'`, `absolute_expires_at`, `last_seen_at`, `revoked_at` |
| `refresh_tokens` | توکن چرخشی؛ فقط هش ذخیره می‌شود | `session_id`, `token_hash`, `family_id`, `expires_at`, `used_at` |

سه جدول احراز هویت که **لازم نیست**: `user_credentials` (رمزی وجود ندارد)، `user_identities` (OAuth نداریم)، `user_devices` (بدون push و بدون «دستگاه‌های من» کار می‌کند؛ `user_sessions.device_id` خالی می‌ماند).

### تنظیمات (۲ جدول)

| جدول | چرا | داخلش |
| --- | --- | --- |
| `user_settings` | `timezone` مرجع محاسبه «امروزِ کاربر» است | `timezone='Asia/Tehran'`, `locale='fa-IR'` |
| `user_learning_settings` | سقف روزانه و جهت‌های کارت از اینجا خوانده می‌شود | `target_language_id`, `daily_new_cards=10`, `daily_review_limit=200`, `card_modes` |

### محتوای آموزشی (۴ جدول)

| جدول | چرا | داخلش |
| --- | --- | --- |
| `languages` | فقط یک‌بار seed می‌شود | `en`, `fa` |
| `vocabulary` | خود کلمه؛ ردیف کاتالوگ (`owner_user_id IS NULL`) یا کلمه شخصی کاربر | `lemma`, `normalized_lemma`, `part_of_speech`, `owner_user_id` |
| `vocabulary_translations` | معنی کلمه به فارسی | `translation`, `language_id` |
| `vocabulary_examples` | یک یا دو جمله نمونه | `sentence`, `translation` |

بدون `learning_decks` و `deck_vocabulary`: v1 «همه کلمه‌های من» یک لیست است، دک لازم ندارد.

### پیشرفت و مرور (۵ جدول)

| جدول | چرا | داخلش |
| --- | --- | --- |
| `user_vocabulary` | تنها دروازه‌ای که کلمه را وارد برنامه مطالعه کاربر می‌کند | `user_id`, `vocabulary_id`, `status`, `source='manual'` |
| `review_cards` | هویت کارت = (کلمه ثبت‌شده، جهت تمرین) | `mode='word_to_fa'`, `is_suspended=false` |
| `fsrs_card_states` | تنها ردیفی که با هر پاسخ عوض می‌شود + `row_version` | `due_at`, `state`, `stability`, `difficulty`, `reps`, `lapses` |
| `fsrs_settings` | سیاست زمان‌بندی هر کاربر | `desired_retention=0.9`, `maximum_interval_days` |
| `review_history` | دفتر فقط‌افزودنی؛ آمار و سقف روزانه از اینجا می‌آید | `rating`, `reviewed_on`, `state_before/after`, `idempotency_key` |

`fsrs_parameters` در v1 لازم نیست: کارت‌ها با پارامترهای پیش‌فرض کد کار می‌کنند (`parameters_id` خالی می‌ماند).

---

## ۳. جدول‌هایی که v1 نمی‌خواهد

| گروه | جدول‌ها | چرا بعداً |
| --- | --- | --- |
| امنیت پیشرفته | `user_security_settings`, `security_events`, `roles`, `user_roles` | بدون 2FA و پنل ادمین، هیچ‌کس این‌ها را نمی‌نویسد |
| پرداخت | `subscription_plans`, `plan_features`, `plan_feature_values`, `user_subscriptions`, `orders`, `payments`, `entitlements` | v1 رایگان است؛ دسترسی کاربر فقط «وضعیت حساب» است |
| اعلان | `notification_preferences`, `notification_deliveries`, `notification_templates` | یادآور مرور بعد از پایدار شدن چرخه مرور |
| زیرساخت | `outbox_events`, `idempotency_keys`, `platform_jobs` | v1 همه‌چیز را در همان تراکنش انجام می‌دهد |
| محتوا | `learning_decks`, `deck_vocabulary`, `audit_logs` | دک و لاگ تغییرات، بعد از تثبیت مدل کلمه |

نکته: این جدول‌ها در migration هستند و خالی می‌مانند؛ خالی بودنشان هزینه‌ای ندارد و لازم نیست حذف شوند.

---

## ۴. سناریوی ورود با شماره تلفن

### گام‌ها

1. کاربر شماره را می‌فرستد. اگر شماره در `users` نباشد، **همین‌جا کاربر ساخته نمی‌شود**؛ فقط کد صادر می‌شود.
2. کد قبلیِ همان شماره باطل می‌شود، کد جدید هش شده در `verification_challenges` می‌نشیند (۲ دقیقه اعتبار، ۵ تلاش).
3. کاربر کد را می‌فرستد. کد با هش مقایسه می‌شود و شمارنده `attempts` بالا می‌رود.
4. اگر کد درست بود: کاربر موجود پیدا/ساخته می‌شود، `phone_verified_at` پر می‌شود، چالش `consumed_at` می‌گیرد، سپس **یک** `user_sessions` و **یک** `refresh_tokens` ساخته می‌شود.
5. access token (۱۵ دقیقه، بی‌حالت) و refresh token (۳۰ روز، فقط یک‌بار قابل استفاده) به کلاینت برمی‌گردد.
6. هر بار access منقضی شد، refresh مصرف و با توکن جدید جایگزین می‌شود. اگر توکن **قبلاً مصرف‌شده** دوباره بیاید، کل خانواده توکن و سشن باطل می‌شود.
7. خروج = `revoked_at` روی سشن + توکن‌های همان سشن.

### دیاگرام ۱ — درخواست کد

```mermaid
sequenceDiagram
    autonumber
    participant App as اپ
    participant API as API
    participant VC as verification_challenges
    participant U as users
    participant SMS as سرویس پیامک

    App->>API: POST /auth/otp/request {phone}
    API->>API: نرمال‌سازی به E.164
    API->>U: SELECT id, status WHERE phone_e164 = $1 AND deleted_at IS NULL
    U-->>API: کاربر (یا هیچ)
    API->>VC: UPDATE pending های همین شماره: invalidated_at = now()
    API->>VC: INSERT (sms, purpose='login', destination, code_hash,<br/>expires_at = now()+2m, max_attempts=5)
    VC-->>API: challenge_id
    API->>SMS: ارسال کد
    API-->>App: 202 {challenge_id, expires_in: 120}
```

### دیاگرام ۲ — تأیید کد و ساخت سشن

```mermaid
sequenceDiagram
    autonumber
    participant App as اپ
    participant API as API
    participant VC as verification_challenges
    participant U as users
    participant S as user_sessions
    participant R as refresh_tokens

    App->>API: POST /auth/otp/verify {challenge_id, code}
    API->>VC: SELECT * FOR UPDATE
    alt منقضی یا مصرف‌شده یا attempts >= max
        API-->>App: 401
    else کد اشتباه
        API->>VC: UPDATE attempts = attempts + 1
        API-->>App: 401 {attempts_left}
    else کد درست
        opt کاربر جدید
            API->>U: INSERT (phone_e164, phone_verified_at=now(), status='active')
            API->>API: INSERT user_settings (timezone) + user_learning_settings + fsrs_settings
        end
        API->>U: UPDATE phone_verified_at, last_active_at
        API->>VC: UPDATE consumed_at = now()
        API->>S: INSERT (user_id, auth_method='sms_otp', ip, user_agent,<br/>absolute_expires_at = now()+90d)
        API->>R: INSERT (session_id, token_hash, family_id=new, expires_at=now()+30d)
        API-->>App: 200 {access_token, refresh_token, expires_in}
    end
```

### دیاگرام ۳ — چرخش refresh و تشخیص استفاده مجدد

```mermaid
sequenceDiagram
    autonumber
    participant App as اپ
    participant API as API
    participant R as refresh_tokens
    participant S as user_sessions

    App->>API: POST /auth/refresh {refresh_token}
    API->>R: SELECT ... WHERE token_hash = sha256(token) FOR UPDATE
    alt پیدا نشد
        API-->>App: 401
    else قبلاً مصرف شده (used_at پر است)
        API->>R: UPDATE همه family_id: revoked_at، reason='reuse_detected'
        API->>S: UPDATE session: revoked_at
        API-->>App: 401 + خروج اجباری
    else معتبر
        API->>R: UPDATE used_at = now()
        API->>R: INSERT توکن بعدی (همان family_id، parent_id = قبلی)
        API-->>App: 200 {access_token, refresh_token}
    end
```

### دیاگرام ۴ — خروج

```mermaid
sequenceDiagram
    autonumber
    participant App as اپ
    participant API as API
    participant S as user_sessions
    participant R as refresh_tokens

    App->>API: POST /auth/logout (Bearer access)
    API->>S: UPDATE revoked_at = now(), revoked_reason='logout'
    API->>R: UPDATE همه توکن‌های این سشن: revoked_at
    API-->>App: 204
```

---

## ۵. وکب در v1 — چه ویژگی‌هایی

**باید باشد:**

1. جست‌وجوی کلمه در کاتالوگ عمومی (`vocabulary` با `owner_user_id IS NULL`).
2. افزودن کلمه شخصی اگر در کاتالوگ نبود (همان جدول، `owner_user_id` پر).
3. معنی (یک یا چند sense) و یک جمله نمونه.
4. «یاد می‌گیرم» → ردیف `user_vocabulary` + ساخت کارت برای هر جهت فعال.
5. صف امروز: کارت‌های `due_at <= now()` با احترام به سقف جدید/مرور.
6. پاسخ دادن با ۱..۴ و ذخیره `review_history` + آپدیت `fsrs_card_states`.
7. علامت known / ignored برای کلمه‌هایی که نباید مرور شوند.
8. آمار ساده: تعداد مرور امروز، تعداد کلمه در حال یادگیری.

**نباید باشد (v1):** آپلود صدا، ایمپورت فایل، دک اشتراکی، تصویر، تولید محتوا با AI، جست‌وجوی پیشرفته/فازی، undo.

| ویژگی | جدول‌های درگیر |
| --- | --- |
| جست‌وجوی کلمه | `vocabulary`, `vocabulary_translations` |
| افزودن کلمه شخصی | `vocabulary`, `vocabulary_translations`, `vocabulary_examples` |
| ورود به برنامه مرور | `user_vocabulary`, `review_cards`, `fsrs_card_states` |
| صف امروز | `review_cards`, `fsrs_card_states`, `user_learning_settings`, `user_settings`, `review_history` |
| ثبت پاسخ | `fsrs_card_states`, `review_history`, `user_vocabulary` |
| آمار | `review_history`, `user_vocabulary` |

---

## ۶. دیاگرام‌های مسیر کاربر

### دیاگرام ۵ — از «کلمه جدید» تا «کارت آماده مرور»

```mermaid
sequenceDiagram
    autonumber
    participant App as اپ
    participant API as API
    participant V as vocabulary
    participant T as vocabulary_translations
    participant E as vocabulary_examples
    participant UV as user_vocabulary
    participant C as review_cards
    participant ST as fsrs_card_states

    App->>API: POST /vocabulary {lemma:'resilient', translation:'تاب‌آور'}
    API->>V: INSERT (target_language_id, lemma, normalized_lemma,<br/>part_of_speech, owner_user_id = من)
    V-->>API: vocabulary_id
    API->>T: INSERT (vocabulary_id, language_id='fa', translation, normalized_translation)
    API->>E: INSERT (vocabulary_id, sentence, translation)
    API-->>App: 201 {vocabulary_id}

    App->>API: POST /vocabulary/{id}/enroll
    API->>UV: INSERT (user_id, vocabulary_id, status='learning', source='manual')<br/>ON CONFLICT (user_id, vocabulary_id) DO NOTHING
    UV-->>API: user_vocabulary_id
    API->>C: INSERT برای هر mode در card_modes<br/>ON CONFLICT (user_vocabulary_id, mode) DO NOTHING
    C-->>API: card_id ها
    API->>ST: INSERT (card_id, user_id, state='new', due_at=now())
    API-->>App: 200 {cards_created: 2}
```

### دیاگرام ۶ — گرفتن صف امروز

```mermaid
sequenceDiagram
    autonumber
    participant App as اپ
    participant API as API
    participant US as user_settings
    participant LS as user_learning_settings
    participant C as review_cards
    participant ST as fsrs_card_states
    participant UV as user_vocabulary
    participant H as review_history

    App->>API: GET /review/queue
    API->>US: SELECT timezone
    API->>LS: SELECT daily_new_cards, daily_review_limit, card_modes
    API->>H: SELECT count(*) WHERE user_id = من AND reviewed_on = today<br/>AND state_before = 'new'
    H-->>API: new_today
    API->>ST: SELECT ... JOIN review_cards ON card_id<br/>WHERE due_at <= now() AND NOT is_suspended<br/>ORDER BY due_at LIMIT ...
    ST->>C: JOIN برای mode و status
    C->>UV: JOIN برای status IN ('learning')
    API-->>App: 200 [{card_id, mode, lemma, translation, state, due_at}]
```

### دیاگرام ۷ — ثبت پاسخ و حرکت کارت در زمان

```mermaid
sequenceDiagram
    autonumber
    participant App as اپ
    participant API as API
    participant ST as fsrs_card_states
    participant H as review_history
    participant UV as user_vocabulary

    App->>API: POST /review/answer {card_id, rating:3, idempotency_key}
    API->>API: BEGIN
    API->>ST: SELECT * WHERE card_id = $1 FOR UPDATE
    ST-->>API: state قبل + row_version
    alt row_version قدیمی است
        API-->>App: 409 (کارت هم‌زمان عوض شد)
    end
    API->>API: محاسبه FSRS → due_at، stability، difficulty، state بعد
    API->>ST: UPDATE ... WHERE card_id AND row_version = expected<br/>(row_version = row_version + 1)
    API->>H: INSERT (rating, reviewed_on, state_before/after,<br/>due_before/after, idempotency_key)
    Note over H: یکتایی (user_id, idempotency_key)<br/>پاسخ تکراری = همان نتیجه، بدون ردیف دوم
    API->>UV: UPDATE last_interacted_at
    API->>API: COMMIT
    API-->>App: 200 {next_due_at, state}
```

### دیاگرام ۸ — چرخه عمر یک کارت

```mermaid
stateDiagram-v2
    [*] --> new: enroll می‌شود
    new --> learning: rating=1 یا 2
    new --> review: rating=3 یا 4
    learning --> learning: پاسخ سخت، چند دقیقه بعد
    learning --> review: از پله‌های یادگیری گذشت
    review --> review: پاسخ درست، فاصله بیشتر
    review --> relearning: rating=1 (فراموشی)
    relearning --> review: دوباره به یاد آورد
    review --> [*]: کاربر کلمه را known می‌کند
```

### دیاگرام ۹ — نقشه «از کجا به کجا»

```mermaid
flowchart TD
    A[شماره تلفن] --> B[verification_challenges]
    B -->|کد درست| C[users]
    C --> D[user_sessions]
    D --> E[refresh_tokens]
    C --> F[user_settings + user_learning_settings + fsrs_settings]

    G[جست‌وجو/افزودن کلمه] --> H[vocabulary]
    H --> I[vocabulary_translations]
    H --> J[vocabulary_examples]

    C --> K[user_vocabulary]
    H --> K
    K --> L[review_cards]
    L --> M[fsrs_card_states]
    M -->|هر پاسخ| N[review_history]
    N -->|آمار و سقف روزانه| O[صف فردا]
    M --> O
```

---

## ۷. ترتیب ساختن

1. seed زبان‌ها + جدول‌های محتوا (بدون endpoint عمومی).
2. OTP: درخواست کد، تأیید، ساخت کاربر و تنظیمات پیش‌فرض.
3. سشن: صدور توکن، refresh چرخشی، logout (سرویس سشن از قبل هست؛ فقط مسیر OTP اضافه می‌شود).
4. وکب: جست‌وجو، افزودن کلمه شخصی، enroll.
5. مرور: صف، پاسخ، FSRS، سقف روزانه.
6. آمار ساده.

## ۸. وضعیت کد فعلی

- احراز هویت v1 پیاده شده است: `POST /auth/otp/request`, `/otp/verify`, `/refresh`, `/logout` و همچنین `/me`، `/sessions`، `/sessions/{id}` و `/sessions/revoke-all`.
- ورود فقط با شماره تلفن است؛ مسیرهای ایمیل/رمز حذف شده‌اند و رمزی ذخیره نمی‌شود.
- عمر توکن‌ها: access ۳۰ دقیقه، refresh ۳۶۵ روز، سقف سشن ۳۶۵ روز. refresh یک‌بارمصرف است و استفاده دوباره، خانواده توکن و سشن را می‌بندد.
- کد یکبارمصرف در همان تراکنش تأیید مصرف می‌شود و کاربر (چه جدید چه قدیم) در پاسخ همان درخواست برمی‌گردد.
- ارائه‌دهنده پیامک هنوز وصل نشده است؛ در توسعه کد در لاگ و در صورت `OTP_EXPOSE_IN_RESPONSE=true` در پاسخ می‌آید.
- مستند مسیرها و کدهای خطا: `docs/api/auth-v1.md`.

ساختار پوشه‌ها: `modules/auth/{domain,application,infrastructure,presentation}` و لایه مشترک `api/` (روتر v1 و هندلر خطای سراسری).
