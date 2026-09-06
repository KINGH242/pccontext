import contextlib
import hashlib
import os
import tempfile
import time
from decimal import Decimal
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple, Union

import cbor2
import koios_python
import requests
from pycardano import (
    Address,
    Anchor,
    AnchorDataHash,
    Asset,
    AssetName,
    CommitteeColdCredential,
    CommitteeHotCredential,
    DatumHash,
    DRep,
    ExecutionUnits,
    GovActionId,
    MultiAsset,
    MultiHostName,
    NativeScript,
    Network,
    PlutusV1Script,
    PlutusV2Script,
    PlutusV3Script,
    PoolKeyHash,
    PoolMetadata,
    PoolMetadataHash,
    PoolOperator,
    PoolParams,
)
from pycardano import ProtocolParameters as PyCardanoProtocolParameters
from pycardano import (
    RawCBOR,
    Relay,
    RewardAccountHash,
    ScriptHash,
    SingleHostAddr,
    SingleHostName,
    TransactionFailedException,
    TransactionId,
    TransactionInput,
    TransactionOutput,
    UTxO,
    Value,
    VerificationKeyHash,
    Vote,
    VrfKeyHash,
)

__all__ = ["KoiosChainContext"]

from pycardano.types import JsonDict
from requests import RequestException

from pccontext.backend import ChainContext
from pccontext.enums import CommitteeMemberStatus, DRepStatus, Era, PoolStatus
from pccontext.exceptions import PoolMetadataError
from pccontext.logging import logger
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
            utxos.append(self._utxo_from_result(result, address))

        return utxos

    def _utxo_from_result(
        self, result: JsonDict, address: Optional[str] = None
    ) -> UTxO:
        """Build a UTxO from one Koios result row.

        Shared by the address query and the single-UTxO lookup, which return the
        same shape under two spellings of the datum hash key: ``data_hash`` for
        ``/address_utxos`` and ``datum_hash`` for ``/utxo_info``.

        Args:
            result (JsonDict): One Koios UTxO row.
            address (Optional[str]): The queried address. Falls back to the row's
                own ``address`` field, which ``/utxo_info`` supplies.

        Returns:
            UTxO: The resolved UTxO.
        """
        tx_in = TransactionInput.from_primitive([result["tx_hash"], result["tx_index"]])

        # Koios returns lovelace as a string; leaving it that way puts a str
        # in Value.coin, which breaks fee arithmetic in the transaction builder.
        lovelace_amount = int(result["value"])
        multi_assets = MultiAsset()
        for item in result["asset_list"]:
            # The utxo contains Multi-asset
            policy_id = ScriptHash(item["policy_id"])
            asset_name = AssetName(item["asset_name"])

            if policy_id not in multi_assets:
                multi_assets[policy_id] = Asset()
            multi_assets[policy_id][asset_name] = int(item["quantity"])

        amount = Value(lovelace_amount, multi_assets)

        raw_datum_hash = result.get("data_hash") or result.get("datum_hash")
        datum_hash = (
            DatumHash.from_primitive(raw_datum_hash)
            if raw_datum_hash and result.get("inline_datum") is None
            else None
        )

        datum = None

        if result.get("inline_datum") is not None:
            datum = RawCBOR(bytes.fromhex(result["inline_datum"]))

        script = None

        if result.get("reference_script"):
            script = self._get_script(result["reference_script"])

        tx_out = TransactionOutput(
            Address.from_primitive(address or result["address"]),
            amount=amount,
            datum_hash=datum_hash,
            datum=datum,
            script=script,
        )
        return UTxO(tx_in, tx_out)

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

    @property
    def era(self) -> Optional[Era]:
        """Current Cardano era, as reported by the chain tip."""
        raw = self._query_chain_tip().get("era")
        if not raw:
            return None
        try:
            return Era(str(raw).lower())
        except ValueError:
            return None

    @property
    def chain_tip(self) -> ChainTip:
        """Get the current chain tip.

        Returns:
            ChainTip: The slot, block hash, height, epoch and era of the latest
            block.
        """
        try:
            return ChainTip.from_json(self._query_chain_tip())
        except RequestException as e:
            logger.error(f"Failed to get the chain tip. Error: {e}")
            raise

    def utxo(self, tx_input: TransactionInput) -> Optional[Tuple[UTxO, bool]]:
        """Resolve a single UTxO by the transaction input that identifies it.

        Args:
            tx_input (TransactionInput): The transaction hash and output index.

        Returns:
            Optional[Tuple[UTxO, bool]]: The UTxO and whether it has been spent,
            or ``None`` if Koios does not know it. Koios tracks spent outputs, so
            unlike a live-UTxO-set backend this can return ``True``.
        """
        reference = f"{tx_input.transaction_id}#{tx_input.index}"
        try:
            results = self.api.get_utxo_info([reference], extended=True)
        except RequestException as e:
            logger.error(f"Failed to get UTxO {reference}. Error: {e}")
            return None

        if not results:
            return None

        result = results[0]
        return self._utxo_from_result(result), bool(result.get("is_spent", False))

    def stake_pools(self) -> List[PoolOperator]:
        """Get every stake pool registered on the chain.

        Returns:
            List[PoolOperator]: The registered pools.
        """
        try:
            results = self.api.get_pool_list()
        except RequestException as e:
            logger.error(f"Failed to get the pool list. Error: {e}")
            raise

        pools = []
        for result in results:
            pool_id_hex = result.get("pool_id_hex")
            if pool_id_hex:
                pools.append(PoolOperator(PoolKeyHash(bytes.fromhex(pool_id_hex))))
        return pools

    @staticmethod
    def _pool_status(result: JsonDict) -> Optional[PoolStatus]:
        """Map Koios' ``pool_status`` string onto :class:`PoolStatus`."""
        raw = result.get("pool_status")
        if not raw:
            return None
        try:
            return PoolStatus(str(raw).lower())
        except ValueError:
            return None

    def _verify_pool_metadata(self, result: JsonDict) -> None:
        """Fetch a pool's off-chain metadata and check it against the registered hash.

        Raises:
            :class:`PoolMetadataError`: If the metadata cannot be fetched or its
                hash does not match the one registered on-chain.
        """
        url = result.get("meta_url")
        expected = result.get("meta_hash")
        if not url or not expected:
            raise PoolMetadataError(
                "Pool has no off-chain metadata registered, so it cannot be verified."
            )

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
        except RequestException as e:
            raise PoolMetadataError(
                f"Failed to fetch pool metadata from {url}. Error: {e}"
            )

        actual = hashlib.blake2b(response.content, digest_size=32).hexdigest()
        if actual != expected:
            raise PoolMetadataError(
                f"Pool metadata hash mismatch for {url}: "
                f"registered {expected}, computed {actual}."
            )

    def stake_pool_info(self, pool_id: str, strict: bool = False) -> StakePoolInfo:
        """Get a stake pool's registered parameters and stake figures.

        Args:
            pool_id (str): The pool's ID, bech32 encoded.
            strict (bool): When ``True``, the pool's off-chain metadata is
                fetched and its hash verified, and any failure is raised. When
                ``False`` (the default) metadata problems are tolerated so the
                on-chain parameters are still returned.

        Returns:
            StakePoolInfo: The pool's information.

        Raises:
            :class:`PoolMetadataError`: When ``strict`` and the metadata cannot
                be verified.
        """
        try:
            results = self.api.get_pool_info(pool_id)
        except RequestException as e:
            logger.error(f"Failed to get info for pool {pool_id}. Error: {e}")
            raise

        if not results or not isinstance(results, list):
            raise ValueError(f"Pool {pool_id} was not found.")

        result = results[0]

        if strict:
            self._verify_pool_metadata(result)

        pool_metadata = None
        if result.get("meta_url") and result.get("meta_hash"):
            pool_metadata = PoolMetadata(
                url=result["meta_url"],
                pool_metadata_hash=PoolMetadataHash(bytes.fromhex(result["meta_hash"])),
            )

        pool_params = None
        if result.get("pool_id_hex") and result.get("vrf_key_hash"):
            pool_params = PoolParams(
                operator=PoolKeyHash(bytes.fromhex(result["pool_id_hex"])),
                vrf_keyhash=VrfKeyHash(bytes.fromhex(result["vrf_key_hash"])),
                pledge=self._as_int(result.get("pledge")) or 0,
                cost=self._as_int(result.get("fixed_cost")) or 0,
                margin=Fraction(str(result.get("margin") or 0)).limit_denominator(),
                reward_account=RewardAccountHash(
                    bytes(Address.decode(result["reward_addr"]).to_primitive())
                ),
                pool_owners=[
                    VerificationKeyHash(
                        bytes(Address.decode(owner).staking_part.payload)
                    )
                    for owner in (result.get("owners") or [])
                ],
                relays=[self._relay(r) for r in (result.get("relays") or [])],
                pool_metadata=pool_metadata,
            )

        # Koios reports `sigma` as the pool's share of active stake. It has no
        # equivalent for live stake, so live_size stays None rather than being
        # computed from a total this endpoint does not return.
        return StakePoolInfo(
            pool_params=pool_params,
            live_pledge=self._as_int(result.get("live_pledge")),
            live_stake=self._as_int(result.get("live_stake")),
            active_stake=self._as_int(result.get("active_stake")),
            active_size=(
                Decimal(str(result["sigma"]))
                if result.get("sigma") is not None
                else None
            ),
            opcert_counter=self._as_int(result.get("op_cert_counter")),
            status=self._pool_status(result),
            retiring_epoch=self._as_int(result.get("retiring_epoch")),
        )

    @staticmethod
    def _relay(relay: JsonDict) -> Relay:
        """Map one Koios relay entry onto the matching pycardano relay type.

        Koios reports every relay with the same four keys and nulls out the ones
        that do not apply, so the shape is inferred from which are populated.
        """
        port = relay.get("port")
        ipv4, ipv6, dns = relay.get("ipv4"), relay.get("ipv6"), relay.get("dns")
        if ipv4 or ipv6:
            return SingleHostAddr(port=port, ipv4=ipv4, ipv6=ipv6)
        if dns and port is not None:
            return SingleHostName(port=port, dns_name=dns)
        return MultiHostName(dns_name=dns)

    def _require_endpoint(self, name: str, query: str) -> Any:
        """Resolve a koios-python client method, or explain its absence.

        Koios itself has supported these endpoints throughout, but
        ``koios-python`` 2.0.0 wraps none of them. Rather than let the call fail
        with an ``AttributeError`` deep in the client, this reports the standard
        :class:`NotImplementedError` the base class documents, so a caller that
        already handles an unsupported query keeps working.

        Args:
            name (str): The client method to resolve.
            query (str): The chain-context query being served, for the message.

        Returns:
            Any: The bound client method.

        Raises:
            NotImplementedError: When the installed client lacks the endpoint.
        """
        method = getattr(self.api, name, None)
        if not callable(method):
            raise NotImplementedError(
                f"{query} is not implemented for {self.name}: the installed "
                f"koios-python has no {name}. Koios supports the endpoint; the "
                f"wrapper does not yet."
            )
        return method

    @staticmethod
    def _as_int(value: Any) -> Optional[int]:
        """Koios returns lovelace amounts as strings; normalise to int."""
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def kes_period_info(
        self,
        pool: Optional[PoolOperator] = None,
        op_cert: Optional[Union[bytes, str]] = None,
    ) -> KESPeriodInfo:
        """Get the KES period information for a pool's operational certificate.

        Koios reports the counter registered on-chain. It has no view of a local
        certificate file, so the on-disk counter and KES start period are not
        populated; a `cardano-cli` context can supply those.

        Args:
            pool (Optional[PoolOperator]): The pool operator. Required here,
                since Koios is queried by pool ID.
            op_cert (Optional[Union[bytes, str]]): Unused by this backend.

        Returns:
            KESPeriodInfo: With the on-chain counter and the next counter to use.

        Raises:
            ValueError: If ``pool`` is not given.
        """
        if pool is None:
            raise ValueError(
                "Koios queries KES period information by pool ID, so a pool "
                "operator must be provided."
            )

        # Koios is queried by bech32 pool ID; PoolOperator.encode() produces it.
        pool_id = pool.encode()

        try:
            results = self.api.get_pool_info(pool_id)
        except RequestException as e:
            logger.error(f"Failed to get KES period info for {pool_id}. Error: {e}")
            raise

        if not results or not isinstance(results, list):
            raise ValueError(f"Pool {pool_id} was not found.")

        on_chain = self._as_int(results[0].get("op_cert_counter"))
        return KESPeriodInfo(
            on_chain_op_cert_count=on_chain,
            next_chain_op_cert_count=None if on_chain is None else on_chain + 1,
        )

    def treasury(self) -> int:
        """Get the current treasury balance, in lovelace.

        Returns:
            int: The treasury balance for the current epoch.
        """
        try:
            results = self.api.get_totals(epoch_no=self.epoch)
        except RequestException as e:
            logger.error(f"Failed to get chain totals. Error: {e}")
            raise

        if not results:
            raise ValueError("Koios returned no totals for the current epoch.")

        treasury = self._as_int(results[0].get("treasury"))
        if treasury is None:
            raise ValueError("Koios totals did not include a treasury balance.")
        return treasury

    # -- Governance --------------------------------------------------------

    def drep_info(self, drep: DRep) -> DRepInfo:
        """Get a delegate representative's registration and voting power.

        Args:
            drep (DRep): The DRep to look up.

        Returns:
            DRepInfo: The DRep's information. A DRep Koios does not know is
            reported as ``NOT_REGISTERED`` with zero stake.

        Raises:
            :class:`RequestException`: When the query fails.
        """
        drep_id = drep.encode()
        try:
            results = self._require_endpoint("get_drep_info", "drep_info")(drep_id)
        except RequestException as e:
            logger.error(f"Failed to get info for DRep {drep_id}. Error: {e}")
            raise

        if not results or not isinstance(results, list):
            return DRepInfo(
                drep=drep, active=False, stake=0, status=DRepStatus.NOT_REGISTERED
            )

        result = results[0]
        anchor = None
        if result.get("meta_url") and result.get("meta_hash"):
            anchor = Anchor(
                url=result["meta_url"],
                data_hash=AnchorDataHash(bytes.fromhex(result["meta_hash"])),
            )

        return DRepInfo(
            drep=drep,
            active=bool(result.get("active", False)),
            anchor=anchor,
            deposit=self._as_int(result.get("deposit")),
            stake=self._as_int(result.get("amount")),
            expiry=self._as_int(result.get("expires_epoch_no")),
            status=self._drep_status(result.get("drep_status")),
        )

    @staticmethod
    def _drep_status(raw: Optional[str]) -> Optional[DRepStatus]:
        """Map Koios' ``drep_status`` string onto :class:`DRepStatus`."""
        mapping = {
            "registered": DRepStatus.REGISTERED,
            "active": DRepStatus.REGISTERED,
            "retired": DRepStatus.RETIRED,
            "deregistered": DRepStatus.RETIRED,
        }
        if raw is None:
            return None
        return mapping.get(str(raw).lower(), DRepStatus.NOT_REGISTERED)

    @staticmethod
    def _paginate(query, page_size: int = 1000) -> List[JsonDict]:
        """Collect every page of a Koios list endpoint.

        Koios caps a response at the requested ``Range``, defaulting to 1000
        rows, and returns no total. A short page is therefore the only signal
        that the end has been reached — without this, a distribution silently
        stops at the first 1000 entries.

        Args:
            query: Callable taking a ``content_range`` string and returning one
                page of rows.
            page_size (int): Rows to request per page.

        Returns:
            List[JsonDict]: Every row, in the order Koios returned them.
        """
        rows: List[JsonDict] = []
        start = 0
        while True:
            page = query(f"{start}-{start + page_size - 1}") or []
            rows.extend(page)
            if len(page) < page_size:
                return rows
            start += page_size

    def drep_stake_distribution(self) -> List[DRepStakeEntry]:
        """Get the stake delegated to each DRep this epoch.

        Returns:
            List[DRepStakeEntry]: One entry per DRep with recorded voting power.

        Raises:
            :class:`RequestException`: When the query fails.
        """
        epoch = self.epoch
        try:
            results = self._paginate(
                lambda rng: self._require_endpoint(
                    "get_drep_voting_power_history", "drep_stake_distribution"
                )(epoch_no=epoch, content_range=rng)
            )
        except RequestException as e:
            logger.error(f"Failed to get the DRep stake distribution. Error: {e}")
            raise

        entries = []
        for result in results or []:
            drep = None
            with contextlib.suppress(Exception):
                drep = DRep.decode(result["drep_id"])
            entries.append(
                DRepStakeEntry(drep=drep, stake=self._as_int(result.get("amount")))
            )
        return entries

    def spo_stake_distribution(self) -> List[SPOStakeEntry]:
        """Get the stake delegated to each stake pool this epoch.

        Returns:
            List[SPOStakeEntry]: One entry per pool with recorded voting power.

        Raises:
            :class:`RequestException`: When the query fails.
        """
        epoch = self.epoch
        try:
            results = self._paginate(
                lambda rng: self._require_endpoint(
                    "get_pool_voting_power_history", "spo_stake_distribution"
                )(epoch_no=epoch, content_range=rng)
            )
        except RequestException as e:
            logger.error(f"Failed to get the pool stake distribution. Error: {e}")
            raise

        return [
            SPOStakeEntry(
                pool_id=result.get("pool_id_bech32"),
                stake=self._as_int(result.get("amount")),
            )
            for result in results or []
        ]

    def _committee_member(self, member: JsonDict, epoch: int) -> CommitteeMemberInfo:
        """Build a committee member from one Koios ``committee_info`` member."""
        cold = hot = None
        if member.get("cc_cold_hex"):
            payload = bytes.fromhex(member["cc_cold_hex"])
            cold = CommitteeColdCredential(
                ScriptHash(payload)
                if member.get("cc_cold_has_script")
                else VerificationKeyHash(payload)
            )
        if member.get("cc_hot_hex"):
            payload = bytes.fromhex(member["cc_hot_hex"])
            hot = CommitteeHotCredential(
                ScriptHash(payload)
                if member.get("cc_hot_has_script")
                else VerificationKeyHash(payload)
            )

        expiration = self._as_int(member.get("expiration_epoch"))
        # Koios reports "authorized" or "resigned". A term runs to the end of
        # its expiration epoch, so a member is EXPIRED only once the chain is
        # past that epoch — during it they are still serving. An authorised
        # member inside its term is ACTIVE; anything else, a resignation
        # included, is not a recognised voter, which is what UNRECOGNIZED means.
        if expiration is not None and expiration < epoch:
            status = CommitteeMemberStatus.EXPIRED
        elif str(member.get("status", "")).lower() == "authorized":
            status = CommitteeMemberStatus.ACTIVE
        else:
            status = CommitteeMemberStatus.UNRECOGNIZED

        return CommitteeMemberInfo(
            cold_credential=cold,
            hot_credential=hot,
            expiration=expiration,
            status=status,
        )

    def committee_state(self) -> CommitteeStateInfo:
        """Get the full constitutional committee state.

        Returns:
            CommitteeStateInfo: Every member with its cold-to-hot authorisation
            and term, plus the quorum threshold Koios reports as a fraction.

        Raises:
            :class:`RequestException`: When the query fails.
        """
        try:
            results = self._require_endpoint("get_committee_info", "committee_state")()
        except RequestException as e:
            logger.error(f"Failed to get the committee state. Error: {e}")
            raise

        if not results or not isinstance(results, list):
            return CommitteeStateInfo()

        result = results[0]
        epoch = self.epoch
        numerator = self._as_int(result.get("quorum_numerator"))
        denominator = self._as_int(result.get("quorum_denominator"))
        threshold = (
            numerator / denominator if numerator is not None and denominator else None
        )

        return CommitteeStateInfo(
            members=[
                self._committee_member(m, epoch) for m in (result.get("members") or [])
            ],
            threshold=threshold,
        )

    def committee_member_info(
        self,
        cold: Optional[CommitteeColdCredential] = None,
        hot: Optional[CommitteeHotCredential] = None,
    ) -> CommitteeMemberInfo:
        """Get a constitutional committee member's authorisation and term.

        Koios reports the committee as a whole, so this filters that state
        rather than issuing a per-member query.

        Args:
            cold (Optional[CommitteeColdCredential]): The member's cold
                credential. Optional if ``hot`` is given.
            hot (Optional[CommitteeHotCredential]): A hot credential the member
                has authorised. Optional if ``cold`` is given.

        Returns:
            CommitteeMemberInfo: The matching member.

        Raises:
            ValueError: If neither credential is given, or no member matches.
        """
        if cold is None and hot is None:
            raise ValueError("A cold or hot committee credential must be provided.")

        for member in self.committee_state().members:
            if cold is not None and member.cold_credential == cold:
                return member
            if hot is not None and member.hot_credential == hot:
                return member

        raise ValueError("No committee member matched the given credential.")

    def _proposals(self) -> List[JsonDict]:
        """Fetch the governance proposal list.

        Koios has no single-proposal endpoint, so a lookup by id filters this
        list. It is a few hundred rows, which one page covers.
        """
        try:
            return self._paginate(
                lambda rng: self._require_endpoint(
                    "get_proposal_list", "Governance proposal queries"
                )(content_range=rng)
            )
        except RequestException as e:
            logger.error(f"Failed to get the governance proposal list. Error: {e}")
            raise

    @staticmethod
    def _proposal_gov_action_id(proposal: JsonDict) -> Optional[GovActionId]:
        tx_hash = proposal.get("proposal_tx_hash")
        index = proposal.get("proposal_index")
        if not tx_hash or index is None:
            return None
        return GovActionId(
            transaction_id=TransactionId(bytes.fromhex(tx_hash)),
            gov_action_index=int(index),
        )

    def _find_proposal(self, gov_action_id: GovActionId) -> JsonDict:
        encoded = gov_action_id.encode()
        for proposal in self._proposals():
            if proposal.get("proposal_id") == encoded:
                return proposal
        raise ValueError(f"Governance action {encoded} was not found.")

    def gov_action_info(self, gov_action_id: GovActionId) -> GovActionInfo:
        """Get the lifecycle information for a governance action.

        Args:
            gov_action_id (GovActionId): The action's identifier.

        Returns:
            GovActionInfo: The action's information. ``gov_action`` carries
            Koios' own description object rather than a parsed pycardano action,
            since Koios returns the proposal as free-form JSON.

        Raises:
            ValueError: If no proposal matches the identifier.
        """
        proposal = self._find_proposal(gov_action_id)
        return GovActionInfo(
            gov_action_id=gov_action_id,
            gov_action=proposal.get("proposal_description"),
            proposed_in=self._as_int(proposal.get("proposed_epoch")),
            expires_after=self._as_int(proposal.get("expiration")),
            ratified_epoch=self._as_int(proposal.get("ratified_epoch")),
            enacted_epoch=self._as_int(proposal.get("enacted_epoch")),
            dropped_epoch=self._as_int(proposal.get("dropped_epoch")),
            expired_epoch=self._as_int(proposal.get("expired_epoch")),
        )

    def _votes_for(
        self, proposal_id: str
    ) -> Tuple[List[CommitteeVote], List[DRepVote], List[StakePoolVote]]:
        """Fetch and split a proposal's votes by voter role."""
        try:
            raw_votes = (
                self._require_endpoint("get_proposal_votes", "Governance vote queries")(
                    proposal_id
                )
                or []
            )
        except RequestException as e:
            logger.error(f"Failed to get votes for {proposal_id}. Error: {e}")
            raise

        committee: List[CommitteeVote] = []
        dreps: List[DRepVote] = []
        pools: List[StakePoolVote] = []

        for raw in raw_votes:
            role = str(raw.get("voter_role", "")).lower()
            voter_id = raw.get("voter_id")
            try:
                vote = Vote[str(raw.get("vote", "")).upper()]
            except KeyError:
                vote = None

            if role == "constitutionalcommittee":
                committee.append(CommitteeVote(vote=vote))
            elif role == "drep":
                drep = None
                with contextlib.suppress(Exception):
                    drep = DRep.decode(voter_id)
                dreps.append(DRepVote(voter=drep, vote=vote))
            elif role == "spo":
                pools.append(StakePoolVote(voter=voter_id, vote=vote))

        return committee, dreps, pools

    def _gov_action_votes(self, proposal: JsonDict) -> GovActionVotes:
        """Assemble a GovActionVotes from a proposal row plus its votes."""
        committee, dreps, pools = self._votes_for(proposal["proposal_id"])
        anchor = None
        if proposal.get("meta_url") and proposal.get("meta_hash"):
            anchor = Anchor(
                url=proposal["meta_url"],
                data_hash=AnchorDataHash(bytes.fromhex(proposal["meta_hash"])),
            )

        return GovActionVotes(
            gov_action_id=self._proposal_gov_action_id(proposal),
            gov_action=proposal.get("proposal_description"),
            committee_votes=committee,
            drep_votes=dreps,
            stake_pool_votes=pools,
            deposit=self._as_int(proposal.get("deposit")),
            deposit_return_addr=proposal.get("return_address"),
            anchor=anchor,
            proposed_in=self._as_int(proposal.get("proposed_epoch")),
            expires_after=self._as_int(proposal.get("expiration")),
            ratified_epoch=self._as_int(proposal.get("ratified_epoch")),
            enacted_epoch=self._as_int(proposal.get("enacted_epoch")),
            dropped_epoch=self._as_int(proposal.get("dropped_epoch")),
            expired_epoch=self._as_int(proposal.get("expired_epoch")),
        )

    def gov_action_votes(self, gov_action_id: GovActionId) -> GovActionVotes:
        """Get the votes recorded against a governance action, by voter class.

        Args:
            gov_action_id (GovActionId): The action's identifier.

        Returns:
            GovActionVotes: The proposal plus its committee, DRep and stake pool
            votes.

        Raises:
            ValueError: If no proposal matches the identifier.
        """
        return self._gov_action_votes(self._find_proposal(gov_action_id))

    def gov_actions_all(self) -> List[GovActionVotes]:
        """Get every governance proposal with its votes.

        Note:
            Koios returns the proposal list in one request but its votes
            per proposal, so this makes one further request per proposal.

        Returns:
            List[GovActionVotes]: One entry per proposal.
        """
        return [self._gov_action_votes(p) for p in self._proposals()]

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
