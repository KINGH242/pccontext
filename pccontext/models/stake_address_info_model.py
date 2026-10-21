from dataclasses import dataclass, field
from typing import Optional

from pccontext.models import BaseModel

__all__ = ["StakeAddressInfo"]


@dataclass(frozen=True)
class StakeAddressInfo(BaseModel):
    """
    Stake address info model class
    """

    active: Optional[bool] = field(default=True)
    active_epoch: Optional[int] = field(default=None)
    address: Optional[str] = field(default=None, metadata={"aliases": ["stake_address", "address"]})
    delegation_deposit: int = field(
        default=0,
        metadata={"aliases": ["delegation_deposit", "delegationDeposit", "deposit"]},
    )
    reward_account_balance: int = field(
        default=0,
        metadata={
            "aliases": [
                "reward_account_balance",
                "rewardAccountBalance",
                "rewards_available",
                "withdrawable_amount",
            ]
        },
    )
    stake_delegation: Optional[str] = field(
        default=None,
        metadata={"aliases": ["stake_delegation", "stakeDelegation", "delegated_pool"]},
    )
    vote_delegation: Optional[str] = field(default=None, metadata={"aliases": ["vote_delegation", "voteDelegation"]})
    delegate_representative: Optional[str] = field(
        default=None,
        metadata={
            "aliases": [
                "delegate_representative",
                "delegateRepresentative",
                "delegated_drep",
                "drep_id",
            ]
        },
    )
