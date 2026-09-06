from __future__ import annotations

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

    stake: Optional[int] = field(
        default=None, metadata={"aliases": ["stake", "amount", "votingPower"]}
    )
    """Delegated stake, in lovelace, or ``None`` when the backend cannot report
    it. ``None`` is not the same answer as ``0``; see
    :attr:`~pccontext.models.drep_info_model.DRepInfo.stake`."""


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

    stake: Optional[int] = field(
        default=None, metadata={"aliases": ["stake", "amount"]}
    )
    """Delegated stake, in lovelace, or ``None`` when the backend cannot report
    it. ``None`` is not the same answer as ``0``; see
    :attr:`~pccontext.models.drep_info_model.DRepInfo.stake`."""
