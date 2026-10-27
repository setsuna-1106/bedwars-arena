"""Integer simulation time; the 20 Hz clock is a platform convention."""

from decimal import Decimal

TICKS_PER_SECOND = 20
MAX_SAFE_INTEGER = 2**53 - 1


def integer(value: object, name: str, minimum: int = 0) -> int:
    """Reject bools, fractions and integers unsafe in JSON consumers."""
    if type(value) is not int or not minimum <= value <= MAX_SAFE_INTEGER:
        raise ValueError(f"{name} must be an integer in [{minimum}, {MAX_SAFE_INTEGER}]")
    return value


def identifier(value: object, name: str = "id") -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError(f"{name} must be a nonempty string of at most 128 characters")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{name} must not contain control characters")
    return value


def seconds_to_ticks(seconds: str | int | Decimal) -> int:
    """Require an exact tick boundary rather than silently rounding."""
    if isinstance(seconds, bool) or isinstance(seconds, float):
        raise ValueError("Use an integer, decimal string or Decimal for seconds")
    value = Decimal(seconds) * TICKS_PER_SECOND
    if not value.is_finite() or value != value.to_integral_value():
        raise ValueError("Time must fall on a finite 50 ms simulation boundary")
    return integer(int(value), "ticks")
