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
from pycardano.governance import CommitteeColdCredential, CommitteeHotCredential
from pycardano.hash import (
    DatumHash,
    PoolMetadataHash,
    RewardAccountHash,
    ScriptHash,
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
from pccontext.enums import CommitteeMemberStatus, Era, PoolStatus
from pccontext.exceptions import OgmiosError
from pccontext.models import (
    ChainTip,
    CommitteeMemberInfo,
    CommitteeStateInfo,
    GenesisParameters,
    ProtocolParameters,
    SPOStakeEntry,
    StakeAddressInfo,
    StakePoolInfo,
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
        ``PoolStatus.REGISTERED``; Ogmios reports no retirement epoch, and the
        installed ``ogmios`` client exposes no operational certificate query, so
        ``retiring_epoch`` and ``opcert_counter`` stay ``None``.

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
