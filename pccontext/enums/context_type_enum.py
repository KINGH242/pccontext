from enum import Enum

__all__ = ["ContextType"]


class ContextType(Enum):
    """
    Enum class for the type of a chain context.

    An ``ONLINE`` context reaches a node or an API to answer queries. An
    ``OFFLINE`` context answers from data captured earlier, so its answers are
    only as fresh as that capture.
    """

    ONLINE = "online"
    OFFLINE = "offline"
