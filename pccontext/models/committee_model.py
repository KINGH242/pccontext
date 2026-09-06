from dataclasses import dataclass, field
from typing import List, Optional

from pycardano import CommitteeColdCredential, CommitteeHotCredential

from pccontext.enums import CommitteeMemberStatus
from pccontext.models import BaseModel

__all__ = ["CommitteeMemberInfo", "CommitteeStateInfo"]


@dataclass(frozen=True)
class CommitteeMemberInfo(BaseModel):
    """
    A single constitutional committee member.

    A member votes with a hot credential that its cold credential has
    authorized. ``hot_credential`` is ``None`` when no authorization is
    currently registered, which is also how a resigned member appears.
    """

    cold_credential: Optional[CommitteeColdCredential] = field(default=None)
    """The member's cold credential, which identifies it."""

    hot_credential: Optional[CommitteeHotCredential] = field(default=None)
    """The authorized hot credential, if any."""

    expiration: Optional[int] = field(
        default=None,
        metadata={"aliases": ["expiration", "expires_after", "expiresAfter"]},
    )
    """The epoch the member's term expires in."""

    status: Optional[CommitteeMemberStatus] = field(default=None)
    """Membership status, where the backend reports it."""


@dataclass(frozen=True)
class CommitteeStateInfo(BaseModel):
    """
    The full constitutional committee state: every member with its
    authorization and term, plus the quorum threshold in force.
    """

    members: List[CommitteeMemberInfo] = field(default_factory=list)
    """The committee's members."""

    threshold: Optional[float] = field(
        default=None, metadata={"aliases": ["threshold", "quorum"]}
    )
    """The fraction of members that must vote yes for the committee to assent."""
