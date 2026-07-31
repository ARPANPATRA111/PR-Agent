# Incident response

Classify incidents as credential exposure, cross-tenant access, duplicate or
failed delivery, provider abuse/cost, data loss, or availability.

1. Contain: disable the affected feature flag, remove the webhook when inbound
   processing is unsafe, and stop the worker when outbound delivery is unsafe.
2. Preserve privacy-safe logs, deployment version, metric snapshots, and
   database snapshots. Do not copy private message bodies into tickets.
3. Rotate exposed bot, webhook, signing, monitoring, database, and provider
   credentials as applicable. Revoking the signing secret invalidates sessions.
4. Determine the affected owner IDs and time window without exposing content.
5. Repair in staging, run the release checklist, and deploy through the normal
   promotion path.
6. Notify affected beta users when confidentiality, integrity, or delivery was
   impacted and document corrective action.

For suspected tenant-isolation failure, immediately disable public access and
preserve the database for investigation. For a lost bot token, revoke it with
BotFather before changing any webhook.
