from dataclasses import dataclass, field
from typing import Optional

from pycardano import Anchor, DRep

from pccontext.enums import DRepStatus
from pccontext.models import BaseModel

__all__ = ["DRepInfo"]


@dataclass(frozen=True)
class DRepInfo(BaseModel):
    """
    Registration and voting-power information for a delegate representative.
    """

    drep: Optional[DRep] = field(default=None)
    """The DRep this record describes."""

    active: bool = field(default=False, metadata={"aliases": ["active", "isActive"]})
    """Whether the DRep is currently active."""

    anchor: Optional[Anchor] = field(default=None)
    """Off-chain metadata anchor, where one is registered."""

    deposit: Optional[int] = field(default=None, metadata={"aliases": ["deposit"]})
    """The deposit held for the registration, in lovelace."""

    stake: int = field(
        default=0,
        metadata={"aliases": ["stake", "votingPower", "voting_power", "amount"]},
    )
    """Stake delegated to this DRep, in lovelace."""

    expiry: Optional[int] = field(
        default=None, metadata={"aliases": ["expiry", "expiresAfter", "expires_after"]}
    )
    """The epoch after which the DRep's registration lapses."""

    status: Optional[DRepStatus] = field(default=None)
    """Registration status, where the backend reports it."""
