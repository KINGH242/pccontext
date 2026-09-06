from enum import Enum

__all__ = ["GovActionStatus"]


class GovActionStatus(Enum):
    """
    Enum class for the lifecycle status of a governance action.
    """

    ENACTED = "enacted"
    RATIFIED = "ratified"
    DROPPED = "dropped"
    EXPIRED = "expired"
