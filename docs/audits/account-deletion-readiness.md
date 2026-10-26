# Account deletion readiness — 2026-10-26

Status: **read-only preflight implemented; no public deletion endpoint or data mutation**. Current code is the Source of Truth. This note must be re-audited before implementation. No production database, backups, or user records were inspected. The owner confirmed the two user-facing choices and retention of the minimum payment information while a refund question is being resolved; this is not approval of a particular retention period or a legal determination.

`bot/services/account_deletion.py:inspect_account_deletion` is an internal read-only inventory. It never calls `get_or_create_user`, commits, mutates or deletes records. It recomputes a proposed `not_before` date from the current Pro row and always reports `destructive_flow_disabled`. The internal function is not attached to FastAPI, Telegram, or the WebApp. Its tests use only fictional in-memory SQLite records in `tests/test_account_deletion_preflight.py`; `tests/test_account_deletion_readiness.py` guards the reviewed user-FK inventory. Neither set of tests proves that deletion, payment separation, rollback or backup restoration works yet.

## Existing identity and partial actions

- `bot/api/deps.py:get_current_user` validates `X-Telegram-Init-Data`, then calls `SubscriptionService.get_or_create_user`. A successful request after a hard deletion would create a new `User` and free `Subscription`; therefore a repeated request is not currently idempotent at the account level.
- `bot/api/routes/misc.py:unlink_clash_account` (`POST /api/account/unlink`) and `bot/handlers/player.py:cmd_unlink` only detach the player tag. `SubscriptionService.unlink_player` in `bot/services/clash_api.py` explicitly leaves tag-keyed battle history intact. Neither action is account deletion; do not change them.
- `bot/api/routes/battles.py:clear_battle_history` (`DELETE /api/battles`) deletes `BattleCache` rows for the currently linked tag through `bot/services/battle_service.py:delete_persisted_battles_for_user`.
- `bot/api/routes/ai.py:clear_ai_session` (`DELETE /api/ai/session`) clears only process-local conversation state. `bot/api/routes/misc.py:clear_cache` clears process-local battle/AI caches.

## Data map

All ORM models below are in `bot/models/database.py`. Foreign keys have no declared `ON DELETE CASCADE`; most are non-nullable. Deleting a `User` without explicit treatment of dependents is unsafe. The list is a source-code inventory, not a claim about a live database schema.

| Data | Key/relationship | Ownership and proposed treatment pending approval |
| --- | --- | --- |
| `User` | unique `telegram_id`, unique nullable `player_tag` | Direct account identity. Remove only after all references and post-delete registration policy are resolved. |
| `UserSettings`, `CardPreference`, `FavoriteDeck`, `TrackedMineDeck`, `WeeklyDigestSent`, `ProReminderSent` | non-null `user_id -> users.id` | Account-specific; candidate for deletion in one transaction. Preserve `UserSettings`/subscription behavior until an approved endpoint exists. |
| `Subscription` | unique non-null `user_id -> users.id`; `payment_id`, `plan_id`, entitlement dates | Account-specific entitlement but linked to paid history. Do not change model or silently terminate active paid access. Owner decision required. |
| `ProPayment` | non-null `user_id -> users.id`, duplicate `telegram_id`, charge IDs, invoice payload, Stars, dates; unique charge ID | Payment audit trail. Do **not** delete or pseudonymize until retention, reconciliation, refund, and lawful-basis policy is approved. A retained row blocks a simple hard delete of `User`. |
| `ReferralReward` | `referrer_user_id -> users.id` | Reward history affecting an inviter's entitlement; cannot delete blindly. |
| `Referral` | `referrer_user_id` and unique `referred_user_id -> users.id`, optional `reward_id` | Connects two accounts and first-purchase rewards. Preserve the other user's result; decide how to sever/anonymize the deleted party. |
| `CreditTransaction` | `user_id -> users.id`, nullable `source_user_id -> users.id`, unique `reference_id` | Append-only ledger and other users' balance/reward history. Do not delete other users' transactions; source references and embedded IDs in reference keys need explicit treatment. |
| `BetaInvite` | nullable `used_by_user_id -> users.id`, plus `created_by_telegram_id` and `used_by_telegram_id` without FK | Admin/invite audit data; decide retention and identifier redaction separately. Do not delete another user's invite. |
| `BattleCache` | `player_tag`, battle time, opponent name/tag, deck and analysis; no `user_id` FK | Tag-keyed history may be reattached after unlink and feeds meta ingest. Never delete solely because a Telegram user is deleted without determining provenance and tag ownership. |
| `MetaBattleObservation` | scanned `player_tag`, `opponent_tag`, dedupe key, source (`cr_api` or `ghosteek_cache`); no user FK | Mixed official-API and Ghosteek-user observations. A linked player can also be an opponent or independently scanned player. Requires provenance/retention policy; no blanket delete by tag. |
| `MetaDeckAggregate`, `MetaDeckDailyStat`, `MetaSnapshot` | deck/mode/day aggregates and snapshot payload; no user FK | Shared statistics. Preserve; changing observations would require a separately approved, consistency-safe rebuild. |
| `FsmStorageRecord` | serialized aiogram key/value without user FK | Telegram/chat-scoped state may contain personal data. Key ownership must be parsed using the configured `DefaultKeyBuilder`; no broad string-match deletion. |

## Process-local and external data

- `bot/services/ghosteek_ai/memory/in_memory.py` stores AI conversations by Telegram ID; `clear_session` exists. `bot/services/battle_session_cache.py` and `bot/api/routes/decks.py:clear_opponents_cache_for_user` can clear per-user memory after a successful transaction. These caches are not transactionally atomic with SQL.
- `bot/services/ghosteek_ai/replay/service.py` removes spooled replay files in `finally`; `EvidenceStore` in `replay/evidence.py` holds bytes for 15 minutes by opaque ID **without owner mapping**. Per-user immediate evidence purge is not currently possible. `GET /api/ai/replay/evidence/{evidence_id}` checks Pro access but not evidence ownership.
- `bot/services/recommendation_cache.py` is shared by deck/context rather than account ID; do not flush all users' results for one deletion request.
- Telegram messages, application logs, backups, and any external payment records are outside the ORM deletion transaction. Their inventory, retention and handling are not established in code.

## Why the endpoint is withheld

1. `ProPayment` cannot be safely removed, yet its non-null FK references `User`; a hard delete is impossible without an approved retained-record/pseudonymization design and schema migration.
2. `Referral` and `CreditTransaction` affect **other users**. Deleting both sides or ledgers would corrupt credits and reward history; `reference_id` and invite records can retain identifiers even if FKs are changed.
3. Tag-keyed battles and observations have mixed provenance. Their deletion may remove shared data or leave personal traces in derived statistics. The current meta collector also samples linked tags and can ingest `BattleCache` rows.
4. `get_current_user` auto-creates missing accounts. An idempotent delete needs an approved re-registration/tombstone policy and a non-creating authenticated lookup for the deletion flow.
5. Replay evidence lacks per-user ownership; FSM state and backups need verified scope. Database commit cannot atomically erase process memory, Telegram messages, or backups.

## Agreed user-facing choices for an active Pro subscription

- **Delete after Pro expires:** keep the account and paid access until the recorded `Subscription.expires_at`, then request account deletion. A later Pro purchase may extend that date, so the eventual execution must re-check the current entitlement; it must not use a stale date captured when the request was made.
- **Delete now:** clearly warn that Pro access ends immediately. For a payment question or a possible refund, direct the user to the existing payment-support channel; do not promise a full or prorated refund or attempt one automatically. This choice includes a partly used current month as well as future paid months.
- Both choices require an explicit confirmation separate from the existing unlink and battle-history actions. Neither choice is implemented or exposed by this note.
- Payment records, inter-user rewards/credits, retention period, backup/log handling, and re-registration policy remain unresolved. Do not label a support request or a hidden account as completed deletion.

## Conditions before enabling irreversible deletion

- Set and publish the exact purposes, categories, legal basis, access restrictions, and end condition for retained payment records, including records with no open dispute. Decide who closes a support case and when remaining identifiers are removed or separately archived. The owner's approval to keep a minimum pending a refund decision does not define these rules.
- Document what is removed immediately, what is retained for a defined purpose, and how requests affecting backups, logs, replay evidence, tag-keyed battles, and shared meta observations are handled. The UI must not promise complete erasure of records that remain.
- Define the no-refund/no-response outcome and how an already-paid, partly used period is treated. The existing Telegram Stars API supports refunding a whole charge by charge ID, not an arbitrary prorated amount; support must not promise a partial automatic Stars refund.
- Obtain a jurisdiction- and operator-specific legal review of the published privacy/deletion notice and retention schedule before enabling the destructive endpoint. For an operator subject to Russian law, Article 5 and Article 21 of Federal Law 152-FZ require purpose limitation and govern termination/deletion; this note is not a substitute for legal advice. Relevant official references: https://mintrud.gov.ru/docs/laws/130 and https://core.telegram.org/bots/payments-stars .

## Proposed gated design (only read-only preflight implemented)

1. Owner supplies decisions on payment/credit/referral/invite retention and anonymization, active Pro entitlements, account re-registration, backups/logs, replay evidence, and tag-keyed battle/meta provenance. Obtain legal review for retention periods and notices; this document asserts no legal rule.
2. Re-audit the actual production schema **read-only** for FK/index drift before any migration. Design explicit nullable/archival references where retention is required; do not add broad cascades. Verify historic records and restore procedure in an isolated copy with fictitious data.
3. Add a non-creating auth dependency using existing Telegram init-data verification. The deletion target must be the authenticated Telegram ID only; never accept `user_id` or `player_tag` as an authority-bearing request parameter. Define an idempotent response for absent/already-deleted accounts without logging personal values.
4. Use a two-step, short-lived confirmation challenge bound to the authenticated account, with an explicit irreversible-action message. Do not require unapproved legal checkbox. Expire and consume the challenge once; defend against concurrent requests.
5. In a single database transaction, lock the account where supported, re-check the confirmation and approved retention rules, then explicitly handle every FK and direct record. If any check fails, roll back completely. Do not modify payment charge IDs, balances of other accounts, shared aggregates, or existing unlink behavior.
6. After commit, clear owned process-local caches and FSM state with exact keys. Record only a non-personal operation result/trace token. Deal with non-atomic cache failure through bounded retry and short TTL; no raw tag, Telegram ID or deleted content in logs.
7. Add a restore-safe rollout gate: endpoint disabled until approved policies, migration, tests, and backup procedure are signed off. Never execute against production in development/tests.

## Acceptance tests required before enablement

Use isolated, in-memory or disposable test databases with fictitious users and mocked Telegram init-data/payment services. Current preflight tests cover active Pro timing, a changed expiry, attached payments and cross-user links, shared meta counting, no account creation for a missing ID, and no writes. They do **not** exercise deletion. Before enablement, add: own account only; cross-user denial; explicit confirmation and expiry; preservation of another user's referral/credits; shared meta rows intact; retained payment record rule; repeated registration after deletion; failure injection with full SQL rollback; concurrent duplicate requests; cache/FSM cleanup; unlinked user; tag reused/relinked; no personal data in logs; restore from a backup without reactivating a deleted account. Do not claim these are passing until the implementation exists.

## Decisions still requiring the owner and legal review

| Decision | Minimal safe proposal; no retention period inferred |
| --- | --- |
| Applicable law and operator status | Confirm the legal entity/individual status and jurisdictions of users, processing, and payments; have a qualified adviser review the final policy before activation. Do not infer that all users are under one jurisdiction from a Moscow timezone. |
| Payment-record retention | Separate payment records from the active account in a future schema change. Retain only fields demonstrably needed for reconciliation, support, and approved obligations; restrict access. Approve a purpose, legal basis, end condition and deletion procedure for each field, including when no dispute is opened. No fixed duration is assigned here. |
| Refund handling | Keep `/paysupport` as the manual route. Decide and publish how requests for wholly unused future periods and partly used current periods are evaluated; do not promise an automatic or prorated Stars refund. Decide when a case is closed if the user does not respond. |
| Account/deletion notice | Approve the exact user-facing wording and a list of what disappears immediately, what remains for a defined purpose, and how to make a support request. Do not call a pending request completed deletion. |
| Shared referral, credits and game history | Preserve already-granted benefits and aggregate Meta. Approve the least-identifying reference necessary for anti-fraud and account reconciliation, plus provenance-based handling of tag-keyed battle records. Never erase another person's balance to satisfy one request. |
| Backups and re-registration | Choose an external, durable deletion ledger or equivalent restore barrier **outside** the database backup being restored. Block public traffic after restore until deletion markers have been reapplied and verified. Define when a deleted Telegram identity may create a new account and whether old paid/credit state can ever be reattached. A marker only inside the same backup is insufficient. |
