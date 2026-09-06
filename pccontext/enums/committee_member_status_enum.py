from enum import Enum

__all__ = ["CommitteeMemberStatus"]


class CommitteeMemberStatus(Enum):
    """
    Enum class for the status of a constitutional committee member.
    """

    ACTIVE = "active"
    EXPIRED = "expired"
    UNRECOGNIZED = "unrecognized"
