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
- propose deletion of one known record;
- request clarification; or
- reject an unsupported request.

There is no SQL tool, code-execution tool, payment tool, publication tool,
third-party messaging tool, medical-diagnosis tool, bulk mutation tool, or
arbitrary HTTP tool.

## Validation and execution

Provider JSON is untrusted. Pydantic discriminated unions reject extra fields,
identity fields, hidden-reasoning fields, invalid money, unsupported currencies,
oversized text, and malformed action shapes. Clear non-destructive creation may
execute with a trusted update-derived idempotency key. Low-confidence or
incomplete proposals create durable clarification state. Deletion always
creates durable confirmation state and requires `/confirmagent ID`.

Pending state stores only the intended action, validated/known arguments,
missing-field names, prompt, expiry, update reference, and idempotency key.
`/answeragent ID ...` resolves clarification and `/cancelagent ID` cancels either
flow. State survives API or bot restarts.

Agent-run logs contain a one-way input hash, provider/model identifiers, safe
status, timestamps, and safe error category. Action logs contain field names,
record references, and status—not the raw prompt, provider reasoning, secrets,
or model response.

## Failure behavior

When the provider is disabled, unavailable, returns malformed JSON, or violates
the schema, no domain write occurs. Explicit slash commands and Mini App CRUD do
not call the provider and continue working.

## Configuration

```text
AI_AGENT_ENABLED=false
AI_PROVIDER=disabled
AI_AGENT_MIN_CONFIDENCE=0.80
AGENT_PENDING_TTL_MINUTES=30
MAX_AGENT_INPUT_LENGTH=4000
```

To use Groq intent extraction, set `AI_PROVIDER=groq` and provide
`GROQ_API_KEY`. Staging and production configuration fails closed if the agent
is enabled without a provider credential.

The versioned evaluation corpus is
`backend/assistant/evaluation_cases.json`. Automated tests additionally cover
schema injection, malformed output, provider failure, duplicate execution,
cross-tenant retrieval and confirmation, durable clarification, deletion
confirmation, exact money, reminder extraction, and ambiguous food handling.
