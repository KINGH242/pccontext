from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pccontext.models import BaseModel

__all__ = ["KESPeriodInfo"]


@dataclass(frozen=True)
class KESPeriodInfo(BaseModel):
    """
    Key Evolving Signature (KES) period information for a stake pool's
    operational certificate.

    KES limits the damage from a compromised key: an operational certificate is
    issued for a KES period and must be rotated before it expires. A pool
    operator compares the on-chain counter against the one in the local
    certificate file to know whether a rotation has taken effect.

    Example:
        >>> info = context.kes_period_info(pool=pool_operator)
        >>> if (
        ...     info.on_disk_op_cert_count is not None
        ...     and info.on_chain_op_cert_count is not None
        ...     and info.on_disk_op_cert_count > info.on_chain_op_cert_count
        ... ):
        ...     print("Operational certificate is ready to rotate")
    """

    on_chain_op_cert_count: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "on_chain_op_cert_count",
                "onChainOpCertCount",
                # Not qKesOnDiskOperationalCertificateNumber: that is the
                # on-disk counter and belongs to the field below. Listing it
                # here too made the mapping depend on field declaration order.
                "qKesNodeStateOperationalCertificateNumber",
            ]
        },
    )
    """The operational certificate counter registered on-chain.

    ``-1`` means the pool has never minted a block.
    """

    on_disk_op_cert_count: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "on_disk_op_cert_count",
                "onDiskOpCertCount",
                "qKesOnDiskOperationalCertificateNumber",
            ]
        },
    )
    """The counter from the local operational certificate file.

    This should be greater than :attr:`on_chain_op_cert_count` while a rotation
    is pending.
    """

    next_chain_op_cert_count: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "next_chain_op_cert_count",
                "nextChainOpCertCount",
                "qKesExpectedOperationalCertificateNumber",
            ]
        },
    )
    """The counter to use when generating the next operational certificate."""

    on_disk_kes_start: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "on_disk_kes_start",
                "onDiskKESStart",
                "qKesStartKesInterval",
            ]
        },
    )
    """The KES period at which the on-disk certificate was issued."""
