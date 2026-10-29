"""Pure-Python helpers shared by the API, the seed generator and the tests.

Nothing here talks to a database.
"""

RANK_NAMES = {3: "OWNER", 2: "TRANSACT", 1: "VIEW"}

# --- Simple, explainable fraud rules (no ML) ---------------------------------
LARGE_MULT = 5              # amount > 5x the account's average transaction ...
LARGE_MIN = 10_000          # ... and at least this big ...
MIN_HISTORY = 3             # ... once the account has this many prior transactions
VELOCITY_WINDOW_MS = 10 * 60 * 1000
VELOCITY_COUNT = 3          # 3 earlier transactions by the same user in 10 minutes
NEW_ACCESS_MS = 24 * 60 * 60 * 1000
NEW_ACCESS_MIN = 10_000     # access gained <24h ago and amount >= this


def rank_of(rel_type, level):
    """OWNS=3 (OWNER), AUTHORIZED_SIGNATORY_OF=2 (TRANSACT), HAS_ACCESS_TO=level."""
    if rel_type == "OWNS":
        return 3
    if rel_type == "AUTHORIZED_SIGNATORY_OF":
        return 2
    return 2 if level == "TRANSACT" else 1


def evaluate_rules(amount, prior_count, prior_avg, recent_by_user, access_age_ms):
    """Return the list of fraud-rule codes triggered by a transaction."""
    reasons = []
    if (
        prior_count >= MIN_HISTORY
        and prior_avg
        and amount >= LARGE_MIN
        and amount > LARGE_MULT * prior_avg
    ):
        reasons.append("LARGE_AMOUNT")
    if recent_by_user >= VELOCITY_COUNT:
        reasons.append("HIGH_VELOCITY")
    if access_age_ms is not None and access_age_ms < NEW_ACCESS_MS and amount >= NEW_ACCESS_MIN:
        reasons.append("NEW_ACCESS_LARGE_TX")
    return reasons


def format_path(steps):
    """['Ravi' -[MEMBER_OF]-> 'Family' -[HAS_ACCESS_TO]-> 'Account'] as one readable string.

    Each step: {src_name, rel_type, dst_name, forward}. forward=False means the stored
    relationship points the other way (we walked it backwards, e.g. parent <- sub-account).
    """
    if not steps:
        return ""
    out = [steps[0]["src_name"]]
    for s in steps:
        arrow = f"-[{s['rel_type']}]->" if s["forward"] else f"<-[{s['rel_type']}]-"
        out.extend([arrow, s["dst_name"]])
    return " ".join(out)
