import os
import tempfile
import time
from decimal import Decimal
from fractions import Fraction
from typing import Dict, List, Optional, Tuple, Union

import cbor2
from blockfrost import ApiError, ApiUrls, BlockFrostApi
from blockfrost.utils import Namespace
from pycardano.address import Address
from pycardano.backend.base import ProtocolParameters as PyCardanoProtocolParameters
from pycardano.exception import TransactionFailedException
from pycardano.hash import (
    SCRIPT_HASH_SIZE,
    DatumHash,
    PoolKeyHash,
    PoolMetadataHash,
    RewardAccountHash,
    ScriptHash,
    VerificationKeyHash,
    VrfKeyHash,
)
from pycardano.nativescript import NativeScript
from pycardano.network import Network as PyCardanoNetwork
from pycardano.plutus import (
    ExecutionUnits,
    PlutusV1Script,
    PlutusV2Script,
    PlutusV3Script,
    script_hash,
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
from pccontext.enums import Network, PoolStatus
from pccontext.exceptions import BlockfrostError, PoolMetadataError
from pccontext.models import (
    ChainTip,
    GenesisParameters,
    KESPeriodInfo,
    ProtocolParameters,
    SPOStakeEntry,
    StakeAddressInfo,
    StakePoolInfo,
)

__all__ = ["BlockFrostChainContext"]

# Blockfrost reports a pool's margin as a float. Rendering it back as a
# fraction over 10^8 keeps every digit the API can meaningfully express.
_MARGIN_DENOMINATOR = 100_000_000


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


def _decode_op_cert(op_cert: Union[bytes, str]) -> Tuple[int, int]:
    """Decode a node operational certificate into its counter and KES period.

    Args:
        op_cert (Union[bytes, str]): The certificate, CBOR encoded either as raw
            bytes or as the hex string found in a ``node.cert`` text envelope.

    Returns:
        Tuple[int, int]: The certificate's sequence number and the KES period it
        was issued for.

    Raises:
        :class:`BlockfrostError`: When the certificate cannot be decoded.
    """
    try:
        raw = bytes.fromhex(op_cert) if isinstance(op_cert, str) else op_cert
        body = cbor2.loads(raw)[0]
        return int(body[1]), int(body[2])
    except Exception as e:
        raise BlockfrostError(
            f"Failed to decode the operational certificate: {e}"
        ) from e


def _relay(relay: Namespace) -> Optional[Relay]:
    """Map a Blockfrost relay record onto a PyCardano relay.

    Args:
        relay (Namespace): One entry of the ``/pools/{pool_id}/relays`` response.

    Returns:
        Optional[Relay]: The relay, or ``None`` when the record names no host at
        all and so cannot be represented.
    """
    port = getattr(relay, "port", None)
    ipv4 = getattr(relay, "ipv4", None)
    ipv6 = getattr(relay, "ipv6", None)
    dns = getattr(relay, "dns", None)
    dns_srv = getattr(relay, "dns_srv", None)

    if ipv4 or ipv6:
        return SingleHostAddr(port=port, ipv4=ipv4, ipv6=ipv6)
    if dns:
        return SingleHostName(port=port, dns_name=dns)
    if dns_srv:
        return MultiHostName(dns_name=dns_srv)
    return None


def _owner_key_hash(owner: str) -> VerificationKeyHash:
    """Extract the key hash a pool owner is identified by.

    Args:
        owner (str): The owner's reward address, bech32 encoded.

    Returns:
        VerificationKeyHash: The hash held in the address' staking part, falling
        back to its payment part.

    Raises:
        :class:`BlockfrostError`: When the address carries neither part.
    """
    address = Address.from_primitive(owner)
    part = address.staking_part or address.payment_part
    if part is None:
        raise BlockfrostError(f"Pool owner address {owner} has no key hash.")
    return VerificationKeyHash(part.payload)


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
    def chain_tip(self) -> ChainTip:
        """Get the current tip of the chain.

        Returns:
            ChainTip: The slot, block hash, height and epoch of the latest
            block. Blockfrost reports no era or sync progress, so those fields
            are ``None``.

        Raises:
            :class:`BlockfrostError`: When the latest block cannot be fetched.
        """
        try:
            block = self.api.block_latest()
        except ApiError as e:
            raise BlockfrostError(f"Failed to fetch the latest block. {e}") from e

        return ChainTip(
            slot=block.slot,
            hash=block.hash,
            block=block.height,
            epoch=block.epoch,
        )

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

    def utxo(self, tx_input: TransactionInput) -> Optional[Tuple[UTxO, bool]]:
        """Resolve a single UTxO by the transaction input that identifies it.

        Blockfrost returns every output of a transaction whether or not it has
        since been consumed, and names the consuming transaction, so the spent
        flag is exact rather than inferred.

        Args:
            tx_input (TransactionInput): The transaction hash and output index.

        Returns:
            Optional[Tuple[UTxO, bool]]: The UTxO and whether it has been spent,
            or ``None`` when the transaction is unknown or has no output at that
            index.

        Raises:
            :class:`BlockfrostError`: When the transaction cannot be fetched.
        """
        tx_hash = str(tx_input.transaction_id)
        output_index = int(tx_input.index)

        try:
            tx_utxos = self.api.transaction_utxos(tx_hash)
        except ApiError as e:
            if e.status_code == 404:
                return None
            raise BlockfrostError(
                f"Failed to fetch the UTxOs of transaction {tx_hash}. {e}"
            ) from e

        result = next(
            (
                output
                for output in tx_utxos.outputs
                if output.output_index == output_index
            ),
            None,
        )
        if result is None:
            return None

        is_spent = getattr(result, "consumed_by_tx", None) is not None

        lovelace_amount = 0
        multi_assets = MultiAsset()
        for item in result.amount:
            if item.unit == "lovelace":
                lovelace_amount = int(item.quantity)
            else:
                data = bytes.fromhex(item.unit)
                policy_id = ScriptHash(data[:SCRIPT_HASH_SIZE])
                asset_name = AssetName(data[SCRIPT_HASH_SIZE:])

                if policy_id not in multi_assets:
                    multi_assets[policy_id] = Asset()
                multi_assets[policy_id][asset_name] = int(item.quantity)

        inline_datum = getattr(result, "inline_datum", None)
        data_hash = getattr(result, "data_hash", None)

        datum_hash = (
            DatumHash.from_primitive(data_hash)
            if data_hash and inline_datum is None
            else None
        )
        datum = RawCBOR(bytes.fromhex(inline_datum)) if inline_datum else None

        reference_script_hash = getattr(result, "reference_script_hash", None)
        script = (
            self._get_script(reference_script_hash) if reference_script_hash else None
        )

        tx_out = TransactionOutput(
            Address.from_primitive(result.address),
            amount=Value(lovelace_amount, multi_assets),
            datum_hash=datum_hash,
            datum=datum,
            script=script,
        )

        return (
            UTxO(TransactionInput.from_primitive([tx_hash, output_index]), tx_out),
            is_spent,
        )

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

    def stake_pools(self) -> List[PoolOperator]:
        """Get every stake pool registered on the chain.

        Returns:
            List[PoolOperator]: The registered pools, in the order Blockfrost
            lists them.

        Raises:
            :class:`BlockfrostError`: When the pool list cannot be fetched.
        """
        try:
            pool_ids = self.api.pools(gather_pages=True)
        except ApiError as e:
            raise BlockfrostError(f"Failed to fetch the stake pool list. {e}") from e

        return [PoolOperator.from_primitive(pool_id) for pool_id in pool_ids]

    def _pool_metadata(self, pool_id: str, strict: bool) -> Optional[PoolMetadata]:
        """Get the metadata anchor a stake pool registered on-chain.

        Blockfrost resolves the off-chain document itself and verifies it
        against the registered hash, returning the document's fields only when
        that succeeds. This backend therefore never fetches the URL a second
        time; ``strict`` decides whether an unresolved document is an error.

        Args:
            pool_id (str): The pool's ID, bech32 encoded.
            strict (bool): Whether metadata problems are raised.

        Returns:
            Optional[PoolMetadata]: The registered URL and hash, or ``None``
            when the pool registered no metadata and ``strict`` is ``False``.

        Raises:
            :class:`PoolMetadataError`: When ``strict`` is ``True`` and the
                metadata is missing or Blockfrost could not verify it.
        """
        try:
            metadata = self.api.pool_metadata(pool_id)
        except ApiError as e:
            if strict:
                raise PoolMetadataError(
                    f"Failed to fetch the off-chain metadata of stake pool {pool_id}. {e}"
                ) from e
            return None

        url = getattr(metadata, "url", None)
        metadata_hash = getattr(metadata, "hash", None)

        if not url or not metadata_hash:
            if strict:
                raise PoolMetadataError(
                    f"Stake pool {pool_id} has no off-chain metadata registered."
                )
            return None

        if strict and not any(
            getattr(metadata, name, None)
            for name in ("ticker", "name", "description", "homepage")
        ):
            raise PoolMetadataError(
                f"Blockfrost could not resolve the off-chain metadata of stake pool "
                f"{pool_id} at {url} against its registered hash."
            )

        return PoolMetadata(
            url=url,
            pool_metadata_hash=PoolMetadataHash(bytes.fromhex(metadata_hash)),
        )

    def _latest_block_op_cert_counter(self, pool_id: str) -> Optional[int]:
        """Get the operational certificate counter of a pool's newest block.

        Args:
            pool_id (str): The pool's ID, bech32 encoded.

        Returns:
            Optional[int]: The counter, or ``None`` when the pool has never
            minted a block or Blockfrost does not report the counter.
        """
        try:
            blocks = self.api.pool_blocks(pool_id, count=1, order="desc")
            if not blocks:
                return None
            block = self.api.block(blocks[0])
        except ApiError:
            return None

        counter = getattr(block, "op_cert_counter", None)
        return int(counter) if counter is not None else None

    def _retirement_status(
        self, pool_id: str, tx_hash: str
    ) -> Tuple[PoolStatus, Optional[int]]:
        """Resolve a pool's retirement certificate into a status.

        Args:
            pool_id (str): The retiring pool's ID, bech32 encoded.
            tx_hash (str): The transaction carrying the newest retirement
                certificate.

        Returns:
            Tuple[PoolStatus, Optional[int]]: The status, and the epoch the pool
            retires in while that is still in the future.
        """
        try:
            retirements = self.api.transaction_pool_retires(tx_hash)
        except ApiError:
            return PoolStatus.RETIRING, None

        retirement = next(
            (r for r in retirements if r.pool_id == pool_id),
            None,
        )
        if retirement is None:
            return PoolStatus.RETIRING, None

        retiring_epoch = int(retirement.retiring_epoch)
        if self.epoch >= retiring_epoch:
            return PoolStatus.RETIRED, None
        return PoolStatus.RETIRING, retiring_epoch

    def stake_pool_info(self, pool_id: str, strict: bool = False) -> StakePoolInfo:
        """Get a stake pool's registered parameters and stake figures.

        Args:
            pool_id (str): The pool's ID, bech32 encoded.
            strict (bool): When ``True``, a metadata anchor that Blockfrost
                could not resolve and verify is raised rather than tolerated.

        Returns:
            StakePoolInfo: The pool's registered parameters, live and active
            stake, operational certificate counter and registration status.

        Raises:
            :class:`BlockfrostError`: When the pool cannot be fetched.
            :class:`PoolMetadataError`: When ``strict`` is ``True`` and the
                pool's off-chain metadata could not be verified.
        """
        try:
            pool = self.api.pool(pool_id)
            relays = self.api.pool_relays(pool_id)
        except ApiError as e:
            raise BlockfrostError(
                f"Failed to fetch stake pool info for {pool_id}. {e}"
            ) from e

        pool_metadata = self._pool_metadata(pool_id, strict)

        margin = Fraction(
            round(float(pool.margin_cost) * _MARGIN_DENOMINATOR),
            _MARGIN_DENOMINATOR,
        )

        pool_params = PoolParams(
            operator=PoolKeyHash(bytes.fromhex(pool.hex)),
            vrf_keyhash=VrfKeyHash(bytes.fromhex(pool.vrf_key)),
            pledge=int(pool.declared_pledge),
            cost=int(pool.fixed_cost),
            margin=margin,
            reward_account=RewardAccountHash(
                bytes(Address.from_primitive(pool.reward_account).to_primitive())
            ),
            pool_owners=[_owner_key_hash(owner) for owner in pool.owners],
            relays=[relay for relay in map(_relay, relays) if relay is not None],
            pool_metadata=pool_metadata,
        )

        retirement = list(getattr(pool, "retirement", None) or [])
        if retirement:
            status, retiring_epoch = self._retirement_status(pool_id, retirement[-1])
        else:
            status, retiring_epoch = PoolStatus.REGISTERED, None

        return StakePoolInfo(
            pool_params=pool_params,
            live_pledge=int(pool.live_pledge),
            live_stake=int(pool.live_stake),
            live_size=Decimal(str(pool.live_size)),
            active_stake=int(pool.active_stake),
            active_size=Decimal(str(pool.active_size)),
            opcert_counter=self._latest_block_op_cert_counter(pool_id),
            status=status,
            retiring_epoch=retiring_epoch,
        )

    def kes_period_info(
        self,
        pool: Optional[PoolOperator] = None,
        op_cert: Optional[Union[bytes, str]] = None,
    ) -> KESPeriodInfo:
        """Get the KES period information for a pool's operational certificate.

        Blockfrost has no query for a node's KES state, so the on-chain counter
        is read from the header of the newest block the pool minted. A pool that
        has never minted a block therefore cannot be reported on.

        Args:
            pool (Optional[PoolOperator]): The pool operator. Required for this
                backend, which has no way to find a pool from its certificate.
            op_cert (Optional[Union[bytes, str]]): The operational certificate,
                CBOR encoded. When given, its counter and KES period are
                reported alongside the on-chain counter.

        Returns:
            KESPeriodInfo: The on-chain counter, the counter to use for the next
            certificate, and the on-disk counter and KES start when ``op_cert``
            was given.

        Raises:
            ValueError: When no pool is given.
            :class:`BlockfrostError`: When the pool has never minted a block, or
                the block or certificate cannot be read.
        """
        if pool is None:
            raise ValueError(
                "A pool operator must be provided; Blockfrost reads the on-chain "
                "operational certificate counter from the pool's newest block."
            )

        pool_id = pool.encode()

        try:
            blocks = self.api.pool_blocks(pool_id, count=1, order="desc")
        except ApiError as e:
            raise BlockfrostError(
                f"Failed to fetch the blocks minted by stake pool {pool_id}. {e}"
            ) from e

        if not blocks:
            raise BlockfrostError(
                f"Stake pool {pool_id} has never minted a block, so its on-chain "
                "operational certificate counter cannot be read from Blockfrost."
            )

        try:
            block = self.api.block(blocks[0])
        except ApiError as e:
            raise BlockfrostError(
                f"Failed to fetch block {blocks[0]} for stake pool {pool_id}. {e}"
            ) from e

        counter = getattr(block, "op_cert_counter", None)
        if counter is None:
            raise BlockfrostError(
                f"Blockfrost reported no operational certificate counter for block "
                f"{blocks[0]}."
            )

        on_chain_op_cert_count = int(counter)

        on_disk_op_cert_count: Optional[int] = None
        on_disk_kes_start: Optional[int] = None
        if op_cert is not None:
            on_disk_op_cert_count, on_disk_kes_start = _decode_op_cert(op_cert)

        return KESPeriodInfo(
            on_chain_op_cert_count=on_chain_op_cert_count,
            on_disk_op_cert_count=on_disk_op_cert_count,
            next_chain_op_cert_count=on_chain_op_cert_count + 1,
            on_disk_kes_start=on_disk_kes_start,
        )

    def treasury(self) -> int:
        """Get the current treasury balance, in lovelace.

        Returns:
            int: The treasury balance.

        Raises:
            :class:`BlockfrostError`: When the network summary cannot be
                fetched.
        """
        try:
            network_info = self.api.network()
        except ApiError as e:
            raise BlockfrostError(
                f"Failed to fetch the network information. {e}"
            ) from e

        return int(network_info.supply.treasury)

    def spo_stake_distribution(self) -> List[SPOStakeEntry]:
        """Get the stake delegated to each stake pool this epoch.

        Returns:
            List[SPOStakeEntry]: One entry per registered pool, carrying the
            active stake Blockfrost reports for the current epoch.

        Raises:
            :class:`BlockfrostError`: When the pool list cannot be fetched.
        """
        try:
            pools = self.api.pools_extended(gather_pages=True)
        except ApiError as e:
            raise BlockfrostError(
                f"Failed to fetch the stake pool stake distribution. {e}"
            ) from e

        return [
            SPOStakeEntry(pool_id=pool.pool_id, stake=int(pool.active_stake))
            for pool in pools
        ]
