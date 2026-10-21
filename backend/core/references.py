"""Human-friendly unique references (tickets, complaints, feedback)."""
import secrets

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I confusion


def new_reference(prefix: str, length: int = 8) -> str:
    return f"{prefix}-" + "".join(secrets.choice(_ALPHABET) for _ in range(length))
