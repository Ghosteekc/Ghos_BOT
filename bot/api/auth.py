import hashlib
import hmac
import json
from urllib.parse import parse_qsl


class InitDataError(Exception):
    pass


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400) -> dict:
    """Validate Telegram WebApp initData per official docs."""
    if not init_data:
        raise InitDataError("Missing init data")

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise InitDataError("Missing hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed, received_hash):
        raise InitDataError("Invalid signature")

    auth_date = int(parsed.get("auth_date", "0"))
    import time
    if auth_date and time.time() - auth_date > max_age_seconds:
        raise InitDataError("Init data expired")

    user_raw = parsed.get("user")
    if not user_raw:
        raise InitDataError("Missing user")
    user = json.loads(user_raw)
    if "id" not in user:
        raise InitDataError("Invalid user payload")

    return user
