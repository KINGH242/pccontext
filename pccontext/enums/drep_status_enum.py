from enum import Enum

__all__ = ["DRepStatus"]


class DRepStatus(Enum):
    """
    Enum class for the registration status of a delegate representative.
    """

    REGISTERED = "registered"
    RETIRED = "retired"
    NOT_REGISTERED = "not_registered"
