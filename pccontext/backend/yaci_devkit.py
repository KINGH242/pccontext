from typing import Any, Dict, List, Optional, Union, cast

import cbor2
from pycardano import TransactionFailedException
from pycardano.address import Address
from pycardano.backend.base import ProtocolParameters as PyCardanoProtocolParameters
from pycardano.hash import SCRIPT_HASH_SIZE, DatumHash, ScriptHash
from pycardano.nativescript import NativeScript
from pycardano.network import Network
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
from yaci_client import Client
from yaci_client.api.account_api import get_stake_account_details
from yaci_client.api.address_service import get_utxos_1
from yaci_client.api.local_epoch_service import (
    get_latest_epoch,
    get_latest_protocol_params,
)
from yaci_client.api.script_service import (
    get_script_by_hash,
    get_script_cbor_by_hash,
    get_script_json_by_hash,
)
from yaci_client.api.tx_submission_service import submit_tx_1
from yaci_client.api.utilities import evaluate_tx
from yaci_client.errors import UnexpectedStatus
from yaci_client.models import (
    EpochNo,
    ProtocolParamsDto,
    ScriptCborDto,
    ScriptDto,
    ScriptJsonDto,
    StakeAccountInfo,
)

from pccontext.backend import ChainContext
from pccontext.logging import logger
from pccontext.models import GenesisParameters, ProtocolParameters, StakeAddressInfo

__all__ = ["YaciDevkitChainContext"]


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


class YaciDevkitChainContext(ChainContext):
    _api_url: Optional[str]
    """Yaci Store API endpoint"""

    api: Client
    """Koios API client"""

    _epoch: Optional[int] = None
    _genesis_param: Optional[GenesisParameters] = None
    _protocol_param: Optional[ProtocolParameters] = None

    def __init__(self, api_url: str):
        self._api_url = api_url
        self.api = Client(base_url=api_url, raise_on_unexpected_status=True)
        self._epoch = None
        self._genesis_param = None
        self._protocol_param = None

    @property
    def name(self) -> str:
        return "YaciDevkit"

    @property
    def network(self) -> Network:
        return Network.TESTNET

    @property
    def epoch(self) -> int:
        if not self._epoch:
            with self.api as client:
                response: Optional[EpochNo] = get_latest_epoch.sync(client=client)
                self._epoch = response.epoch or 0 if response else 0
        return self._epoch

    @property
    def protocol_param(self) -> PyCardanoProtocolParameters:
        if not self._protocol_param:
            with self.api as client:
                params: Optional[ProtocolParamsDto] = get_latest_protocol_params.sync(
                    client=client
                )
            if not params:
                raise ValueError("Failed to get protocol parameters.")
            self._protocol_param = ProtocolParameters.from_json(params.to_dict())
        return self._protocol_param.to_pycardano()

    def _get_script(
        self, script_hash: str
    ) -> Union[PlutusV1Script, PlutusV2Script, PlutusV3Script, NativeScript]:
        with self.api as client:
            script: Optional[ScriptDto] = get_script_by_hash.sync(
                script_hash=script_hash, client=client
            )

        script_type = script.type if script else None

        def get_plutus_cbor(script_hash: str) -> str:
            with self.api as client:
                script_cbor: Optional[ScriptCborDto] = get_script_cbor_by_hash.sync(
                    script_hash=script_hash, client=client
                )
            return str(script_cbor.cbor) if script_cbor else ""

        if script_type == "plutusV1":
            v1script = PlutusV1Script(bytes.fromhex(get_plutus_cbor(script_hash)))
            return _try_fix_script(script_hash, v1script)
        elif script_type == "plutusV2":
            v2script = PlutusV2Script(bytes.fromhex(get_plutus_cbor(script_hash)))
            return _try_fix_script(script_hash, v2script)
        elif script_type == "plutusV3":
            v3script = PlutusV3Script(bytes.fromhex(get_plutus_cbor(script_hash)))
            return _try_fix_script(script_hash, v3script)
        else:
            with self.api as client:
                script_json: Optional[ScriptJsonDto] = get_script_json_by_hash.sync(
                    script_hash=script_hash, client=client
                )
            return NativeScript.from_dict(script_json.json if script_json else {})

    def _utxos(self, address: str) -> List[UTxO]:
        """Get all UTxOs associated with an address with Kupo.
        Since UTxO querying will be deprecated from Ogmios in next
        major release: https://ogmios.dev/mini-protocols/local-state-query/.

        Args:
            address (str): An address encoded with bech32.

        Returns:
            List[UTxO]: A list of UTxOs.
        """
        utxos: List[UTxO] = []

        try:
            with self.api as client:
                results = get_utxos_1.sync(address=address, client=client)
        except UnexpectedStatus as e:
            logger.error(f"Failed to get UTxOs for address {address}. Error: {e}")
            return utxos

        for result in results or []:
            tx_in = TransactionInput.from_primitive(
                [result.tx_hash, result.output_index]
            )
            amount = result.amount
            lovelace_amount = 0
            multi_assets = MultiAsset()
            for item in amount or []:
                if item["unit"] == "lovelace":
                    lovelace_amount = int(item["quantity"])
                else:
                    # The utxo contains Multi-asset
                    data = bytes.fromhex(item["unit"])
                    policy_id = ScriptHash(data[:SCRIPT_HASH_SIZE])
                    asset_name = AssetName(data[SCRIPT_HASH_SIZE:])

                    if policy_id not in multi_assets:
                        multi_assets[policy_id] = Asset()
                    multi_assets[policy_id][asset_name] = int(item["quantity"])

            amount = Value(lovelace_amount, multi_assets)

            datum_hash = (
                DatumHash.from_primitive(result.data_hash)
                if result.data_hash and result.inline_datum is None
                else None
            )

            datum = None

            if hasattr(result, "inline_datum") and result.inline_datum is not None:
                datum = RawCBOR(bytes.fromhex(str(result.inline_datum)))

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

        if isinstance(cbor, bytes):
            cbor = cbor.decode("utf-8")

        try:
            with self.api as client:
                response: Optional[str] = submit_tx_1.sync(body=cbor, client=client)
            return response or ""
        except UnexpectedStatus as e:
            raise TransactionFailedException(
                f"Failed to submit transaction. Error code: {e.status_code}. Error message: {e.content}"
            ) from e

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
            cbor = cbor.decode("utf-8")

        try:
            with self.api as client:
                response: Optional[dict] = evaluate_tx.sync(body=cbor, client=client)
        except UnexpectedStatus as e:
            raise TransactionFailedException(
                f"Failed to evaluate transaction. Error code: {e.status_code}. Error message: {e.content}"
            ) from e

        result: Optional[Dict[str, Any]] = (
            cast(Dict[str, Any], response["result"]) if response else None
        )

        if not result or not result.get("EvaluationResult"):
            raise TransactionFailedException(result)
        else:
            return {
                k: ExecutionUnits(
                    k["memory"],
                    k["steps"],
                )
                for k in result["EvaluationResult"]
            }

    def stake_address_info(self, stake_address: str) -> List[StakeAddressInfo]:
        """Get the stake address information.

        Args:
            stake_address (str): The stake address.

        Returns:
            List[StakeAddressInfo]: The stake address information.
        """
        try:
            with self.api as client:
                response: Optional[StakeAccountInfo] = get_stake_account_details.sync(
                    stake_address=stake_address, client=client
                )
        except UnexpectedStatus as e:
            print(e)

        return [
            (
                StakeAddressInfo(
                    address=response.stake_address or "",
                    stake_delegation=response.pool_id or "",
                    reward_account_balance=response.withdrawable_amount or 0,
                )
                if response
                else StakeAddressInfo()
            )
        ]
