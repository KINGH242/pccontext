from __future__ import annotations

import contextlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple, Union

from cachetools import func
from pycardano import CommitteeColdCredential, CommitteeHotCredential, DRep
from pycardano import GenesisParameters as PyCardanoGenesisParameters
from pycardano import GovActionId
from pycardano import Network as PyCardanoNetwork
from pycardano import PoolOperator
from pycardano import ProtocolParameters as PyCardanoProtocolParameters
from pycardano import Transaction, TransactionInput, UTxO

from pccontext.backend import ChainContext
from pccontext.enums import (
    CommitteeMemberStatus,
    ContextType,
    Era,
    HistoryType,
    Network,
    TransactionType,
)
from pccontext.exceptions import OfflineTransferFileError
from pccontext.models import (
    ChainTip,
    CommitteeMemberInfo,
    CommitteeStateInfo,
    DRepInfo,
    DRepStakeEntry,
    GenesisParameters,
    GovActionInfo,
    GovActionVotes,
    KESPeriodInfo,
    OfflineTransfer,
    OfflineTransferHistory,
    OfflineTransferTransaction,
    ProtocolParameters,
    SPOStakeEntry,
    StakeAddressInfo,
    StakePoolInfo,
)
from pccontext.models.offline_transfer_model import TransactionJSON
from pccontext.utils import check_file_exists, dump_file, load_json_file

__all__ = ["OfflineTransferFileContext"]


def byron_to_shelley_epoch_transition(
    network: Network, byron_to_shelley_epoch: Optional[int] = None
) -> int:
    """
    The number of Byron Epochs before the Chain forks to Shelley-Era
    :return:
    """
    if network == Network.MAINNET:
        return 208
    elif network == Network.PREPROD:
        return 4
    elif network == Network.PREVIEW:
        return 0
    elif network == Network.GUILDNET:
        return 2
    elif network == Network.CUSTOM:
        return byron_to_shelley_epoch or 0
    else:
        return 0


class OfflineTransferFileContext(ChainContext):
    """
    Offline transfer file context. To be used with the offline transfer file.

    Every answer comes from the JSON transfer file, which was captured on an
    online machine and carried across. Nothing here reaches the network, so a
    query is only as fresh as the capture: stake and voting-power figures are
    those of the capture's epoch, and a pool, DRep, proposal or committee member
    registered since is simply not in the file. Slot and epoch are the exception
    — they are computed from the captured genesis parameters and the wall clock,
    which makes them exact.

    A section the capture did not write is reported as a missing section, never
    as an empty chain: :meth:`stake_pools` on a file with no ``stake_pools``
    section raises, while one that captured an empty register returns ``[]``.
    Files written before a section existed keep loading, with that section
    absent.
    """

    _offline_transfer_file: Path
    """Path to the offline transfer file"""

    _offline_transfer: OfflineTransfer
    """Offline transfer file object model"""

    _genesis_param: Optional[GenesisParameters]
    """Genesis protocol_parameters"""

    _protocol_param: Optional[ProtocolParameters]
    """Protocol protocol_parameters"""

    def __init__(
        self,
        offline_transfer_file: Path,
    ):
        super().__init__()
        self._offline_transfer_file = offline_transfer_file
        self._genesis_param = None
        self._protocol_param = None
        self._offline_transfer = self.load()

    @property
    def name(self) -> str:
        return "OfflineTransferFile"

    @property
    def context_type(self) -> ContextType:
        return ContextType.OFFLINE

    @property
    def offline_transfer(self) -> OfflineTransfer:
        """
        Get the offline transfer file
        :return: The offline transfer file
        """
        return self._offline_transfer

    def check(self) -> None:
        """
        Check that the offlineTransfer.json file exist
        :return: None
        """
        try:
            check_file_exists(self._offline_transfer_file)
        except FileNotFoundError:
            print(
                f"Offline transfer file is not a file or does not exist: "
                f"{self._offline_transfer_file.as_posix()}\n"
                f"Creating a new one..."
            )
            OfflineTransfer.new(self._offline_transfer_file)

    def load(self) -> OfflineTransfer:
        """
        Load the offline transfer file
        :return: The offline transfer file
        """
        try:
            self.check()
            return OfflineTransfer.from_json(
                load_json_file(self._offline_transfer_file)
            )
        except FileNotFoundError as e:
            raise OfflineTransferFileError(
                f"Offline transfer file does not exist: {self._offline_transfer_file}"
            ) from e

    def _fetch_protocol_param(self) -> ProtocolParameters:
        if not self.offline_transfer.protocol:
            raise OfflineTransferFileError(
                "Protocol parameters not found in the offline transfer file."
            )
        result = self.offline_transfer.protocol.protocol_parameters
        if isinstance(result, ProtocolParameters):
            return result
        elif isinstance(result, dict):
            return ProtocolParameters.from_json(result)
        else:
            return ProtocolParameters(**result.__dict__)

    def _fetch_genesis_param(self) -> GenesisParameters:
        if not self.offline_transfer.protocol:
            raise OfflineTransferFileError(
                "Protocol parameters not found in the offline transfer file."
            )
        result = self.offline_transfer.protocol.genesis_parameters
        if isinstance(result, GenesisParameters):
            return result
        elif isinstance(result, dict):
            return GenesisParameters.from_json(result)
        else:
            return GenesisParameters(**result.__dict__)

    @property
    def genesis_param(self) -> PyCardanoGenesisParameters:
        if not self._genesis_param:
            self._genesis_param = self._fetch_genesis_param()
        return self._genesis_param.to_pycardano()

    @property
    def protocol_param(self) -> PyCardanoProtocolParameters:
        """Get current protocol parameters"""
        if not self._protocol_param:
            self._protocol_param = self._fetch_protocol_param()
        return self._protocol_param.to_pycardano()

    @property
    def epoch(self) -> Union[int, None]:
        """Current epoch number"""
        if isinstance(self.genesis_param.system_start, datetime):
            start_time_sec = int(self.genesis_param.system_start.timestamp())
        elif isinstance(self.genesis_param.system_start, str):
            start_time_sec = int(
                datetime.strptime(
                    self.genesis_param.system_start, "%Y-%m-%dT%H:%M:%SZ"
                ).timestamp()
            )
        else:
            start_time_sec = self.genesis_param.system_start  # in seconds (UTC)

        current_time_sec = int(
            datetime.now(timezone.utc).timestamp()
        )  # in seconds (UTC)

        epoch_length = int(self.genesis_param.epoch_length)

        current_epoch = (
            current_time_sec - start_time_sec
        ) / epoch_length  # returns a integer number, we like that

        return int(current_epoch)

    @property
    def era(self) -> Optional[Era]:
        """Current Cardano era"""
        if self._offline_transfer.protocol:
            return self._offline_transfer.protocol.era
        return None

    @property
    def chain_tip(self) -> ChainTip:
        """The current tip of the chain, derived rather than observed.

        An offline context cannot see the live tip. ``slot`` and ``epoch`` are
        computed from the captured genesis parameters and the wall clock, which
        makes them exact rather than stale — both are pure functions of time
        once the genesis parameters are known. ``era`` comes from the capture,
        so it is only as fresh as the file and will be wrong across a hard fork.
        ``hash``, ``block`` and ``sync_progress`` describe a block this context
        has never seen and are always ``None``.

        Returns:
            ChainTip: The derived slot and epoch, plus the captured era.

        Raises:
            :class:`OfflineTransferFileError`: If the file carries no genesis
                parameters, so neither slot nor epoch can be computed.
        """
        return ChainTip(slot=self.last_block_slot, epoch=self.epoch, era=self.era)

    @property
    @func.ttl_cache(ttl=1)
    def last_block_slot(self) -> int:
        if not self._genesis_param:
            self._genesis_param = self._fetch_genesis_param()

        shelley_genesis = self._genesis_param.shelley_genesis
        byron_genesis = self._genesis_param.byron_genesis

        if not shelley_genesis:
            raise OfflineTransferFileError(
                "Shelley Genesis not found in the offline transfer file."
            )

        if not byron_genesis:
            raise OfflineTransferFileError(
                "Byron Genesis not found in the offline transfer file."
            )

        if (
            not self._offline_transfer.protocol
            or not self._offline_transfer.protocol.network
        ):
            raise OfflineTransferFileError(
                "Network not found in the offline transfer file protocol parameters."
            )

        byron_to_shelley_epochs = byron_to_shelley_epoch_transition(
            self._offline_transfer.protocol.network
        )

        byron_slot_length = int(byron_genesis["blockVersionData"]["slotDuration"])
        byron_k = int(byron_genesis["protocolConsts"]["k"])
        byron_start_time_sec = int(byron_genesis["startTime"])
        byron_epoch_length = 10 * byron_k
        byron_end_time_sec = byron_start_time_sec + (
            (byron_to_shelley_epochs * byron_epoch_length * byron_slot_length) / 1000
        )

        current_time_sec = int(time.time())

        if current_time_sec < byron_end_time_sec:
            current_tip = (
                (current_time_sec - byron_start_time_sec) * 1000
            ) / byron_slot_length
        else:
            byron_slots = byron_to_shelley_epochs * byron_epoch_length
            slot_length = int(shelley_genesis["slotLength"])

            shelley_slots = (current_time_sec - byron_end_time_sec) / slot_length
            current_tip = byron_slots + shelley_slots

        return int(current_tip)

    @property
    def network(self) -> Optional[PyCardanoNetwork]:
        """Current Cardano network"""
        if self._offline_transfer.protocol and (
            self._offline_transfer.protocol.network
            and self._offline_transfer.protocol.network.value == "mainnet"
        ):
            return PyCardanoNetwork.MAINNET
        return PyCardanoNetwork.TESTNET

    def _utxos(self, address: str) -> Optional[List[UTxO]]:
        """
        Get all UTxOs associated with an address.

        Args:
            address (str): An address encoded with bech32.

        Returns:
            List[UTxO]: A list of UTxOs or an empty list if the address is not found.
        """

        return next(
            (
                offline_address.utxos
                for offline_address in self._offline_transfer.addresses
                if address == str(offline_address.address)
            ),
            [],
        )

    def submit_tx_cbor(self, cbor: Union[bytes, str]):
        """Save the transaction to the offline transfer file.

        Args:
            cbor (Union[bytes, str]): The serialized transaction to be submitted.

        Raises:
            :class:`InvalidArgumentException`: When the transaction is invalid.
            :class:`TransactionFailedException`: When fails to submit the transaction to blockchain.
        """
        if isinstance(cbor, bytes):
            cbor = cbor.hex()

        # self.era is an Era enum; interpolating it directly yields
        # "Witnessed Tx Era.CONWAYEra" rather than "Witnessed Tx ConwayEra".
        era_name = self.era.value.capitalize() if self.era else ""
        tx_json = TransactionJSON(
            f"Witnessed Tx {era_name}Era",
            "Generated by PyCardano",
            cbor,
        )

        tx = Transaction.from_cbor(cbor)
        offline_transaction = OfflineTransferTransaction(
            type=TransactionType.TRANSACTION,
            tx_json=tx_json,
        )

        action = HistoryType.SAVE_TRANSACTION.value(tx.id)

        self._offline_transfer.transactions.append(offline_transaction)
        self._offline_transfer.history.append(OfflineTransferHistory(action=action))

        dump_file(
            self._offline_transfer_file,
            self._offline_transfer.to_json(),
        )

    def stake_address_info(self, stake_address: str) -> List[StakeAddressInfo]:
        """Get the stake address information.

        Args:
            stake_address (str): The stake address.

        Returns:
            List[StakeAddressInfo]: The stake address information.
        """

        # select stake_address_info from the addresses in the offline transfer file that match the stake_address
        return next(
            (
                offline_address.stake_address_info or []
                for offline_address in self._offline_transfer.addresses
                if offline_address.stake_address_info
                and any(
                    stake_address == stake_info.address
                    for stake_info in offline_address.stake_address_info
                )
            ),
            [],
        )

    # -- Reading the captured sections -------------------------------------

    def _section(self, name: str) -> Any:
        """Return a captured section, or explain that the file has none.

        A section is ``None`` when the capture never wrote it — which includes
        every file written before the section existed. That is a different fact
        from a section that was captured and found empty, and the two must not
        be conflated: "no committee section" is a gap in the file, "no members"
        is a statement about the chain. Only the first is an error.

        Args:
            name (str): The :class:`~pccontext.models.OfflineTransfer` field.

        Returns:
            Any: The section's value.

        Raises:
            :class:`OfflineTransferFileError`: If the section is absent.
        """
        section = getattr(self._offline_transfer, name)
        if section is None:
            raise OfflineTransferFileError(
                f"The offline transfer file has no '{name}' section. Capture it "
                f"on an online machine before transferring the file."
            )
        return section

    def utxo(self, tx_input: TransactionInput) -> Optional[Tuple[UTxO, bool]]:
        """Resolve a single UTxO by the transaction input that identifies it.

        The captured addresses hold the UTxOs that were unspent when the file
        was written. This context cannot watch the chain, so it never reports a
        UTxO as spent — a UTxO spent since the capture is still returned here,
        and the transaction built from it will be rejected on submission.

        Args:
            tx_input (TransactionInput): The transaction hash and output index.

        Returns:
            Optional[Tuple[UTxO, bool]]: The UTxO and ``False`` for its spent
            flag, or ``None`` if no captured address holds it.
        """
        for offline_address in self._offline_transfer.addresses:
            for utxo in offline_address.utxos or []:
                if utxo.input == tx_input:
                    return utxo, False
        return None

    # -- Stake pools -------------------------------------------------------

    def stake_pools(self) -> List[PoolOperator]:
        """Get every stake pool captured in the transfer file.

        Returns:
            List[PoolOperator]: The captured pools, which is the chain's pool
            register as of the capture, not as of now.

        Raises:
            :class:`OfflineTransferFileError`: If the file has no
                ``stake_pools`` section.
        """
        return list(self._section("stake_pools"))

    def stake_pool_info(self, pool_id: str, strict: bool = False) -> StakePoolInfo:
        """Get a stake pool's registered parameters and stake figures.

        Args:
            pool_id (str): The pool's ID, bech32 encoded.
            strict (bool): Ignored. Verifying a pool's metadata means fetching
                it over the network, which this context cannot do; the captured
                parameters are returned either way.

        Returns:
            StakePoolInfo: The pool's captured information. Stake figures are
            those of the capture's epoch.

        Raises:
            :class:`OfflineTransferFileError`: If the file has no
                ``stake_pool_infos`` section, or none of its entries is the
                requested pool.
        """
        for info in self._section("stake_pool_infos"):
            if info.pool_params is None:
                continue
            operator = PoolOperator(info.pool_params.operator)
            with contextlib.suppress(Exception):
                if operator.encode() == pool_id:
                    return info

        raise OfflineTransferFileError(
            f"Pool info for '{pool_id}' was not captured in the offline "
            f"transfer file."
        )

    def kes_period_info(
        self,
        pool: Optional[PoolOperator] = None,
        op_cert: Optional[Union[bytes, str]] = None,
    ) -> KESPeriodInfo:
        """Get the KES period information captured for an operational certificate.

        Note:
            The captured entries carry no pool identity, so neither ``pool`` nor
            ``op_cert`` can select among them and the first is returned. Capture
            one entry per transfer file if you operate more than one pool.

        Args:
            pool (Optional[PoolOperator]): Unused by this context.
            op_cert (Optional[Union[bytes, str]]): Unused by this context.

        Returns:
            KESPeriodInfo: The first captured entry. Its counters are those of
            the capture, so a rotation made since will not be reflected.

        Raises:
            :class:`OfflineTransferFileError`: If the file has no
                ``kes_period_infos`` section, or that section is empty.
        """
        infos = self._section("kes_period_infos")
        if not infos:
            raise OfflineTransferFileError(
                "The offline transfer file captured no KES period information."
            )
        return infos[0]

    # -- Treasury ----------------------------------------------------------

    def treasury(self) -> int:
        """Get the treasury balance, in lovelace, as of the capture.

        Returns:
            int: The captured balance. The treasury moves every epoch, so this
            is only current if the file was captured this epoch.

        Raises:
            :class:`OfflineTransferFileError`: If the file has no ``treasury``
                section.
        """
        return int(self._section("treasury"))

    # -- Governance --------------------------------------------------------

    def drep_info(self, drep: DRep) -> DRepInfo:
        """Get a delegate representative's registration and voting power.

        Args:
            drep (DRep): The DRep to look up.

        Returns:
            DRepInfo: The DRep's captured information. Unlike an online backend,
            a DRep that is simply missing from the capture is reported as an
            error rather than as ``NOT_REGISTERED`` — the file cannot tell the
            two apart.

        Raises:
            :class:`OfflineTransferFileError`: If the file has no ``drep_infos``
                section, or none of its entries is the requested DRep.
        """
        for info in self._section("drep_infos"):
            if info.drep == drep:
                return info

        raise OfflineTransferFileError(
            "DRep info was not captured in the offline transfer file."
        )

    def gov_action_info(self, gov_action_id: GovActionId) -> GovActionInfo:
        """Get the lifecycle information for a governance action.

        Both the ``gov_action_infos`` section and the actions carried by
        ``gov_action_votes`` are searched, so a capture that stored only the
        votes still answers this.

        Args:
            gov_action_id (GovActionId): The action's identifier.

        Returns:
            GovActionInfo: The action's captured lifecycle information.

        Raises:
            :class:`OfflineTransferFileError`: If neither section was captured,
                or neither holds the requested action.
        """
        infos = self._offline_transfer.gov_action_infos
        votes = self._offline_transfer.gov_action_votes
        if infos is None and votes is None:
            raise OfflineTransferFileError(
                "The offline transfer file has no 'gov_action_infos' section. "
                "Capture it on an online machine before transferring the file."
            )

        for info in infos or []:
            if info.gov_action_id == gov_action_id:
                return info

        for recorded in votes or []:
            if recorded.gov_action_id == gov_action_id:
                return recorded.as_gov_action_info()

        raise OfflineTransferFileError(
            f"Governance action '{gov_action_id.encode()}' was not captured in "
            f"the offline transfer file."
        )

    def gov_action_votes(self, gov_action_id: GovActionId) -> GovActionVotes:
        """Get the votes recorded against a governance action, by voter class.

        Args:
            gov_action_id (GovActionId): The action's identifier.

        Returns:
            GovActionVotes: The captured proposal and its committee, DRep and
            stake pool votes. Votes cast since the capture are not in it.

        Raises:
            :class:`OfflineTransferFileError`: If the file has no
                ``gov_action_votes`` section, or none of its entries is the
                requested action.
        """
        for recorded in self._section("gov_action_votes"):
            if recorded.gov_action_id == gov_action_id:
                return recorded

        raise OfflineTransferFileError(
            f"Votes for governance action '{gov_action_id.encode()}' were not "
            f"captured in the offline transfer file."
        )

    def gov_actions_all(self) -> List[GovActionVotes]:
        """Get every governance proposal captured with its votes.

        Returns:
            List[GovActionVotes]: One entry per captured proposal. An empty list
            means the capture found no proposals, not that none were captured.

        Raises:
            :class:`OfflineTransferFileError`: If the file has no
                ``gov_action_votes`` section.
        """
        return list(self._section("gov_action_votes"))

    def _aged_status(self, member: CommitteeMemberInfo) -> CommitteeMemberInfo:
        """Expire a captured member whose term has ended since the capture.

        A term runs to the *end* of its expiration epoch, so a member is expired
        only once the chain is past that epoch. The expiration epoch is fixed
        on-chain and the current epoch is computed from genesis, so this ages a
        stale ``ACTIVE`` forward without inventing anything. It never does the
        reverse: a member captured as expired or unrecognized is left alone.

        Args:
            member (CommitteeMemberInfo): The captured member.

        Returns:
            CommitteeMemberInfo: The member, with ``status`` set to ``EXPIRED``
            if its term has run out. Returned unchanged when the current epoch
            cannot be computed.
        """
        if member.expiration is None or member.status == CommitteeMemberStatus.EXPIRED:
            return member

        epoch = None
        with contextlib.suppress(Exception):
            epoch = self.epoch
        if epoch is None or member.expiration >= epoch:
            return member

        return CommitteeMemberInfo(
            cold_credential=member.cold_credential,
            hot_credential=member.hot_credential,
            expiration=member.expiration,
            status=CommitteeMemberStatus.EXPIRED,
        )

    def committee_member_info(
        self,
        cold: Optional[CommitteeColdCredential] = None,
        hot: Optional[CommitteeHotCredential] = None,
    ) -> CommitteeMemberInfo:
        """Get a constitutional committee member's authorization and term.

        The per-member ``committee_member_infos`` section is searched first, then
        the members of the ``committee_state`` snapshot, so a capture that stored
        either one answers this.

        Args:
            cold (Optional[CommitteeColdCredential]): The member's cold
                credential. Optional if ``hot`` is given.
            hot (Optional[CommitteeHotCredential]): A hot credential the member
                has authorized. Optional if ``cold`` is given.

        Returns:
            CommitteeMemberInfo: The matching member, with an expired term
            reflected in ``status`` even if the capture predates the expiry.

        Raises:
            ValueError: If neither credential is given.
            :class:`OfflineTransferFileError`: If neither section was captured,
                or no captured member matches the credential.
        """
        if cold is None and hot is None:
            raise ValueError("A cold or hot committee credential must be provided.")

        members = self._offline_transfer.committee_member_infos
        state = self._offline_transfer.committee_state
        if members is None and state is None:
            raise OfflineTransferFileError(
                "The offline transfer file has no 'committee_member_infos' "
                "section. Capture it on an online machine before transferring "
                "the file."
            )

        candidates = list(members or []) + list(state.members if state else [])
        for member in candidates:
            if cold is not None and member.cold_credential == cold:
                return self._aged_status(member)
            if hot is not None and member.hot_credential == hot:
                return self._aged_status(member)

        raise OfflineTransferFileError(
            "No captured committee member matched the given credential."
        )

    def committee_state(self) -> CommitteeStateInfo:
        """Get the full constitutional committee state.

        Returns:
            CommitteeStateInfo: The captured committee, with each member's term
            aged against the current epoch. A committee with no members is
            reported as such; a file that captured no committee is an error.

        Raises:
            :class:`OfflineTransferFileError`: If the file has no
                ``committee_state`` section.
        """
        state: CommitteeStateInfo = self._section("committee_state")
        return CommitteeStateInfo(
            members=[self._aged_status(member) for member in state.members],
            threshold=state.threshold,
        )

    # -- Stake distributions -----------------------------------------------

    def drep_stake_distribution(self) -> List[DRepStakeEntry]:
        """Get the stake delegated to each DRep, as of the capture's epoch.

        Returns:
            List[DRepStakeEntry]: One entry per captured DRep. Voting power is
            recomputed every epoch, so this is stale as soon as the epoch turns.

        Raises:
            :class:`OfflineTransferFileError`: If the file has no
                ``drep_stake_entries`` section.
        """
        return list(self._section("drep_stake_entries"))

    def spo_stake_distribution(self) -> List[SPOStakeEntry]:
        """Get the stake delegated to each stake pool, as of the capture's epoch.

        Returns:
            List[SPOStakeEntry]: One entry per captured pool. Voting power is
            recomputed every epoch, so this is stale as soon as the epoch turns.

        Raises:
            :class:`OfflineTransferFileError`: If the file has no
                ``spo_stake_entries`` section.
        """
        return list(self._section("spo_stake_entries"))
