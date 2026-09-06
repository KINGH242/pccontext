import time
from fractions import Fraction
from typing import Dict, List, Optional, Union

from cachetools import Cache, LRUCache, TTLCache, func
from ogmios.client import Client as OgmiosClient
from ogmios.datatypes import Address as OgmiosAddress
from ogmios.datatypes import Era as OgmiosEra
from ogmios.datatypes import ProtocolParameters as OgmiosProtocolParameters
from ogmios.datatypes import Tip as OgmiosTip
from ogmios.datatypes import TxOutputReference as OgmiosTxOutputReference
from ogmios.datatypes import Utxo as OgmiosUtxo
from ogmios.utils import GenesisParameters as OgmiosGenesisParameters
from ogmios.utils import get_current_era
from pycardano.backend.base import ProtocolParameters as PyCardanoProtocolParameters
from pycardano.hash import DatumHash, ScriptHash
from pycardano.network import Network
from pycardano.plutus import (
    ExecutionUnits,
    PlutusV1Script,
    PlutusV2Script,
    PlutusV3Script,
)
from pycardano.serialization import RawCBOR
from pycardano.transaction import (
    Address,
    Asset,
    AssetName,
    MultiAsset,
    TransactionInput,
    TransactionOutput,
    UTxO,
    Value,
)

from pccontext.backend import ChainContext
from pccontext.backend.kupo import KupoChainContextExtension
from pccontext.models import GenesisParameters, ProtocolParameters, StakeAddressInfo

ALONZO_COINS_PER_UTXO_WORD = 34482
DEFAULT_REFETCH_INTERVAL = 1000

__all__ = ["OgmiosChainContext"]


class OgmiosChainContext(ChainContext):
    """Ogmios chain context for use with PyCardano"""

    _network: Network
    _client: OgmiosClient
    _service_name: str
    _last_known_block_slot: int
    _last_chain_tip_fetch: float
    _genesis_param: Optional[GenesisParameters]
    _protocol_param: Optional[OgmiosProtocolParameters]
    _utxo_cache: Cache
    _datum_cache: Cache

    def __init__(
        self,
        host: str = "localhost",
        port: int = 1337,
        secure: bool = False,
        refetch_chain_tip_interval: Optional[float] = None,
        utxo_cache_size: int = 10000,
        datum_cache_size: int = 10000,
        network: Network = Network.TESTNET,
    ):
        self.host = host
        self.port = port
        self.secure = secure
        self._network = network
        self._service_name = "ogmios"
        self._last_known_block_slot = 0
        self._refetch_chain_tip_interval = (
            refetch_chain_tip_interval
            if refetch_chain_tip_interval is not None
            else DEFAULT_REFETCH_INTERVAL
        )
        self._last_chain_tip_fetch = 0
        self._genesis_param = None
        self._protocol_param = None

        self._utxo_cache = TTLCache(
            ttl=self._refetch_chain_tip_interval, maxsize=utxo_cache_size
        )
        self._datum_cache = LRUCache(maxsize=datum_cache_size)

    @property
    def name(self) -> str:
        return "Ogmios"

    def _query_current_era(self) -> OgmiosEra:
        with OgmiosClient(self.host, self.port, self.secure) as client:
            return get_current_era(client)

    def _query_current_epoch(self) -> int:
        with OgmiosClient(self.host, self.port, self.secure) as client:
            epoch, _ = client.query_epoch.execute()
            return epoch

    def _query_chain_tip(self) -> OgmiosTip:
        with OgmiosClient(self.host, self.port, self.secure) as client:
            tip, _ = client.query_network_tip.execute()
            return tip

    def _query_utxos_by_address(self, address: Address) -> List[OgmiosUtxo]:
        with OgmiosClient(self.host, self.port, self.secure) as client:
            utxos, _ = client.query_utxo.execute([address])
            return utxos

    def _query_utxos_by_tx_id(self, tx_id: str, index: int) -> List[OgmiosUtxo]:
        with OgmiosClient(self.host, self.port, self.secure) as client:
            utxos, _ = client.query_utxo.execute(
                [OgmiosTxOutputReference(tx_id, index)]
            )
            return utxos

    def _is_chain_tip_updated(self):
        # fetch at most every twenty seconds!
        if time.time() - self._last_chain_tip_fetch < self._refetch_chain_tip_interval:
            return False
        self._last_chain_tip_fetch = time.time()
        slot = self.last_block_slot
        if self._last_known_block_slot < slot:
            self._last_known_block_slot = slot
            return True
        else:
            return False

    @staticmethod
    def _fraction_parser(fraction: str) -> float:
        x, y = fraction.split("/")
        return int(x) / int(y)

    @property
    def protocol_param(self) -> PyCardanoProtocolParameters:
        if not self._protocol_param or self._is_chain_tip_updated():
            self._protocol_param = self._fetch_protocol_param()
        return self._protocol_param.to_pycardano()

    def _fetch_protocol_param(self) -> ProtocolParameters:
        with OgmiosClient(self.host, self.port, self.secure) as client:
            protocol_parameters, _ = client.query_protocol_parameters.execute()
            return ProtocolParameters(
                collateral_percent=protocol_parameters.collateral_percentage,
                committee_max_term_length=protocol_parameters.constitutional_committee_max_term_length,
                committee_min_size=protocol_parameters.constitutional_committee_min_size,
                cost_models=self._parse_cost_models(
                    protocol_parameters.plutus_cost_models
                ),
                d_rep_activity=protocol_parameters.delegate_representative_max_idle_time,
                d_rep_deposit=protocol_parameters.delegate_representative_deposit.lovelace,
                dvt_motion_no_confidence=float(
                    Fraction(
                        protocol_parameters.delegate_representative_voting_thresholds[
                            "noConfidence"
                        ]
                    )
                ),
                dvt_committee_normal=float(
                    Fraction(
                        protocol_parameters.delegate_representative_voting_thresholds[
                            "constitutionalCommittee"
                        ]["default"]
                    )
                ),
                dvt_committee_no_confidence=float(
                    Fraction(
                        protocol_parameters.delegate_representative_voting_thresholds[
                            "constitutionalCommittee"
                        ]["stateOfNoConfidence"]
                    )
                ),
                dvt_update_to_constitution=float(
                    Fraction(
                        protocol_parameters.delegate_representative_voting_thresholds[
                            "constitution"
                        ]
                    )
                ),
                dvt_hard_fork_initiation=float(
                    Fraction(
                        protocol_parameters.delegate_representative_voting_thresholds[
                            "hardForkInitiation"
                        ]
                    )
                ),
                dvt_p_p_network_group=float(
                    Fraction(
                        protocol_parameters.delegate_representative_voting_thresholds[
                            "protocolParametersUpdate"
                        ]["network"]
                    )
                ),
                dvt_p_p_economic_group=float(
                    Fraction(
                        protocol_parameters.delegate_representative_voting_thresholds[
                            "protocolParametersUpdate"
                        ]["economic"]
                    )
                ),
                dvt_p_p_technical_group=float(
                    Fraction(
                        protocol_parameters.delegate_representative_voting_thresholds[
                            "protocolParametersUpdate"
                        ]["technical"]
                    )
                ),
                dvt_p_p_gov_group=float(
                    Fraction(
                        protocol_parameters.delegate_representative_voting_thresholds[
                            "protocolParametersUpdate"
                        ]["governance"]
                    )
                ),
                dvt_treasury_withdrawal=float(
                    Fraction(
                        protocol_parameters.delegate_representative_voting_thresholds[
                            "treasuryWithdrawals"
                        ]
                    )
                ),
                gov_action_deposit=protocol_parameters.governance_action_deposit.lovelace,
                gov_action_lifetime=protocol_parameters.governance_action_lifetime,
                max_block_size=protocol_parameters.max_block_body_size.get("bytes"),
                max_tx_size=protocol_parameters.max_transaction_size.get("bytes"),
                max_block_header_size=protocol_parameters.max_block_header_size.get(
                    "bytes"
                ),
                max_block_ex_mem=protocol_parameters.max_execution_units_per_block.get(
                    "memory"
                ),
                max_block_ex_steps=protocol_parameters.max_execution_units_per_block.get(
                    "cpu"
                ),
                max_collateral_inputs=protocol_parameters.max_collateral_inputs,
                min_fee_constant=protocol_parameters.min_fee_constant.lovelace,
                min_fee_coefficient=protocol_parameters.min_fee_coefficient,
                min_fee_ref_script_cost_per_byte=protocol_parameters.min_fee_ref_scripts,
                min_pool_cost=protocol_parameters.min_stake_pool_cost.lovelace,
                key_deposit=protocol_parameters.stake_credential_deposit.lovelace,
                pool_deposit=protocol_parameters.stake_pool_deposit.lovelace,
                pool_influence=eval(protocol_parameters.stake_pool_pledge_influence),
                monetary_expansion=eval(protocol_parameters.monetary_expansion),
                treasury_expansion=eval(protocol_parameters.treasury_expansion),
                decentralization_param=None,  # type: ignore[arg-type]
                extra_entropy=protocol_parameters.extra_entropy,
                protocol_major_version=protocol_parameters.version.get("major"),
                protocol_minor_version=protocol_parameters.version.get("minor"),
                min_utxo=None,  # type: ignore[arg-type]
                price_mem=eval(
                    protocol_parameters.script_execution_prices.get("memory")
                ),
                price_step=eval(protocol_parameters.script_execution_prices.get("cpu")),
                max_tx_ex_mem=protocol_parameters.max_execution_units_per_transaction.get(
                    "memory"
                ),
                max_tx_ex_steps=protocol_parameters.max_execution_units_per_transaction.get(
                    "cpu"
                ),
                max_val_size=protocol_parameters.max_value_size.get("bytes"),
                coins_per_utxo_word=ALONZO_COINS_PER_UTXO_WORD,
                coins_per_utxo_byte=protocol_parameters.min_utxo_deposit_coefficient,
            )

    @property
    def genesis_param(self) -> GenesisParameters:
        if not self._genesis_param or self._is_chain_tip_updated():
            ogmios_genesis_param = self._fetch_genesis_param()
            self._genesis_param = GenesisParameters(
                active_slots_coefficient=(
                    ogmios_genesis_param.active_slots_coefficient
                    if hasattr(ogmios_genesis_param, "active_slots_coefficient")
                    else None
                ),
                update_quorum=(
                    ogmios_genesis_param.update_quorum
                    if hasattr(ogmios_genesis_param, "update_quorum")
                    else None
                ),
                max_lovelace_supply=(
                    ogmios_genesis_param.max_lovelace_supply
                    if hasattr(ogmios_genesis_param, "max_lovelace_supply")
                    else None
                ),
                network_magic=(
                    ogmios_genesis_param.network_magic
                    if hasattr(ogmios_genesis_param, "network_magic")
                    else None
                ),
                epoch_length=(
                    ogmios_genesis_param.epoch_length
                    if hasattr(ogmios_genesis_param, "epoch_length")
                    else None
                ),
                system_start=(
                    ogmios_genesis_param.start_time
                    if hasattr(ogmios_genesis_param, "start_time")
                    else None
                ),
                slots_per_kes_period=(
                    ogmios_genesis_param.slots_per_kes_period
                    if hasattr(ogmios_genesis_param, "slots_per_kes_period")
                    else None
                ),
                slot_length=(
                    ogmios_genesis_param.slot_length
                    if hasattr(ogmios_genesis_param, "slot_length")
                    else None
                ),
                max_kes_evolutions=(
                    ogmios_genesis_param.max_kes_evolutions
                    if hasattr(ogmios_genesis_param, "max_kes_evolutions")
                    else None
                ),
                security_param=(
                    ogmios_genesis_param.security_parameter
                    if hasattr(ogmios_genesis_param, "security_parameter")
                    else None
                ),
            )

            # Update the refetch interval if we haven't calculated it yet
            if (
                self._refetch_chain_tip_interval == DEFAULT_REFETCH_INTERVAL
                and self._genesis_param is not None
                and self._genesis_param.slot_length is not None
                and self._genesis_param.active_slots_coefficient is not None
            ):
                self._refetch_chain_tip_interval = (
                    self._genesis_param.slot_length
                    / float(self._genesis_param.active_slots_coefficient)
                )
        return self._genesis_param  # type: ignore[return-value]

    def _fetch_genesis_param(self) -> OgmiosGenesisParameters:
        with OgmiosClient(self.host, self.port, self.secure) as client:
            return OgmiosGenesisParameters(client, self._query_current_era())

    @property
    def network(self) -> Network:
        return self._network

    @property
    def epoch(self) -> int:
        return self._query_current_epoch()

    @property
    @func.ttl_cache(ttl=1)
    def last_block_slot(self) -> int:
        tip = self._query_chain_tip()
        return tip.slot

    def _utxos(self, address: str) -> List[UTxO]:
        key = (self.last_block_slot, address)
        if key in self._utxo_cache:
            return self._utxo_cache[key]

        utxos = self._utxos_ogmios(OgmiosAddress(address=address))

        self._utxo_cache[key] = utxos

        return utxos

    def _check_utxo_unspent(self, tx_id: str, index: int) -> bool:
        results = self._query_utxos_by_tx_id(tx_id, index)
        return len(results) > 0

    def _utxos_ogmios(self, address: Address) -> List[OgmiosUtxo]:
        """Get all UTxOs associated with an address with Ogmios.

        Args:
            address (str): An address encoded with bech32.

        Returns:
            List[UTxO]: A list of UTxOs.
        """
        results = self._query_utxos_by_address(address)

        utxos = []
        for result in results:
            utxos.append(self._utxo_from_ogmios_result(result))

        return utxos

    def _utxo_from_ogmios_result(self, utxo: OgmiosUtxo) -> UTxO:
        """Convert an Ogmios UTxO result to a PyCardano UTxO."""
        tx_in = TransactionInput.from_primitive([utxo.tx_id, utxo.index])
        lovelace_amount = utxo.value.get("ada").get("lovelace", 0)
        script = utxo.script
        if script:
            # TODO: Need to test with native scripts
            if script["language"] == "plutus:v2":
                script = PlutusV2Script(bytes.fromhex(script["cbor"]))
            elif script["language"] == "plutus:v1":
                script = PlutusV1Script(bytes.fromhex(script["cbor"]))
            elif script["language"] == "plutus:v3":
                script = PlutusV3Script(bytes.fromhex(script["cbor"]))
            else:
                raise ValueError("Unknown plutus script type")
        datum_hash = (
            DatumHash.from_primitive(utxo.datum_hash) if utxo.datum_hash else None
        )
        datum = None
        if utxo.datum and utxo.datum != utxo.datum_hash:
            datum = RawCBOR(bytes.fromhex(utxo.datum))
        if set(utxo.value.keys()) == {"ada"}:
            tx_out = TransactionOutput(
                Address.from_primitive(utxo.address),
                amount=lovelace_amount,
                datum_hash=datum_hash,
                datum=datum,
                script=script,
            )
        else:
            multi_assets = MultiAsset()
            for asset_hex, token in utxo.value.items():
                if asset_hex != "ada":
                    for token_name_hex, quantity in token.items():
                        policy = ScriptHash.from_primitive(asset_hex)
                        token_name = AssetName.from_primitive(token_name_hex)
                        multi_assets.setdefault(policy, Asset())[token_name] = quantity

            tx_out = TransactionOutput(
                Address.from_primitive(utxo.address),
                amount=Value(lovelace_amount, multi_assets),
                datum_hash=datum_hash,
                datum=datum,
                script=script,
            )
        pyc_utxo = UTxO(tx_in, tx_out)
        return pyc_utxo

    def utxo_by_tx_id(self, tx_id: str, index: int) -> Optional[UTxO]:
        utxos = self._query_utxos_by_tx_id(tx_id, index)
        if len(utxos) > 0:
            return self._utxo_from_ogmios_result(utxos[0])
        return None

    def submit_tx_cbor(self, cbor: Union[bytes, str]):
        if isinstance(cbor, bytes):
            cbor = cbor.hex()
        with OgmiosClient(self.host, self.port, self.secure) as client:
            client.submit_transaction.execute(cbor)

    def evaluate_tx_cbor(self, cbor: Union[bytes, str]) -> Dict[str, ExecutionUnits]:
        if isinstance(cbor, bytes):
            cbor = cbor.hex()
        with OgmiosClient(self.host, self.port, self.secure) as client:
            result, _ = client.evaluate_transaction.execute(cbor)
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

    def _parse_cost_models(self, plutus_cost_models):
        ogmios_cost_models = plutus_cost_models or {}

        cost_models = {}
        if "plutus:v1" in ogmios_cost_models:
            cost_models["PlutusV1"] = ogmios_cost_models["plutus:v1"]
        if "plutus:v2" in ogmios_cost_models:
            cost_models["PlutusV2"] = ogmios_cost_models["plutus:v2"]
        if "plutus:v3" in ogmios_cost_models:
            cost_models["PlutusV3"] = ogmios_cost_models["plutus:v3"]
        return cost_models

    def stake_address_info(self, stake_address: str) -> List[StakeAddressInfo]:
        """Get the stake address information.

        Args:
            stake_address (str): The stake address.

        Returns:
            List[StakeAddressInfo]: The stake address information.
        """
        with OgmiosClient(self.host, self.port, self.secure) as client:
            result, _ = client.query_reward_account_summaries.execute(
                keys=[stake_address]
            )

            return [
                StakeAddressInfo(
                    address=stake_address,
                    delegation_deposit=result["deposit"]["ada"]["lovelace"],
                    stake_delegation=result["delegate"]["id"],
                    reward_account_balance=result["rewards"]["ada"]["lovelace"],
                )
                for result in result
            ]


def KupoOgmiosV6ChainContext(
    host: str,
    port: int,
    secure: bool,
    refetch_chain_tip_interval: Optional[float] = None,
    utxo_cache_size: int = 10000,
    datum_cache_size: int = 10000,
    network: Network = Network.TESTNET,
    kupo_url: Optional[str] = None,
) -> KupoChainContextExtension:
    return KupoChainContextExtension(
        OgmiosChainContext(
            host,
            port,
            secure,
            refetch_chain_tip_interval,
            utxo_cache_size,
            datum_cache_size,
            network,
        ),
        kupo_url,
    )
