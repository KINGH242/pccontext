import json
import time
from decimal import Decimal
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple, Union

import ogmios.model.model_map as mm
import ogmios.model.ogmios_model as om
from cachetools import Cache, LRUCache, TTLCache, func
from ogmios.client import Client as OgmiosClient
from ogmios.datatypes import Address as OgmiosAddress
from ogmios.datatypes import Era as OgmiosEra
from ogmios.datatypes import Origin as OgmiosOrigin
from ogmios.datatypes import ProtocolParameters as OgmiosProtocolParameters
from ogmios.datatypes import Tip as OgmiosTip
from ogmios.datatypes import TxOutputReference as OgmiosTxOutputReference
from ogmios.datatypes import Utxo as OgmiosUtxo
from ogmios.utils import GenesisParameters as OgmiosGenesisParameters
from ogmios.utils import get_current_era
from pycardano.backend.base import ProtocolParameters as PyCardanoProtocolParameters
from pycardano.certificate import DRep, DRepKind
from pycardano.governance import (
    Anchor,
    CommitteeColdCredential,
    CommitteeHotCredential,
    GovActionId,
    Vote,
)
from pycardano.hash import (
    AnchorDataHash,
    DatumHash,
    PoolMetadataHash,
    RewardAccountHash,
    ScriptHash,
    TransactionId,
    VerificationKeyHash,
    VrfKeyHash,
)
from pycardano.network import Network
from pycardano.plutus import (
    ExecutionUnits,
    PlutusV1Script,
    PlutusV2Script,
    PlutusV3Script,
)
from pycardano.pool_params import (
    MultiHostName,
    PoolMetadata,
    PoolOperator,
    PoolParams,
    Relay,
    SingleHostAddr,
    SingleHostName,
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
from pccontext.enums import CommitteeMemberStatus, DRepStatus, Era, PoolStatus
from pccontext.exceptions import OgmiosError
from pccontext.models import (
    ChainTip,
    CommitteeMemberInfo,
    CommitteeStateInfo,
    CommitteeVote,
    DRepInfo,
    DRepStakeEntry,
    DRepVote,
    GenesisParameters,
    GovActionInfo,
    GovActionVotes,
    KESPeriodInfo,
    ProtocolParameters,
    SPOStakeEntry,
    StakeAddressInfo,
    StakePoolInfo,
    StakePoolVote,
)

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

    def _query_block_height(self) -> Optional[int]:
        with OgmiosClient(self.host, self.port, self.secure) as client:
            block_height, _ = client.query_block_height.execute()
            if isinstance(block_height, OgmiosOrigin):
                return 0
            return block_height

    def _query_stake_pools(
        self, pool_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        with OgmiosClient(self.host, self.port, self.secure) as client:
            if pool_ids:
                stake_pools, _ = client.query_stake_pools.execute(pool_ids)
                return stake_pools
            # ``QueryStakePools.execute`` always sends a ``stakePools`` filter, and
            # an empty filter selects no pool at all. Ogmios returns every
            # registered pool only when the parameter is left out entirely, so
            # send the bare request and let the library parse the response.
            payload = om.QueryLedgerStateStakePools(
                jsonrpc=client.rpc_version,
                method=mm.Method.queryLedgerState_stakePools.value,
            )
            client.send(payload.json(exclude_none=True))
            stake_pools, _ = client.query_stake_pools.receive()
            return stake_pools

    def _query_rewards_provenance(self) -> Dict[str, Any]:
        with OgmiosClient(self.host, self.port, self.secure) as client:
            provenance, _ = client.query_rewards_provenance.execute()
            return provenance

    def _query_treasury_and_reserves(self) -> Tuple[int, int]:
        with OgmiosClient(self.host, self.port, self.secure) as client:
            treasury, reserves, _ = client.query_treasury_and_reserves.execute()
            return treasury.lovelace, reserves.lovelace

    def _query_constitutional_committee(self) -> Dict[str, Any]:
        with OgmiosClient(self.host, self.port, self.secure) as client:
            committee, _ = client.query_constitutional_committee.execute()
            return committee

    def _query_ledger_state(
        self, method: str, params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Send a ledger-state query the installed ``ogmios`` client does not bind.

        The client (1.4.3, the latest release) exposes no request model and no
        ``mm.Method`` entry for ``queryLedgerState/operationalCertificates``,
        ``queryLedgerState/delegateRepresentatives`` or
        ``queryLedgerState/governanceProposals``, so — unlike
        :meth:`_query_stake_pools`, which can still borrow the library's model
        class — the JSON-RPC envelope has to be built by hand here. It is
        deliberately the only place in this backend that does so; every mapping
        function below reads the parsed result defensively.

        The request and response shapes are those of the Ogmios v6 JSON schema
        (``ogmios.json`` / ``cardano.json``).

        Args:
            method (str): The JSON-RPC method name.
            params (Optional[Dict[str, Any]]): The method's parameters, omitted
                from the request entirely when ``None``.

        Returns:
            Any: The response's ``result``, parsed from JSON.

        Raises:
            OgmiosError: If Ogmios answers with an error, answers a different
                method, or returns no result at all.
        """
        with OgmiosClient(self.host, self.port, self.secure) as client:
            rpc_version = getattr(client.rpc_version, "value", client.rpc_version)
            request: Dict[str, Any] = {"jsonrpc": rpc_version, "method": method}
            if params is not None:
                request["params"] = params
            client.send(json.dumps(request))
            response = client.receive()

        if not isinstance(response, dict):
            raise OgmiosError(f"Malformed response to {method}: {response!r}")
        if response.get("error"):
            raise OgmiosError(f"Ogmios responded with an error to {method}: {response}")
        if response.get("method") != method:
            raise OgmiosError(f"Incorrect method for {method} response: {response}")
        if "result" not in response:
            raise OgmiosError(f"Failed to parse {method} response: {response}")
        return response["result"]

    def _query_operational_certificates(self) -> Dict[str, int]:
        """Get every stake pool's operational certificate counter, by pool ID."""
        result = self._query_ledger_state(
            "queryLedgerState/operationalCertificates",
        )
        return result if isinstance(result, dict) else {}

    def _query_delegate_representatives(
        self,
        keys: Optional[List[str]] = None,
        scripts: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get the registered DRep summaries, optionally filtered.

        Args:
            keys (Optional[List[str]]): Verification key hashes to filter on,
                hex encoded.
            scripts (Optional[List[str]]): Script hashes to filter on, hex
                encoded.

        Returns:
            List[Dict[str, Any]]: One summary per DRep. With no filter this is
            every registered DRep plus the two predefined options; the
            predefined options are returned whether or not a filter is given.
        """
        params: Optional[Dict[str, Any]] = None
        if keys:
            params = {"keys": keys}
        elif scripts:
            params = {"scripts": scripts}

        result = self._query_ledger_state(
            "queryLedgerState/delegateRepresentatives", params
        )
        return result if isinstance(result, list) else []

    def _query_governance_proposals(self) -> List[Dict[str, Any]]:
        """Get the currently active governance proposals with their votes."""
        result = self._query_ledger_state("queryLedgerState/governanceProposals")
        return result if isinstance(result, list) else []

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

    # -- Chain state ------------------------------------------------------

    @property
    def era(self) -> Optional[Era]:
        """The era the chain is currently in.

        Derived from ``queryLedgerState/eraSummaries``: the last summary
        describes the era the chain is in now.

        Returns:
            Optional[Era]: The current era, or ``None`` when Ogmios names an era
            this library does not know about.
        """
        try:
            return Era(self._query_current_era().value)
        except ValueError:
            return None

    @property
    def chain_tip(self) -> ChainTip:
        """The current tip of the chain.

        The slot and block hash come from ``queryNetwork/tip``, the height from
        ``queryNetwork/blockHeight``, the epoch from ``queryLedgerState/epoch``
        and the era from ``queryLedgerState/eraSummaries``. Ogmios's JSON-RPC
        interface reports no synchronisation percentage — that lives on the
        server's HTTP ``/health`` endpoint — so
        :attr:`~pccontext.models.ChainTip.sync_progress` is always ``None``.

        Returns:
            ChainTip: The slot, block hash, height, epoch and era of the tip.
        """
        tip: Any = self._query_chain_tip()

        if isinstance(tip, OgmiosOrigin):
            slot: Optional[int] = 0
            block_hash: Optional[str] = None
        else:
            slot = tip.slot
            block_hash = tip.id

        return ChainTip(
            slot=slot,
            hash=block_hash,
            block=self._query_block_height(),
            epoch=self._query_current_epoch(),
            era=self.era,
        )

    def utxo(self, tx_input: TransactionInput) -> Optional[Tuple[UTxO, bool]]:
        """Resolve a single UTxO by the transaction input that identifies it.

        Args:
            tx_input (TransactionInput): The transaction hash and output index.

        Returns:
            Optional[Tuple[UTxO, bool]]: The UTxO and ``False``, because
            ``queryLedgerState/utxo`` only sees the live UTxO set: anything it
            returns is unspent. A spent output is indistinguishable from one
            that never existed, and both give ``None``.
        """
        utxos = self._query_utxos_by_tx_id(str(tx_input.transaction_id), tx_input.index)
        if not utxos:
            return None
        return self._utxo_from_ogmios_result(utxos[0]), False

    # -- Stake pools ------------------------------------------------------

    def stake_pools(self) -> List[PoolOperator]:
        """Get every stake pool registered on the chain.

        Backed by ``queryLedgerState/stakePools`` with no filter, which returns
        the currently registered and active pools.

        Returns:
            List[PoolOperator]: The registered pools.
        """
        return [
            PoolOperator.from_primitive(pool_id)
            for pool_id in self._query_stake_pools()
        ]

    def stake_pool_info(self, pool_id: str, strict: bool = False) -> StakePoolInfo:
        """Get a stake pool's registered parameters and stake figures.

        The registered parameters come from ``queryLedgerState/stakePools``, and
        the stake figures from ``queryLedgerState/rewardsProvenance``, which
        reports the epoch's stake snapshot per pool. A pool that
        ``queryLedgerState/stakePools`` returns is registered, so
        :attr:`~pccontext.models.StakePoolInfo.status` is always
        ``PoolStatus.REGISTERED``; Ogmios reports no retirement epoch, so
        ``retiring_epoch`` stays ``None``. ``opcert_counter`` also stays
        ``None``: the counter lives in a separate whole-chain query, which
        :meth:`kes_period_info` makes rather than paying for it here.

        Args:
            pool_id (str): The pool's ID, bech32 encoded.
            strict (bool): Ignored. Ogmios never fetches a pool's off-chain
                metadata, so the registered URL and hash are reported as they
                stand on chain and no hash can be verified.

        Returns:
            StakePoolInfo: The pool's information.

        Raises:
            OgmiosError: If the pool is not registered, or a relay it registered
                has a shape this backend does not recognise.
        """
        params = self._query_stake_pools([pool_id]).get(pool_id)
        if params is None:
            raise OgmiosError(f"Stake pool not found: {pool_id}")

        active_stake: Optional[int] = None
        active_size: Optional[Decimal] = None
        owner_stake: Optional[int] = None

        # Rewards provenance is a heavier query than the pool parameters and is
        # unavailable on a node that has not yet reached a rewards snapshot.
        # Report the registered parameters without stake figures in that case
        # rather than failing the whole call.
        try:
            provenance = self._query_rewards_provenance()
        except Exception:
            provenance = {}

        summary = provenance.get("stakePools", {}).get(pool_id)
        if summary is not None:
            active_stake = summary["stake"]["ada"]["lovelace"]
            owner_stake = summary["ownerStake"]["ada"]["lovelace"]
            total_stake = provenance["activeStakeInEpoch"]["ada"]["lovelace"]
            if total_stake:
                active_size = Decimal(active_stake) / Decimal(total_stake)

        return StakePoolInfo(
            pool_params=self._pool_params_from_ogmios(pool_id, params),
            live_pledge=owner_stake,
            active_stake=active_stake,
            active_size=active_size,
            status=PoolStatus.REGISTERED,
        )

    def kes_period_info(
        self,
        pool: Optional[PoolOperator] = None,
        op_cert: Optional[Union[bytes, str]] = None,
    ) -> KESPeriodInfo:
        """Get the KES period information for a pool's operational certificate.

        Backed by ``queryLedgerState/operationalCertificates``, which reports
        the counter registered on chain for every stake pool that has issued an
        operational certificate.

        Ogmios has no view of a local certificate file and reports no KES
        period, so ``on_disk_op_cert_count`` and ``on_disk_kes_start`` are never
        populated; a `cardano-cli` context can supply those. ``op_cert`` is
        accepted for signature compatibility and ignored — decoding the CBOR
        certificate is the caller's job, and inventing counters from it here
        would not make them Ogmios' answer.

        Args:
            pool (Optional[PoolOperator]): The pool operator. Required here,
                since the counters are keyed by pool ID.
            op_cert (Optional[Union[bytes, str]]): Ignored, see above.

        Returns:
            KESPeriodInfo: The on-chain counter and the counter to use for the
            next certificate.

        Raises:
            OgmiosError: If ``pool`` is not given, or if the pool has no
                counter on chain. Ogmios lists only pools that have issued an
                operational certificate, so a missing pool is reported as such
                rather than as a counter of ``-1``, which would claim the pool
                is registered but has never minted a block.
        """
        if pool is None:
            raise OgmiosError(
                "Ogmios reports operational certificate counters by pool ID, so "
                "a pool operator must be provided."
            )

        pool_id = pool.encode()
        counters = self._query_operational_certificates()
        if pool_id not in counters:
            raise OgmiosError(
                f"No operational certificate counter found for pool: {pool_id}"
            )

        on_chain = int(counters[pool_id])
        return KESPeriodInfo(
            on_chain_op_cert_count=on_chain,
            next_chain_op_cert_count=on_chain + 1,
        )

    # -- Treasury ---------------------------------------------------------

    def treasury(self) -> int:
        """Get the current treasury balance, in lovelace.

        Backed by ``queryLedgerState/treasuryAndReserves``.

        Returns:
            int: The treasury balance, in lovelace.
        """
        treasury, _reserves = self._query_treasury_and_reserves()
        return treasury

    # -- Governance -------------------------------------------------------

    def drep_info(self, drep: DRep) -> DRepInfo:
        """Get a delegate representative's registration and voting power.

        Backed by ``queryLedgerState/delegateRepresentatives``, filtered on the
        DRep's credential so the node does not have to enumerate every DRep.
        The two predefined options — always-abstain and always-no-confidence —
        are answered from the unfiltered query, which always returns them.

        ``active`` is derived: Ogmios reports the epoch a registration lapses in
        (``mandate``) rather than a liveness flag, so a DRep counts as active
        while the current epoch has not passed that expiry. That costs one extra
        ``queryLedgerState/epoch`` call. A DRep with no mandate is reported as
        active, since nothing says it has lapsed.

        Args:
            drep (DRep): The DRep to look up.

        Returns:
            DRepInfo: The DRep's information. A key- or script-hash DRep the
            ledger does not list is reported as ``NOT_REGISTERED`` with zero
            stake. ``status`` is only ever ``REGISTERED`` or
            ``NOT_REGISTERED``: the ledger drops a DRep's record when it
            retires, so ``RETIRED`` is indistinguishable from never registered
            here.

        Raises:
            OgmiosError: If a key- or script-hash DRep carries no credential, or
                if Ogmios omits a predefined option it is documented to always
                return.
        """
        predefined = {
            DRepKind.ALWAYS_ABSTAIN: "abstain",
            DRepKind.ALWAYS_NO_CONFIDENCE: "noConfidence",
        }.get(drep.kind)

        if predefined is not None:
            for summary in self._query_delegate_representatives():
                if summary.get("type") == predefined:
                    return DRepInfo(
                        drep=drep,
                        active=True,
                        stake=self._lovelace(summary.get("stake")),
                        status=DRepStatus.REGISTERED,
                    )
            raise OgmiosError(
                f"Ogmios did not report the {predefined} delegate representative."
            )

        if drep.credential is None:
            raise OgmiosError(f"DRep carries no credential to look up: {drep.kind}")

        credential = drep.credential.payload.hex()
        if drep.kind == DRepKind.SCRIPT_HASH:
            summaries = self._query_delegate_representatives(scripts=[credential])
        else:
            summaries = self._query_delegate_representatives(keys=[credential])

        for summary in summaries:
            # The predefined options come back alongside the filtered results.
            if summary.get("type") != "registered":
                continue
            if summary.get("id") != credential:
                continue
            return self._drep_info_from_summary(drep, summary, self.epoch)

        return DRepInfo(
            drep=drep, active=False, stake=0, status=DRepStatus.NOT_REGISTERED
        )

    def gov_action_info(self, gov_action_id: GovActionId) -> GovActionInfo:
        """Get the lifecycle information for a governance action.

        Backed by ``queryLedgerState/governanceProposals``, which has no
        single-proposal form here, so the list is fetched and filtered.

        Args:
            gov_action_id (GovActionId): The action's identifier.

        Returns:
            GovActionInfo: The action's information. ``gov_action`` carries
            Ogmios' own ``action`` object rather than a parsed pycardano action:
            Ogmios describes an action as free-form JSON keyed by governance
            type, which does not map onto pycardano's action classes without
            guessing. ``ratified_epoch``, ``enacted_epoch``, ``dropped_epoch``
            and ``expired_epoch`` are always unset — this query returns only
            proposals that are still live, so a resolved action is absent
            rather than annotated, and :attr:`GovActionInfo.status` is always
            ``None`` here.

        Raises:
            OgmiosError: If the action is not among the active proposals.
        """
        proposal = self._find_proposal(gov_action_id)
        since = proposal.get("since") or {}
        until = proposal.get("until") or {}
        return GovActionInfo(
            gov_action_id=gov_action_id,
            gov_action=proposal.get("action"),
            proposed_in=since.get("epoch"),
            expires_after=until.get("epoch"),
        )

    def gov_action_votes(self, gov_action_id: GovActionId) -> GovActionVotes:
        """Get the votes recorded against a governance action, by voter class.

        Backed by ``queryLedgerState/governanceProposals``, whose entries carry
        the proposal procedure and every vote cast so far.

        Args:
            gov_action_id (GovActionId): The action's identifier.

        Returns:
            GovActionVotes: The proposal plus its committee, DRep and stake pool
            votes. Empty vote lists mean no votes have been recorded, not that
            Ogmios cannot report them. See :meth:`gov_action_info` for what
            ``gov_action`` holds and why the resolution epochs stay unset.

        Raises:
            OgmiosError: If the action is not among the active proposals.
        """
        return self._gov_action_votes(self._find_proposal(gov_action_id))

    def gov_actions_all(self) -> List[GovActionVotes]:
        """Get every active governance proposal with its votes.

        Backed by a single unfiltered ``queryLedgerState/governanceProposals``,
        which already carries the votes — unlike the REST backends, this needs
        no further request per proposal.

        Returns:
            List[GovActionVotes]: One entry per proposal the ledger still holds.
            A proposal whose reference cannot be read is skipped rather than
            returned without an identifier.
        """
        actions = []
        for proposal in self._query_governance_proposals():
            if self._proposal_gov_action_id(proposal) is None:
                continue
            actions.append(self._gov_action_votes(proposal))
        return actions

    def committee_member_info(
        self,
        cold: Optional[CommitteeColdCredential] = None,
        hot: Optional[CommitteeHotCredential] = None,
    ) -> CommitteeMemberInfo:
        """Get a constitutional committee member's authorization and term.

        Backed by ``queryLedgerState/constitutionalCommittee``, whose members
        are matched on the given credential.

        Args:
            cold (Optional[CommitteeColdCredential]): The member's cold
                credential. Optional if ``hot`` is given.
            hot (Optional[CommitteeHotCredential]): A hot credential the member
                has authorized. Optional if ``cold`` is given.

        Returns:
            CommitteeMemberInfo: The member's information.

        Raises:
            OgmiosError: If neither credential is given, if no member matches,
                or if a member carries a credential origin this backend does not
                recognise.
        """
        if cold is None and hot is None:
            raise OgmiosError(
                "Either a cold or a hot committee credential must be given."
            )

        for raw_member in self._query_constitutional_committee().get("members", []):
            member = self._committee_member_from_ogmios(raw_member)
            if cold is not None and member.cold_credential != cold:
                continue
            if hot is not None and member.hot_credential != hot:
                continue
            return member

        raise OgmiosError(
            f"Committee member not found for credential: {cold if cold else hot}"
        )

    def committee_state(self) -> CommitteeStateInfo:
        """Get the full constitutional committee state.

        Backed by ``queryLedgerState/constitutionalCommittee``.

        Returns:
            CommitteeStateInfo: Every member with its cold-to-hot authorization
            and term expiration, plus the quorum threshold. The threshold is
            ``None`` when Ogmios reports none, which is how a committee defined
            in the Conway genesis file can appear.

        Raises:
            OgmiosError: If a member carries a credential origin this backend
                does not recognise.
        """
        committee = self._query_constitutional_committee()
        return CommitteeStateInfo(
            members=[
                self._committee_member_from_ogmios(member)
                for member in committee.get("members", [])
            ],
            threshold=self._ratio_to_float(committee.get("quorum")),
        )

    # -- Stake distributions ----------------------------------------------

    def drep_stake_distribution(self) -> List[DRepStakeEntry]:
        """Get the stake delegated to each DRep this epoch.

        Backed by an unfiltered ``queryLedgerState/delegateRepresentatives``,
        whose ``stake`` field is the DRep's voting power in lovelace.

        Returns:
            List[DRepStakeEntry]: One entry per registered DRep, plus one each
            for the always-abstain and always-no-confidence options, which the
            ledger tracks as stake pots of their own. A summary whose credential
            cannot be read is skipped rather than returned with no DRep.
        """
        entries = []
        for summary in self._query_delegate_representatives():
            drep = self._drep_from_summary(summary)
            if drep is None:
                continue
            entries.append(
                DRepStakeEntry(drep=drep, stake=self._lovelace(summary.get("stake")))
            )
        return entries

    def spo_stake_distribution(self) -> List[SPOStakeEntry]:
        """Get the stake delegated to each stake pool this epoch.

        Backed by ``queryLedgerState/rewardsProvenance``, which reports each
        pool's stake for the ongoing epoch in lovelace.
        ``queryLedgerState/liveStakeDistribution`` is not used here: it reports
        each pool's share as a ratio of the total, not an amount.

        Returns:
            List[SPOStakeEntry]: One entry per pool.
        """
        stake_pools = self._query_rewards_provenance().get("stakePools", {})
        return [
            SPOStakeEntry(pool_id=pool_id, stake=summary["stake"]["ada"]["lovelace"])
            for pool_id, summary in stake_pools.items()
        ]

    # -- Parsing helpers --------------------------------------------------

    @staticmethod
    def _ratio_to_float(ratio: Optional[str]) -> Optional[float]:
        """Convert an Ogmios ``"numerator/denominator"`` ratio to a float."""
        if not ratio:
            return None
        return float(Fraction(ratio))

    @staticmethod
    def _relay_from_ogmios(relay: Dict[str, Any]) -> Relay:
        """Convert an Ogmios relay entry to a PyCardano relay."""
        relay_type = relay.get("type")
        if relay_type == "ipAddress":
            return SingleHostAddr(
                port=relay.get("port"),
                ipv4=relay.get("ipv4"),
                ipv6=relay.get("ipv6"),
            )
        if relay_type == "hostname":
            # Ogmios collapses both name-based relays onto one shape. The SRV
            # record of a multi-host relay is the one without a port.
            if relay.get("port") is None:
                return MultiHostName(dns_name=relay.get("hostname"))
            return SingleHostName(
                port=relay.get("port"), dns_name=relay.get("hostname")
            )
        raise OgmiosError(f"Unknown stake pool relay type: {relay_type}")

    @classmethod
    def _pool_params_from_ogmios(
        cls, pool_id: str, params: Dict[str, Any]
    ) -> PoolParams:
        """Convert an Ogmios stake pool entry to PyCardano pool parameters."""
        metadata = params.get("metadata")
        pool_metadata = (
            PoolMetadata(
                url=metadata["url"],
                pool_metadata_hash=PoolMetadataHash(bytes.fromhex(metadata["hash"])),
            )
            if metadata
            else None
        )
        reward_account = Address.from_primitive(params["rewardAccount"])

        return PoolParams(
            operator=PoolOperator.from_primitive(pool_id).pool_key_hash,
            vrf_keyhash=VrfKeyHash(bytes.fromhex(params["vrfVerificationKeyHash"])),
            pledge=params["pledge"]["ada"]["lovelace"],
            cost=params["cost"]["ada"]["lovelace"],
            margin=Fraction(params["margin"]),
            reward_account=RewardAccountHash(bytes(reward_account.to_primitive())),
            pool_owners=[
                VerificationKeyHash(bytes.fromhex(owner))
                for owner in params.get("owners", [])
            ],
            relays=[
                cls._relay_from_ogmios(relay) for relay in params.get("relays", [])
            ],
            pool_metadata=pool_metadata,
        )

    @staticmethod
    def _credential_payload(
        entry: Dict[str, Any],
    ) -> Union[ScriptHash, VerificationKeyHash]:
        """Build a credential hash from an Ogmios ``{id, from}`` pair."""
        origin = entry.get("from")
        payload = bytes.fromhex(entry["id"])
        if origin == "script":
            return ScriptHash(payload)
        if origin == "verificationKey":
            return VerificationKeyHash(payload)
        raise OgmiosError(f"Unknown committee credential origin: {origin}")

    @classmethod
    def _committee_member_from_ogmios(
        cls, member: Dict[str, Any]
    ) -> CommitteeMemberInfo:
        """Convert an Ogmios constitutional committee member entry."""
        cold_credential = CommitteeColdCredential(
            credential=cls._credential_payload(member)
        )

        delegate = member.get("delegate") or {}
        hot_credential = (
            CommitteeHotCredential(credential=cls._credential_payload(delegate))
            if delegate.get("status") == "authorized"
            else None
        )

        status = member.get("status")
        mandate = member.get("mandate") or {}

        return CommitteeMemberInfo(
            cold_credential=cold_credential,
            hot_credential=hot_credential,
            expiration=mandate.get("epoch"),
            status=CommitteeMemberStatus(status) if status else None,
        )

    # -- Governance parsing helpers ---------------------------------------

    @staticmethod
    def _lovelace(value: Any) -> Optional[int]:
        """Read a lovelace amount from Ogmios' ``{"ada": {"lovelace": n}}``."""
        if not isinstance(value, dict):
            return None
        ada = value.get("ada")
        if not isinstance(ada, dict):
            return None
        lovelace = ada.get("lovelace")
        return lovelace if isinstance(lovelace, int) else None

    @staticmethod
    def _anchor_from_ogmios(value: Any) -> Optional[Anchor]:
        """Convert Ogmios' ``{"url", "hash"}`` metadata to a PyCardano anchor."""
        if not isinstance(value, dict):
            return None
        url = value.get("url")
        data_hash = value.get("hash")
        if not isinstance(url, str) or not isinstance(data_hash, str):
            return None
        try:
            return Anchor(url=url, data_hash=AnchorDataHash(bytes.fromhex(data_hash)))
        except (AssertionError, ValueError, TypeError):
            return None

    @staticmethod
    def _drep_from_credential(entry: Any) -> Optional[DRep]:
        """Build a DRep from an Ogmios ``{id, from}`` credential pair.

        Args:
            entry (Any): The pair, as it appears on a DRep summary or on the
                issuer of a vote.

        Returns:
            Optional[DRep]: The DRep, or ``None`` when the pair is unreadable or
            names a credential origin this backend does not recognise.
        """
        if not isinstance(entry, dict):
            return None
        origin = entry.get("from")
        payload = entry.get("id")
        if not isinstance(payload, str):
            return None
        try:
            if origin == "script":
                return DRep(
                    kind=DRepKind.SCRIPT_HASH,
                    credential=ScriptHash(bytes.fromhex(payload)),
                )
            if origin == "verificationKey":
                return DRep(
                    kind=DRepKind.VERIFICATION_KEY_HASH,
                    credential=VerificationKeyHash(bytes.fromhex(payload)),
                )
        except (AssertionError, ValueError, TypeError):
            return None
        return None

    @classmethod
    def _drep_from_summary(cls, summary: Any) -> Optional[DRep]:
        """Build a DRep from one ``delegateRepresentatives`` entry."""
        if not isinstance(summary, dict):
            return None
        kinds = {
            "abstain": DRepKind.ALWAYS_ABSTAIN,
            "noConfidence": DRepKind.ALWAYS_NO_CONFIDENCE,
        }
        summary_type = summary.get("type")
        kind = kinds.get(summary_type) if isinstance(summary_type, str) else None
        if kind is not None:
            return DRep(kind=kind)
        return cls._drep_from_credential(summary)

    @classmethod
    def _drep_info_from_summary(
        cls, drep: DRep, summary: Dict[str, Any], current_epoch: int
    ) -> DRepInfo:
        """Convert a registered ``delegateRepresentatives`` entry to a DRepInfo."""
        mandate = summary.get("mandate") or {}
        expiry = mandate.get("epoch") if isinstance(mandate, dict) else None

        return DRepInfo(
            drep=drep,
            active=expiry is None or current_epoch <= expiry,
            anchor=cls._anchor_from_ogmios(summary.get("metadata")),
            deposit=cls._lovelace(summary.get("deposit")),
            stake=cls._lovelace(summary.get("stake")),
            expiry=expiry,
            status=DRepStatus.REGISTERED,
        )

    @staticmethod
    def _proposal_gov_action_id(proposal: Any) -> Optional[GovActionId]:
        """Read the action id from a proposal's ``proposal`` reference."""
        if not isinstance(proposal, dict):
            return None
        reference = proposal.get("proposal")
        if not isinstance(reference, dict):
            return None
        transaction = reference.get("transaction")
        tx_id = transaction.get("id") if isinstance(transaction, dict) else None
        index = reference.get("index")
        if not isinstance(tx_id, str) or not isinstance(index, int):
            return None
        try:
            return GovActionId(
                transaction_id=TransactionId(bytes.fromhex(tx_id)),
                gov_action_index=index,
            )
        except (AssertionError, ValueError, TypeError):
            return None

    def _find_proposal(self, gov_action_id: GovActionId) -> Dict[str, Any]:
        """Find one active proposal by its action id.

        Raises:
            OgmiosError: If no active proposal carries that id.
        """
        for proposal in self._query_governance_proposals():
            if self._proposal_gov_action_id(proposal) == gov_action_id:
                return proposal
        raise OgmiosError(
            "Governance action not found among the active proposals: "
            f"{gov_action_id.transaction_id}#{gov_action_id.gov_action_index}"
        )

    @staticmethod
    def _parse_vote(value: Any) -> Optional[Vote]:
        """Parse Ogmios' spelling of a vote."""
        votes = {"yes": Vote.YES, "no": Vote.NO, "abstain": Vote.ABSTAIN}
        return votes.get(value) if isinstance(value, str) else None

    @classmethod
    def _split_votes(
        cls, raw_votes: Any
    ) -> Tuple[List[CommitteeVote], List[DRepVote], List[StakePoolVote]]:
        """Split a proposal's flat vote list by the role of its issuer.

        Genesis delegate votes are dropped: they are a pre-Conway construct with
        no place in any of the three voter classes the models keep.
        """
        committee: List[CommitteeVote] = []
        dreps: List[DRepVote] = []
        pools: List[StakePoolVote] = []

        for raw in raw_votes if isinstance(raw_votes, list) else []:
            if not isinstance(raw, dict):
                continue
            issuer = raw.get("issuer")
            if not isinstance(issuer, dict):
                continue
            vote = cls._parse_vote(raw.get("vote"))
            anchor = cls._anchor_from_ogmios(raw.get("metadata"))
            role = issuer.get("role")

            if role == "constitutionalCommittee":
                try:
                    voter = CommitteeHotCredential(cls._credential_payload(issuer))
                except (AssertionError, OgmiosError, KeyError, ValueError, TypeError):
                    continue
                committee.append(CommitteeVote(voter=voter, vote=vote, anchor=anchor))
            elif role == "delegateRepresentative":
                drep = cls._drep_from_credential(issuer)
                if drep is None:
                    continue
                dreps.append(DRepVote(voter=drep, vote=vote, anchor=anchor))
            elif role == "stakePoolOperator":
                pool_id = issuer.get("id")
                if not isinstance(pool_id, str):
                    continue
                pools.append(StakePoolVote(voter=pool_id, vote=vote, anchor=anchor))

        return committee, dreps, pools

    @classmethod
    def _gov_action_votes(cls, proposal: Dict[str, Any]) -> GovActionVotes:
        """Assemble a GovActionVotes from one ``governanceProposals`` entry."""
        committee, dreps, pools = cls._split_votes(proposal.get("votes"))
        since = proposal.get("since") or {}
        until = proposal.get("until") or {}

        return GovActionVotes(
            gov_action_id=cls._proposal_gov_action_id(proposal),
            gov_action=proposal.get("action"),
            committee_votes=committee,
            drep_votes=dreps,
            stake_pool_votes=pools,
            deposit=cls._lovelace(proposal.get("deposit")),
            deposit_return_addr=proposal.get("returnAccount"),
            anchor=cls._anchor_from_ogmios(proposal.get("metadata")),
            proposed_in=since.get("epoch") if isinstance(since, dict) else None,
            expires_after=until.get("epoch") if isinstance(until, dict) else None,
        )


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
