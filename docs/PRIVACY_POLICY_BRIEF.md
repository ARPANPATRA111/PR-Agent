# Privacy policy brief

Hand this whole file to whoever writes the policy — an LLM, a lawyer, or you.
It states exactly what the system does, so the resulting policy describes
reality rather than a generic template. Everything below was read off the code,
not assumed.

Once the policy is hosted, set `PRIVACY_POLICY_URL` to its public https URL.
The bot then links it from `/start` and `/privacy` automatically; while the
variable is blank it omits the link rather than showing a broken one.

---

## Prompt to use

> You are writing a privacy policy for a personal-tracking Telegram bot and its
> companion Telegram Mini App. Write it in plain, direct English that an
> ordinary person can read in about three minutes. Do not use boilerplate that
> does not apply. Do not claim certifications, audits, or compliance
> frameworks the operator does not have. Where a practice is a limitation
> rather than a guarantee, say so honestly.
>
> The operator is an individual developer, not a company. The service is free
> and in early release. Users are worldwide with an expected majority in India,
> so the policy must satisfy India's Digital Personal Data Protection Act 2023
> and be broadly consistent with the GDPR for any EU users.
>
> Base every factual statement on the system description below. If something is
> not listed, do not invent it. Produce the policy as a single HTML page with a
> visible "last updated" date and clear headings.

---

## System description

### What the service is

A Telegram bot plus a Telegram Mini App that let one person record and retrieve
their own daily life: work done, private notes, reminders, income and expenses,
meals with estimated nutrition, and personal goals. The primary interface is
voice: the user speaks, the speech is transcribed, and the interpretation is
shown for confirmation before anything is saved.

### Who the controller is

An individual developer operating the service personally. Provide a contact
email placeholder as `[CONTACT EMAIL]` for the writer to fill in.

### Identity and how accounts work

- There is no separate signup, password, or email address.
- Identity comes from Telegram. The service stores the user's Telegram numeric
  user ID, first name, last name if set, and username if set.
- The Mini App authenticates by validating Telegram's signed `initData` and
  then issuing its own time-limited session.
- Each user's records are strictly scoped to their own Telegram identity. Every
  read and write is filtered by owner, and this is covered by automated tests.
  No user can read another user's records.

### What personal data is stored

Content the user deliberately records:

- work and progress log entries, as free text with optional category and tags;
- private notes, with title, body, and tags;
- reminders, with title, schedule, timezone, and delivery state;
- financial entries: amount, currency, direction (spending or income),
  description, category, and date. This is personal financial information;
- meals: the food described, estimated calories and protein, and the
  assumptions behind those estimates. This is health-adjacent information;
- goals, with target values and progress.

Operational data:

- per-user preferences, including timezone and digest settings;
- application sessions;
- Telegram chat IDs and message IDs used to schedule message cleanup — the
  message *bodies* are not stored for this purpose, only the identifiers;
- assistant run records: a one-way hash of the request, the provider and model
  used, status, timestamps, and a coarse error category. The raw text of what
  the user said is **not** stored in these logs;
- counters used for rate limiting.

### What is NOT stored

- No password.
- No email address or phone number.
- No payment details. The service is free and takes no payments.
- No location data.
- No advertising or analytics identifiers.
- Voice audio is **not** retained. The audio file is downloaded from Telegram
  into temporary storage, sent for transcription, and deleted immediately
  afterwards, including when transcription fails. Only the resulting text is
  kept, and only as part of a record the user chose to save.

### Third parties who receive data

1. **Telegram** — the messaging platform itself. All messages pass through it
   and are subject to Telegram's own privacy policy. The service does not
   control Telegram.
2. **Groq** — receives voice audio for transcription (Whisper), and receives
   the transcribed or typed text for interpretation and for nutrition
   estimation. This is the most important disclosure in the policy: the user's
   spoken words leave the service and are processed by a third-party AI
   provider.
3. **Render** — hosts the application.
4. **Neon** — hosts the PostgreSQL database.
5. **Sentry**, if enabled — receives error reports. These are configured to
   exclude personally identifying request bodies.

State plainly that no personal data is sold, rented, or shared for advertising,
and that there is no advertising in the product.

### Automated processing

Requests are interpreted by a large language model that proposes a bounded
action. The policy should state:

- the model can only propose actions from a fixed allow-list — creating,
  reading, editing, or deleting the user's own records;
- it cannot send messages to other people, make payments, browse the web, or
  reach any external service;
- anything that writes or deletes data is shown to the user for explicit
  confirmation before it happens;
- interpretation can be wrong, and the confirmation step exists for that
  reason.

### Nutrition estimates

Calorie and protein figures are produced by a language model from an ordinary
description of a meal. They are approximations, not measurements, and are not
medical or dietary advice. Users should not rely on them for medical decisions.
The service displays the assumptions behind each estimate.

### Retention and deletion

- Records the user creates are kept until the user deletes them or deletes
  their account. There is no automatic expiry of the user's own content.
- Processed Telegram chat messages are queued for deletion from the chat about
  one hour after processing, unless the user pins them. This is best-effort
  cleanup of the conversation, not of the stored records.
- Operational metadata such as completed delivery and cleanup rows is pruned on
  a rolling window (currently 30 days).
- Temporary voice audio is deleted immediately after transcription.
- `/export` produces a copy of everything held about the user.
- `/deleteaccount` permanently erases the user's records. Deletion requires a
  recent authentication to prevent someone acting on an abandoned session.

### User rights

Describe how to actually exercise each right, using the real commands:

- **Access / portability** — `/export` in the bot.
- **Erasure** — `/deleteaccount` in the bot.
- **Rectification** — the user can edit or delete any record by voice, by
  command, or in the Mini App.
- **Withdraw consent** — stop using the bot and run `/deleteaccount`.
- **Complaint** — for Indian users, the Data Protection Board of India; for EU
  users, their local supervisory authority.

### Legal basis and consent

Processing is based on the user's consent, given by choosing to send a message
to the bot and to save a record. Consent is specific to operating the service
and is withdrawable at any time by deleting the account. For DPDP purposes the
notice must be clear about the purposes above, and about the transfer of voice
and text to the AI provider.

### Children

The service is not intended for anyone under 18. Under DPDP, processing a
child's data requires verifiable parental consent, which this service does not
implement. State the age restriction plainly.

### Security — describe accurately, do not overstate

True and safe to state:

- traffic is served over HTTPS;
- the Telegram webhook is authenticated with a secret header;
- Mini App sessions are signed and expire;
- records are scoped per user at the database query level, with automated
  cross-tenant tests;
- the bot only operates in one-to-one chats and refuses group chats, so
  records cannot be printed into a shared conversation;
- secrets are held as masked environment variables, not in source control.

Must **not** be claimed:

- no end-to-end encryption;
- no SOC 2, ISO 27001, HIPAA, or any certification;
- no formal third-party security audit;
- no guaranteed uptime or backup restoration.

Include an honest sentence that no service can guarantee absolute security.

### Service reliability

The service runs on free hosting tiers in early release. Reminders and
scheduled summaries are best-effort and can be delayed. The policy should note
that users should not depend on it for time-critical or safety-critical
reminders.

### Changes and contact

Material changes will be announced through the bot. Include the contact email
placeholder and the last-updated date.

---

## Checklist for the finished policy

- [ ] Names the AI provider and says clearly that voice and text are sent there
- [ ] States that voice audio is not retained
- [ ] States that no user can see another user's data
- [ ] Explains `/export` and `/deleteaccount` by name
- [ ] Declares financial and health-adjacent data explicitly
- [ ] States nutrition figures are estimates and not medical advice
- [ ] Makes no security claim from the "must not be claimed" list
- [ ] Says reminders are best-effort
- [ ] Has an 18+ statement
- [ ] Has a contact address and a last-updated date
- [ ] Names the DPDP Act and the complaint route for Indian users
