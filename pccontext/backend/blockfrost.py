import os
import tempfile
import time
from typing import Dict, List, Optional, Union

import cbor2
from blockfrost import ApiError, ApiUrls, BlockFrostApi
from blockfrost.utils import Namespace
from pycardano.address import Address
from pycardano.backend.base import ProtocolParameters as PyCardanoProtocolParameters
from pycardano.exception import TransactionFailedException
from pycardano.hash import SCRIPT_HASH_SIZE, DatumHash, ScriptHash
from pycardano.nativescript import NativeScript
from pycardano.network import Network as PyCardanoNetwork
from pycardano.plutus import (
    ExecutionUnits,
    PlutusV1Script,
    PlutusV2Script,
    PlutusV3Script,
    script_hash,
)
from pycardano.serialization import RawCBOR
from pycardano.transaction import (
    Asset,
    AssetName,
    MultiAsset,
    TransactionInput,
    TransactionOutput,
    UTxO,
    Value,
)
from pycardano.types import JsonDict

from pccontext.backend import ChainContext
from pccontext.enums import Network
from pccontext.exceptions import BlockfrostError
from pccontext.models import GenesisParameters, ProtocolParameters, StakeAddressInfo

__all__ = ["BlockFrostChainContext"]


def _try_fix_script(
    scripth: str, script: Union[PlutusV1Script, PlutusV2Script, PlutusV3Script]
) -> Union[PlutusV1Script, PlutusV2Script, PlutusV3Script]:
    if str(script_hash(script)) == scripth:
        return script
    new_script = script.__class__(cbor2.loads(script))
    if str(script_hash(new_script)) == scripth:
        return new_script
    else:
        raise ValueError("Cannot recover script from hash.")


class BlockFrostChainContext(ChainContext):
    """A `BlockFrost <https://blockfrost.io/>`_ API wrapper for the client code to interact with.

    Args:
        project_id (str): A BlockFrost project ID obtained from https://blockfrost.io.
        network (Network): Network to use.
        base_url (str): Base URL for the BlockFrost API. Defaults to the preprod url.
    """

    api: BlockFrostApi
    _network: Network
    _epoch_info: Namespace
    _epoch: Optional[int] = None
    _genesis_param: Optional[GenesisParameters] = None
    _protocol_param: Optional[ProtocolParameters] = None

    def __init__(
        self,
        project_id: str,
        network: Optional[Network] = None,
        base_url: Optional[str] = None,
    ):
        if not project_id:
            raise ValueError("Project ID must be provided.")

        if network is not None:
            self._network = network
        elif project_id.startswith("mainnet"):
            self._network = Network.MAINNET
        elif project_id.startswith("preprod"):
            self._network = Network.PREPROD
        elif project_id.startswith("preview"):
            self._network = Network.PREVIEW
        else:
            raise ValueError(
                "Project ID might not be valid. Or try specifying the network explicitly."
            )

        if base_url is not None:
            self._base_url = base_url
        elif self._network == Network.MAINNET:
            self._base_url = ApiUrls.mainnet.value
        elif self._network == Network.PREPROD:
            self._base_url = ApiUrls.preprod.value
        elif self._network == Network.PREVIEW:
            self._base_url = ApiUrls.preview.value
        else:
            raise ValueError(
                "Project ID might not be valid. Or try specifying the network explicitly."
            )

        self._project_id = project_id

        self.api = BlockFrostApi(project_id=self._project_id, base_url=self._base_url)

        try:
            self._epoch_info = self.api.epoch_latest()
            self._epoch = self._epoch_info.epoch
        except ApiError as e:
            if e.status_code == 404:
                raise BlockfrostError(
                    f"Failed to fetch epoch information. Please check your project ID and network: {e.message}"
                ) from e
            else:
                raise BlockfrostError(
                    f"An error occurred while fetching epoch information: {e.message}"
                ) from e

        self._genesis_param = None
        self._protocol_param = None

    @property
    def name(self) -> str:
        return "Blockfrost"

    def _check_epoch_and_update(self):
        if int(time.time()) < self._epoch_info.end_time:
            return False
        self._epoch_info = self.api.epoch_latest()
        return True

    @property
    def network(self) -> PyCardanoNetwork:
        return self._network.get_network()

    @property
    def epoch(self) -> int:
        if not self._epoch or self._check_epoch_and_update():
            new_epoch: int = self.api.epoch_latest().epoch
            self._epoch = new_epoch
        return self._epoch

    @property
    def last_block_slot(self) -> int:
        block = self.api.block_latest()
        return block.slot

    @property
    def genesis_param(self) -> GenesisParameters:
        if not self._genesis_param or self._check_epoch_and_update():
            params = self.api.genesis(return_type="json")
            self._genesis_param = GenesisParameters.from_json(params)
        return self._genesis_param

    @property
    def protocol_param(self) -> PyCardanoProtocolParameters:
        if not self._protocol_param or self._check_epoch_and_update():
            params = self.api.epoch_latest_parameters(return_type="json")
            self._protocol_param = ProtocolParameters.from_json(params)
        return self._protocol_param.to_pycardano()

    def _get_script(
        self, script_hash: str
    ) -> Union[PlutusV1Script, PlutusV2Script, PlutusV3Script, NativeScript]:
        script_type = self.api.script(script_hash).type
        if script_type == "plutusV1":
            v1script = PlutusV1Script(
                bytes.fromhex(self.api.script_cbor(script_hash).cbor)
            )
            return _try_fix_script(script_hash, v1script)
        elif script_type == "plutusV2":
            v2script = PlutusV2Script(
                bytes.fromhex(self.api.script_cbor(script_hash).cbor)
            )
            return _try_fix_script(script_hash, v2script)
        elif script_type == "plutusV3":
            v3script = PlutusV3Script(
                bytes.fromhex(self.api.script_cbor(script_hash).cbor)
            )
            return _try_fix_script(script_hash, v3script)
        else:
            script_json: JsonDict = self.api.script_json(
                script_hash, return_type="json"
            )["json"]
            return NativeScript.from_dict(script_json)

    def _utxos(self, address: str) -> List[UTxO]:
        try:
            results = self.api.address_utxos(address, gather_pages=True)
        except ApiError as e:
            if e.status_code == 404:
                return []
            else:
                raise e

        utxos = []

        for result in results:
            tx_in = TransactionInput.from_primitive(
                [result.tx_hash, result.output_index]
            )
            amount = result.amount
            lovelace_amount = 0
            multi_assets = MultiAsset()
            for item in amount:
                if item.unit == "lovelace":
                    lovelace_amount = int(item.quantity)
                else:
                    # The utxo contains Multi-asset
                    data = bytes.fromhex(item.unit)
                    policy_id = ScriptHash(data[:SCRIPT_HASH_SIZE])
                    asset_name = AssetName(data[SCRIPT_HASH_SIZE:])

                    if policy_id not in multi_assets:
                        multi_assets[policy_id] = Asset()
                    multi_assets[policy_id][asset_name] = int(item.quantity)

            amount = Value(lovelace_amount, multi_assets)

            datum_hash = (
                DatumHash.from_primitive(result.data_hash)
                if result.data_hash and result.inline_datum is None
                else None
            )

            datum = None

            if hasattr(result, "inline_datum") and result.inline_datum is not None:
                datum = RawCBOR(bytes.fromhex(result.inline_datum))

            script = None

            if (
                hasattr(result, "reference_script_hash")
                and result.reference_script_hash
            ):
                script = self._get_script(result.reference_script_hash)

            tx_out = TransactionOutput(
                Address.from_primitive(address),
                amount=amount,
                datum_hash=datum_hash,
                datum=datum,
                script=script,
            )
            utxos.append(UTxO(tx_in, tx_out))

        return utxos

    def submit_tx_cbor(self, cbor: Union[bytes, str]) -> str:
        """Submit a transaction.

        Args:
            cbor (Union[bytes, str]): The serialized transaction to be submitted.

        Returns:
            str: The transaction hash.

        Raises:
            :class:`TransactionFailedException`: When fails to submit the transaction.
        """
        if isinstance(cbor, str):
            cbor = bytes.fromhex(cbor)
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(cbor)
        try:
            response = self.api.transaction_submit(f.name)
        except ApiError as e:
            os.remove(f.name)
            raise TransactionFailedException(
                f"Failed to submit transaction. Error code: {e.status_code}. Error message: {e.message}"
            ) from e
        os.remove(f.name)
        return response

    def evaluate_tx_cbor(self, cbor: Union[bytes, str]) -> Dict[str, ExecutionUnits]:
        """Evaluate execution units of a transaction.

        Args:
            cbor (Union[bytes, str]): The serialized transaction to be evaluated.

        Returns:
            Dict[str, ExecutionUnits]: A list of execution units calculated for each of the transaction's redeemers

        Raises:
            :class:`TransactionFailedException`: When fails to evaluate the transaction.
        """
        if isinstance(cbor, bytes):
            cbor = cbor.hex()
        with tempfile.NamedTemporaryFile(delete=False, mode="w") as f:
            f.write(cbor)
        result = self.api.transaction_evaluate(f.name).result
        os.remove(f.name)
        return_val = {}
        if not hasattr(result, "EvaluationResult"):
            raise TransactionFailedException(result)
        else:
            for k in vars(result.EvaluationResult):
                return_val[k] = ExecutionUnits(
                    getattr(result.EvaluationResult, k).memory,
                    getattr(result.EvaluationResult, k).steps,
                )
            return return_val

    def stake_address_info(self, stake_address: str) -> List[StakeAddressInfo]:
        """Get the stake address information.

        Args:
            stake_address (str): The stake address.

        Returns:
            List[StakeAddressInfo]: The stake address information.
        """
        try:
            rewards_state = self.api.accounts(stake_address)

            return [
                StakeAddressInfo(
                    active=rewards_state.active,
                    active_epoch=rewards_state.active_epoch,
                    address=rewards_state.stake_address,
                    stake_delegation=rewards_state.pool_id,
                    reward_account_balance=int(rewards_state.withdrawable_amount),
                    delegate_representative=rewards_state.drep_id,
                )
            ]
        except ApiError as e:
            raise BlockfrostError(
                f"Failed to fetch stake address info for {stake_address}. {e}"
            ) from e
