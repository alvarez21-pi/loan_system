def can_approve(user, record):
    """Return whether user can approve record under maker-checker rules."""
    if user is None or record is None:
        return False

    creator_id = getattr(record, "created_by", None)
    if creator_id is None:
        return False

    if getattr(user, "id", None) == creator_id:
        return False

    if getattr(user, "role", None) in {"admin", "checker"}:
        return True

    return False
