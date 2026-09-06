import os
import tempfile
import time
from typing import Any, Dict, List, Optional, Union

import cbor2
import koios_python
from pycardano import (
    Address,
    Asset,
    AssetName,
    DatumHash,
    ExecutionUnits,
    MultiAsset,
    NativeScript,
    Network,
    PlutusV1Script,
    PlutusV2Script,
    PlutusV3Script,
)
from pycardano import ProtocolParameters as PyCardanoProtocolParameters
from pycardano import (
    RawCBOR,
    ScriptHash,
    TransactionFailedException,
    TransactionInput,
    TransactionOutput,
    UTxO,
    Value,
)

__all__ = ["KoiosChainContext"]

from pycardano.types import JsonDict
from requests import RequestException

from pccontext.backend import ChainContext
from pccontext.logging import logger
from pccontext.models import GenesisParameters, ProtocolParameters, StakeAddressInfo


class KoiosChainContext(ChainContext):
    """A `Koios <https://api.koios.rest/>`_ API wrapper for the client code to interact with.

    Args:
        api_key (str): Koios API key
        network (str): Koios network
        server (str): Koios server
        endpoint (str): Koios API endpoint
    """

    _endpoint: Optional[str] = None
    """Koios API endpoint"""

    _network: Optional[str] = None
    """Koios Network"""

    _server: Optional[str] = None
    """Koios Server"""

    _api_key: Optional[str] = None
    """Koios API key"""

    api: koios_python.URLs
    """Koios API client"""

    _epoch_info: Dict[str, Any]
    _epoch: Optional[int] = None
    _genesis_param: Optional[GenesisParameters] = None
    _protocol_param: Optional[ProtocolParameters] = None

    def __init__(
        self,
        api_key: Optional[str] = None,
        network: Optional[str] = "mainnet",
        server: Optional[str] = "koios",
        endpoint: Optional[str] = "https://api.koios.rest/api/v1/",
    ):
        self._api_key = api_key
        self._endpoint = endpoint
        self._server = server
        self._network = network

        self.api = koios_python.URLs(
            url=self._endpoint,
            network=self._network,
            server=self._server,
            bearer=self._api_key,
        )

        self._epoch = self.api.get_tip()[0]["epoch_no"]
        self._epoch_info = self.api.get_epoch_info(epoch_no=self._epoch)[0]
        self._genesis_param = None
        self._protocol_param = None

    @property
    def name(self) -> str:
        return "Koios"

    def _query_chain_tip(self) -> JsonDict:
        return self.api.get_tip()[0]

    def _check_epoch_and_update(self):
        if int(time.time()) < self._epoch_info["end_time"]:
            return False
        self._epoch_info = self.api.get_tip()[0]["epoch_no"]
        return True

    @property
    def network(self) -> Network:
        return Network.MAINNET if self._network == "mainnet" else Network.TESTNET

    @property
    def epoch(self) -> int:
        if not self._epoch or self._check_epoch_and_update():
            new_epoch: int = self.api.get_tip()[0]["epoch_no"]
            self._epoch = new_epoch
        return self._epoch

    @property
    def last_block_slot(self) -> int:
        tip = self._query_chain_tip()
        return tip["abs_slot"]

    @property
    def genesis_param(self) -> GenesisParameters:
        if not self._genesis_param or self._check_epoch_and_update():
            params = self.api.get_genesis()[0]
            self._genesis_param = GenesisParameters.from_json(params)
        return self._genesis_param

    @property
    def protocol_param(self) -> PyCardanoProtocolParameters:
        if not self._protocol_param or self._check_epoch_and_update():
            params = self.api.get_epoch_params(epoch_no=self.epoch)[0]
            self._protocol_param = ProtocolParameters.from_json(params)
        return self._protocol_param.to_pycardano()

    @staticmethod
    def _get_script(
        reference_script: dict,
    ) -> Union[PlutusV1Script, PlutusV2Script, PlutusV3Script, NativeScript]:
        """
        Get a script object from a reference script dictionary.
        Args:
            reference_script:

        Returns:
            Union[PlutusV1Script, PlutusV2Script, PlutusV3Script, NativeScript]
        """
        script_type = reference_script["type"]
        if script_type == "plutusV1":
            return PlutusV1Script(cbor2.loads(bytes.fromhex(reference_script["bytes"])))
        elif script_type == "plutusV2":
            return PlutusV2Script(cbor2.loads(bytes.fromhex(reference_script["bytes"])))
        elif script_type == "plutusV3":
            return PlutusV3Script(cbor2.loads(bytes.fromhex(reference_script["bytes"])))
        else:
            return NativeScript.from_dict(reference_script["value"])

    def _utxos(self, address: str) -> List[Union[UTxO, None]]:
        utxos: List[UTxO] = []

        try:
            results = self.api.get_address_utxos([address], extended=True)
        except RequestException as e:
            logger.error(f"Failed to get UTxOs for address {address}. Error: {e}")
            return utxos

        for result in results:
            tx_in = TransactionInput.from_primitive(
                [result["tx_hash"], result["tx_index"]]
            )

            lovelace_amount = result["value"]
            multi_assets = MultiAsset()
            for item in result["asset_list"]:
                # The utxo contains Multi-asset
                policy_id = ScriptHash(item["policy_id"])
                asset_name = AssetName(item["asset_name"])

                if policy_id not in multi_assets:
                    multi_assets[policy_id] = Asset()
                multi_assets[policy_id][asset_name] = int(item["quantity"])

            amount = Value(lovelace_amount, multi_assets)

            datum_hash = (
                DatumHash.from_primitive(result["data_hash"])
                if result.get("data_hash") and result.get("inline_datum") is None
                else None
            )

            datum = None

            if result.get("inline_datum") is not None:
                datum = RawCBOR(bytes.fromhex(result["inline_datum"]))

            script = None

            if result.get("reference_script"):
                script = self._get_script(result["reference_script"])

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
            response = self.api.submit_tx(f.name)
        except RequestException as e:
            raise TransactionFailedException(
                f"Failed to submit transaction. Error: {e}"
            ) from e
        finally:
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

        params = {"transaction": {"cbor": cbor}}
        result = self.api.query(
            "evaluateTransaction",
            params,
        )

        result_dict = {}

        for res in result:
            purpose = res["validator"]["purpose"]
            # Hotfix: this purpose has been renamed in the latest version of Ogmios
            if purpose == "withdraw":
                purpose = "withdrawal"
            result_dict[f"{purpose}:{res['validator']['index']}"] = ExecutionUnits(
                mem=res["budget"]["memory"],
                steps=res["budget"]["cpu"],
            )
        return result_dict

    def stake_address_info(self, stake_address: str) -> List[StakeAddressInfo]:
        """Get the stake address information.

        Args:
            stake_address (str): The stake address.

        Returns:
            List[StakeAddressInfo]: The stake address information.
        """
        info: List[StakeAddressInfo] = []
        try:
            results = self.api.get_account_info([stake_address])
            info = [
                StakeAddressInfo(
                    address=result.get("stake_address", None),
                    delegation_deposit=result.get("deposit", None),
                    stake_delegation=result.get("delegated_pool", None),
                    reward_account_balance=result.get("rewards_available", None),
                    delegate_representative=result.get("delegated_drep", None),
                )
                for result in results
            ]
        except RequestException as e:
            logger.error(
                f"Failed to get Stake Address info for address {stake_address}. Error: {e}"
            )
        return info
