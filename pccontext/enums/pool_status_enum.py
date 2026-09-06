from enum import Enum

__all__ = ["PoolStatus"]


class PoolStatus(Enum):
    """
    Enum class for the registration status of a stake pool.
    """

    REGISTERED = "registered"
    RETIRED = "retired"
    RETIRING = "retiring"
