"""Remove unneeded identity fields from structured facts sent to a model.

Free-form user text and game facts may still contain identifying information.
This is minimisation, not anonymisation.
"""

_IDENTITY_FIELDS = frozenset({
    "telegram_id", "user_id", "chat_id", "player_tag", "opponent_tag",
    "tag", "username", "player_name", "opponent_name", "payment_id",
    "telegram_payment_charge_id", "provider_payment_charge_id", "invoice_payload",
})


def minimize_model_facts(value):
    if isinstance(value, dict):
        return {
            key: minimize_model_facts(item)
            for key, item in value.items()
            if not isinstance(key, str) or key.lower() not in _IDENTITY_FIELDS
        }
    if isinstance(value, list):
        return [minimize_model_facts(item) for item in value]
    return value
