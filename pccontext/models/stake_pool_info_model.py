from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from pycardano import PoolParams

from pccontext.enums import PoolStatus
from pccontext.models import BaseModel

__all__ = ["StakePoolInfo"]


@dataclass(frozen=True)
class StakePoolInfo(BaseModel):
    """
    On-chain registration and stake figures for a single stake pool.

    ``pool_params`` carries the registered parameters (pledge, cost, margin,
    reward account, owners, relays and metadata). The remaining fields are
    reported by the backend where it can supply them, and are ``None``
    otherwise.
    """

    pool_params: Optional[PoolParams] = field(default=None)
    """The pool's registered parameters."""

    live_pledge: Optional[int] = field(
        default=None, metadata={"aliases": ["live_pledge", "livePledge"]}
    )
    """Lovelace currently pledged by the owners."""

    live_stake: Optional[int] = field(
        default=None, metadata={"aliases": ["live_stake", "liveStake"]}
    )
    """Lovelace currently delegated to the pool."""

    live_size: Optional[Decimal] = field(
        default=None, metadata={"aliases": ["live_size", "liveSize"]}
    )
    """The pool's live stake as a fraction of total live stake."""

    active_stake: Optional[int] = field(
        default=None, metadata={"aliases": ["active_stake", "activeStake"]}
    )
    """Lovelace counted toward this epoch's rewards."""

    active_size: Optional[Decimal] = field(
        default=None, metadata={"aliases": ["active_size", "activeSize"]}
    )
    """The pool's active stake as a fraction of total active stake."""

    opcert_counter: Optional[int] = field(
        default=None,
        metadata={"aliases": ["opcert_counter", "opcertCounter", "op_cert_counter"]},
    )
    """The operational certificate counter registered on-chain."""

    status: Optional[PoolStatus] = field(default=None)
    """Registration status, where the backend reports it."""

    retiring_epoch: Optional[int] = field(
        default=None,
        metadata={"aliases": ["retiring_epoch", "retiringEpoch", "retiring_at"]},
    )
    """The epoch the pool retires in, when :attr:`status` is ``RETIRING``."""
