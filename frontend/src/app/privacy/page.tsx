export default function PrivacyPage() {
  return (
    <main className="mx-auto min-h-screen max-w-3xl px-5 py-12 text-slate-900">
      <h1 className="text-3xl font-bold">PR-Agent Privacy Notice</h1>
      <p className="mt-2 text-sm text-slate-500">Effective 23 August 2026</p>

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
            optional AI requests may be processed by the configured speech and
            language-model providers. A typed, explicitly labelled vault save
            is parsed by application code before the intent model, and a vault
            value typed into the Mini App is sent directly to the PR-Agent API.
            A vault value spoken in a voice message is necessarily sent to the
            configured speech-to-text provider for transcription, but the
            resulting explicit vault save is not sent to the intent model. If
            you ask for a stored item by label, the model receives the label,
            not the stored value; application code decrypts it only after your
            separate reveal confirmation.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold">Security and access</h2>
          <p className="mt-2">
            Access is tied to Telegram-signed identity and every record is
            scoped to its owner. Vault values use application-layer encryption
            and masked display. The general secret type accepts passwords and
            other private text without trying to decide whether the secret is
            suitable. The dedicated Aadhaar type intentionally accepts only
            the final four digits. No online service can promise zero risk:
            anyone choosing to store a password, recovery phrase, private key,
            OTP, PIN, CVV, card number, or other high-impact credential accepts
            the additional risk of placing it in an online service.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold">Your controls</h2>
          <p className="mt-2">
            Use the Mini App to edit or delete individual records, export your
            ordinary account data, or permanently delete your account. Vault
            entries are create-only: they can be created, revealed, or deleted,
            but never edited in chat, by voice, or in the Mini App. Replacing a
            value means deleting it and creating a new encrypted entry. Vault
            values are intentionally excluded from ordinary exports. A
            confirmed private-chat reveal is queued for automatic deletion,
            but Telegram delivery still places that value in your chat until
            deletion succeeds.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold">Retention and contact</h2>
          <p className="mt-2">
            User records remain until you delete them. Processed Telegram chat
            messages are queued for best-effort deletion after 40 hours, while
            minimal operational metadata is pruned periodically. Telegram or a
            temporary delivery failure may delay or prevent chat deletion. For
            a privacy request, contact the project owner through the public
            repository.
          </p>
        </section>
      </div>
    </main>
  );
}
