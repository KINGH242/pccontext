from dataclasses import dataclass, field
from typing import Any, List, Optional

from pycardano import Anchor, CommitteeHotCredential, DRep, GovActionId, Vote

from pccontext.enums import GovActionStatus
from pccontext.models import BaseModel
from pccontext.models.gov_action_info_model import GovActionInfo

__all__ = [
    "CommitteeVote",
    "DRepVote",
    "StakePoolVote",
    "GovActionVotes",
]


@dataclass(frozen=True)
class CommitteeVote(BaseModel):
    """A vote cast on a governance action by a constitutional committee member."""

    voter: Optional[CommitteeHotCredential] = field(default=None)
    """The hot credential the member voted with."""

    vote: Optional[Vote] = field(default=None)
    """The vote cast."""

    anchor: Optional[Anchor] = field(default=None)
    """Optional off-chain rationale for the vote."""


@dataclass(frozen=True)
class DRepVote(BaseModel):
    """A vote cast on a governance action by a delegate representative."""

    voter: Optional[DRep] = field(default=None)
    vote: Optional[Vote] = field(default=None)
    anchor: Optional[Anchor] = field(default=None)


@dataclass(frozen=True)
class StakePoolVote(BaseModel):
    """A vote cast on a governance action by a stake pool operator."""

    voter: Optional[str] = field(
        default=None, metadata={"aliases": ["voter", "pool_id", "poolId"]}
    )
    """The voting pool's ID, bech32 encoded."""

    vote: Optional[Vote] = field(default=None)
    anchor: Optional[Anchor] = field(default=None)


@dataclass(frozen=True)
class GovActionVotes(BaseModel):
    """
    A governance action together with every vote recorded against it, split by
    voter class, plus the proposal procedure needed to display it.

    Vote lists are empty when no votes have been recorded for that class yet,
    which is not the same as the backend being unable to report them.
    """

    gov_action_id: Optional[GovActionId] = field(default=None)
    gov_action: Optional[Any] = field(default=None)

    committee_votes: List[CommitteeVote] = field(default_factory=list)
    drep_votes: List[DRepVote] = field(default_factory=list)
    stake_pool_votes: List[StakePoolVote] = field(default_factory=list)

    deposit: Optional[int] = field(default=None, metadata={"aliases": ["deposit"]})
    """The deposit paid to submit the proposal, in lovelace."""

    deposit_return_addr: Optional[str] = field(
        default=None,
        metadata={
            "aliases": [
                "deposit_return_addr",
                "depositReturnAddr",
                "reward_account",
                "returnAddr",
            ]
        },
    )
    """The reward account the deposit returns to."""

    anchor: Optional[Anchor] = field(default=None)

    proposed_in: Optional[int] = field(
        default=None, metadata={"aliases": ["proposed_in", "proposedIn"]}
    )
    expires_after: Optional[int] = field(
        default=None, metadata={"aliases": ["expires_after", "expiresAfter"]}
    )
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
        """The action's lifecycle status, derived exactly as for
        :class:`~pccontext.models.gov_action_info_model.GovActionInfo`."""
        return self.as_gov_action_info().status

    def as_gov_action_info(self) -> GovActionInfo:
        """Narrow this aggregate to just the action's lifecycle information,
        dropping the votes and the proposal procedure."""
        return GovActionInfo(
            gov_action_id=self.gov_action_id,
            gov_action=self.gov_action,
            proposed_in=self.proposed_in,
            expires_after=self.expires_after,
            ratified_epoch=self.ratified_epoch,
            enacted_epoch=self.enacted_epoch,
            dropped_epoch=self.dropped_epoch,
            expired_epoch=self.expired_epoch,
        )
