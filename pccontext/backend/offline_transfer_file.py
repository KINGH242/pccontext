from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Union

from cachetools import func
from pycardano import GenesisParameters as PyCardanoGenesisParameters
from pycardano import Network as PyCardanoNetwork
from pycardano import ProtocolParameters as PyCardanoProtocolParameters
from pycardano import Transaction, UTxO

from pccontext.backend import ChainContext
from pccontext.enums import ContextType, Era, HistoryType, Network, TransactionType
from pccontext.exceptions import OfflineTransferFileError
from pccontext.models import (
    GenesisParameters,
    OfflineTransfer,
    OfflineTransferHistory,
    OfflineTransferTransaction,
    ProtocolParameters,
    StakeAddressInfo,
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
