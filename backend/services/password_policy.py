"""Phase 2 item 3: one shared password-strength rule, used by the CEO seed
script and the mandatory change-password endpoint alike — never duplicated."""

MIN_PASSWORD_LENGTH = 12

# A SMALL list of obviously-weak passwords that would otherwise pass the
# length check alone — not an exhaustive breach-corpus check, just the
# "no one should ever actually use this" list.
OBVIOUS_PASSWORDS = {
    "admin12345", "administrator", "password123", "password1234",
    "123456789012", "1234567890123", "qwertyuiop12", "qwertyuiop123",
    "letmein12345", "changeme1234", "changeme12345", "welcome12345",
    "welcome123456", "iloveyou1234", "trustno1trustno1",
}


def validate_password_strength(password, field="password"):
    """Raises ValueError with a clear message if `password` is too short or
    a known-obvious value. Never returns a reason for a WEAK-but-acceptable
    password — just pass/fail."""
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"{field} must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if password.lower() in OBVIOUS_PASSWORDS:
        raise ValueError(f"{field} is too common/predictable. Choose a less obvious password.")
