export default function PrivacyPage() {
  return (
    <main className="mx-auto min-h-screen max-w-3xl px-5 py-12 text-slate-900">
      <h1 className="text-3xl font-bold">PR-Agent Privacy Notice</h1>
      <p className="mt-2 text-sm text-slate-500">Effective 14 August 2026</p>

      <div className="mt-8 space-y-6 leading-7">
        <section>
          <h2 className="text-xl font-semibold">What is stored</h2>
          <p className="mt-2">
            PR-Agent stores the records you deliberately create, your Telegram
            account identifier, preferences, reminders, and limited operational
            metadata needed to run the service. Voice audio is downloaded for
            transcription and is not retained after processing.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold">How it is used</h2>
          <p className="mt-2">
            Data is used only to provide your private tracking, search,
            reminders, summaries, security controls, and support. Voice and
            optional AI requests may be processed by configured service
            providers. Private-vault plaintext is never sent to AI or voice
            providers. If you ask for a vault item by label, only the label is
            interpreted; the encrypted value is opened by application code
            after your separate confirmation.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold">Security and access</h2>
          <p className="mt-2">
            Access is tied to Telegram-signed identity and every record is
            scoped to its owner. Vault values use application-layer encryption
            and masked display. No online service can promise zero risk, so do
            not store passwords, OTPs, PINs, CVVs, card numbers, recovery
            phrases, private keys, or a full Aadhaar number.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold">Your controls</h2>
          <p className="mt-2">
            Use the Mini App to edit or delete individual records, export your
            ordinary account data, or permanently delete your account. Vault
            values are intentionally excluded from ordinary exports and must be
            deleted from the vault itself. A confirmed private-chat reveal is
            queued for automatic deletion, but Telegram delivery still places
            that value in your chat temporarily.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold">Retention and contact</h2>
          <p className="mt-2">
            User records remain until you delete them. Processed Telegram chat
            messages are removed on a best-effort schedule, while minimal
            operational metadata is pruned periodically. For a privacy request,
            contact the project owner through the public repository.
          </p>
        </section>
      </div>
    </main>
  );
}
