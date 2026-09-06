from contextlib import contextmanager
from fractions import Fraction
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Tuple,
    TypeVar,
    Union,
    cast,
)

import cbor2
from pycardano import (
    Anchor,
    AnchorDataHash,
    CommitteeHotCredential,
    DRep,
    DRepKind,
    GovActionId,
    MultiHostName,
    PoolKeyHash,
    PoolMetadata,
    PoolMetadataHash,
    PoolOperator,
    PoolParams,
    Relay,
    RewardAccountHash,
    SingleHostAddr,
    SingleHostName,
    TransactionFailedException,
    TransactionId,
    VerificationKeyHash,
    Vote,
    VrfKeyHash,
)
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
from yaci_client.api.block_service import get_latest_block
from yaci_client.api.d_rep_service import (
    get_d_rep_de_registrations,
    get_d_rep_registrations,
    get_d_rep_updates,
)
from yaci_client.api.gov_action_proposal_service import (
    get_gov_action_proposal_by_tx,
    get_gov_action_proposal_list,
    get_voting_procedures_for_gov_action_proposal,
)
from yaci_client.api.local_epoch_service import (
    get_latest_epoch,
    get_latest_protocol_params,
)
from yaci_client.api.pool_service import get_pool_registrations, get_retirements
from yaci_client.api.script_service import (
    get_script_by_hash,
    get_script_cbor_by_hash,
    get_script_json_by_hash,
)
from yaci_client.api.transaction_service import get_utxo as get_utxo_by_ref
from yaci_client.api.tx_submission_service import submit_tx_1
from yaci_client.api.utilities import evaluate_tx
from yaci_client.errors import UnexpectedStatus
from yaci_client.models import (
    AddressUtxo,
    BlockDto,
    DRepRegistration,
    DRepRegistrationType,
    EpochNo,
    GovActionProposal,
    PoolRegistration,
    PoolRetirement,
    ProtocolParamsDto,
    ScriptCborDto,
    ScriptDto,
    ScriptJsonDto,
    StakeAccountInfo,
    VotingProcedure,
    VotingProcedureVoterType,
)
from yaci_client.types import Unset

from pccontext.backend import ChainContext
from pccontext.enums import DRepStatus, Era, PoolStatus
from pccontext.logging import logger
from pccontext.models import (
    ChainTip,
    CommitteeVote,
    DRepInfo,
    DRepVote,
    GenesisParameters,
    GovActionInfo,
    GovActionVotes,
    ProtocolParameters,
    StakeAddressInfo,
    StakePoolInfo,
    StakePoolVote,
)

__all__ = ["YaciDevkitChainContext"]

_T = TypeVar("_T")

_PAGE_SIZE = 100
"""Rows requested per page from Yaci's paginated list endpoints."""

_MAX_PAGES = 1000
"""Hard stop on pagination, so a misbehaving endpoint cannot loop forever."""

_ERA_BY_INDEX: Dict[int, Era] = {
    1: Era.BYRON,
    2: Era.SHELLEY,
    3: Era.ALLEGRA,
    4: Era.MARY,
    5: Era.ALONZO,
    6: Era.BABBAGE,
    7: Era.CONWAY,
}
"""Yaci reports a block's era as the hard-fork combinator's era index."""


def _opt(value: Union[Unset, _T, None]) -> Optional[_T]:
    """Normalise the generated client's ``UNSET`` sentinel to ``None``.

    Args:
        value (Union[Unset, _T, None]): A field of a generated model.

    Returns:
        Optional[_T]: The value, or ``None`` when the field was absent.
    """
    if isinstance(value, Unset):
        return None
    return value


def _anchor(url: Optional[str], data_hash: Optional[str]) -> Optional[Anchor]:
    """Build an anchor from the URL and hash Yaci reports beside a certificate.

    Args:
        url (Optional[str]): The anchor URL.
        data_hash (Optional[str]): The anchor data hash, hex encoded.

    Returns:
        Optional[Anchor]: The anchor, or ``None`` when either half is missing
        or the hash is not valid hex.
    """
    if not url or not data_hash:
        return None
    try:
        return Anchor(url=url, data_hash=AnchorDataHash(bytes.fromhex(data_hash)))
    except ValueError:
        return None


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

    @contextmanager
    def _client(self) -> Iterator[Client]:
        """Hand out the generated API client for the duration of one request.

        The generated ``Client`` is itself a context manager, but entering it
        opens the underlying ``httpx.Client`` and leaving it closes it, and httpx
        refuses to reopen a closed client. Using ``with self.api`` directly would
        therefore let a chain context serve exactly one request in its lifetime.
        The endpoint helpers do not need an entered client — they construct the
        ``httpx.Client`` lazily — so this yields it as-is and leaves it open for
        reuse.

        Yields:
            Client: The Yaci Store API client.
        """
        yield self.api

    @property
    def epoch(self) -> int:
        if not self._epoch:
            with self._client() as client:
                response: Optional[EpochNo] = get_latest_epoch.sync(client=client)
                self._epoch = response.epoch or 0 if response else 0
        return self._epoch

    @property
    def protocol_param(self) -> PyCardanoProtocolParameters:
        if not self._protocol_param:
            with self._client() as client:
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
        with self._client() as client:
            script: Optional[ScriptDto] = get_script_by_hash.sync(
                script_hash=script_hash, client=client
            )

        script_type = script.type if script else None

        def get_plutus_cbor(script_hash: str) -> str:
            with self._client() as client:
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
            with self._client() as client:
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
            with self._client() as client:
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
            with self._client() as client:
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
            with self._client() as client:
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
            with self._client() as client:
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

    # -- Pagination --------------------------------------------------------

    def _paginate(
        self,
        fetch: Callable[[int, int], Optional[List[_T]]],
        page_size: int = _PAGE_SIZE,
    ) -> List[_T]:
        """Collect every page of one of Yaci's ``page``/``count`` endpoints.

        Yaci returns a bare list with no total, so a short page is the only
        signal that the end has been reached.

        Args:
            fetch (Callable[[int, int], Optional[List[_T]]]): Callable taking a
                zero-based page number and a page size, returning one page.
            page_size (int): Rows to request per page.

        Returns:
            List[_T]: Every row, in the order Yaci returned them.
        """
        rows: List[_T] = []
        for page in range(_MAX_PAGES):
            chunk = fetch(page, page_size) or []
            rows.extend(chunk)
            if len(chunk) < page_size:
                break
        return rows

    # -- Chain state -------------------------------------------------------

    def _latest_block(self) -> BlockDto:
        """Get the most recently indexed block.

        Returns:
            BlockDto: The latest block.

        Raises:
            :class:`UnexpectedStatus`: When the query fails.
            ValueError: When Yaci reports no block at all.
        """
        try:
            with self._client() as client:
                block: Optional[BlockDto] = get_latest_block.sync(client=client)
        except UnexpectedStatus as e:
            logger.error(f"Failed to get the latest block. Error: {e}")
            raise

        if block is None:
            raise ValueError("Yaci DevKit returned no latest block.")
        return block

    @property
    def era(self) -> Optional[Era]:
        """The era the chain is currently in.

        Yaci records the hard-fork combinator's era index on every block rather
        than an era name, so this maps that index (``1`` Byron through ``7``
        Conway). An index outside that range — a future era this mapping does
        not know — is reported as ``None`` rather than guessed at.

        Returns:
            Optional[Era]: The era of the latest block.

        Raises:
            :class:`UnexpectedStatus`: When the query fails.
        """
        index = _opt(self._latest_block().era)
        if index is None:
            return None
        return _ERA_BY_INDEX.get(index)

    @property
    def chain_tip(self) -> ChainTip:
        """The current tip of the chain.

        Returns:
            ChainTip: The slot, block hash, height, epoch and era of the latest
            block Yaci has indexed. ``sync_progress`` is not populated: Yaci
            reports how far it has indexed but not how far behind the node it
            is, so there is nothing to compare against.

        Raises:
            :class:`UnexpectedStatus`: When the query fails.
        """
        block = self._latest_block()
        era_index = _opt(block.era)
        number = _opt(block.number)
        return ChainTip(
            slot=_opt(block.slot),
            hash=_opt(block.hash_),
            block=number if number is not None else _opt(block.height),
            epoch=_opt(block.epoch),
            era=None if era_index is None else _ERA_BY_INDEX.get(era_index),
        )

    def _is_unspent(self, address: str, tx_hash: str, index: int) -> bool:
        """Whether an output is still in the address' live UTxO set.

        Args:
            address (str): The address that owns the output.
            tx_hash (str): The transaction hash of the output.
            index (int): The output index.

        Returns:
            bool: ``True`` when the output is still unspent.
        """

        def fetch(page: int, count: int) -> Optional[List[Any]]:
            with self._client() as client:
                return get_utxos_1.sync(
                    address=address, client=client, page=page, count=count
                )

        try:
            live = self._paginate(fetch)
        except UnexpectedStatus as e:
            logger.error(f"Failed to get the UTxO set of {address}. Error: {e}")
            raise

        return any(
            _opt(utxo.tx_hash) == tx_hash and _opt(utxo.output_index) == index
            for utxo in live
        )

    def utxo(self, tx_input: TransactionInput) -> Optional[Tuple[UTxO, bool]]:
        """Resolve a single UTxO by the transaction input that identifies it.

        Yaci's output store keeps outputs after they are spent but records no
        spent flag on them, so whether the output is still live is decided by
        looking for it in its own address' live UTxO set. That costs one extra
        (paginated) request, and an address with a very large UTxO set makes it
        an expensive one.

        Args:
            tx_input (TransactionInput): The transaction hash and output index.

        Returns:
            Optional[Tuple[UTxO, bool]]: The UTxO and whether it has been spent,
            or ``None`` if Yaci has not indexed it. Yaci retains spent outputs,
            so unlike a live-UTxO-set backend this can return ``True``.
        """
        tx_hash = str(tx_input.transaction_id)
        index = int(tx_input.index)

        try:
            with self._client() as client:
                result: Optional[AddressUtxo] = get_utxo_by_ref.sync(
                    tx_hash=tx_hash, index=index, client=client
                )
        except UnexpectedStatus as e:
            logger.error(f"Failed to get UTxO {tx_hash}#{index}. Error: {e}")
            return None

        if result is None:
            return None

        address = _opt(result.owner_addr)
        if not address:
            return None

        lovelace = _opt(result.lovelace_amount) or 0
        multi_assets = MultiAsset()
        for amount in _opt(result.amounts) or []:
            unit = _opt(amount.unit)
            quantity = int(_opt(amount.quantity) or 0)
            if not unit or unit == "lovelace":
                if unit == "lovelace":
                    lovelace = quantity
                continue
            data = bytes.fromhex(unit)
            policy_id = ScriptHash(data[:SCRIPT_HASH_SIZE])
            asset_name = AssetName(data[SCRIPT_HASH_SIZE:])
            if policy_id not in multi_assets:
                multi_assets[policy_id] = Asset()
            multi_assets[policy_id][asset_name] = quantity

        inline_datum = _opt(result.inline_datum)
        data_hash = _opt(result.data_hash)
        reference_script_hash = _opt(result.reference_script_hash)

        tx_out = TransactionOutput(
            Address.from_primitive(address),
            amount=Value(lovelace, multi_assets),
            datum_hash=(
                DatumHash.from_primitive(data_hash)
                if data_hash and inline_datum is None
                else None
            ),
            datum=RawCBOR(bytes.fromhex(inline_datum)) if inline_datum else None,
            script=(
                self._get_script(reference_script_hash)
                if reference_script_hash
                else None
            ),
        )

        return UTxO(tx_input, tx_out), not self._is_unspent(address, tx_hash, index)

    # -- Stake pools -------------------------------------------------------

    def _pool_registrations(self) -> List[PoolRegistration]:
        """Every pool registration certificate Yaci has indexed, oldest first."""

        def fetch(page: int, count: int) -> Optional[List[PoolRegistration]]:
            with self._client() as client:
                return get_pool_registrations.sync(
                    client=client, page=page, count=count
                )

        try:
            rows = self._paginate(fetch)
        except UnexpectedStatus as e:
            logger.error(f"Failed to get pool registrations. Error: {e}")
            raise

        return sorted(
            rows, key=lambda r: ((_opt(r.slot) or 0), _opt(r.cert_index) or 0)
        )

    def _pool_retirements(self) -> List[PoolRetirement]:
        """Every pool retirement certificate Yaci has indexed, oldest first."""

        def fetch(page: int, count: int) -> Optional[List[PoolRetirement]]:
            with self._client() as client:
                return get_retirements.sync(client=client, page=page, count=count)

        try:
            rows = self._paginate(fetch)
        except UnexpectedStatus as e:
            logger.error(f"Failed to get pool retirements. Error: {e}")
            raise

        return sorted(
            rows, key=lambda r: ((_opt(r.slot) or 0), _opt(r.cert_index) or 0)
        )

    @staticmethod
    def _pool_id_hex(pool_id: str) -> str:
        """Normalise a bech32 or hex pool ID to the hex key hash Yaci indexes by."""
        return PoolOperator.from_primitive(pool_id).pool_key_hash.payload.hex()

    def _pool_certificates(
        self,
    ) -> Dict[str, Tuple[PoolRegistration, Optional[PoolRetirement]]]:
        """Fold the pool certificate log into the latest state of every pool.

        Note:
            This is a reconstruction, not a state read. Yaci exposes pool
            registrations and retirements as an event log with no current-state
            view, so the latest registration for a pool is taken as its live
            parameters and a retirement is kept only when no later registration
            has superseded it — which is exactly how the ledger resolves them.
            It goes wrong if Yaci is pruned or has not finished syncing, since
            an unseen certificate is indistinguishable from one that was never
            submitted.

        Returns:
            Dict[str, Tuple[PoolRegistration, Optional[PoolRetirement]]]: Keyed
            by the pool's hex key hash.
        """
        registrations: Dict[str, PoolRegistration] = {}
        for registration in self._pool_registrations():
            pool_id = _opt(registration.pool_id)
            if pool_id:
                registrations[pool_id] = registration

        retirements: Dict[str, PoolRetirement] = {}
        for retirement in self._pool_retirements():
            pool_id = _opt(retirement.pool_id)
            if pool_id:
                retirements[pool_id] = retirement

        state: Dict[str, Tuple[PoolRegistration, Optional[PoolRetirement]]] = {}
        for pool_id, registration in registrations.items():
            outstanding: Optional[PoolRetirement] = retirements.get(pool_id)
            if outstanding is not None and (_opt(outstanding.slot) or 0) < (
                _opt(registration.slot) or 0
            ):
                # Re-registering after announcing a retirement cancels it.
                outstanding = None
            state[pool_id] = (registration, outstanding)
        return state

    def _pool_status(
        self, retirement: Optional[PoolRetirement], epoch: int
    ) -> PoolStatus:
        """Derive a pool's status from its outstanding retirement, if any.

        A retirement takes effect at the start of its ``retirement_epoch``, so
        the pool is still ``RETIRING`` for every epoch before that one.
        """
        if retirement is None:
            return PoolStatus.REGISTERED
        retiring_epoch = _opt(retirement.retirement_epoch)
        if retiring_epoch is not None and epoch < retiring_epoch:
            return PoolStatus.RETIRING
        return PoolStatus.RETIRED

    def stake_pools(self) -> List[PoolOperator]:
        """Get every stake pool registered on the chain.

        Note:
            Reconstructed from Yaci's pool certificate log; see
            :meth:`_pool_certificates`. Pools whose retirement epoch has already
            passed are excluded, so this is the set of pools that are live or
            still winding down.

        Returns:
            List[PoolOperator]: The registered pools.

        Raises:
            :class:`UnexpectedStatus`: When the query fails.
        """
        epoch = self.epoch
        return [
            PoolOperator(PoolKeyHash(bytes.fromhex(pool_id)))
            for pool_id, (_, retirement) in self._pool_certificates().items()
            if self._pool_status(retirement, epoch) is not PoolStatus.RETIRED
        ]

    @staticmethod
    def _relay(relay: Any) -> Relay:
        """Map one Yaci relay entry onto the matching pycardano relay type.

        Yaci reports every relay with the same four fields and leaves the ones
        that do not apply unset, so the shape is inferred from which are
        populated.
        """
        port = _opt(relay.port)
        ipv4, ipv6 = _opt(relay.ipv4), _opt(relay.ipv6)
        dns = _opt(relay.dns_name)
        if ipv4 or ipv6:
            return SingleHostAddr(port=port, ipv4=ipv4, ipv6=ipv6)
        if dns and port is not None:
            return SingleHostName(port=port, dns_name=dns)
        return MultiHostName(dns_name=dns)

    @staticmethod
    def _pool_owner(owner: str) -> VerificationKeyHash:
        """Map one registered pool owner onto its staking key hash.

        Yaci reports owners as raw key hashes, but tolerate a bech32 stake
        address here too so a differently configured store still resolves.
        """
        if owner.startswith("stake"):
            payload = Address.decode(owner).staking_part
            return VerificationKeyHash(bytes(payload.payload))  # type: ignore[union-attr]
        return VerificationKeyHash(bytes.fromhex(owner))

    @staticmethod
    def _reward_account(registration: PoolRegistration) -> RewardAccountHash:
        """Map a pool's registered reward account onto its 29-byte form."""
        bech32 = _opt(registration.reward_account_bech32)
        if bech32:
            return RewardAccountHash(bytes(Address.decode(bech32).to_primitive()))
        return RewardAccountHash(bytes.fromhex(_opt(registration.reward_account) or ""))

    def _pool_params(self, registration: PoolRegistration) -> PoolParams:
        """Build pycardano pool parameters from a registration certificate."""
        metadata_url = _opt(registration.metadata_url)
        metadata_hash = _opt(registration.metadata_hash)
        pool_metadata = None
        if metadata_url and metadata_hash:
            pool_metadata = PoolMetadata(
                url=metadata_url,
                pool_metadata_hash=PoolMetadataHash(bytes.fromhex(metadata_hash)),
            )

        return PoolParams(
            operator=PoolKeyHash(bytes.fromhex(_opt(registration.pool_id) or "")),
            vrf_keyhash=VrfKeyHash(
                bytes.fromhex(_opt(registration.vrf_key_hash) or "")
            ),
            pledge=_opt(registration.pledge) or 0,
            cost=_opt(registration.cost) or 0,
            margin=Fraction(str(_opt(registration.margin) or 0)).limit_denominator(),
            reward_account=self._reward_account(registration),
            pool_owners=[
                self._pool_owner(owner)
                for owner in _opt(registration.pool_owners) or []
            ],
            relays=[self._relay(relay) for relay in _opt(registration.relays) or []],
            pool_metadata=pool_metadata,
        )

    def stake_pool_info(self, pool_id: str, strict: bool = False) -> StakePoolInfo:
        """Get a stake pool's registered parameters and stake figures.

        Note:
            Reconstructed from Yaci's pool certificate log; see
            :meth:`_pool_certificates`. Yaci indexes certificates rather than
            ledger state, so it reports no stake figures at all: ``live_stake``,
            ``live_pledge``, ``live_size``, ``active_stake``, ``active_size``
            and ``opcert_counter`` are left ``None`` rather than guessed at.
            ``pledge`` inside ``pool_params`` is the *declared* pledge from the
            certificate, which is not the same thing as live pledge.

        Args:
            pool_id (str): The pool's ID, bech32 or hex encoded.
            strict (bool): Ignored. Yaci never fetches a pool's off-chain
                metadata, so there is no hash to verify; the registered URL and
                hash are returned as they appear on-chain.

        Returns:
            StakePoolInfo: The pool's registered parameters and status.

        Raises:
            ValueError: If the pool has no registration certificate on-chain.
            :class:`UnexpectedStatus`: When the query fails.
        """
        certificates = self._pool_certificates().get(self._pool_id_hex(pool_id))
        if certificates is None:
            raise ValueError(f"Pool {pool_id} was not found.")

        registration, retirement = certificates
        return StakePoolInfo(
            pool_params=self._pool_params(registration),
            status=self._pool_status(retirement, self.epoch),
            retiring_epoch=(
                None if retirement is None else _opt(retirement.retirement_epoch)
            ),
        )

    # -- Governance --------------------------------------------------------

    def _drep_certificates(self) -> List[DRepRegistration]:
        """Every DRep certificate Yaci has indexed, oldest first.

        Yaci splits registrations, updates and retirements across three
        endpoints; a DRep's current state is the latest row of the three.
        """

        def registrations(page: int, count: int) -> Optional[List[DRepRegistration]]:
            with self._client() as client:
                return get_d_rep_registrations.sync(
                    client=client, page=page, count=count
                )

        def updates(page: int, count: int) -> Optional[List[DRepRegistration]]:
            with self._client() as client:
                return get_d_rep_updates.sync(client=client, page=page, count=count)

        def deregistrations(page: int, count: int) -> Optional[List[DRepRegistration]]:
            with self._client() as client:
                return get_d_rep_de_registrations.sync(
                    client=client, page=page, count=count
                )

        try:
            rows = (
                self._paginate(registrations)
                + self._paginate(updates)
                + self._paginate(deregistrations)
            )
        except UnexpectedStatus as e:
            logger.error(f"Failed to get DRep certificates. Error: {e}")
            raise

        return sorted(
            rows, key=lambda r: ((_opt(r.slot) or 0), _opt(r.cert_index) or 0)
        )

    def drep_info(self, drep: DRep) -> DRepInfo:
        """Get a delegate representative's registration.

        Note:
            This is a reconstruction, not a state read. Yaci exposes DRep
            registrations, updates and retirements as an event log with no
            current-state view, so the DRep's status is taken from its latest
            certificate: a retirement last means ``RETIRED``, a registration or
            update last means ``REGISTERED``, and no certificate at all means
            ``NOT_REGISTERED``. It goes wrong if Yaci is pruned or still
            syncing, since an unseen certificate is indistinguishable from one
            that was never submitted.

        Warning:
            Yaci reports no DRep voting power. ``stake`` is therefore always
            ``0`` — the model's default, not a measurement — and must not be
            read as "no stake is delegated to this DRep". ``expiry`` is left
            ``None`` for the same reason: it depends on the DRep's last activity
            including its votes, which Yaci does not aggregate.

        Args:
            drep (DRep): The DRep to look up.

        Returns:
            DRepInfo: The DRep's registration. A DRep with no certificates is
            reported as ``NOT_REGISTERED``.

        Raises:
            :class:`UnexpectedStatus`: When the query fails.
        """
        credential = drep.credential
        if credential is None:
            # ALWAYS_ABSTAIN and ALWAYS_NO_CONFIDENCE are predefined DReps that
            # are never registered by a certificate, so Yaci has nothing on them.
            return DRepInfo(drep=drep, status=DRepStatus.NOT_REGISTERED)

        drep_hash = credential.payload.hex()
        certificates = [
            certificate
            for certificate in self._drep_certificates()
            if _opt(certificate.drep_hash) == drep_hash
        ]

        if not certificates:
            return DRepInfo(drep=drep, status=DRepStatus.NOT_REGISTERED)

        latest = certificates[-1]
        retired = _opt(latest.type) is DRepRegistrationType.UNREG_DREP_CERT
        deposit = next(
            (
                _opt(certificate.deposit)
                for certificate in reversed(certificates)
                if _opt(certificate.type) is DRepRegistrationType.REG_DREP_CERT
            ),
            None,
        )

        return DRepInfo(
            drep=drep,
            active=not retired,
            anchor=_anchor(_opt(latest.anchor_url), _opt(latest.anchor_hash)),
            deposit=deposit,
            status=DRepStatus.RETIRED if retired else DRepStatus.REGISTERED,
        )

    def _gov_action_lifetime(self) -> Optional[int]:
        """The number of epochs a governance action stays open for voting."""
        try:
            with self._client() as client:
                params: Optional[ProtocolParamsDto] = get_latest_protocol_params.sync(
                    client=client
                )
        except UnexpectedStatus as e:
            logger.error(f"Failed to get protocol parameters. Error: {e}")
            raise

        return _opt(params.gov_action_lifetime) if params else None

    def _proposals(self) -> List[GovActionProposal]:
        """Every governance action proposal Yaci has indexed."""

        def fetch(page: int, count: int) -> Optional[List[GovActionProposal]]:
            with self._client() as client:
                return get_gov_action_proposal_list.sync(
                    client=client, page=page, count=count
                )

        try:
            return self._paginate(fetch)
        except UnexpectedStatus as e:
            logger.error(f"Failed to get the governance proposal list. Error: {e}")
            raise

    def _find_proposal(self, gov_action_id: GovActionId) -> GovActionProposal:
        """Find one proposal by its identifier.

        Args:
            gov_action_id (GovActionId): The action's identifier.

        Returns:
            GovActionProposal: The matching proposal.

        Raises:
            ValueError: If no proposal matches the identifier.
        """
        tx_hash = str(gov_action_id.transaction_id)
        try:
            with self._client() as client:
                proposals = get_gov_action_proposal_by_tx.sync(
                    tx_hash=tx_hash, client=client
                )
        except UnexpectedStatus as e:
            logger.error(f"Failed to get governance proposals of {tx_hash}. Error: {e}")
            raise

        for proposal in proposals or []:
            if _opt(proposal.index) == gov_action_id.gov_action_index:
                return proposal

        raise ValueError(f"Governance action {gov_action_id.encode()} was not found.")

    @staticmethod
    def _proposal_gov_action_id(
        proposal: GovActionProposal,
    ) -> Optional[GovActionId]:
        """Build a GovActionId from the proposal's transaction hash and index."""
        tx_hash = _opt(proposal.tx_hash)
        index = _opt(proposal.index)
        if not tx_hash or index is None:
            return None
        return GovActionId(
            transaction_id=TransactionId(bytes.fromhex(tx_hash)),
            gov_action_index=index,
        )

    @staticmethod
    def _proposal_action(proposal: GovActionProposal) -> Optional[Any]:
        """The proposed action itself, as the JSON document Yaci indexed.

        Yaci stores a governance action as free-form JSON rather than CBOR, so
        this is a plain dict and not a parsed pycardano action — the same
        compromise the Koios backend makes.
        """
        details = _opt(proposal.details)
        return details.to_dict() if details is not None else None

    def _votes_for(
        self, tx_hash: str, index: int
    ) -> Tuple[List[CommitteeVote], List[DRepVote], List[StakePoolVote]]:
        """Fetch a proposal's voting procedures and split them by voter role.

        A voter may vote more than once on the same action and only its last
        vote counts, so rows are reduced to the latest one per voter before
        being split.

        Args:
            tx_hash (str): The proposing transaction's hash.
            index (int): The proposal's index within that transaction.

        Returns:
            Tuple[List[CommitteeVote], List[DRepVote], List[StakePoolVote]]: The
            committee, DRep and stake pool votes.
        """

        def fetch(page: int, count: int) -> Optional[List[VotingProcedure]]:
            with self._client() as client:
                return get_voting_procedures_for_gov_action_proposal.sync(
                    tx_hash=tx_hash,
                    index_in_tx=index,
                    client=client,
                    page=page,
                    count=count,
                )

        try:
            rows = self._paginate(fetch)
        except UnexpectedStatus as e:
            logger.error(f"Failed to get votes for {tx_hash}#{index}. Error: {e}")
            raise

        latest: Dict[Tuple[Any, Optional[str]], VotingProcedure] = {}
        for row in sorted(
            rows, key=lambda v: ((_opt(v.slot) or 0), _opt(v.index) or 0)
        ):
            latest[(_opt(row.voter_type), _opt(row.voter_hash))] = row

        committee: List[CommitteeVote] = []
        dreps: List[DRepVote] = []
        pools: List[StakePoolVote] = []

        for row in latest.values():
            voter_type = _opt(row.voter_type)
            voter_hash = _opt(row.voter_hash)
            if not voter_hash:
                continue

            raw_vote = _opt(row.vote)
            vote = None if raw_vote is None else Vote[raw_vote.value.upper()]
            anchor = _anchor(_opt(row.anchor_url), _opt(row.anchor_hash))
            payload = bytes.fromhex(voter_hash)

            if (
                voter_type
                is VotingProcedureVoterType.CONSTITUTIONAL_COMMITTEE_HOT_KEY_HASH
            ):
                committee.append(
                    CommitteeVote(
                        voter=CommitteeHotCredential(VerificationKeyHash(payload)),
                        vote=vote,
                        anchor=anchor,
                    )
                )
            elif (
                voter_type
                is VotingProcedureVoterType.CONSTITUTIONAL_COMMITTEE_HOT_SCRIPT_HASH
            ):
                committee.append(
                    CommitteeVote(
                        voter=CommitteeHotCredential(ScriptHash(payload)),
                        vote=vote,
                        anchor=anchor,
                    )
                )
            elif voter_type is VotingProcedureVoterType.DREP_KEY_HASH:
                dreps.append(
                    DRepVote(
                        voter=DRep(
                            DRepKind.VERIFICATION_KEY_HASH,
                            VerificationKeyHash(payload),
                        ),
                        vote=vote,
                        anchor=anchor,
                    )
                )
            elif voter_type is VotingProcedureVoterType.DREP_SCRIPT_HASH:
                dreps.append(
                    DRepVote(
                        voter=DRep(DRepKind.SCRIPT_HASH, ScriptHash(payload)),
                        vote=vote,
                        anchor=anchor,
                    )
                )
            elif voter_type is VotingProcedureVoterType.STAKING_POOL_KEY_HASH:
                pools.append(
                    StakePoolVote(
                        voter=PoolOperator(PoolKeyHash(payload)).encode(),
                        vote=vote,
                        anchor=anchor,
                    )
                )

        return committee, dreps, pools

    def gov_action_info(self, gov_action_id: GovActionId) -> GovActionInfo:
        """Get the lifecycle information for a governance action.

        Warning:
            Yaci indexes the proposal certificate, not the ledger's governance
            state, so it has no record of whether an action was ratified,
            enacted, dropped or expired. Those four epochs are always ``None``,
            which makes :attr:`~pccontext.models.GovActionInfo.status` report
            ``None`` — "still open" — for every action, including ones that have
            long since concluded. Use a backend that reads governance state if
            the outcome matters. ``expires_after`` is derived, not read: it is
            the proposal's epoch plus the current ``govActionLifetime``, which
            is wrong for an action whose lifetime parameter has since changed.

        Args:
            gov_action_id (GovActionId): The action's identifier.

        Returns:
            GovActionInfo: The action's information. ``gov_action`` carries
            Yaci's own JSON description rather than a parsed pycardano action.

        Raises:
            ValueError: If no proposal matches the identifier.
            :class:`UnexpectedStatus`: When the query fails.
        """
        proposal = self._find_proposal(gov_action_id)
        proposed_in = _opt(proposal.epoch)
        lifetime = self._gov_action_lifetime()
        return GovActionInfo(
            gov_action_id=gov_action_id,
            gov_action=self._proposal_action(proposal),
            proposed_in=proposed_in,
            expires_after=(
                None
                if proposed_in is None or lifetime is None
                else proposed_in + lifetime
            ),
        )

    def _gov_action_votes(
        self, proposal: GovActionProposal, lifetime: Optional[int]
    ) -> GovActionVotes:
        """Assemble a GovActionVotes from a proposal plus its voting procedures."""
        tx_hash = _opt(proposal.tx_hash) or ""
        index = _opt(proposal.index) or 0
        committee, dreps, pools = self._votes_for(tx_hash, index)
        proposed_in = _opt(proposal.epoch)

        return GovActionVotes(
            gov_action_id=self._proposal_gov_action_id(proposal),
            gov_action=self._proposal_action(proposal),
            committee_votes=committee,
            drep_votes=dreps,
            stake_pool_votes=pools,
            deposit=_opt(proposal.deposit),
            deposit_return_addr=_opt(proposal.return_address),
            anchor=_anchor(_opt(proposal.anchor_url), _opt(proposal.anchor_hash)),
            proposed_in=proposed_in,
            expires_after=(
                None
                if proposed_in is None or lifetime is None
                else proposed_in + lifetime
            ),
        )

    def gov_action_votes(self, gov_action_id: GovActionId) -> GovActionVotes:
        """Get the votes recorded against a governance action, by voter class.

        Note:
            The lifecycle epochs carry the same caveat as
            :meth:`gov_action_info`: Yaci does not index governance state, so
            the outcome epochs are always ``None``.

        Args:
            gov_action_id (GovActionId): The action's identifier.

        Returns:
            GovActionVotes: The proposal plus its committee, DRep and stake pool
            votes.

        Raises:
            ValueError: If no proposal matches the identifier.
            :class:`UnexpectedStatus`: When the query fails.
        """
        return self._gov_action_votes(
            self._find_proposal(gov_action_id), self._gov_action_lifetime()
        )

    def gov_actions_all(self) -> List[GovActionVotes]:
        """Get every governance proposal with its votes.

        Warning:
            The base interface asks for the *active* proposals. Yaci cannot tell
            an active proposal from a concluded one — it has no governance state
            — so this returns every proposal it has indexed, including expired
            and enacted ones. Filtering on
            :attr:`~pccontext.models.GovActionVotes.status` will not narrow it,
            because that is always ``None`` here.

        Note:
            Yaci returns the proposal list in pages but its voting procedures
            per proposal, so this makes at least one further request per
            proposal.

        Returns:
            List[GovActionVotes]: One entry per indexed proposal.

        Raises:
            :class:`UnexpectedStatus`: When the query fails.
        """
        lifetime = self._gov_action_lifetime()
        return [
            self._gov_action_votes(proposal, lifetime) for proposal in self._proposals()
        ]
