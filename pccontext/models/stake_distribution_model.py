from dataclasses import dataclass, field
from typing import Optional

from pycardano import DRep

from pccontext.models import BaseModel

__all__ = ["DRepStakeEntry", "SPOStakeEntry"]


@dataclass(frozen=True)
class DRepStakeEntry(BaseModel):
    """
    One row of the DRep stake distribution: the stake that counts toward a
    DRep's voting power this epoch.
    """

    drep: Optional[DRep] = field(default=None)
    """The DRep the stake is delegated to."""

    stake: int = field(
        default=0, metadata={"aliases": ["stake", "amount", "votingPower"]}
    )
    """Delegated stake, in lovelace."""


@dataclass(frozen=True)
class SPOStakeEntry(BaseModel):
    """
    One row of the stake pool operator stake distribution: the stake that
    counts toward a pool's voting power this epoch.
    """

    pool_id: Optional[str] = field(
        default=None, metadata={"aliases": ["pool_id", "poolId", "pool"]}
    )
    """The pool's ID, bech32 encoded."""

    stake: int = field(default=0, metadata={"aliases": ["stake", "amount"]})
    """Delegated stake, in lovelace."""
