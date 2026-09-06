from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from pycardano import GovActionId

from pccontext.enums import GovActionStatus
from pccontext.models import BaseModel

__all__ = ["GovActionInfo"]


@dataclass(frozen=True)
class GovActionInfo(BaseModel):
    """
    Lifecycle information for a single governance action.

    The epoch fields record where the action reached in its lifecycle; at most
    one of them is set for a resolved action, and :attr:`status` derives from
    whichever it is.
    """

    gov_action_id: Optional[GovActionId] = field(default=None)
    """The action's identifier."""

    gov_action: Optional[Any] = field(default=None)
    """The proposed action itself (a :mod:`pycardano` governance action)."""

    proposed_in: Optional[int] = field(
        default=None, metadata={"aliases": ["proposed_in", "proposedIn"]}
    )
    """The epoch the action was proposed in."""

    expires_after: Optional[int] = field(
        default=None, metadata={"aliases": ["expires_after", "expiresAfter"]}
    )
    """The epoch after which the action expires if not ratified."""

    ratified_epoch: Optional[int] = field(
        default=None, metadata={"aliases": ["ratified_epoch", "ratifiedEpoch"]}
    )
    enacted_epoch: Optional[int] = field(
        default=None, metadata={"aliases": ["enacted_epoch", "enactedEpoch"]}
    )
    dropped_epoch: Optional[int] = field(
        default=None, metadata={"aliases": ["dropped_epoch", "droppedEpoch"]}
    )
    expired_epoch: Optional[int] = field(
        default=None, metadata={"aliases": ["expired_epoch", "expiredEpoch"]}
    )

    @property
    def status(self) -> Optional[GovActionStatus]:
        """The action's lifecycle status, or ``None`` while it is still open.

        Enactment is checked first: an action that was ratified and then enacted
        has both epochs set, and ``ENACTED`` is the later, more specific state.
        """
        if self.enacted_epoch is not None:
            return GovActionStatus.ENACTED
        if self.ratified_epoch is not None:
            return GovActionStatus.RATIFIED
        if self.dropped_epoch is not None:
            return GovActionStatus.DROPPED
        if self.expired_epoch is not None:
            return GovActionStatus.EXPIRED
        return None
