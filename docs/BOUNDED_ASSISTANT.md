# Bounded assistant

The optional assistant is an interface over the same deterministic,
tenant-scoped domain services used by slash commands and the Mini App. It is
disabled by default.

## Boundary

The provider receives message text plus limited time/clarification context and
may return only one strictly validated intent. It never receives a database
session, an owner ID, credentials, or arbitrary tools. Owner identity is derived
from the authenticated Telegram update and supplied to the domain service
outside model-generated arguments.

Allowed proposal families are:

- create one work log, note, ledger entry, reminder, nutrition draft, or goal;
- retrieve a bounded daily/weekly, spending, nutrition, or goal view;
- list or search the caller's own records of one type (`list_records`);
- answer a greeting or an ordinary general-knowledge question in at most 400
  characters (`smalltalk`);
- propose deletion of one record, identified by id or by description;
- request clarification; or
- reject an unsupported request.

There is no SQL tool, code-execution tool, payment tool, publication tool,
third-party messaging tool, medical-diagnosis tool, bulk mutation tool, or
arbitrary HTTP tool.

`smalltalk` is a reply, not a capability. It carries no arguments the
application acts on, cannot reach a record, and is length-capped by the schema
rather than by instruction, so the model cannot use it to become a
general-purpose chatbot. `unsupported` remains reserved for requests that must
be refused (email, browsing, payments, code execution, external services)
rather than for anything that merely lacks a create action.

## Retrieval and reference resolution

`list_records` filters are applied by the owner-scoped domain queries that
already back the Mini App and slash commands. The model chooses what to look
for; it never supplies, and cannot influence, whose records are searched.

`delete_record` accepts `search` or `ordinal` instead of `record_id`, because
people say "delete my note about the invoice" rather than a row number. The
application resolves the reference against the caller's own records before
anything is stored or reviewed:

- no match — the request is rejected and the user is told what was searched;
- one match — a confirmation naming the record's own text;
- several matches — a `disambiguation` pending state offering up to five
  candidates as buttons, with the record id carried in callback data.

A tapped choice is honoured only when it matches a candidate the server offered
for that pending action, so a crafted callback cannot select an arbitrary row.
Confirmation is still required after a choice.

## Validation and execution

Provider JSON is untrusted. Pydantic discriminated unions reject extra fields,
identity fields, hidden-reasoning fields, invalid money, unsupported currencies,
oversized text, and malformed action shapes. Clear non-destructive creation may
execute with a trusted update-derived idempotency key. Deletion always creates
durable confirmation state.

### When review applies

The Correct/Wrong review and the confidence floor both exist to protect writes,
so they are applied to writes only:

- a batch containing any write is reviewed before a voice request executes;
- a batch of only reads or a `smalltalk` reply executes immediately, because a
  button tap between a question and its answer adds friction without adding
  safety;
- a low-confidence write on a *reviewed* path is shown as a hedged proposal
  rather than refused — nothing is saved until the user confirms, so showing a
  usable interpretation beats discarding the transcript;
- a low-confidence write on an unreviewed path still asks the user to restate.

Pending state stores only the intended action, validated/known arguments,
missing-field names, prompt, expiry, update reference, and idempotency key. A
plain reply — spoken or typed — is bound automatically to the caller's newest
open clarification, so no command or id has to be quoted back. `/answeragent`,
`/confirmagent`, and `/cancelagent` remain as deterministic fallbacks. State
survives API or bot restarts.

Agent-run logs contain a one-way input hash, provider/model identifiers, safe
status, timestamps, and safe error category. Action logs contain field names,
record references, and status—not the raw prompt, provider reasoning, secrets,
or model response.

## Failure behavior

When the provider is disabled, unavailable, returns malformed JSON, or violates
the schema, no domain write occurs. Explicit slash commands and Mini App CRUD do
not call the provider and continue working.

`GLOBAL_DAILY_AI_LIMIT` adds a deployment-wide ceiling on top of the per-user
quotas. One provider key serves every user of a public bot, so a total cap is
what actually protects the provider allowance; per-user quotas alone only bound
one person. On reaching it the assistant says it is at capacity and points at
the slash commands, rather than failing as though the request were malformed.
Zero disables the ceiling, which is the right setting for a private deployment.

## Configuration

```text
AI_AGENT_ENABLED=false
AI_PROVIDER=disabled
AI_AGENT_MIN_CONFIDENCE=0.80
AGENT_PENDING_TTL_MINUTES=30
MAX_AGENT_INPUT_LENGTH=4000
GLOBAL_DAILY_AI_LIMIT=0
```

To use Groq intent extraction, set `AI_PROVIDER=groq` and provide
`GROQ_API_KEY`. Staging and production configuration fails closed if the agent
is enabled without a provider credential.

The versioned evaluation corpus is
`backend/assistant/evaluation_cases.json`. Automated tests additionally cover
schema injection, malformed output, provider failure, duplicate execution,
cross-tenant retrieval and confirmation, durable clarification, deletion
confirmation, exact money, reminder extraction, and ambiguous food handling.
