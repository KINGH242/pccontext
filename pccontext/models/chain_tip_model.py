from dataclasses import dataclass, field
from typing import Optional

from pccontext.enums import Era
from pccontext.models import BaseModel

__all__ = ["ChainTip"]


@dataclass(frozen=True)
class ChainTip(BaseModel):
    """
    The current tip of the chain, as reported by a chain context.

    Backends differ in how much of this they can answer. ``slot`` is the only
    field every backend supplies; the rest are ``None`` when the backend does
    not report them.
    """

    slot: Optional[int] = field(
        default=None, metadata={"aliases": ["slot", "slot_no", "slotNo", "absSlot"]}
    )
    hash: Optional[str] = field(
        default=None,
        metadata={"aliases": ["hash", "block_hash", "blockHash", "headerHash", "id"]},
    )
    block: Optional[int] = field(
        default=None,
        metadata={
            "aliases": ["block", "block_no", "blockNo", "height", "block_height"]
        },
    )
    epoch: Optional[int] = field(
        default=None, metadata={"aliases": ["epoch", "epoch_no", "epochNo"]}
    )
    era: Optional[Era] = field(default=None, metadata={"aliases": ["era"]})
    sync_progress: Optional[float] = field(
        default=None,
        metadata={"aliases": ["sync_progress", "syncProgress", "syncPercentage"]},
    )
