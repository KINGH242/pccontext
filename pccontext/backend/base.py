"""Defines interfaces for client codes to interact (read/write) with the blockchain."""

from typing import List, Optional, Tuple, Union

from pycardano import ChainContext as BaseChainContext
from pycardano import (
    CommitteeColdCredential,
    CommitteeHotCredential,
    DRep,
    GovActionId,
    PoolOperator,
    TransactionInput,
    UTxO,
)

from pccontext.enums import ContextType, Era
from pccontext.models import (
    ChainTip,
    CommitteeMemberInfo,
    CommitteeStateInfo,
    DRepInfo,
    DRepStakeEntry,
    GovActionInfo,
    GovActionVotes,
    KESPeriodInfo,
    SPOStakeEntry,
    StakeAddressInfo,
    StakePoolInfo,
)

__all__ = [
    "ChainContext",
]


class ChainContext(BaseChainContext):
    """Extends PyCardano's chain context with stake, pool and governance queries.

    Every query below has a default implementation that raises
    :class:`NotImplementedError`, so a backend only implements what the service
    behind it can actually answer. Callers that need to work across backends
    should be prepared for that; see the capability matrix in the documentation
    for what each backend supports.
    """

    @property
    def name(self) -> str:
        """A human-readable name for this context, used in logs and errors."""
        return type(self).__name__

    @property
    def context_type(self) -> ContextType:
        """Whether this context reaches the network or answers from captured data.

        Defaults to :attr:`~pccontext.enums.ContextType.ONLINE`; the offline
        transfer file context overrides it.
        """
        return ContextType.ONLINE

    # -- Chain state ------------------------------------------------------

    @property
    def era(self) -> Optional[Era]:
        """The era the chain is currently in."""
        raise NotImplementedError(f"era is not implemented for {self.name}.")

    @property
    def chain_tip(self) -> ChainTip:
        """The current tip of the chain.

        Returns:
            ChainTip: The slot, block hash and height of the latest block, as
            far as the backend reports them.
        """
        raise NotImplementedError(f"chain_tip is not implemented for {self.name}.")

    def utxo(self, tx_input: TransactionInput) -> Optional[Tuple[UTxO, bool]]:
        """Resolve a single UTxO by the transaction input that identifies it.

        Args:
            tx_input (TransactionInput): The transaction hash and output index.

        Returns:
            Optional[Tuple[UTxO, bool]]: The UTxO and whether it has been spent,
            or ``None`` if it does not exist. Backends that only see the live
            UTxO set report ``False`` for a UTxO they return, and ``None``
            rather than ``True`` for one that has been spent.
        """
        raise NotImplementedError(f"utxo is not implemented for {self.name}.")

    # -- Stake addresses --------------------------------------------------

    def stake_address_info(self, stake_address: str) -> List[StakeAddressInfo]:
        """Get the stake address information.

        Args:
            stake_address (str): The stake address.

        Returns:
            List[StakeAddressInfo]: The stake address information.
        """
        raise NotImplementedError(
            f"stake_address_info is not implemented for {self.name}."
        )

    # -- Stake pools ------------------------------------------------------

    def stake_pools(self) -> List[PoolOperator]:
        """Get every stake pool registered on the chain.

        Returns:
            List[PoolOperator]: The registered pools.
        """
        raise NotImplementedError(f"stake_pools is not implemented for {self.name}.")

    def stake_pool_info(self, pool_id: str, strict: bool = False) -> StakePoolInfo:
        """Get a stake pool's registered parameters and stake figures.

        Args:
            pool_id (str): The pool's ID, bech32 encoded.
            strict (bool): When ``True``, the pool's off-chain metadata is
                fetched and its hash verified, and any failure — an unreachable
                URL or a hash mismatch — is raised. When ``False`` (the default)
                metadata problems are tolerated so the on-chain parameters can
                still be returned. Backends that never fetch off-chain metadata
                ignore this argument.

        Returns:
            StakePoolInfo: The pool's information.
        """
        raise NotImplementedError(
            f"stake_pool_info is not implemented for {self.name}."
        )

    def kes_period_info(
        self,
        pool: Optional[PoolOperator] = None,
        op_cert: Optional[Union[bytes, str]] = None,
    ) -> KESPeriodInfo:
        """Get the KES period information for a pool's operational certificate.

        Args:
            pool (Optional[PoolOperator]): The pool operator. Optional if
                ``op_cert`` is given.
            op_cert (Optional[Union[bytes, str]]): The operational certificate,
                CBOR encoded. Optional if ``pool`` is given.

        Returns:
            KESPeriodInfo: The current KES period and the counters needed to
            decide whether the certificate should be rotated.
        """
        raise NotImplementedError(
            f"kes_period_info is not implemented for {self.name}."
        )

    # -- Treasury ---------------------------------------------------------

    def treasury(self) -> int:
        """Get the current treasury balance, in lovelace."""
        raise NotImplementedError(f"treasury is not implemented for {self.name}.")

    # -- Governance -------------------------------------------------------

    def drep_info(self, drep: DRep) -> DRepInfo:
        """Get a delegate representative's registration and voting power.

        Args:
            drep (DRep): The DRep to look up.

        Returns:
            DRepInfo: The DRep's information.
        """
        raise NotImplementedError(f"drep_info is not implemented for {self.name}.")

    def gov_action_info(self, gov_action_id: GovActionId) -> GovActionInfo:
        """Get the lifecycle information for a governance action.

        Args:
            gov_action_id (GovActionId): The action's identifier.

        Returns:
            GovActionInfo: The action's information.
        """
        raise NotImplementedError(
            f"gov_action_info is not implemented for {self.name}."
        )

    def gov_action_votes(self, gov_action_id: GovActionId) -> GovActionVotes:
        """Get the votes recorded against a governance action, by voter class.

        Args:
            gov_action_id (GovActionId): The action's identifier.

        Returns:
            GovActionVotes: The proposal procedure and the committee, DRep and
            stake pool votes.
        """
        raise NotImplementedError(
            f"gov_action_votes is not implemented for {self.name}."
        )

    def gov_actions_all(self) -> List[GovActionVotes]:
        """Get every active governance proposal with its votes.

        The equivalent of ``cardano-cli query gov-state``'s proposals, shaped so
        the caller can filter in memory.

        Returns:
            List[GovActionVotes]: One entry per active proposal.
        """
        raise NotImplementedError(
            f"gov_actions_all is not implemented for {self.name}."
        )

    def committee_member_info(
        self,
        cold: Optional[CommitteeColdCredential] = None,
        hot: Optional[CommitteeHotCredential] = None,
    ) -> CommitteeMemberInfo:
        """Get a constitutional committee member's authorization and term.

        Args:
            cold (Optional[CommitteeColdCredential]): The member's cold
                credential. Optional if ``hot`` is given.
            hot (Optional[CommitteeHotCredential]): A hot credential the member
                has authorized. Optional if ``cold`` is given.

        Returns:
            CommitteeMemberInfo: The member's information.
        """
        raise NotImplementedError(
            f"committee_member_info is not implemented for {self.name}."
        )

    def committee_state(self) -> CommitteeStateInfo:
        """Get the full constitutional committee state.

        Returns:
            CommitteeStateInfo: Every member with its cold-to-hot authorization
            and term expiration, plus the active quorum threshold.
        """
        raise NotImplementedError(
            f"committee_state is not implemented for {self.name}."
        )

    # -- Stake distributions ----------------------------------------------

    def drep_stake_distribution(self) -> List[DRepStakeEntry]:
        """Get the stake delegated to each DRep this epoch.

        Returns:
            List[DRepStakeEntry]: One entry per DRep.
        """
        raise NotImplementedError(
            f"drep_stake_distribution is not implemented for {self.name}."
        )

    def spo_stake_distribution(self) -> List[SPOStakeEntry]:
        """Get the stake delegated to each stake pool this epoch.

        Returns:
            List[SPOStakeEntry]: One entry per pool.
        """
        raise NotImplementedError(
            f"spo_stake_distribution is not implemented for {self.name}."
        )
