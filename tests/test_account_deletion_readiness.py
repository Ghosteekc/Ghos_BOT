"""Read-only guard for the account-deletion dependency inventory.

This deliberately parses source instead of importing the database module: no engine,
environment secrets, or real database can be touched by this test.
"""

import ast
from pathlib import Path


MODEL_SOURCE = Path(__file__).resolve().parents[1] / "bot" / "models" / "database.py"

USER_REFERENCES = {
    ("UserSettings", "user_id"),
    ("Subscription", "user_id"),
    ("ProPayment", "user_id"),
    ("CardPreference", "user_id"),
    ("FavoriteDeck", "user_id"),
    ("TrackedMineDeck", "user_id"),
    ("WeeklyDigestSent", "user_id"),
    ("ProReminderSent", "user_id"),
    ("ReferralReward", "referrer_user_id"),
    ("Referral", "referrer_user_id"),
    ("Referral", "referred_user_id"),
    ("CreditTransaction", "user_id"),
    ("CreditTransaction", "source_user_id"),
    ("BetaInvite", "used_by_user_id"),
}


def test_every_user_foreign_key_is_in_deletion_review():
    tree = ast.parse(MODEL_SOURCE.read_text(encoding="utf-8"))
    found = set()
    for model in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        for field in (node for node in model.body if isinstance(node, ast.AnnAssign)):
            if not isinstance(field.target, ast.Name) or field.value is None:
                continue
            for call in (node for node in ast.walk(field.value) if isinstance(node, ast.Call)):
                if not isinstance(call.func, ast.Name) or call.func.id != "ForeignKey":
                    continue
                if not call.args or not isinstance(call.args[0], ast.Constant):
                    continue
                if call.args[0].value == "users.id":
                    found.add((model.name, field.target.id))
                    assert not any(keyword.arg == "ondelete" for keyword in call.keywords)
    assert found == USER_REFERENCES


def test_shared_meta_models_do_not_reference_account_identity():
    tree = ast.parse(MODEL_SOURCE.read_text(encoding="utf-8"))
    shared = {"MetaDeckAggregate", "MetaDeckDailyStat", "MetaSnapshot"}
    models = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    assert shared <= models.keys()
    for name in shared:
        calls = (node for node in ast.walk(models[name]) if isinstance(node, ast.Call))
        assert not any(
            isinstance(call.func, ast.Name)
            and call.func.id == "ForeignKey"
            and call.args
            and isinstance(call.args[0], ast.Constant)
            and call.args[0].value == "users.id"
            for call in calls
        )
