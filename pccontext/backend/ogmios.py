import threading
import time
from decimal import Decimal
from fractions import Fraction
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import pyogmios
from cachetools import Cache, LRUCache, TTLCache, func
from pycardano.backend.base import GenesisParameters as PyCardanoGenesisParameters
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
from pycardano.nativescript import (
    InvalidBefore,
    InvalidHereAfter,
    NativeScript,
    ScriptAll,
    ScriptAny,
    ScriptNofK,
    ScriptPubkey,
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
from pyogmios import types as ot

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

#: The eras in the order Ogmios lists them in ``queryLedgerState/eraSummaries``.
ERAS: Tuple[str, ...] = (
    "byron",
    "shelley",
    "allegra",
    "mary",
    "alonzo",
    "babbage",
    "conway",
    "dijkstra",
)

#: Ogmios v7 redeemer purposes, keyed to the redeemer tag names pycardano keys
#: execution units by (``RedeemerTag.<NAME>.name.lower()``).
REDEEMER_PURPOSES: Dict[str, str] = {
    "spend": "spend",
    "mint": "mint",
    "publish": "certificate",
    "withdraw": "withdrawal",
    "vote": "voting",
    "propose": "proposing",
}

__all__ = ["OgmiosChainContext"]


class OgmiosChainContext(ChainContext):
    """Ogmios v7 chain context for use with PyCardano.

    Built on `pyogmios <https://github.com/Kingpin-Apps/pyogmios>`_'s synchronous
    client. Every query goes over one long-lived WebSocket connection, opened on
    first use and reopened by pyogmios if it drops. Call :meth:`close` (or use the
    context as a ``with`` block) to release it.

    Errors Ogmios reports are raised as pyogmios' typed exceptions, for example
    :class:`pyogmios.errors.MissingSignatoriesError` when a submitted transaction
    lacks a signature. :class:`~pccontext.exceptions.OgmiosError` is raised for
    conditions this context detects itself, such as a pool that is not found.

    Args:
        host (str): The Ogmios host.
        port (int): The Ogmios port.
        secure (bool): Whether to connect over ``wss://`` rather than ``ws://``.
        refetch_chain_tip_interval (Optional[float]): Seconds between chain tip
            checks that decide whether cached protocol parameters are stale.
            Defaults to the expected block interval from the Shelley genesis.
        utxo_cache_size (int): How many address lookups to cache.
        datum_cache_size (int): How many datums to cache.
        network (Network): The network the node is on.
        client (Optional[pyogmios.Client]): A ready-made pyogmios client, for
            example one carrying an API key header for hosted Ogmios. When given,
            ``host``, ``port`` and ``secure`` are ignored.
    """

    _network: Network
    _service_name: str
    _last_known_block_slot: int
    _last_chain_tip_fetch: float
    _genesis_param: Optional[GenesisParameters]
    _protocol_param: Optional[ProtocolParameters]
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
        *,
        client: Optional[pyogmios.Client] = None,
    ):
        self.host = host
        self.port = port
        self.secure = secure
        self._network = network
        self._service_name = "ogmios"
        self._last_known_block_slot = 0
        self._refetch_chain_tip_interval = (
            refetch_chain_tip_interval if refetch_chain_tip_interval is not None else DEFAULT_REFETCH_INTERVAL
        )
        self._last_chain_tip_fetch = 0
        self._genesis_param = None
        self._protocol_param = None

        self._utxo_cache = TTLCache(ttl=self._refetch_chain_tip_interval, maxsize=utxo_cache_size)
        self._datum_cache = LRUCache(maxsize=datum_cache_size)

        self._ogmios: Optional[pyogmios.Client] = client
        self._ogmios_lock = threading.Lock()

    @property
    def name(self) -> str:
        return "Ogmios"

    @property
    def url(self) -> str:
        """The WebSocket URL this context connects to."""
        if self._ogmios is not None:
            return self._ogmios.url
        scheme = "wss" if self.secure else "ws"
        return f"{scheme}://{self.host}:{self.port}"

    @property
    def client(self) -> pyogmios.Client:
        """The pyogmios client, created on first use and kept for later calls.

        pyogmios connects it on the first request and reconnects it if the
        connection drops, so one client serves the context's whole lifetime.
        """
        if self._ogmios is None:
            with self._ogmios_lock:
                if self._ogmios is None:
                    self._ogmios = pyogmios.Client(self.url)
        return self._ogmios

    def close(self) -> None:
        """Close the connection to Ogmios. A later query opens a new one."""
        with self._ogmios_lock:
            client, self._ogmios = self._ogmios, None
        if client is not None:
            client.close()

    def __enter__(self) -> "OgmiosChainContext":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # -- Queries ----------------------------------------------------------

    def _query_current_era(self) -> str:
        """The current era's name, from the number of era summaries."""
        summaries = self.client.ledger_state.era_summaries()
        index = len(summaries) - 1
        if not 0 <= index < len(ERAS):
            raise OgmiosError(f"Unknown era at position {index} of the era summaries")
        return ERAS[index]

    def _query_current_epoch(self) -> int:
        return self.client.ledger_state.epoch()

    def _query_chain_tip(self) -> Union[ot.Point, str]:
        return self.client.network.tip()

    def _query_block_height(self) -> int:
        height = self.client.network.block_height()
        return 0 if height == "origin" else height

    def _query_stake_pools(self, pool_ids: Optional[List[str]] = None) -> Dict[str, ot.StakePoolView]:
        if pool_ids:
            return self.client.ledger_state.stake_pools(stake_pools=[{"id": pool_id} for pool_id in pool_ids])
        # An empty filter selects no pool at all: leave it out for every pool.
        return self.client.ledger_state.stake_pools()

    def _query_stake_pools_performances(self) -> ot.StakePoolsPerformances:
        return self.client.ledger_state.stake_pools_performances()

    def _query_treasury_and_reserves(self) -> Tuple[int, int]:
        result = self.client.ledger_state.treasury_and_reserves()
        return result.treasury.ada.lovelace, result.reserves.ada.lovelace

    def _query_constitutional_committee(
        self,
    ) -> Optional[ot.QueryLedgerStateConstitutionalCommitteeResultValue]:
        return self.client.ledger_state.constitutional_committee()

    def _query_operational_certificates(self) -> Dict[str, int]:
        """Get every stake pool's operational certificate counter, by pool ID."""
        return self.client.ledger_state.operational_certificates()

    def _query_delegate_representatives(
        self,
        keys: Optional[List[str]] = None,
        scripts: Optional[List[str]] = None,
    ) -> List[Any]:
        """Get the registered DRep summaries, optionally filtered.

        Args:
            keys (Optional[List[str]]): Verification key hashes to filter on,
                hex encoded.
            scripts (Optional[List[str]]): Script hashes to filter on, hex
                encoded.

        Returns:
            List[Any]: One summary per DRep. With no filter this is every
            registered DRep plus the two predefined options; the predefined
            options are returned whether or not a filter is given.
        """
        return self.client.ledger_state.delegate_representatives(keys=keys or None, scripts=scripts or None)

    def _query_governance_proposals(
        self, proposals: Optional[List[Dict[str, Any]]] = None
    ) -> List[ot.GovernanceProposalState]:
        """Get the active governance proposals with their votes, optionally filtered."""
        return self.client.ledger_state.governance_proposals(proposals=proposals)

    def _query_utxos_by_address(self, address: str) -> List[ot.UtxoItem]:
        return self.client.ledger_state.utxo(addresses=[address])

    def _query_utxos_by_tx_id(self, tx_id: str, index: int) -> List[ot.UtxoItem]:
        return self.client.ledger_state.utxo(output_references=[{"transaction": {"id": tx_id}, "index": index}])

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

    # -- Protocol and genesis parameters ----------------------------------

    @property
    def protocol_param(self) -> PyCardanoProtocolParameters:
        if not self._protocol_param or self._is_chain_tip_updated():
            self._protocol_param = self._fetch_protocol_param()
        return self._protocol_param.to_pycardano()

    def _fetch_protocol_param(self) -> ProtocolParameters:
        return self._protocol_param_from_ogmios(self.client.ledger_state.protocol_parameters())

    @classmethod
    def _protocol_param_from_ogmios(cls, params: ot.ProtocolParameters) -> ProtocolParameters:
        """Convert Ogmios v7 protocol parameters to pccontext's model.

        Ratios are kept as exact fractions. The reference-script fee and size
        limit are passed through in the ``{"range", "base", "multiplier"}`` and
        ``{"bytes"}`` shapes pycardano prices reference scripts from.
        """
        dvt = params.delegate_representative_voting_thresholds
        pvt = params.stake_pool_voting_thresholds
        prices = params.script_execution_prices
        tx_units = params.max_execution_units_per_transaction
        block_units = params.max_execution_units_per_block
        ref_fee = params.min_fee_reference_scripts
        ref_size = params.max_reference_scripts_size_per_transaction

        # pycardano reads these two as mappings; see ProtocolParameters.to_pycardano.
        max_reference_scripts_size: Any = {"bytes": ref_size.bytes} if ref_size else None
        min_fee_reference_scripts: Any = (
            {
                "range": ref_fee.range,
                "base": ref_fee.base,
                "multiplier": ref_fee.multiplier,
            }
            if ref_fee
            else None
        )
        decentralization_param: Any = (
            Fraction(params.federated_block_production_ratio) if params.federated_block_production_ratio else None
        )

        return ProtocolParameters(
            collateral_percent=params.collateral_percentage,
            committee_max_term_length=params.constitutional_committee_max_term_length,
            committee_min_size=params.constitutional_committee_min_size,
            cost_models=cls._parse_cost_models(params.plutus_cost_models),
            d_rep_activity=params.delegate_representative_max_idle_time,
            d_rep_deposit=cls._ada(params.delegate_representative_deposit),
            dvt_motion_no_confidence=cls._ratio_to_float(dvt.no_confidence if dvt else None),
            dvt_committee_normal=cls._ratio_to_float(dvt.constitutional_committee.default if dvt else None),
            dvt_committee_no_confidence=cls._ratio_to_float(
                dvt.constitutional_committee.state_of_no_confidence if dvt else None
            ),
            dvt_update_to_constitution=cls._ratio_to_float(dvt.constitution if dvt else None),
            dvt_hard_fork_initiation=cls._ratio_to_float(dvt.hard_fork_initiation if dvt else None),
            dvt_p_p_network_group=cls._ratio_to_float(dvt.protocol_parameters_update.network if dvt else None),
            dvt_p_p_economic_group=cls._ratio_to_float(dvt.protocol_parameters_update.economic if dvt else None),
            dvt_p_p_technical_group=cls._ratio_to_float(dvt.protocol_parameters_update.technical if dvt else None),
            dvt_p_p_gov_group=cls._ratio_to_float(dvt.protocol_parameters_update.governance if dvt else None),
            dvt_treasury_withdrawal=cls._ratio_to_float(dvt.treasury_withdrawals if dvt else None),
            pvt_motion_no_confidence=cls._ratio_to_float(pvt.no_confidence if pvt else None),
            pvt_committee_normal=cls._ratio_to_float(pvt.constitutional_committee.default if pvt else None),
            pvt_committee_no_confidence=cls._ratio_to_float(
                pvt.constitutional_committee.state_of_no_confidence if pvt else None
            ),
            pvt_hard_fork_initiation=cls._ratio_to_float(pvt.hard_fork_initiation if pvt else None),
            pvt_pp_security_group=cls._ratio_to_float(pvt.protocol_parameters_update.security if pvt else None),
            gov_action_deposit=cls._ada(params.governance_action_deposit),
            gov_action_lifetime=params.governance_action_lifetime,
            max_block_size=params.max_block_body_size.bytes,
            max_tx_size=(params.max_transaction_size.bytes if params.max_transaction_size else None),
            max_block_header_size=params.max_block_header_size.bytes,
            max_block_ex_mem=block_units.memory if block_units else None,
            max_block_ex_steps=block_units.cpu if block_units else None,
            max_collateral_inputs=params.max_collateral_inputs,
            max_reference_scripts_size=max_reference_scripts_size,
            min_fee_ref_script_cost_per_byte=min_fee_reference_scripts,
            min_fee_constant=params.min_fee_constant.ada.lovelace,
            min_fee_coefficient=params.min_fee_coefficient,
            min_pool_cost=params.min_stake_pool_cost.ada.lovelace,
            min_utxo_deposit_constant=params.min_utxo_deposit_constant.ada.lovelace,
            key_deposit=params.stake_credential_deposit.ada.lovelace,
            pool_deposit=params.stake_pool_deposit.ada.lovelace,
            pool_retire_max_epoch=params.stake_pool_retirement_epoch_bound,
            pool_target_num=params.desired_number_of_stake_pools,
            pool_influence=Fraction(params.stake_pool_pledge_influence),  # type: ignore[arg-type]
            monetary_expansion=Fraction(params.monetary_expansion),  # type: ignore[arg-type]
            treasury_expansion=Fraction(params.treasury_expansion),  # type: ignore[arg-type]
            decentralization_param=decentralization_param,
            extra_entropy=params.extra_entropy,
            protocol_major_version=params.version.major,
            protocol_minor_version=params.version.minor,
            min_utxo=None,  # type: ignore[arg-type]
            price_mem=Fraction(prices.memory) if prices else None,  # type: ignore[arg-type]
            price_step=Fraction(prices.cpu) if prices else None,  # type: ignore[arg-type]
            max_tx_ex_mem=tx_units.memory if tx_units else None,
            max_tx_ex_steps=tx_units.cpu if tx_units else None,
            max_val_size=params.max_value_size.bytes if params.max_value_size else None,
            coins_per_utxo_word=ALONZO_COINS_PER_UTXO_WORD,
            coins_per_utxo_byte=params.min_utxo_deposit_coefficient,
        )

    @property
    def genesis_param(self) -> PyCardanoGenesisParameters:
        """The Shelley genesis parameters, fetched once and cached.

        ``system_start`` is in unix seconds and ``slot_length`` in seconds, as
        pycardano expects.
        """
        if not self._genesis_param:
            self._genesis_param = self._fetch_genesis_param()

            # Update the refetch interval if we haven't calculated it yet
            if (
                self._refetch_chain_tip_interval == DEFAULT_REFETCH_INTERVAL
                and self._genesis_param.slot_length is not None
                and self._genesis_param.active_slots_coefficient is not None
            ):
                self._refetch_chain_tip_interval = self._genesis_param.slot_length / float(
                    self._genesis_param.active_slots_coefficient
                )
        return self._genesis_param.to_pycardano()

    def _fetch_genesis_param(self) -> GenesisParameters:
        genesis = self.client.network.genesis_configuration(era="shelley")
        if not isinstance(genesis, ot.GenesisShelley):
            raise OgmiosError(f"Expected the Shelley genesis, got: {genesis!r:.200}")
        return self._genesis_param_from_ogmios(genesis)

    @staticmethod
    def _genesis_param_from_ogmios(genesis: ot.GenesisShelley) -> GenesisParameters:
        """Convert Ogmios' Shelley genesis configuration to pccontext's model."""
        slot_length = Fraction(genesis.slot_length.milliseconds, 1000)
        return GenesisParameters(
            active_slots_coefficient=Fraction(genesis.active_slots_coefficient),
            update_quorum=genesis.update_quorum,
            max_lovelace_supply=genesis.max_lovelace_supply,
            network_magic=genesis.network_magic,
            epoch_length=genesis.epoch_length,
            system_start=genesis.start_time,
            slots_per_kes_period=genesis.slots_per_kes_period,
            slot_length=(
                int(slot_length) if slot_length.denominator == 1 else float(slot_length)  # type: ignore[arg-type]
            ),
            max_kes_evolutions=genesis.max_kes_evolutions,
            security_param=genesis.security_parameter,
        )

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
        return 0 if isinstance(tip, str) else tip.slot

    # -- UTxOs ------------------------------------------------------------

    def _utxos(self, address: str) -> List[UTxO]:
        key = (self.last_block_slot, address)
        if key in self._utxo_cache:
            return self._utxo_cache[key]

        utxos = self._utxos_ogmios(address)

        self._utxo_cache[key] = utxos

        return utxos

    def _check_utxo_unspent(self, tx_id: str, index: int) -> bool:
        results = self._query_utxos_by_tx_id(tx_id, index)
        return len(results) > 0

    def _utxos_ogmios(self, address: str) -> List[UTxO]:
        """Get all UTxOs associated with an address with Ogmios.

        Args:
            address (str): An address encoded with bech32.

        Returns:
            List[UTxO]: A list of UTxOs.
        """
        return [self._utxo_from_ogmios_result(result) for result in self._query_utxos_by_address(address)]

    @classmethod
    def _utxo_from_ogmios_result(cls, utxo: ot.UtxoItem) -> UTxO:
        """Convert an Ogmios UTxO to a PyCardano UTxO."""
        tx_in = TransactionInput.from_primitive([utxo.transaction.id, utxo.index])
        lovelace_amount = utxo.value.ada.lovelace

        multi_assets = MultiAsset()
        for policy_hex, tokens in (utxo.value.model_extra or {}).items():
            policy = ScriptHash.from_primitive(policy_hex)
            for token_name_hex, quantity in tokens.items():
                token_name = AssetName.from_primitive(token_name_hex)
                multi_assets.setdefault(policy, Asset())[token_name] = quantity

        # An output carries either an inline datum or the hash of one, never both.
        datum = RawCBOR(bytes.fromhex(utxo.datum)) if utxo.datum else None
        datum_hash = DatumHash.from_primitive(utxo.datum_hash) if utxo.datum_hash and datum is None else None

        tx_out = TransactionOutput(
            Address.from_primitive(utxo.address),
            amount=(Value(lovelace_amount, multi_assets) if multi_assets else lovelace_amount),
            datum_hash=datum_hash,
            datum=datum,
            script=cls._script_from_ogmios(utxo.script) if utxo.script else None,
        )
        return UTxO(tx_in, tx_out)

    @classmethod
    def _script_from_ogmios(
        cls, script: Union[ot.Native, ot.Plutus]
    ) -> Union[NativeScript, PlutusV1Script, PlutusV2Script, PlutusV3Script]:
        """Convert an Ogmios script to a PyCardano script.

        Raises:
            OgmiosError: For a script language pycardano cannot represent yet
                (Plutus v4) or a native script using the Dijkstra ``guard``
                clause.
        """
        if script.language == "native":
            return cls._native_script_from_ogmios(script.json_)
        plutus_scripts = {
            "plutus:v1": PlutusV1Script,
            "plutus:v2": PlutusV2Script,
            "plutus:v3": PlutusV3Script,
        }
        plutus_script = plutus_scripts.get(script.language)
        if plutus_script is None:
            raise OgmiosError(f"Unsupported script language {script.language!r}: pycardano has no type for it yet.")
        return plutus_script(bytes.fromhex(script.cbor))

    @classmethod
    def _native_script_from_ogmios(cls, clause: Any) -> NativeScript:
        """Convert an Ogmios native script (its JSON clause tree) to PyCardano.

        Ogmios' ``after`` is the slot a script becomes valid from (pycardano's
        :class:`InvalidBefore`) and ``before`` the slot it stops being valid at
        (:class:`InvalidHereAfter`).

        Raises:
            OgmiosError: For the Dijkstra ``guard`` clause, which pycardano
                cannot represent yet.
        """
        kind = clause.clause
        if kind == "signature":
            return ScriptPubkey(VerificationKeyHash(bytes.fromhex(clause.from_)))
        if kind == "all":
            return ScriptAll([cls._native_script_from_ogmios(c) for c in clause.from_])
        if kind == "any":
            return ScriptAny([cls._native_script_from_ogmios(c) for c in clause.from_])
        if kind == "some":
            return ScriptNofK(
                clause.at_least,
                [cls._native_script_from_ogmios(c) for c in clause.from_],
            )
        if kind == "after":
            return InvalidBefore(clause.slot)
        if kind == "before":
            return InvalidHereAfter(clause.slot)
        raise OgmiosError(f"Unsupported native script clause {kind!r}: pycardano has no type for it yet.")

    def utxo_by_tx_id(self, tx_id: str, index: int) -> Optional[UTxO]:
        utxos = self._query_utxos_by_tx_id(tx_id, index)
        if len(utxos) > 0:
            return self._utxo_from_ogmios_result(utxos[0])
        return None

    # -- Transactions -----------------------------------------------------

    def submit_tx_cbor(self, cbor: Union[bytes, str]) -> str:
        """Submit a signed transaction.

        Returns:
            str: The id of the submitted transaction.

        Raises:
            pyogmios.errors.SubmitTransactionError: A subclass for the ledger
                rule the transaction broke, with the ledger's details.
        """
        result = self.client.submit_transaction(cbor)
        return result.transaction.id

    def evaluate_tx_cbor(self, cbor: Union[bytes, str]) -> Dict[str, ExecutionUnits]:
        """Evaluate the execution units each of a transaction's redeemers needs.

        Returns:
            Dict[str, ExecutionUnits]: Units keyed ``"<tag>:<index>"`` with
            pycardano's redeemer tag names (``spend``, ``mint``,
            ``certificate``, ``withdrawal``, ``voting``, ``proposing``).

        Raises:
            pyogmios.errors.EvaluateTransactionError: If a script fails.
            OgmiosError: For a Dijkstra ``guard`` redeemer, which pycardano
                has no tag for yet.
        """
        result_dict = {}
        for result in self.client.evaluate_transaction(cbor):
            purpose = result.validator.purpose
            tag = REDEEMER_PURPOSES.get(purpose)
            if tag is None:
                raise OgmiosError(
                    f"Unsupported redeemer purpose {purpose!r}: pycardano has no redeemer tag for it yet."
                )
            result_dict[f"{tag}:{result.validator.index}"] = ExecutionUnits(
                mem=result.budget.memory,
                steps=result.budget.cpu,
            )
        return result_dict

    @staticmethod
    def _parse_cost_models(plutus_cost_models: Optional[Mapping[Any, List[int]]]):
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

        Backed by ``queryLedgerState/rewardAccountSummaries``. An address that
        is not registered gives an empty list.

        Args:
            stake_address (str): The stake address, bech32 encoded.

        Returns:
            List[StakeAddressInfo]: The stake address information.
            ``delegate_representative`` is the CIP-129 DRep id the address
            delegates its vote to, or ``drep_always_abstain`` /
            ``drep_always_no_confidence``.
        """
        staking_part = Address.from_primitive(stake_address).staking_part
        if isinstance(staking_part, ScriptHash):
            results = self.client.ledger_state.reward_account_summaries(scripts=[stake_address])
        else:
            results = self.client.ledger_state.reward_account_summaries(keys=[stake_address])

        return [
            StakeAddressInfo(
                address=stake_address,
                delegation_deposit=result.deposit.ada.lovelace,
                stake_delegation=result.stake_pool.id if result.stake_pool else None,
                reward_account_balance=result.rewards.ada.lovelace,
                delegate_representative=self._drep_id(result.delegate_representative),
            )
            for result in results
        ]

    @classmethod
    def _drep_id(cls, delegate: Any) -> Optional[str]:
        """The bech32 id of a reward account's vote delegation, if any."""
        if delegate is None:
            return None
        drep = cls._drep_from_summary(delegate)
        return drep.encode() if drep is not None else None

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
            return Era(self._query_current_era())
        except (ValueError, OgmiosError):
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
        tip = self._query_chain_tip()

        if isinstance(tip, str):  # "origin"
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
        return [PoolOperator.from_primitive(pool_id) for pool_id in self._query_stake_pools()]

    def stake_pool_info(self, pool_id: str, strict: bool = False) -> StakePoolInfo:
        """Get a stake pool's registered parameters and stake figures.

        The registered parameters come from ``queryLedgerState/stakePools``, and
        the stake figures from ``queryLedgerState/stakePoolsPerformances``,
        which reports the epoch's stake snapshot per pool. A pool that
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
            OgmiosError: If the pool is not registered.
        """
        params = self._query_stake_pools([pool_id]).get(pool_id)
        if params is None:
            raise OgmiosError(f"Stake pool not found: {pool_id}")

        active_stake: Optional[int] = None
        active_size: Optional[Decimal] = None
        owner_stake: Optional[int] = None

        # The performances query is heavier than the pool parameters and is
        # unavailable on a node that has not yet reached a stake snapshot.
        # Report the registered parameters without stake figures in that case
        # rather than failing the whole call.
        try:
            performances: Optional[ot.StakePoolsPerformances] = self._query_stake_pools_performances()
        except Exception:
            performances = None

        summary = performances.stake_pools.get(pool_id) if performances else None
        if performances is not None and summary is not None:
            active_stake = summary.stake.ada.lovelace
            owner_stake = summary.owner_stake.ada.lovelace
            total_stake = performances.active_stake_in_epoch.ada.lovelace
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
                "Ogmios reports operational certificate counters by pool ID, so a pool operator must be provided."
            )

        pool_id = pool.encode()
        counters = self._query_operational_certificates()
        if pool_id not in counters:
            raise OgmiosError(f"No operational certificate counter found for pool: {pool_id}")

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
        ``queryLedgerState/epoch`` call.

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
                if summary.type == predefined:
                    return DRepInfo(
                        drep=drep,
                        active=True,
                        stake=summary.stake.ada.lovelace,
                        status=DRepStatus.REGISTERED,
                    )
            raise OgmiosError(f"Ogmios did not report the {predefined} delegate representative.")

        if drep.credential is None:
            raise OgmiosError(f"DRep carries no credential to look up: {drep.kind}")

        credential = drep.credential.payload.hex()
        if drep.kind == DRepKind.SCRIPT_HASH:
            summaries = self._query_delegate_representatives(scripts=[credential])
        else:
            summaries = self._query_delegate_representatives(keys=[credential])

        for summary in summaries:
            # The predefined options come back alongside the filtered results.
            if summary.type != "registered" or summary.id != credential:
                continue
            return self._drep_info_from_summary(drep, summary, self.epoch)

        return DRepInfo(drep=drep, active=False, stake=0, status=DRepStatus.NOT_REGISTERED)

    def gov_action_info(self, gov_action_id: GovActionId) -> GovActionInfo:
        """Get the lifecycle information for a governance action.

        Backed by ``queryLedgerState/governanceProposals``, filtered on the
        action's reference.

        Args:
            gov_action_id (GovActionId): The action's identifier.

        Returns:
            GovActionInfo: The action's information. ``gov_action`` carries
            Ogmios' own ``action`` object, as the JSON Ogmios sent, rather than
            a parsed pycardano action: Ogmios describes an action as JSON keyed
            by governance type, which does not map onto pycardano's action
            classes without guessing. ``ratified_epoch``, ``enacted_epoch``,
            ``dropped_epoch`` and ``expired_epoch`` are always unset — this
            query returns only proposals that are still live, so a resolved
            action is absent rather than annotated, and
            :attr:`GovActionInfo.status` is always ``None`` here.

        Raises:
            OgmiosError: If the action is not among the active proposals.
        """
        proposal = self._find_proposal(gov_action_id)
        return GovActionInfo(
            gov_action_id=gov_action_id,
            gov_action=self._to_json(proposal.action),
            proposed_in=proposal.since.epoch,
            expires_after=proposal.until.epoch,
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
        """
        return [self._gov_action_votes(proposal) for proposal in self._query_governance_proposals()]

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
            OgmiosError: If neither credential is given, or if no member
                matches.
        """
        if cold is None and hot is None:
            raise OgmiosError("Either a cold or a hot committee credential must be given.")

        committee = self._query_constitutional_committee()
        for raw_member in committee.members if committee else []:
            member = self._committee_member_from_ogmios(raw_member)
            if cold is not None and member.cold_credential != cold:
                continue
            if hot is not None and member.hot_credential != hot:
                continue
            return member

        raise OgmiosError(f"Committee member not found for credential: {cold if cold else hot}")

    def committee_state(self) -> CommitteeStateInfo:
        """Get the full constitutional committee state.

        Backed by ``queryLedgerState/constitutionalCommittee``.

        Returns:
            CommitteeStateInfo: Every member with its cold-to-hot authorization
            and term expiration, plus the quorum threshold. The threshold is
            ``None`` when Ogmios reports none, which is how a committee defined
            in the Conway genesis file can appear, and the member list is empty
            when there is no committee at all.
        """
        committee = self._query_constitutional_committee()
        if committee is None:
            return CommitteeStateInfo(members=[], threshold=None)
        return CommitteeStateInfo(
            members=[self._committee_member_from_ogmios(member) for member in committee.members],
            threshold=self._ratio_to_float(committee.quorum),
        )

    # -- Stake distributions ----------------------------------------------

    def drep_stake_distribution(self) -> List[DRepStakeEntry]:
        """Get the stake delegated to each DRep this epoch.

        Backed by an unfiltered ``queryLedgerState/delegateRepresentatives``,
        whose ``stake`` field is the DRep's voting power in lovelace.

        Returns:
            List[DRepStakeEntry]: One entry per registered DRep, plus one each
            for the always-abstain and always-no-confidence options, which the
            ledger tracks as stake pots of their own.
        """
        entries = []
        for summary in self._query_delegate_representatives():
            drep = self._drep_from_summary(summary)
            if drep is None:
                continue
            entries.append(DRepStakeEntry(drep=drep, stake=summary.stake.ada.lovelace))
        return entries

    def spo_stake_distribution(self) -> List[SPOStakeEntry]:
        """Get the stake delegated to each stake pool this epoch.

        Backed by ``queryLedgerState/stakePoolsPerformances``, which reports
        each pool's stake for the ongoing epoch in lovelace.
        ``queryLedgerState/liveStakeDistribution`` is not used here: it reports
        each pool's share as a ratio of the total, not an amount.

        Returns:
            List[SPOStakeEntry]: One entry per pool.
        """
        stake_pools = self._query_stake_pools_performances().stake_pools
        return [
            SPOStakeEntry(pool_id=pool_id, stake=summary.stake.ada.lovelace) for pool_id, summary in stake_pools.items()
        ]

    # -- Parsing helpers --------------------------------------------------

    @staticmethod
    def _ratio_to_float(ratio: Optional[str]) -> Optional[float]:
        """Convert an Ogmios ``"numerator/denominator"`` ratio to a float."""
        if not ratio:
            return None
        return float(Fraction(ratio))

    @staticmethod
    def _ada(value: Optional[Any]) -> Optional[int]:
        """Read the lovelace of an optional Ogmios ``{"ada": {"lovelace": n}}``."""
        return value.ada.lovelace if value is not None else None

    @staticmethod
    def _to_json(model: Any) -> Any:
        """A pyogmios model as the JSON Ogmios sent (camelCase, unset fields left out)."""
        return model.model_dump(mode="json", by_alias=True, exclude_unset=True)

    @staticmethod
    def _relay_from_ogmios(relay: Any) -> Relay:
        """Convert an Ogmios relay entry to a PyCardano relay."""
        if relay.type == "ipAddress":
            return SingleHostAddr(port=relay.port, ipv4=relay.ipv4, ipv6=relay.ipv6)
        if relay.type == "hostname":
            # Ogmios collapses both name-based relays onto one shape. The SRV
            # record of a multi-host relay is the one without a port.
            if relay.port is None:
                return MultiHostName(dns_name=relay.hostname)
            return SingleHostName(port=relay.port, dns_name=relay.hostname)
        raise OgmiosError(f"Unknown stake pool relay type: {relay.type}")

    @classmethod
    def _pool_params_from_ogmios(cls, pool_id: str, params: ot.StakePoolView) -> PoolParams:
        """Convert an Ogmios stake pool entry to PyCardano pool parameters."""
        if params.vrf_verification_key_hash is None or params.margin is None or params.reward_account is None:
            raise OgmiosError(f"Incomplete parameters for stake pool: {pool_id}")
        metadata = params.metadata
        pool_metadata = (
            PoolMetadata(
                url=metadata.url,
                pool_metadata_hash=PoolMetadataHash(bytes.fromhex(metadata.hash)),
            )
            if metadata
            else None
        )
        reward_account = Address.from_primitive(params.reward_account)

        return PoolParams(
            operator=PoolOperator.from_primitive(pool_id).pool_key_hash,
            vrf_keyhash=VrfKeyHash(bytes.fromhex(params.vrf_verification_key_hash)),
            pledge=cls._ada(params.pledge),
            cost=cls._ada(params.cost),
            margin=Fraction(params.margin),
            reward_account=RewardAccountHash(bytes(reward_account.to_primitive())),
            pool_owners=[VerificationKeyHash(bytes.fromhex(owner)) for owner in params.owners or []],
            relays=[cls._relay_from_ogmios(relay) for relay in params.relays or []],
            pool_metadata=pool_metadata,
        )

    @staticmethod
    def _credential_payload(entry: Any) -> Union[ScriptHash, VerificationKeyHash]:
        """Build a credential hash from an Ogmios ``{id, from}`` pair."""
        payload = bytes.fromhex(entry.id)
        if entry.from_ == "script":
            return ScriptHash(payload)
        return VerificationKeyHash(payload)

    @classmethod
    def _committee_member_from_ogmios(cls, member: ot.ConstitutionalCommitteeMember) -> CommitteeMemberInfo:
        """Convert an Ogmios constitutional committee member entry."""
        cold_credential = CommitteeColdCredential(credential=cls._credential_payload(member))

        delegate = member.delegate
        hot_credential = (
            CommitteeHotCredential(credential=cls._credential_payload(delegate))
            if delegate.status == "authorized"
            else None
        )

        return CommitteeMemberInfo(
            cold_credential=cold_credential,
            hot_credential=hot_credential,
            expiration=member.mandate.epoch if member.mandate else None,
            status=CommitteeMemberStatus(member.status),
        )

    # -- Governance parsing helpers ---------------------------------------

    @staticmethod
    def _anchor_from_ogmios(value: Optional[ot.Anchor]) -> Optional[Anchor]:
        """Convert Ogmios' ``{"url", "hash"}`` metadata to a PyCardano anchor."""
        if value is None:
            return None
        try:
            return Anchor(url=value.url, data_hash=AnchorDataHash(bytes.fromhex(value.hash)))
        except (AssertionError, ValueError, TypeError):
            # A metadata hash that is not 32 bytes cannot be an anchor.
            return None

    @staticmethod
    def _drep_from_credential(entry: Any) -> DRep:
        """Build a DRep from an Ogmios ``{id, from}`` credential pair."""
        payload = bytes.fromhex(entry.id)
        if entry.from_ == "script":
            return DRep(kind=DRepKind.SCRIPT_HASH, credential=ScriptHash(payload))
        return DRep(
            kind=DRepKind.VERIFICATION_KEY_HASH,
            credential=VerificationKeyHash(payload),
        )

    @classmethod
    def _drep_from_summary(cls, summary: Any) -> Optional[DRep]:
        """Build a DRep from a DRep summary or a reward account's delegation."""
        if summary.type == "abstain":
            return DRep(kind=DRepKind.ALWAYS_ABSTAIN)
        if summary.type == "noConfidence":
            return DRep(kind=DRepKind.ALWAYS_NO_CONFIDENCE)
        if summary.type == "registered":
            return cls._drep_from_credential(summary)
        return None

    @classmethod
    def _drep_info_from_summary(
        cls,
        drep: DRep,
        summary: ot.DelegateRepresentativeSummaryRegistered,
        current_epoch: int,
    ) -> DRepInfo:
        """Convert a registered ``delegateRepresentatives`` entry to a DRepInfo."""
        expiry = summary.mandate.epoch
        return DRepInfo(
            drep=drep,
            active=current_epoch <= expiry,
            anchor=cls._anchor_from_ogmios(summary.metadata),
            deposit=summary.deposit.ada.lovelace,
            stake=summary.stake.ada.lovelace,
            expiry=expiry,
            status=DRepStatus.REGISTERED,
        )

    @staticmethod
    def _proposal_gov_action_id(proposal: ot.GovernanceProposalState) -> GovActionId:
        """Read the action id from a proposal's ``proposal`` reference."""
        return GovActionId(
            transaction_id=TransactionId(bytes.fromhex(proposal.proposal.transaction.id)),
            gov_action_index=proposal.proposal.index,
        )

    def _find_proposal(self, gov_action_id: GovActionId) -> ot.GovernanceProposalState:
        """Find one active proposal by its action id.

        Raises:
            OgmiosError: If no active proposal carries that id.
        """
        reference = {
            "transaction": {"id": str(gov_action_id.transaction_id)},
            "index": gov_action_id.gov_action_index,
        }
        for proposal in self._query_governance_proposals(proposals=[reference]):
            if self._proposal_gov_action_id(proposal) == gov_action_id:
                return proposal
        raise OgmiosError(
            "Governance action not found among the active proposals: "
            f"{gov_action_id.transaction_id}#{gov_action_id.gov_action_index}"
        )

    @staticmethod
    def _parse_vote(value: str) -> Optional[Vote]:
        """Parse Ogmios' spelling of a vote."""
        return {"yes": Vote.YES, "no": Vote.NO, "abstain": Vote.ABSTAIN}.get(value)

    @classmethod
    def _split_votes(
        cls, raw_votes: Sequence[ot.GovernanceVote]
    ) -> Tuple[List[CommitteeVote], List[DRepVote], List[StakePoolVote]]:
        """Split a proposal's flat vote list by the role of its issuer.

        Genesis delegate votes are dropped: they are a pre-Conway construct with
        no place in any of the three voter classes the models keep.
        """
        committee: List[CommitteeVote] = []
        dreps: List[DRepVote] = []
        pools: List[StakePoolVote] = []

        for raw in raw_votes:
            issuer = raw.issuer
            vote = cls._parse_vote(raw.vote)
            anchor = cls._anchor_from_ogmios(raw.metadata)

            if issuer.role == "constitutionalCommittee":
                voter = CommitteeHotCredential(cls._credential_payload(issuer))
                committee.append(CommitteeVote(voter=voter, vote=vote, anchor=anchor))
            elif issuer.role == "delegateRepresentative":
                dreps.append(
                    DRepVote(
                        voter=cls._drep_from_credential(issuer),
                        vote=vote,
                        anchor=anchor,
                    )
                )
            elif issuer.role == "stakePoolOperator":
                pools.append(StakePoolVote(voter=issuer.id, vote=vote, anchor=anchor))

        return committee, dreps, pools

    @classmethod
    def _gov_action_votes(cls, proposal: ot.GovernanceProposalState) -> GovActionVotes:
        """Assemble a GovActionVotes from one ``governanceProposals`` entry."""
        committee, dreps, pools = cls._split_votes(proposal.votes)

        return GovActionVotes(
            gov_action_id=cls._proposal_gov_action_id(proposal),
            gov_action=cls._to_json(proposal.action),
            committee_votes=committee,
            drep_votes=dreps,
            stake_pool_votes=pools,
            deposit=proposal.deposit.ada.lovelace,
            deposit_return_addr=proposal.return_account,
            anchor=cls._anchor_from_ogmios(proposal.metadata),
            proposed_in=proposal.since.epoch,
            expires_after=proposal.until.epoch,
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
