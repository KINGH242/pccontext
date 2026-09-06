"""
Cardano CLI Chain Context
"""

import hashlib
import json
import os
import subprocess
import tempfile
import time
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, cast

import cbor2
import docker
import requests
from cachetools import Cache, LRUCache, TTLCache, func
from docker.errors import APIError
from pycardano.address import Address
from pycardano.backend.base import ProtocolParameters as PyCardanoProtocolParameters
from pycardano.certificate import Anchor, DRep, DRepKind
from pycardano.exception import (
    CardanoCliError,
    PyCardanoException,
    TransactionFailedException,
)
from pycardano.governance import (
    CommitteeColdCredential,
    CommitteeHotCredential,
    DRepVotingThresholds,
    ExUnitPrices,
    GovActionId,
    HardForkInitiationAction,
    InfoAction,
    NewConstitution,
    NoConfidence,
    ParameterChangeAction,
    PoolVotingThresholds,
    ProtocolParamUpdate,
    TreasuryWithdrawal,
    TreasuryWithdrawalsAction,
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
from pycardano.nativescript import NativeScript
from pycardano.network import Network as PyCardanoNetwork
from pycardano.plutus import (
    Datum,
    ExecutionUnits,
    PlutusV1Script,
    PlutusV2Script,
    PlutusV3Script,
    RawPlutusData,
    RedeemerTag,
)
from pycardano.pool_params import (
    MultiHostName,
    PoolMetadata,
    PoolOperator,
    PoolParams,
    SingleHostAddr,
    SingleHostName,
)
from pycardano.serialization import RawCBOR
from pycardano.transaction import (
    Asset,
    AssetName,
    MultiAsset,
    Transaction,
    TransactionInput,
    TransactionOutput,
    UTxO,
    Value,
)
from pycardano.types import JsonDict
from requests import RequestException

from pccontext.backend import ChainContext
from pccontext.enums import CommitteeMemberStatus, DRepStatus, Era, Network, PoolStatus
from pccontext.exceptions import CardanoCLIError
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

__all__ = ["CardanoCliChainContext", "DockerConfig"]


class DockerConfig:
    """
    Docker configuration to use the cardano-cli in a Docker container
    """

    container_name: str
    """ The name of the Docker container containing the cardano-cli"""

    host_socket: Optional[Path]
    """ The path to the Docker host socket file"""

    def __init__(self, container_name: str, host_socket: Optional[Path] = None):
        self.container_name = container_name
        self.host_socket = host_socket


class CardanoCliChainContext(ChainContext):
    _binary: Path
    _socket: Optional[Path]
    _config_file: Path
    _network: Network
    _last_known_block_slot: int
    _last_chain_tip_fetch: float
    _genesis_param: Optional[GenesisParameters]
    _protocol_param: Optional[ProtocolParameters]
    _utxo_cache: Cache
    _datum_cache: Cache
    _docker_config: Optional[DockerConfig]
    _network_magic_number: Optional[int]

    def __init__(
        self,
        binary: Path,
        socket: Path,
        config_file: Path,
        network: Network,
        refetch_chain_tip_interval: Optional[float] = None,
        utxo_cache_size: int = 10000,
        datum_cache_size: int = 10000,
        docker_config: Optional[DockerConfig] = None,
        network_magic_number: Optional[int] = None,
    ):
        if docker_config is None:
            if not binary.exists() or not binary.is_file():
                raise CardanoCliError(f"cardano-cli binary file not found: {binary}")

            # Check the socket path file and set the CARDANO_NODE_SOCKET_PATH environment variable
            try:
                if not socket.exists():
                    raise CardanoCliError(f"cardano-node socket not found: {socket}")
                elif not socket.is_socket():
                    raise CardanoCliError(f"{socket} is not a socket file")

                self._socket = socket
                os.environ["CARDANO_NODE_SOCKET_PATH"] = self._socket.as_posix()
            except CardanoCliError:
                self._socket = None

        self._binary = binary
        self._network = network
        self._config_file = config_file
        self._last_known_block_slot = 0
        self._refetch_chain_tip_interval = (
            refetch_chain_tip_interval
            if refetch_chain_tip_interval is not None
            else 1000
        )
        self._last_chain_tip_fetch = 0
        self._genesis_param = None
        self._protocol_param = None
        if refetch_chain_tip_interval is None:
            slot_length = self.genesis_param.slot_length or 1
            active_slots_coefficient = (
                self.genesis_param.active_slots_coefficient or 0.05
            )
            self._refetch_chain_tip_interval = float(
                slot_length / active_slots_coefficient
            )

        self._utxo_cache = TTLCache(
            ttl=self._refetch_chain_tip_interval, maxsize=utxo_cache_size
        )
        self._datum_cache = LRUCache(maxsize=datum_cache_size)
        self._docker_config = docker_config
        self._network_magic_number = network_magic_number

    @property
    def name(self) -> str:
        return "CardanoCli"

    @property
    def _network_args(self) -> List[str]:
        if self._network is Network.CUSTOM:
            return self._network.get_cli_network_args(self._network_magic_number)
        else:
            return self._network.get_cli_network_args()

    def _run_command(self, cmd: List[str]) -> str:
        """
        Runs the command in the cardano-cli. If the docker configuration is set, it will run the command in the
        docker container.

        :param cmd: Command as a list of strings
        :return: The stdout if the command runs successfully
        """
        try:
            if self._docker_config:
                docker_config = self._docker_config
                if docker_config.host_socket is None:
                    client = docker.from_env()
                else:
                    client = docker.DockerClient(
                        base_url=docker_config.host_socket.as_posix()
                    )

                container = client.containers.get(docker_config.container_name)

                exec_result = container.exec_run(
                    [self._binary.as_posix()] + cmd, stdout=True, stderr=True
                )

                if exec_result.exit_code == 0:
                    output = exec_result.output.decode()
                    return output
                else:
                    error = exec_result.output.decode()
                    raise CardanoCliError(error)
            else:
                result = subprocess.run(
                    [self._binary.as_posix()] + cmd, capture_output=True, check=True
                )
                return result.stdout.decode().strip()
        except subprocess.CalledProcessError as err:
            raise CardanoCliError(err.stderr.decode()) from err
        except APIError as err:
            raise CardanoCliError(err) from err

    def _query_chain_tip(self) -> JsonDict:
        result = self._run_command(["query", "tip"] + self._network_args)
        return json.loads(result)

    def _query_current_protocol_params(self) -> JsonDict:
        result = self._run_command(
            ["query", "protocol-parameters"] + self._network_args
        )
        return json.loads(result)

    def _query_genesis_config(self) -> GenesisParameters:
        return GenesisParameters.from_config_file(self._config_file)

    def _is_chain_tip_updated(self):
        # fetch at almost every twenty seconds!
        if time.time() - self._last_chain_tip_fetch < self._refetch_chain_tip_interval:
            return False
        self._last_chain_tip_fetch = time.time()
        result = self._query_chain_tip()
        return float(result["syncProgress"]) != 100.0

    def _fetch_protocol_param(self) -> ProtocolParameters:
        result = self._query_current_protocol_params()
        return ProtocolParameters.from_json(result)

    @property
    def protocol_param(self) -> PyCardanoProtocolParameters:
        """Get current protocol parameters"""
        if not self._protocol_param or self._is_chain_tip_updated():
            self._protocol_param = self._fetch_protocol_param()
        return self._protocol_param.to_pycardano()

    @property
    def genesis_param(self) -> GenesisParameters:
        """Get chain genesis parameters"""
        if not self._genesis_param:
            self._genesis_param = self._query_genesis_config()
        return self._genesis_param

    @property
    def network(self) -> PyCardanoNetwork:
        """Cet current network"""
        return self._network.get_network()

    @property
    def epoch(self) -> int:
        """Current epoch number"""
        result = self._query_chain_tip()
        return result["epoch"]

    @property
    def _era_name(self) -> str:
        """The era exactly as ``cardano-cli query tip`` spells it, e.g. "Conway".

        Transaction envelopes embed this spelling verbatim, so it is kept
        separate from :attr:`era`, which returns the parsed enum.
        """
        return str(self._query_chain_tip()["era"])

    @property
    def era(self) -> Optional[Era]:
        """Current Cardano era"""
        try:
            return Era(self._era_name.lower())
        except ValueError:
            return None

    @property
    @func.ttl_cache(ttl=1)
    def last_block_slot(self) -> int:
        result = self._query_chain_tip()
        return result["slot"]

    def version(self):
        """
        Gets the cardano-cli version
        """
        return self._run_command(["version"])

    @staticmethod
    def _get_script(
        reference_script: dict,
    ) -> Union[PlutusV1Script, PlutusV2Script, NativeScript]:
        """
        Get a script object from a reference script dictionary.
        Args:
            reference_script:

        Returns:

        """
        script_type = reference_script["script"]["type"]
        script_json: JsonDict = reference_script["script"]
        if script_type == "PlutusScriptV1":
            v1script = PlutusV1Script(
                cbor2.loads(bytes.fromhex(script_json["cborHex"]))
            )
            return v1script
        elif script_type == "PlutusScriptV2":
            v2script = PlutusV2Script(
                cbor2.loads(bytes.fromhex(script_json["cborHex"]))
            )
            return v2script
        elif script_type == "PlutusScriptV3":
            v3script = PlutusV3Script(
                cbor2.loads(bytes.fromhex(script_json["cborHex"]))
            )
            return v3script
        else:
            return NativeScript.from_dict(script_json)

    def _utxos(self, address: str) -> List[UTxO]:
        """Get all UTxOs associated with an address.

        Args:
            address (str): An address encoded with bech32.

        Returns:
            List[UTxO]: A list of UTxOs.
        """
        key = (self.last_block_slot, address)
        if key in self._utxo_cache:
            return self._utxo_cache[key]

        result = self._run_command(
            ["query", "utxo", "--address", address, "--out-file", "/dev/stdout"]
            + self._network_args
        )

        raw_utxos = json.loads(result)

        utxos = []
        for tx_hash in raw_utxos.keys():
            tx_id, tx_idx = tx_hash.split("#")
            tx_in = TransactionInput.from_primitive([tx_id, int(tx_idx)])
            utxos.append(self._utxo_from_raw(tx_in, raw_utxos[tx_hash]))

        self._utxo_cache[key] = utxos

        return utxos

    def _utxo_from_raw(self, tx_in: TransactionInput, utxo: JsonDict) -> UTxO:
        """Build a UTxO from one entry of ``cardano-cli query utxo`` output.

        Args:
            tx_in (TransactionInput): The input the entry is keyed by.
            utxo (JsonDict): The entry: address, value, datum and any
                reference script.

        Returns:
            UTxO: The parsed UTxO.
        """
        value = Value()
        multi_asset = MultiAsset()
        for asset in utxo["value"].keys():
            if asset == "lovelace":
                value.coin = utxo["value"][asset]
            else:
                policy_id = asset
                policy = ScriptHash.from_primitive(policy_id)

                for asset_hex_name in utxo["value"][asset].keys():
                    asset_name = AssetName.from_primitive(asset_hex_name)
                    amount = utxo["value"][asset][asset_hex_name]
                    multi_asset.setdefault(policy, Asset())[asset_name] = amount

        value.multi_asset = multi_asset

        datum_hash = (
            DatumHash.from_primitive(utxo["datumhash"])
            if utxo.get("datumhash") is not None
            else None
        )

        datum: Optional[Datum] = None

        if utxo.get("datum"):
            datum = RawCBOR(bytes.fromhex(utxo["datum"]))
        elif utxo.get("inlineDatumhash"):
            datum = RawPlutusData.from_dict(utxo["inlineDatum"])

        script = None

        if utxo.get("referenceScript"):
            script = self._get_script(utxo["referenceScript"])

        tx_out = TransactionOutput(
            Address.from_primitive(utxo["address"]),
            amount=value,
            datum_hash=datum_hash,
            datum=datum,
            script=script,
        )

        return UTxO(tx_in, tx_out)

    def submit_tx_cbor(self, cbor: Union[bytes, str]) -> str:
        """Submit a transaction to the blockchain.

        Args:
            cbor (Union[bytes, str]): The transaction to be submitted.

        Returns:
            str: The transaction hash.

        Raises:
            :class:`TransactionFailedException`: When fails to submit the transaction to blockchain.
            :class:`PyCardanoException`: When fails to retrieve the transaction hash.
        """
        if isinstance(cbor, bytes):
            cbor = cbor.hex()

        with tempfile.NamedTemporaryFile(mode="w") as tmp_tx_file:
            tx_json = {
                "type": f"Witnessed Tx {self._era_name}Era",
                "description": "Generated by PyCardano",
                "cborHex": cbor,
            }

            tmp_tx_file.write(json.dumps(tx_json))

            tmp_tx_file.flush()

            try:
                self._run_command(
                    [
                        "latest",
                        "transaction",
                        "submit",
                        "--tx-file",
                        tmp_tx_file.name,
                    ]
                    + self._network_args
                )
            except CardanoCliError:
                try:
                    self._run_command(
                        ["transaction", "submit", "--tx-file", tmp_tx_file.name]
                        + self._network_args
                    )
                except CardanoCliError as err:
                    raise TransactionFailedException(
                        "Failed to submit transaction"
                    ) from err

            # Get the transaction ID
            try:
                txid = self._run_command(
                    ["latest", "transaction", "txid", "--tx-file", tmp_tx_file.name]
                )
            except CardanoCliError:
                try:
                    txid = self._run_command(
                        ["transaction", "txid", "--tx-file", tmp_tx_file.name]
                    )
                except CardanoCliError as err:
                    raise PyCardanoException(
                        f"Unable to get transaction id for {tmp_tx_file.name}"
                    ) from err

        return txid

    @staticmethod
    def _redeemer_keys(cbor: Union[bytes, str]) -> List[str]:
        """The transaction's redeemer keys, in canonical ledger order.

        Keys are formatted the way :class:`pycardano.txbuilder.TransactionBuilder` looks them
        up when it assigns estimated execution units, that is
        ``f"{redeemer.tag.name.lower()}:{redeemer.index}"`` -- for example ``"spend:0"``.

        Args:
            cbor (Union[bytes, str]): The serialized transaction.

        Returns:
            List[str]: The redeemer keys, ordered by redeemer tag then index. Empty if the
            transaction carries no redeemers.
        """
        tx = Transaction.from_cbor(cbor)
        redeemers = tx.transaction_witness_set.redeemer
        if not redeemers:
            return []

        pairs: List[Tuple[int, int]] = []
        if hasattr(redeemers, "items"):  # Conway: a RedeemerKey -> RedeemerValue map
            for redeemer_key in redeemers.keys():
                pairs.append((RedeemerTag(redeemer_key.tag).value, redeemer_key.index))
        else:  # Legacy: a plain list of Redeemer
            for redeemer in redeemers:
                pairs.append((RedeemerTag(redeemer.tag).value, redeemer.index))

        pairs.sort()
        return [f"{RedeemerTag(tag).name.lower()}:{index}" for tag, index in pairs]

    #: Maps the redeemer purpose names other tools use onto the :class:`RedeemerTag` names that
    #: pycardano keys execution units by.
    _PURPOSE_ALIASES = {
        "spend": "spend",
        "mint": "mint",
        "cert": "certificate",
        "certificate": "certificate",
        "publish": "certificate",
        "withdraw": "withdrawal",
        "withdrawal": "withdrawal",
        "vote": "voting",
        "voting": "voting",
        "propose": "proposing",
        "proposal": "proposing",
        "proposing": "proposing",
    }

    #: Fragments cardano-cli's argument parser emits when it is asked for a command or an
    #: option it does not have. A failure carrying one of these means the installed cli cannot
    #: be driven the way this backend needs, rather than that the transaction is bad.
    _UNSUPPORTED_COMMAND_MARKERS = (
        "invalid argument",
        "invalid option",
        "unknown option",
        "missing:",
    )

    @classmethod
    def _is_unsupported_command(cls, error: CardanoCliError) -> bool:
        """Whether `error` is cardano-cli rejecting the command line, not the transaction."""
        text = str(error).lower()
        return any(marker in text for marker in cls._UNSUPPORTED_COMMAND_MARKERS)

    def _version_or_unknown(self) -> str:
        """The installed cli version, for error messages; never raises."""
        try:
            return self.version().splitlines()[0].strip()
        except (
            Exception
        ):  # noqa: BLE001 - diagnostics must not mask the original failure
            return "cardano-cli version unknown"

    @classmethod
    def _parse_script_costs(
        cls, payload: Any, redeemer_keys: List[str]
    ) -> Dict[str, ExecutionUnits]:
        """Turn ``calculate-plutus-script-cost`` output into execution units per redeemer.

        The command reports one entry per Plutus script in the transaction. Entries that name
        their own redeemer purpose and index are keyed on that; entries that only report a
        script hash and a cost are paired positionally with ``redeemer_keys``, which is sound
        because both sides are in canonical redeemer order.

        Args:
            payload (Any): The parsed JSON emitted by the cli.
            redeemer_keys (List[str]): Keys from :meth:`_redeemer_keys`, used for the
                positional fallback and to validate the entry count.

        Returns:
            Dict[str, ExecutionUnits]: Execution units keyed by ``"{purpose}:{index}"``.

        Raises:
            :class:`TransactionFailedException`: When the output is not shaped as expected, is
                missing execution units, or reports a number of entries that cannot be matched
                to the transaction's redeemers.
        """
        if isinstance(payload, dict):
            # Tolerate a wrapper object around the list of costs.
            for wrapper in ("result", "scripts", "plutusScripts"):
                if isinstance(payload.get(wrapper), list):
                    payload = payload[wrapper]
                    break
        if not isinstance(payload, list):
            raise TransactionFailedException(
                f"Unexpected plutus script cost output: {payload!r}"
            )

        costs: Dict[str, ExecutionUnits] = {}
        for position, entry in enumerate(payload):
            if not isinstance(entry, dict):
                raise TransactionFailedException(
                    f"Unexpected plutus script cost entry: {entry!r}"
                )

            units = entry.get("executionUnits", entry.get("execution_units", entry))
            if not isinstance(units, dict):
                raise TransactionFailedException(
                    f"Plutus script cost entry has no execution units: {entry!r}"
                )
            memory = units.get("memory", units.get("mem"))
            steps = units.get("steps", units.get("cpu"))
            if memory is None or steps is None:
                # A script the node could not run reports an error instead of a cost.
                raise TransactionFailedException(
                    f"Plutus script evaluation failed: {entry!r}"
                )

            validator = entry.get("validator")
            validator = validator if isinstance(validator, dict) else {}
            purpose = entry.get("purpose", validator.get("purpose"))
            index = entry.get("index", validator.get("index"))
            if purpose is not None and index is not None:
                tag = cls._PURPOSE_ALIASES.get(str(purpose).lower())
                if tag is None:
                    raise TransactionFailedException(
                        f"Unknown redeemer purpose in plutus script cost output: {purpose!r}"
                    )
                key = f"{tag}:{index}"
            elif position < len(redeemer_keys):
                key = redeemer_keys[position]
            else:
                raise TransactionFailedException(
                    f"cardano-cli reported {len(payload)} plutus script costs but the "
                    f"transaction has {len(redeemer_keys)} redeemers: {payload!r}"
                )

            costs[key] = ExecutionUnits(mem=int(memory), steps=int(steps))

        return costs

    def evaluate_tx_cbor(self, cbor: Union[bytes, str]) -> Dict[str, ExecutionUnits]:
        """Evaluate execution units of a transaction.

        Runs ``cardano-cli latest transaction calculate-plutus-script-cost online``, which
        costs the transaction's Plutus scripts against the local node's ledger state. This
        needs the same node socket the rest of this context already uses -- unlike the
        ``offline`` mode of that command, which would additionally require an era history, a
        utxo file and a protocol parameters file to be supplied by hand.

        Args:
            cbor (Union[bytes, str]): The serialized transaction to be evaluated.

        Returns:
            Dict[str, ExecutionUnits]: Execution units keyed by ``"{purpose}:{index}"``, for
            example ``"spend:0"``. Empty when the transaction has no redeemers.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When the installed cardano-cli has
                no ``calculate-plutus-script-cost`` command this backend can drive, which is
                the case for older releases.
            :class:`TransactionFailedException`: When the cli runs but fails to evaluate the
                transaction.
        """
        if isinstance(cbor, bytes):
            cbor = cbor.hex()

        redeemer_keys = self._redeemer_keys(cbor)
        if not redeemer_keys:
            return {}

        with tempfile.NamedTemporaryFile(mode="w") as tmp_tx_file:
            tx_json = {
                "type": f"Witnessed Tx {self._era_name}Era",
                "description": "Generated by PyCardano",
                "cborHex": cbor,
            }

            tmp_tx_file.write(json.dumps(tx_json))

            tmp_tx_file.flush()

            socket = getattr(self, "_socket", None)
            socket_args = ["--socket-path", socket.as_posix()] if socket else []
            tx_args = ["--tx-file", tmp_tx_file.name]

            # `online` split off from a flat command in cardano-cli 10; try newest first.
            attempts = [
                ["latest", "transaction", "calculate-plutus-script-cost", "online"]
                + socket_args
                + self._network_args
                + tx_args,
                ["transaction", "calculate-plutus-script-cost", "online"]
                + socket_args
                + self._network_args
                + tx_args,
                ["transaction", "calculate-plutus-script-cost"]
                + self._network_args
                + tx_args,
            ]

            result = None
            errors: List[CardanoCliError] = []
            for cmd in attempts:
                try:
                    result = self._run_command(cmd)
                    break
                except CardanoCliError as err:
                    errors.append(err)

            if result is None:
                if errors and all(map(self._is_unsupported_command, errors)):
                    raise CardanoCLIError(
                        command=" ".join(attempts[0]),
                        message=(
                            "This cardano-cli does not provide "
                            "`transaction calculate-plutus-script-cost` in a form this "
                            "backend can drive, so it cannot evaluate Plutus script costs "
                            f"({self._version_or_unknown()}). Upgrade cardano-cli, or use a "
                            "backend that evaluates transactions itself, such as Ogmios."
                        ),
                    )
                raise TransactionFailedException(
                    f"Failed to evaluate transaction: {errors[-1] if errors else result!r}"
                ) from (errors[-1] if errors else None)

        try:
            payload = json.loads(result)
        except json.JSONDecodeError as err:
            raise TransactionFailedException(
                f"Unable to parse plutus script cost output: {result!r}"
            ) from err

        return self._parse_script_costs(payload, redeemer_keys)

    def stake_address_info(self, stake_address: str) -> List[StakeAddressInfo]:
        """Get the stake address information.

        Args:
            stake_address (str): The stake address.

        Returns:
            List[StakeAddressInfo]: The stake address information.
        """

        result = self._run_command(
            [
                "query",
                "stake-address-info",
                "--address",
                stake_address,
                "--out-file",
                "/dev/stdout",
            ]
            + self._network_args
        )

        info = json.loads(result)

        return [
            StakeAddressInfo(
                address=stake_address,
                delegation_deposit=rewards_state.get("delegationDeposit", None),
                stake_delegation=rewards_state.get("stakeDelegation", None),
                reward_account_balance=rewards_state.get("rewardAccountBalance", None),
                vote_delegation=rewards_state.get("voteDelegation", None),
            )
            for rewards_state in info
        ]

    # -- Chain state ------------------------------------------------------

    @property
    def chain_tip(self) -> ChainTip:
        """The current tip of the chain, from ``cardano-cli query tip``.

        Returns:
            ChainTip: The slot, block hash, block height, epoch, era and sync
            progress the node reports.
        """
        result = self._query_chain_tip()

        era: Optional[Era] = None
        era_name = result.get("era")
        if era_name is not None:
            try:
                era = Era(str(era_name).lower())
            except ValueError:
                era = None

        sync_progress = result.get("syncProgress")

        return ChainTip(
            slot=result.get("slot"),
            hash=result.get("hash"),
            block=result.get("block"),
            epoch=result.get("epoch"),
            era=era,
            sync_progress=(float(sync_progress) if sync_progress is not None else None),
        )

    def utxo(self, tx_input: TransactionInput) -> Optional[Tuple[UTxO, bool]]:
        """Resolve a single UTxO with ``cardano-cli query utxo --tx-in``.

        Args:
            tx_input (TransactionInput): The transaction hash and output index.

        Returns:
            Optional[Tuple[UTxO, bool]]: The UTxO and whether it has been spent,
            or ``None`` when the node does not have it. A node only holds the
            live UTxO set, so a returned UTxO is always unspent (``False``) and
            a spent one is indistinguishable from one that never existed.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When the cli output
                cannot be parsed as JSON.
        """
        tx_in = f"{tx_input.transaction_id}#{tx_input.index}"

        result = self._run_command(
            [
                "query",
                "utxo",
                "--tx-in",
                tx_in,
                "--output-json",
                "--out-file",
                "/dev/stdout",
            ]
            + self._network_args
        )

        raw_utxos = self._load_json(result, "query utxo")
        if not isinstance(raw_utxos, dict):
            return None

        raw_utxo = raw_utxos.get(tx_in)
        if raw_utxo is None:
            # The cli echoes the input back verbatim, but be tolerant of a
            # differently cased transaction hash.
            for key, value in raw_utxos.items():
                if key.lower() == tx_in.lower():
                    raw_utxo = value
                    break

        if not isinstance(raw_utxo, dict):
            return None

        return self._utxo_from_raw(tx_input, raw_utxo), False

    # -- Stake pools ------------------------------------------------------

    def stake_pools(self) -> List[PoolOperator]:
        """Every registered stake pool, from ``cardano-cli query stake-pools``.

        Returns:
            List[PoolOperator]: The registered pools.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When a reported pool
                id cannot be decoded.
        """
        result = self._run_command(["query", "stake-pools"] + self._network_args)

        stripped = result.strip()
        if stripped.startswith("["):
            # Newer releases can emit a JSON array instead of one id per line.
            payload = self._load_json(stripped, "query stake-pools")
            entries = (
                [str(entry) for entry in payload] if isinstance(payload, list) else []
            )
        else:
            entries = [line.strip() for line in stripped.splitlines() if line.strip()]

        pools = []
        for entry in entries:
            try:
                pools.append(PoolOperator.from_primitive(entry))
            except (
                Exception
            ) as err:  # noqa: BLE001 - any decoding failure is fatal here
                raise CardanoCLIError(
                    command="query stake-pools",
                    message=f"Unable to decode stake pool id {entry!r}: {err}",
                ) from err

        return pools

    def stake_pool_info(self, pool_id: str, strict: bool = False) -> StakePoolInfo:
        """A stake pool's registered parameters and stake figures.

        Combines ``cardano-cli query pool-state`` (the registered parameters and
        any pending retirement), ``query stake-snapshot`` (the active stake this
        epoch) and ``query protocol-state`` (the on-chain operational
        certificate counter).

        Args:
            pool_id (str): The pool's ID, bech32 encoded or hex.
            strict (bool): When ``True``, the off-chain metadata document named
                by the registered parameters is fetched and its hash verified,
                and any failure is raised. When ``False`` the on-chain metadata
                url and hash are still returned, unverified.

        Returns:
            StakePoolInfo: The pool's information. ``live_pledge`` and
            ``live_stake`` are ``None``: the node reports stake snapshots, not
            a live figure.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When the pool is not
                registered, when the cli output cannot be parsed, or -- with
                ``strict`` -- when the off-chain metadata is unreachable or its
                hash does not match.
        """
        pool_operator = self._pool_operator(pool_id)
        bech32_pool_id = pool_operator.encode()

        pool_state = self._query_json(
            ["query", "pool-state", "--stake-pool-id", bech32_pool_id]
        )
        pool_entry = self._pool_keyed_value(pool_state, pool_operator)
        if not isinstance(pool_entry, dict):
            raise CardanoCLIError(
                command="query pool-state",
                message=f"Stake pool {bech32_pool_id} is not registered",
            )

        raw_params = pool_entry.get("poolParams")
        if not isinstance(raw_params, dict):
            raise CardanoCLIError(
                command="query pool-state",
                message=f"Stake pool {bech32_pool_id} has no pool parameters",
            )

        pool_params = self._parse_pool_params(pool_operator, raw_params, strict)

        active_stake: Optional[int] = None
        active_size: Optional[Decimal] = None
        snapshot = self._query_json(
            ["query", "stake-snapshot", "--stake-pool-id", bech32_pool_id]
        )
        if isinstance(snapshot, dict):
            pool_snapshot = self._pool_keyed_value(snapshot.get("pools"), pool_operator)
            if isinstance(pool_snapshot, dict):
                active_stake = self._parse_lovelace(pool_snapshot.get("stakeSet"))
                total = snapshot.get("total")
                total_set = (
                    self._parse_lovelace(total.get("stakeSet"))
                    if isinstance(total, dict)
                    else None
                )
                if active_stake is not None and total_set:
                    active_size = Decimal(active_stake) / Decimal(total_set)

        opcert_counter: Optional[int] = None
        protocol_state = self._query_json(["query", "protocol-state"])
        if isinstance(protocol_state, dict):
            counter = self._pool_keyed_value(
                protocol_state.get("oCertCounters"), pool_operator
            )
            if isinstance(counter, int):
                opcert_counter = counter

        retiring_epoch = pool_entry.get("retiring")
        status = (
            PoolStatus.REGISTERED if retiring_epoch is None else PoolStatus.RETIRING
        )

        return StakePoolInfo(
            pool_params=pool_params,
            active_stake=active_stake,
            active_size=active_size,
            opcert_counter=opcert_counter,
            status=status,
            retiring_epoch=retiring_epoch,
        )

    def kes_period_info(
        self,
        pool: Optional[PoolOperator] = None,
        op_cert: Optional[Union[bytes, str]] = None,
    ) -> KESPeriodInfo:
        """KES period information, from ``cardano-cli query kes-period-info``.

        The cli reads the operational certificate from a local file, so
        ``op_cert`` is required; a pool id alone identifies no certificate and
        the node exposes no way to fetch one.

        Args:
            pool (Optional[PoolOperator]): Ignored -- accepted for interface
                compatibility with backends that look a pool up by id.
            op_cert (Optional[Union[bytes, str]]): The operational certificate,
                CBOR encoded, as raw bytes or a hex string.

        Returns:
            KESPeriodInfo: The on-chain and on-disk certificate counters, the
            counter to use next, and the KES period the certificate started in.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When ``op_cert`` is
                not given, or the cli output cannot be parsed.
        """
        if op_cert is None:
            raise CardanoCLIError(
                command="query kes-period-info",
                message=(
                    "cardano-cli reads the operational certificate from a local file, "
                    "so kes_period_info needs op_cert"
                    + (
                        f"; the pool id {pool.encode()} alone is not enough."
                        if pool is not None
                        else "."
                    )
                ),
            )

        cbor_hex = op_cert.hex() if isinstance(op_cert, bytes) else op_cert

        with tempfile.NamedTemporaryFile(mode="w", suffix=".opcert") as tmp_op_cert:
            tmp_op_cert.write(
                json.dumps(
                    {
                        "type": "NodeOperationalCertificate",
                        "description": "",
                        "cborHex": cbor_hex,
                    }
                )
            )
            tmp_op_cert.flush()

            result = self._run_command(
                [
                    "query",
                    "kes-period-info",
                    "--op-cert-file",
                    tmp_op_cert.name,
                    "--out-file",
                    "/dev/stdout",
                ]
                + self._network_args
            )

        info = self._load_json(result, "query kes-period-info")
        if not isinstance(info, dict):
            raise CardanoCLIError(
                command="query kes-period-info",
                message=f"Unexpected kes-period-info output: {result!r}",
            )

        on_chain = info.get("qKesNodeStateOperationalCertificateNumber")
        on_disk = info.get("qKesOnDiskOperationalCertificateNumber")
        next_count = info.get("qKesExpectedOperationalCertificateNumber")
        if next_count is None and isinstance(on_chain, int):
            next_count = on_chain + 1

        return KESPeriodInfo(
            on_chain_op_cert_count=on_chain,
            on_disk_op_cert_count=on_disk,
            next_chain_op_cert_count=next_count,
            on_disk_kes_start=info.get("qKesStartKesInterval"),
        )

    # -- Treasury ---------------------------------------------------------

    def treasury(self) -> int:
        """The treasury balance, from ``cardano-cli query treasury``.

        Returns:
            int: The current treasury balance, in lovelace.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When the cli output
                is not a lovelace amount.
        """
        result = self._run_command(["query", "treasury"] + self._network_args).strip()

        balance = self._parse_lovelace(result)
        if balance is None:
            balance = self._parse_lovelace(self._load_json(result, "query treasury"))

        if balance is None:
            raise CardanoCLIError(
                command="query treasury",
                message=f"Unable to parse treasury balance from {result!r}",
            )

        return balance

    # -- Governance -------------------------------------------------------

    def drep_info(self, drep: DRep) -> DRepInfo:
        """A DRep's registration and voting power.

        Registered DReps come from ``cardano-cli query drep-state``; the two
        predefined DReps (abstain and no confidence) have no registration, so
        their voting power is read from ``query drep-stake-distribution``.

        Args:
            drep (DRep): The DRep to look up.

        Returns:
            DRepInfo: The DRep's information. A DRep the node does not know is
            reported as :attr:`~pccontext.enums.DRepStatus.NOT_REGISTERED` with
            zero stake, not as an error.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When the DRep carries
                no credential to query by, or the cli output cannot be parsed.
        """
        if drep.kind in (DRepKind.ALWAYS_ABSTAIN, DRepKind.ALWAYS_NO_CONFIDENCE):
            key = (
                "drep-alwaysAbstain"
                if drep.kind is DRepKind.ALWAYS_ABSTAIN
                else "drep-alwaysNoConfidence"
            )
            payload = self._query_json(
                ["query", "drep-stake-distribution", "--all-dreps", "--output-json"]
            )
            # --all-dreps enumerates every DRep, so a predefined DRep absent
            # from the listing has no delegated stake. That is a measurement,
            # not a missing figure, so it stays 0 rather than None.
            stake: Optional[int] = 0
            for entry_key, entry_value in self._key_value_entries(payload):
                if entry_key == key:
                    stake = self._parse_lovelace(entry_value)
                    break

            return DRepInfo(
                drep=drep,
                active=True,
                stake=stake,
                status=DRepStatus.REGISTERED,
            )

        credential = drep.credential
        if credential is None:
            raise CardanoCLIError(
                command="query drep-state",
                message=f"DRep {drep} carries no credential to query by",
            )

        flag = (
            "--drep-script-hash"
            if isinstance(credential, ScriptHash)
            else "--drep-key-hash"
        )
        payload = self._query_json(
            [
                "query",
                "drep-state",
                flag,
                credential.payload.hex(),
                "--include-stake",
                "--output-json",
            ]
        )

        state = None
        if isinstance(payload, list):
            for entry in payload:
                if (
                    isinstance(entry, list)
                    and len(entry) == 2
                    and isinstance(entry[1], dict)
                ):
                    state = entry[1]
                    break

        if state is None:
            return DRepInfo(
                drep=drep,
                active=False,
                stake=0,
                status=DRepStatus.NOT_REGISTERED,
            )

        return DRepInfo(
            drep=drep,
            active=True,
            anchor=self._parse_anchor(state.get("anchor")),
            deposit=self._parse_lovelace(state.get("deposit")),
            stake=self._parse_lovelace(state.get("stake")),
            expiry=state.get("expiry"),
            status=DRepStatus.REGISTERED,
        )

    def gov_action_info(self, gov_action_id: GovActionId) -> GovActionInfo:
        """A governance action's lifecycle, from ``cardano-cli query gov-state``.

        The node reports live proposals plus the actions the next epoch
        boundary will enact or expire; an action that has already left the
        proposal set can only be dated to the current epoch.

        Args:
            gov_action_id (GovActionId): The action's identifier.

        Returns:
            GovActionInfo: The action's information. ``gov_action`` is ``None``
            when the action is no longer in the proposal set, since the node no
            longer reports what was proposed.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When the gov-state
                output cannot be parsed.
        """
        gov_state = self._query_gov_state()
        proposals = self._gov_state_proposals(gov_state)
        current_epoch = self.epoch

        proposal = self._find_proposal(proposals, gov_action_id)

        next_ratify_state = gov_state.get("nextRatifyState")
        next_ratify_state = (
            next_ratify_state if isinstance(next_ratify_state, dict) else {}
        )
        in_enacted = self._action_listed(
            next_ratify_state.get("enactedGovActions"), gov_action_id
        )
        in_expired = self._action_listed(
            next_ratify_state.get("expiredGovActions"), gov_action_id
        )

        proposed_in = proposal.get("proposedIn") if proposal is not None else None
        expires_after = proposal.get("expiresAfter") if proposal is not None else None
        expired_by_epoch = expires_after is not None and current_epoch > expires_after

        ratified_epoch = current_epoch if proposal is not None and in_enacted else None
        dropped_epoch = (
            current_epoch if ratified_epoch is None and not proposals else None
        )
        expired_epoch = (
            current_epoch
            if ratified_epoch is None
            and dropped_epoch is None
            and (in_expired or proposal is None or expired_by_epoch)
            else None
        )

        gov_action = None
        if proposal is not None:
            procedure = proposal.get("proposalProcedure")
            if isinstance(procedure, dict):
                gov_action = self._parse_gov_action(procedure.get("govAction"))

        return GovActionInfo(
            gov_action_id=gov_action_id,
            gov_action=gov_action,
            proposed_in=proposed_in,
            expires_after=expires_after,
            ratified_epoch=ratified_epoch,
            dropped_epoch=dropped_epoch,
            expired_epoch=expired_epoch,
        )

    def gov_action_votes(self, gov_action_id: GovActionId) -> GovActionVotes:
        """The votes recorded against one governance action.

        Args:
            gov_action_id (GovActionId): The action's identifier.

        Returns:
            GovActionVotes: The proposal procedure and the committee, DRep and
            stake pool votes recorded so far.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When the action is
                not in the node's proposal set, or the output cannot be parsed.
        """
        gov_state = self._query_gov_state()
        proposals = self._gov_state_proposals(gov_state)

        proposal = self._find_proposal(proposals, gov_action_id)
        if proposal is None:
            raise CardanoCLIError(
                command="query gov-state",
                message=(
                    "Governance action not found in gov-state: "
                    f"{gov_action_id.transaction_id}#{gov_action_id.gov_action_index}"
                ),
            )

        return self._build_gov_action_votes(proposal, gov_action_id, self.epoch)

    def gov_actions_all(self) -> List[GovActionVotes]:
        """Every active governance proposal with its votes.

        Returns:
            List[GovActionVotes]: One entry per proposal the node still holds.
            Empty when no proposal is active.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When the gov-state
                output cannot be parsed.
        """
        gov_state = self._query_gov_state()
        proposals = self._gov_state_proposals(gov_state)
        current_epoch = self.epoch

        actions = []
        for proposal in proposals:
            gov_action_id = self._proposal_action_id(proposal)
            if gov_action_id is None:
                continue
            actions.append(
                self._build_gov_action_votes(proposal, gov_action_id, current_epoch)
            )

        return actions

    def committee_member_info(
        self,
        cold: Optional[CommitteeColdCredential] = None,
        hot: Optional[CommitteeHotCredential] = None,
    ) -> CommitteeMemberInfo:
        """One constitutional committee member, from ``query committee-state``.

        Args:
            cold (Optional[CommitteeColdCredential]): The member's cold
                credential. Optional if ``hot`` is given.
            hot (Optional[CommitteeHotCredential]): A hot credential the member
                has authorized. Optional if ``cold`` is given.

        Returns:
            CommitteeMemberInfo: The member's cold and hot credentials, term
            expiration and status. ``hot_credential`` is ``None`` when the
            member has not authorized one, which is also how a resignation
            appears.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When neither
                credential is given, no member matches, or the output cannot be
                parsed.
        """
        if cold is None and hot is None:
            raise CardanoCLIError(
                command="query committee-state",
                message="committee_member_info needs either a cold or a hot credential",
            )

        if cold is not None:
            flag = (
                "--cold-script-hash"
                if isinstance(cold.credential, ScriptHash)
                else "--cold-verification-key-hash"
            )
            credential_hash = cold.credential.payload.hex()
        else:
            assert hot is not None
            flag = (
                "--hot-script-hash"
                if isinstance(hot.credential, ScriptHash)
                else "--hot-key-hash"
            )
            credential_hash = hot.credential.payload.hex()

        payload = self._query_json(
            ["query", "committee-state", flag, credential_hash, "--output-json"]
        )
        committee = payload.get("committee") if isinstance(payload, dict) else None
        if not isinstance(committee, dict) or not committee:
            raise CardanoCLIError(
                command="query committee-state",
                message=f"No committee member matches {flag} {credential_hash}",
            )

        if cold is not None:
            member_key = None
            for key in committee:
                parsed = self._parse_committee_cold_key(key)
                if parsed is not None and parsed.credential == cold.credential:
                    member_key = key
                    break
            if member_key is None:
                raise CardanoCLIError(
                    command="query committee-state",
                    message=f"No committee member matches {flag} {credential_hash}",
                )
            cold_credential: Optional[CommitteeColdCredential] = cold
        else:
            # Queried by hot credential: the cli keys the answer by the cold
            # credential that authorized it.
            member_key = next(iter(committee))
            cold_credential = self._parse_committee_cold_key(member_key)

        entry = committee.get(member_key)
        entry = entry if isinstance(entry, dict) else {}

        return CommitteeMemberInfo(
            cold_credential=cold_credential,
            hot_credential=self._parse_hot_creds_auth_status(
                entry.get("hotCredsAuthStatus")
            )
            or hot,
            expiration=entry.get("expiration"),
            status=self._parse_committee_member_status(entry.get("status")),
        )

    def committee_state(self) -> CommitteeStateInfo:
        """The full constitutional committee, from ``query committee-state``.

        Returns:
            CommitteeStateInfo: Every member with its cold-to-hot authorization
            and term expiration, plus the quorum threshold in force.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When the output
                cannot be parsed.
        """
        payload = self._query_json(["query", "committee-state", "--output-json"])
        if not isinstance(payload, dict):
            raise CardanoCLIError(
                command="query committee-state",
                message=f"Unexpected committee-state output: {payload!r}",
            )

        committee = payload.get("committee")
        committee = committee if isinstance(committee, dict) else {}

        members = []
        for key, entry in committee.items():
            cold_credential = self._parse_committee_cold_key(key)
            if cold_credential is None:
                continue
            entry = entry if isinstance(entry, dict) else {}
            members.append(
                CommitteeMemberInfo(
                    cold_credential=cold_credential,
                    hot_credential=self._parse_hot_creds_auth_status(
                        entry.get("hotCredsAuthStatus")
                    ),
                    expiration=entry.get("expiration"),
                    status=self._parse_committee_member_status(entry.get("status")),
                )
            )

        return CommitteeStateInfo(
            members=members,
            threshold=self._parse_threshold(payload.get("threshold")),
        )

    # -- Stake distributions ----------------------------------------------

    def drep_stake_distribution(self) -> List[DRepStakeEntry]:
        """The stake behind each DRep this epoch.

        Runs ``cardano-cli query drep-stake-distribution --all-dreps``.

        Returns:
            List[DRepStakeEntry]: One entry per DRep, including the two
            predefined DReps the node reports.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When the output
                cannot be parsed.
        """
        payload = self._query_json(
            ["query", "drep-stake-distribution", "--all-dreps", "--output-json"]
        )

        entries = []
        for key, value in self._key_value_entries(payload):
            drep = self._parse_drep_key(key)
            stake = self._parse_lovelace(value)
            if drep is None or stake is None:
                continue
            entries.append(DRepStakeEntry(drep=drep, stake=stake))

        return entries

    def spo_stake_distribution(self) -> List[SPOStakeEntry]:
        """The stake behind each stake pool this epoch.

        Runs ``cardano-cli query spo-stake-distribution --all-spos``.

        Returns:
            List[SPOStakeEntry]: One entry per pool.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When the output
                cannot be parsed.
        """
        payload = self._query_json(
            ["query", "spo-stake-distribution", "--all-spos", "--output-json"]
        )

        entries = []
        for key, value in self._key_value_entries(payload):
            pool_id = self._parse_pool_key(key)
            stake = self._parse_lovelace(value)
            if pool_id is None or stake is None:
                continue
            entries.append(SPOStakeEntry(pool_id=pool_id, stake=stake))

        return entries

    # -- Query helpers ----------------------------------------------------

    @staticmethod
    def _load_json(result: str, command: str) -> Any:
        """Parse cli output as JSON, tolerating leading diagnostics.

        ``query kes-period-info`` prints its checks before the JSON document,
        so a plain :func:`json.loads` is retried from the first brace.

        Args:
            result (str): The cli's stdout.
            command (str): The command that produced it, for the error message.

        Returns:
            Any: The parsed document.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When no JSON
                document can be read out of `result`.
        """
        text = result.strip() if isinstance(result, str) else result
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass

        if isinstance(text, str):
            for opening in ("{", "["):
                start = text.find(opening)
                if start == -1:
                    continue
                try:
                    payload, _ = json.JSONDecoder().raw_decode(text[start:])
                    return payload
                except json.JSONDecodeError:
                    continue

        raise CardanoCLIError(
            command=command,
            message=f"Unable to parse `{command}` output as JSON: {result!r}",
        )

    def _query_json(self, cmd: List[str]) -> Any:
        """Run a network query and parse its JSON output.

        Args:
            cmd (List[str]): The cli arguments, without the network arguments.

        Returns:
            Any: The parsed document.
        """
        result = self._run_command(cmd + self._network_args)
        return self._load_json(result, " ".join(cmd))

    def _query_gov_state(self) -> JsonDict:
        """The parsed ``cardano-cli query gov-state`` document.

        Returns:
            JsonDict: The governance state.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When the output is
                not a JSON object.
        """
        payload = self._query_json(["query", "gov-state", "--output-json"])
        if not isinstance(payload, dict):
            raise CardanoCLIError(
                command="query gov-state",
                message=f"Unexpected gov-state output: {payload!r}",
            )
        return payload

    @staticmethod
    def _gov_state_proposals(gov_state: JsonDict) -> List[JsonDict]:
        """The proposal entries of a gov-state document.

        Args:
            gov_state (JsonDict): The parsed gov-state document.

        Returns:
            List[JsonDict]: The proposals, empty when none are active.
        """
        proposals = gov_state.get("proposals")
        if not isinstance(proposals, list):
            return []
        return [proposal for proposal in proposals if isinstance(proposal, dict)]

    @staticmethod
    def _key_value_entries(payload: Any) -> List[Tuple[str, Any]]:
        """Normalise a cli map that may be emitted as an object or as pairs.

        ``query drep-stake-distribution`` and ``query spo-stake-distribution``
        emit either a JSON object keyed by credential, or an array of
        ``[key, value]`` pairs, depending on the release.

        Args:
            payload (Any): The parsed document.

        Returns:
            List[Tuple[str, Any]]: The key/value pairs it holds.
        """
        if isinstance(payload, dict):
            return [(str(key), value) for key, value in payload.items()]
        if isinstance(payload, list):
            pairs = []
            for entry in payload:
                if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    pairs.append((str(entry[0]), entry[1]))
            return pairs
        return []

    # -- Parsing helpers --------------------------------------------------

    @staticmethod
    def _pool_operator(pool_id: str) -> PoolOperator:
        """Decode a pool id given as bech32 or hex.

        Args:
            pool_id (str): The pool's ID.

        Returns:
            PoolOperator: The decoded operator.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When it cannot be
                decoded.
        """
        try:
            return PoolOperator.from_primitive(pool_id)
        except Exception as err:  # noqa: BLE001 - any decoding failure is fatal here
            raise CardanoCLIError(
                command="query pool-state",
                message=f"Unable to decode stake pool id {pool_id!r}: {err}",
            ) from err

    @staticmethod
    def _pool_keyed_value(payload: Any, pool_operator: PoolOperator) -> Any:
        """Look a pool up in a cli map keyed by pool id.

        Releases differ on whether the key is the raw hex key hash, a
        ``keyHash-`` prefixed hex string, or the bech32 pool id.

        Args:
            payload (Any): The map to search.
            pool_operator (PoolOperator): The pool to find.

        Returns:
            Any: The matching value, or ``None``.
        """
        if not isinstance(payload, dict):
            return None

        pool_hash = pool_operator.pool_key_hash.payload.hex()
        candidates = {pool_hash, f"keyHash-{pool_hash}", pool_operator.encode()}
        for key, value in payload.items():
            if str(key).lower() in candidates:
                return value
        return None

    @staticmethod
    def _split_credential_key(key: str) -> Optional[Tuple[str, bytes]]:
        """Split a ``keyHash-<hex>`` / ``scriptHash-<hex>`` cli map key.

        Args:
            key (str): The map key.

        Returns:
            Optional[Tuple[str, bytes]]: ``("key" | "script", hash bytes)``, or
            ``None`` when the key is not shaped that way.
        """
        for prefix, kind in (("keyHash-", "key"), ("scriptHash-", "script")):
            if key.startswith(prefix):
                try:
                    return kind, bytes.fromhex(key[len(prefix) :])
                except ValueError:
                    return None
        return None

    @classmethod
    def _parse_committee_cold_key(cls, key: str) -> Optional[CommitteeColdCredential]:
        """Parse a committee cold credential from a cli map key.

        Args:
            key (str): The map key.

        Returns:
            Optional[CommitteeColdCredential]: The credential, or ``None``.
        """
        split = cls._split_credential_key(key)
        if split is None:
            return None
        kind, payload = split
        try:
            if kind == "script":
                return CommitteeColdCredential(ScriptHash(payload))
            return CommitteeColdCredential(VerificationKeyHash(payload))
        except (AssertionError, ValueError, TypeError):
            return None

    @classmethod
    def _parse_committee_hot_key(cls, key: str) -> Optional[CommitteeHotCredential]:
        """Parse a committee hot credential from a cli map key.

        Args:
            key (str): The map key.

        Returns:
            Optional[CommitteeHotCredential]: The credential, or ``None``.
        """
        split = cls._split_credential_key(key)
        if split is None:
            return None
        kind, payload = split
        try:
            if kind == "script":
                return CommitteeHotCredential(ScriptHash(payload))
            return CommitteeHotCredential(VerificationKeyHash(payload))
        except (AssertionError, ValueError, TypeError):
            return None

    @staticmethod
    def _parse_hot_creds_auth_status(value: Any) -> Optional[CommitteeHotCredential]:
        """Parse a committee entry's ``hotCredsAuthStatus`` object.

        Args:
            value (Any): The object, as emitted by the cli.

        Returns:
            Optional[CommitteeHotCredential]: The authorized hot credential, or
            ``None`` when the member has authorized none.
        """
        if not isinstance(value, dict):
            return None

        contents = value.get("contents")
        if not isinstance(contents, dict):
            return None

        try:
            key_hash = contents.get("keyHash")
            if isinstance(key_hash, str):
                return CommitteeHotCredential(
                    VerificationKeyHash(bytes.fromhex(key_hash))
                )
            script_hash = contents.get("scriptHash")
            if isinstance(script_hash, str):
                return CommitteeHotCredential(ScriptHash(bytes.fromhex(script_hash)))
        except (AssertionError, ValueError, TypeError):
            return None

        return None

    @staticmethod
    def _parse_committee_member_status(value: Any) -> Optional[CommitteeMemberStatus]:
        """Parse a committee member's status string.

        Args:
            value (Any): The ``status`` field, e.g. ``"Active"``.

        Returns:
            Optional[CommitteeMemberStatus]: The status, or ``None`` when the
            cli reports one this library does not model.
        """
        if not isinstance(value, str):
            return None
        try:
            return CommitteeMemberStatus(value.lower())
        except ValueError:
            return None

    @staticmethod
    def _parse_drep_key(key: str) -> Optional[DRep]:
        """Parse a DRep from a cli map key.

        ``query drep-stake-distribution`` prefixes its keys with ``drep-``;
        the vote maps in gov-state do not.

        Args:
            key (str): The map key.

        Returns:
            Optional[DRep]: The DRep, or ``None`` when the key is not one.
        """
        stripped = key[len("drep-") :] if key.startswith("drep-") else key

        if stripped.lower() == "alwaysabstain":
            return DRep(kind=DRepKind.ALWAYS_ABSTAIN)
        if stripped.lower() == "alwaysnoconfidence":
            return DRep(kind=DRepKind.ALWAYS_NO_CONFIDENCE)

        split = CardanoCliChainContext._split_credential_key(stripped)
        if split is None:
            return None
        kind, payload = split
        try:
            if kind == "script":
                return DRep(kind=DRepKind.SCRIPT_HASH, credential=ScriptHash(payload))
            return DRep(
                kind=DRepKind.VERIFICATION_KEY_HASH,
                credential=VerificationKeyHash(payload),
            )
        except (AssertionError, ValueError, TypeError):
            return None

    @staticmethod
    def _parse_pool_key(key: str) -> Optional[str]:
        """Parse a pool id from a cli map key into its bech32 form.

        Args:
            key (str): The map key: bech32, raw hex, or ``keyHash-`` prefixed
                hex, depending on the command.

        Returns:
            Optional[str]: The bech32 pool id, or ``None``.
        """
        stripped = key[len("keyHash-") :] if key.startswith("keyHash-") else key
        try:
            return PoolOperator.from_primitive(stripped).encode()
        except Exception:  # noqa: BLE001 - an unparseable key is simply skipped
            return None

    @staticmethod
    def _parse_lovelace(value: Any) -> Optional[int]:
        """Parse a lovelace amount the cli may emit in several shapes.

        Args:
            value (Any): A number, a numeric string, or an object wrapping a
                ``lovelace`` key.

        Returns:
            Optional[int]: The amount, or ``None`` when there is none.
        """
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return None
        if isinstance(value, dict):
            return CardanoCliChainContext._parse_lovelace(value.get("lovelace"))
        return None

    @staticmethod
    def _parse_threshold(value: Any) -> Optional[float]:
        """Parse a quorum or voting threshold.

        Args:
            value (Any): A number, a numeric string, a ``[numerator,
                denominator]`` pair, or a ``{"numerator", "denominator"}``
                object.

        Returns:
            Optional[float]: The threshold, or ``None`` when it cannot be read.
        """
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        if isinstance(value, dict):
            numerator = value.get("numerator")
            denominator = value.get("denominator")
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            numerator, denominator = value[0], value[1]
        else:
            return None

        if isinstance(numerator, (int, float)) and denominator:
            return float(numerator) / float(denominator)
        return None

    @staticmethod
    def _parse_fraction(value: Any) -> Optional[Fraction]:
        """Parse a ratio the cli emits as a decimal or as a numerator pair.

        Args:
            value (Any): The value to parse.

        Returns:
            Optional[Fraction]: The exact fraction, or ``None``.
        """
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int):
            return Fraction(value, 1)
        if isinstance(value, float):
            return Fraction(str(value))
        if isinstance(value, str):
            try:
                return Fraction(value)
            except (ValueError, ZeroDivisionError):
                return None
        if isinstance(value, dict):
            numerator = value.get("numerator")
            denominator = value.get("denominator")
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            numerator, denominator = value[0], value[1]
        else:
            return None

        if isinstance(numerator, int) and isinstance(denominator, int) and denominator:
            return Fraction(numerator, denominator)
        return None

    @staticmethod
    def _parse_vote(value: Any) -> Optional[Vote]:
        """Parse a vote from the cli's spelling of it.

        Args:
            value (Any): ``"yes"``/``"VoteYes"``, ``"no"``/``"VoteNo"`` or
                ``"abstain"``/``"Abstain"``.

        Returns:
            Optional[Vote]: The vote, or ``None`` when unrecognised.
        """
        if not isinstance(value, str):
            return None
        votes = {
            "yes": Vote.YES,
            "voteyes": Vote.YES,
            "no": Vote.NO,
            "voteno": Vote.NO,
            "abstain": Vote.ABSTAIN,
            "voteabstain": Vote.ABSTAIN,
        }
        return votes.get(value.lower())

    @staticmethod
    def _parse_anchor(value: Any) -> Optional[Anchor]:
        """Parse an off-chain metadata anchor.

        Args:
            value (Any): An object with a ``url`` and a data hash.

        Returns:
            Optional[Anchor]: The anchor, or ``None`` when there is none.
        """
        if not isinstance(value, dict):
            return None

        url = value.get("url")
        data_hash = value.get("dataHash") or value.get("anchorDataHash")
        if not isinstance(url, str) or not isinstance(data_hash, str):
            return None

        try:
            return Anchor(url=url, data_hash=AnchorDataHash(bytes.fromhex(data_hash)))
        except (AssertionError, ValueError, TypeError):
            return None

    def _reward_account_bytes(self, value: Any) -> Optional[bytes]:
        """Build reward account bytes from a cli credential blob.

        The cli emits either the account's hex bytes, or a credential object
        that needs the network header byte prepended. When the object carries
        no network, this context's network is used.

        Args:
            value (Any): The credential blob or hex string.

        Returns:
            Optional[bytes]: The reward account bytes, or ``None``.
        """
        if isinstance(value, str):
            try:
                return bytes.fromhex(value)
            except ValueError:
                return None

        if not isinstance(value, dict):
            return None

        credential = value.get("credential")
        credential = credential if isinstance(credential, dict) else value

        network = value.get("network")
        if isinstance(network, str):
            mainnet = network.lower() == "mainnet"
        else:
            mainnet = self._network is Network.MAINNET

        key_hash = credential.get("keyHash")
        script_hash = credential.get("scriptHash")
        if isinstance(key_hash, str):
            header = 0xE1 if mainnet else 0xE0
            hash_hex = key_hash
        elif isinstance(script_hash, str):
            header = 0xF1 if mainnet else 0xF0
            hash_hex = script_hash
        else:
            return None

        try:
            return bytes([header]) + bytes.fromhex(hash_hex)
        except ValueError:
            return None

    def _parse_reward_address(self, value: Any) -> Optional[str]:
        """Parse a reward account into its bech32 stake address.

        Args:
            value (Any): The credential blob or hex string the cli emits.

        Returns:
            Optional[str]: The bech32 stake address, or ``None``.
        """
        account = self._reward_account_bytes(value)
        if account is None:
            return None
        try:
            return str(Address.from_primitive(account))
        except Exception:  # noqa: BLE001 - an unparseable account is reported as absent
            return None

    # -- Governance action parsing ----------------------------------------

    @classmethod
    def _parse_gov_action_id(cls, value: Any) -> Optional[GovActionId]:
        """Parse a governance action id object.

        Args:
            value (Any): A ``{"txId", "govActionIx"}`` object.

        Returns:
            Optional[GovActionId]: The id, or ``None``.
        """
        if not isinstance(value, dict):
            return None

        tx_id = value.get("txId")
        index = value.get("govActionIx")
        if not isinstance(tx_id, str) or not isinstance(index, int):
            return None

        try:
            return GovActionId(
                transaction_id=TransactionId(bytes.fromhex(tx_id)),
                gov_action_index=index,
            )
        except (AssertionError, ValueError, TypeError):
            return None

    @classmethod
    def _proposal_action_id(cls, proposal: JsonDict) -> Optional[GovActionId]:
        """The action id a gov-state proposal entry carries.

        Args:
            proposal (JsonDict): One entry of ``gov-state``'s ``proposals``.

        Returns:
            Optional[GovActionId]: The id, or ``None``.
        """
        return cls._parse_gov_action_id(proposal.get("actionId"))

    @classmethod
    def _find_proposal(
        cls, proposals: List[JsonDict], gov_action_id: GovActionId
    ) -> Optional[JsonDict]:
        """Find the proposal for an action id.

        Args:
            proposals (List[JsonDict]): The gov-state proposals.
            gov_action_id (GovActionId): The action to find.

        Returns:
            Optional[JsonDict]: The matching proposal, or ``None``.
        """
        for proposal in proposals:
            if cls._proposal_action_id(proposal) == gov_action_id:
                return proposal
        return None

    @classmethod
    def _action_listed(cls, entries: Any, gov_action_id: GovActionId) -> bool:
        """Whether an action appears in one of ``nextRatifyState``'s lists.

        Entries are either action ids or objects wrapping one under
        ``actionId``.

        Args:
            entries (Any): The list to search.
            gov_action_id (GovActionId): The action to look for.

        Returns:
            bool: ``True`` when the action is listed.
        """
        if not isinstance(entries, list):
            return False

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if cls._parse_gov_action_id(entry.get("actionId")) == gov_action_id:
                return True
            if cls._parse_gov_action_id(entry) == gov_action_id:
                return True
        return False

    def _build_gov_action_votes(
        self,
        proposal: JsonDict,
        gov_action_id: GovActionId,
        current_epoch: int,
    ) -> GovActionVotes:
        """Turn one gov-state proposal into a :class:`GovActionVotes`.

        Args:
            proposal (JsonDict): The proposal entry.
            gov_action_id (GovActionId): Its action id.
            current_epoch (int): The current epoch, used to date an expiry the
                node has not yet processed.

        Returns:
            GovActionVotes: The proposal with its votes.
        """
        procedure = proposal.get("proposalProcedure")
        procedure = procedure if isinstance(procedure, dict) else {}

        expires_after = proposal.get("expiresAfter")
        expired = expires_after is not None and current_epoch > expires_after

        return GovActionVotes(
            gov_action_id=gov_action_id,
            gov_action=self._parse_gov_action(procedure.get("govAction")),
            committee_votes=self._parse_committee_votes(proposal.get("committeeVotes")),
            drep_votes=self._parse_drep_votes(proposal.get("dRepVotes")),
            stake_pool_votes=self._parse_stake_pool_votes(
                proposal.get("stakePoolVotes")
            ),
            deposit=self._parse_lovelace(procedure.get("deposit")),
            deposit_return_addr=self._parse_reward_address(procedure.get("returnAddr")),
            anchor=self._parse_anchor(procedure.get("anchor")),
            proposed_in=proposal.get("proposedIn"),
            expires_after=expires_after,
            expired_epoch=current_epoch if expired else None,
        )

    @classmethod
    def _parse_committee_votes(cls, value: Any) -> List[CommitteeVote]:
        """Parse a proposal's ``committeeVotes`` map.

        Args:
            value (Any): The map, keyed by the voting hot credential.

        Returns:
            List[CommitteeVote]: The votes; empty when none were cast.
        """
        votes = []
        for key, raw_vote in cls._key_value_entries(value):
            voter = cls._parse_committee_hot_key(key)
            vote = cls._parse_vote(raw_vote)
            if voter is None or vote is None:
                continue
            votes.append(CommitteeVote(voter=voter, vote=vote))
        return votes

    @classmethod
    def _parse_drep_votes(cls, value: Any) -> List[DRepVote]:
        """Parse a proposal's ``dRepVotes`` map.

        Args:
            value (Any): The map, keyed by the voting DRep.

        Returns:
            List[DRepVote]: The votes; empty when none were cast.
        """
        votes = []
        for key, raw_vote in cls._key_value_entries(value):
            voter = cls._parse_drep_key(key)
            vote = cls._parse_vote(raw_vote)
            if voter is None or vote is None:
                continue
            votes.append(DRepVote(voter=voter, vote=vote))
        return votes

    @classmethod
    def _parse_stake_pool_votes(cls, value: Any) -> List[StakePoolVote]:
        """Parse a proposal's ``stakePoolVotes`` map.

        Args:
            value (Any): The map, keyed by the voting pool.

        Returns:
            List[StakePoolVote]: The votes; empty when none were cast.
        """
        votes = []
        for key, raw_vote in cls._key_value_entries(value):
            voter = cls._parse_pool_key(key)
            vote = cls._parse_vote(raw_vote)
            if voter is None or vote is None:
                continue
            votes.append(StakePoolVote(voter=voter, vote=vote))
        return votes

    def _parse_gov_action(self, value: Any) -> Any:
        """Parse a proposal's ``govAction`` into a pycardano governance action.

        Args:
            value (Any): The ``{"tag", "contents"}`` object the cli emits.

        Returns:
            Any: The pycardano action, or the cli's own object unchanged when
            this backend cannot map that variant -- notably ``UpdateCommittee``,
            whose pycardano representation needs hashable committee credentials
            that pycardano does not provide. Returning the raw object keeps the
            caller's view faithful instead of substituting a placeholder action.
        """
        if not isinstance(value, dict):
            return value

        tag = value.get("tag")
        contents = value.get("contents")
        contents = contents if isinstance(contents, list) else []

        def previous(index: int = 0) -> Optional[GovActionId]:
            return (
                self._parse_gov_action_id(contents[index])
                if len(contents) > index
                else None
            )

        def script_hash(index: int) -> Optional[ScriptHash]:
            if len(contents) <= index or not isinstance(contents[index], str):
                return None
            try:
                return ScriptHash(bytes.fromhex(contents[index]))
            except (AssertionError, ValueError):
                return None

        try:
            if tag == "InfoAction":
                return InfoAction()

            if tag == "NoConfidence":
                return NoConfidence(gov_action_id=previous())

            if tag == "ParameterChange":
                update = (
                    self._parse_protocol_param_update(contents[1])
                    if len(contents) > 1 and isinstance(contents[1], dict)
                    else ProtocolParamUpdate()
                )
                return ParameterChangeAction(
                    gov_action_id=previous(),
                    protocol_param_update=update,
                    policy_hash=script_hash(2),
                )

            if tag == "HardForkInitiation":
                version = contents[1] if len(contents) > 1 else None
                if not isinstance(version, dict):
                    return value
                major = version.get("major")
                minor = version.get("minor")
                if not isinstance(major, int) or not isinstance(minor, int):
                    return value
                # pycardano types the field as a Fraction but unpacks it as a
                # (major, minor) pair, which only a tuple satisfies.
                return HardForkInitiationAction(
                    gov_action_id=previous(),
                    protocol_version=cast(Fraction, (major, minor)),
                )

            if tag == "TreasuryWithdrawals":
                withdrawals = TreasuryWithdrawal()
                raw_withdrawals = contents[0] if contents else None
                if isinstance(raw_withdrawals, list):
                    for entry in raw_withdrawals:
                        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                            continue
                        account = self._reward_account_bytes(entry[0])
                        amount = self._parse_lovelace(entry[1])
                        if account is None or amount is None:
                            continue
                        withdrawals[account] = amount
                return TreasuryWithdrawalsAction(
                    withdrawals=withdrawals,
                    policy_hash=script_hash(1),
                )

            if tag == "NewConstitution":
                constitution = contents[1] if len(contents) > 1 else None
                if not isinstance(constitution, dict):
                    return value
                anchor = self._parse_anchor(constitution.get("anchor"))
                if anchor is None:
                    return value
                guardrail = constitution.get("script")
                guardrail_hash = None
                if isinstance(guardrail, str) and guardrail:
                    try:
                        guardrail_hash = ScriptHash(bytes.fromhex(guardrail))
                    except (AssertionError, ValueError):
                        guardrail_hash = None
                return NewConstitution(
                    gov_action_id=previous(),
                    constitution=(anchor, guardrail_hash),
                )
        except (AssertionError, ValueError, TypeError):
            # A variant whose payload does not fit its pycardano type is
            # reported as the cli emitted it, never as a different action.
            return value

        return value

    @classmethod
    def _parse_protocol_param_update(cls, params: JsonDict) -> ProtocolParamUpdate:
        """Parse the protocol parameter update of a ``ParameterChange`` action.

        Only the parameters the update actually names are set; everything else
        stays ``None``. Cost models are carried through as the cli reports
        them, keyed by language name.

        Args:
            params (JsonDict): The update object.

        Returns:
            ProtocolParamUpdate: The parsed update.
        """

        def integer(*keys: str) -> Optional[int]:
            for key in keys:
                value = params.get(key)
                if isinstance(value, bool):
                    continue
                if isinstance(value, int):
                    return value
                if isinstance(value, float):
                    return int(value)
            return None

        def fraction(*keys: str) -> Optional[Fraction]:
            for key in keys:
                if key in params:
                    parsed = cls._parse_fraction(params[key])
                    if parsed is not None:
                        return parsed
            return None

        def execution_units(*keys: str) -> Optional[ExecutionUnits]:
            for key in keys:
                value = params.get(key)
                if not isinstance(value, dict):
                    continue
                memory = value.get("memory", value.get("mem"))
                steps = value.get("steps", value.get("step"))
                if isinstance(memory, int) and isinstance(steps, int):
                    return ExecutionUnits(mem=memory, steps=steps)
            return None

        update = ProtocolParamUpdate(
            min_fee_a=integer("txFeePerByte", "minFeeA"),
            min_fee_b=integer("txFeeFixed", "minFeeB"),
            max_block_body_size=integer("maxBlockBodySize"),
            max_transaction_size=integer("maxTxSize", "maxTransactionSize"),
            max_block_header_size=integer("maxBlockHeaderSize"),
            key_deposit=integer("stakeAddressDeposit", "keyDeposit"),
            pool_deposit=integer("stakePoolDeposit", "poolDeposit"),
            maximum_epoch=integer("poolRetireMaxEpoch", "maximumEpoch"),
            n_opt=integer("stakePoolTargetNum", "nOpt"),
            pool_pledge_influence=fraction("poolPledgeInfluence"),
            expansion_rate=fraction("monetaryExpansion", "expansionRate"),
            treasury_growth_rate=fraction("treasuryCut", "treasuryGrowthRate"),
            min_pool_cost=integer("minPoolCost"),
            ada_per_utxo_byte=integer("utxoCostPerByte", "adaPerUTxOByte"),
            max_value_size=integer("maxValueSize"),
            collateral_percentage=integer("collateralPercentage"),
            max_collateral_inputs=integer("maxCollateralInputs"),
            min_committee_size=integer("committeeMinSize", "minCommitteeSize"),
            committee_term_limit=integer(
                "committeeMaxTermLength", "committeeTermLimit"
            ),
            governance_action_validity_period=integer(
                "govActionLifetime", "governanceActionValidityPeriod"
            ),
            governance_action_deposit=integer(
                "govActionDeposit", "governanceActionDeposit"
            ),
            drep_deposit=integer("dRepDeposit", "drepDeposit"),
            drep_inactivity_period=integer("dRepActivity", "drepInactivityPeriod"),
            min_fee_ref_script_cost=fraction(
                "minFeeRefScriptCostPerByte", "minFeeRefScriptCoinsPerByte"
            ),
            max_tx_ex_units=execution_units("maxTxExecutionUnits", "maxTxExUnits"),
            max_block_ex_units=execution_units(
                "maxBlockExecutionUnits", "maxBlockExUnits"
            ),
        )

        cost_models = params.get("costModels")
        if isinstance(cost_models, dict) and cost_models:
            update.cost_models = cost_models

        prices = params.get("executionUnitPrices", params.get("executionCosts"))
        if isinstance(prices, dict):
            memory_price = cls._parse_fraction(prices.get("priceMemory"))
            step_price = cls._parse_fraction(prices.get("priceSteps"))
            if memory_price is not None and step_price is not None:
                update.execution_costs = ExUnitPrices(
                    mem_price=memory_price, step_price=step_price
                )

        pool_thresholds = params.get("poolVotingThresholds")
        if isinstance(pool_thresholds, dict):
            values = [
                cls._parse_fraction(pool_thresholds.get(key))
                for key in (
                    "motionNoConfidence",
                    "committeeNormal",
                    "committeeNoConfidence",
                    "hardForkInitiation",
                    "ppSecurityGroup",
                )
            ]
            if all(value is not None for value in values):
                update.pool_voting_thresholds = PoolVotingThresholds(
                    *cast(List[Fraction], values)
                )

        drep_thresholds = params.get("dRepVotingThresholds")
        if isinstance(drep_thresholds, dict):
            values = [
                cls._parse_fraction(drep_thresholds.get(key))
                for key in (
                    "motionNoConfidence",
                    "committeeNormal",
                    "committeeNoConfidence",
                    "updateToConstitution",
                    "hardForkInitiation",
                    "ppNetworkGroup",
                    "ppEconomicGroup",
                    "ppTechnicalGroup",
                    "ppGovGroup",
                    "treasuryWithdrawal",
                )
            ]
            if all(value is not None for value in values):
                update.drep_voting_thresholds = DRepVotingThresholds(
                    *cast(List[Fraction], values)
                )

        return update

    # -- Stake pool parameter parsing -------------------------------------

    #: Seconds to wait for an off-chain pool metadata document under `strict`.
    _METADATA_TIMEOUT = 10

    def _parse_pool_params(
        self,
        pool_operator: PoolOperator,
        params: JsonDict,
        strict: bool,
    ) -> PoolParams:
        """Parse ``query pool-state``'s registered parameters.

        Args:
            pool_operator (PoolOperator): The pool the parameters belong to;
                the cli carries it as the map key, not inside the object.
            params (JsonDict): The ``poolParams`` object.
            strict (bool): Whether to fetch and hash-verify the off-chain
                metadata document.

        Returns:
            PoolParams: The registered parameters.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When a required
                parameter is missing or malformed, or -- with ``strict`` -- the
                off-chain metadata cannot be verified.
        """

        def required(*keys: str) -> Any:
            for key in keys:
                if params.get(key) is not None:
                    return params[key]
            raise CardanoCLIError(
                command="query pool-state",
                message=f"Pool parameters are missing {keys[0]}",
            )

        vrf = required("spsVrf", "vrf")
        pledge = self._parse_lovelace(required("spsPledge", "pledge"))
        cost = self._parse_lovelace(required("spsCost", "cost"))
        margin = self._parse_fraction(required("spsMargin", "margin"))
        if pledge is None or cost is None or margin is None:
            raise CardanoCLIError(
                command="query pool-state",
                message=f"Pool parameters are malformed: {params!r}",
            )

        reward_account = self._reward_account_bytes(
            required("spsAccountId", "spsRewardAccount", "rewardAccount")
        )
        if reward_account is None:
            raise CardanoCLIError(
                command="query pool-state",
                message="Pool parameters carry no readable reward account",
            )

        owners = params.get("spsOwners", params.get("owners")) or []
        pool_owners = []
        for owner in owners:
            if isinstance(owner, dict):
                owner = owner.get("keyHash")
            if isinstance(owner, str):
                pool_owners.append(VerificationKeyHash(bytes.fromhex(owner)))

        try:
            return PoolParams(
                operator=pool_operator.pool_key_hash,
                vrf_keyhash=VrfKeyHash(bytes.fromhex(str(vrf))),
                pledge=pledge,
                cost=cost,
                margin=margin,
                reward_account=RewardAccountHash(reward_account),
                pool_owners=pool_owners,
                relays=self._parse_relays(
                    params.get("spsRelays", params.get("relays"))
                ),
                pool_metadata=self._parse_pool_metadata(
                    params.get("spsMetadata", params.get("metadata")), strict
                ),
            )
        except (AssertionError, ValueError, TypeError) as err:
            raise CardanoCLIError(
                command="query pool-state",
                message=f"Pool parameters are malformed: {err}",
            ) from err

    @staticmethod
    def _parse_relays(value: Any) -> List[Any]:
        """Parse the relay list of a pool's registered parameters.

        Args:
            value (Any): The ``spsRelays`` array.

        Returns:
            List[Any]: The relays, in the order the cli reported them.
        """
        if not isinstance(value, list):
            return []

        relays: List[Any] = []
        for entry in value:
            if not isinstance(entry, dict):
                continue
            for raw_kind, raw_relay in entry.items():
                if not isinstance(raw_relay, dict):
                    continue
                kind = raw_kind.lower().replace(" ", "")
                if kind in ("singlehostaddress", "singlehostaddr"):
                    relays.append(
                        SingleHostAddr(
                            port=raw_relay.get("port"),
                            ipv4=raw_relay.get("IPv4", raw_relay.get("ipv4")),
                            ipv6=raw_relay.get("IPv6", raw_relay.get("ipv6")),
                        )
                    )
                elif kind == "singlehostname":
                    relays.append(
                        SingleHostName(
                            port=raw_relay.get("port"),
                            dns_name=raw_relay.get("dnsName"),
                        )
                    )
                elif kind == "multihostname":
                    relays.append(MultiHostName(dns_name=raw_relay.get("dnsName")))
        return relays

    def _parse_pool_metadata(self, value: Any, strict: bool) -> Optional[PoolMetadata]:
        """Parse the registered metadata anchor, verifying it when strict.

        Args:
            value (Any): The ``spsMetadata`` object: a ``url`` and a ``hash``.
            strict (bool): Whether to fetch the document the url names and
                check its hash against the registered one.

        Returns:
            Optional[PoolMetadata]: The registered url and hash, or ``None``
            when the pool registered no metadata.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: With ``strict``, when
                the document cannot be fetched or its hash does not match.
        """
        if not isinstance(value, dict):
            return None

        url = value.get("url")
        metadata_hash = value.get("hash")
        if not isinstance(url, str) or not isinstance(metadata_hash, str):
            return None

        if strict:
            self._verify_pool_metadata(url, metadata_hash)

        try:
            return PoolMetadata(
                url=url,
                pool_metadata_hash=PoolMetadataHash(bytes.fromhex(metadata_hash)),
            )
        except (AssertionError, ValueError) as err:
            if strict:
                raise CardanoCLIError(
                    command="query pool-state",
                    message=f"Registered pool metadata hash is malformed: {err}",
                ) from err
            return None

    def _verify_pool_metadata(self, url: str, metadata_hash: str) -> None:
        """Fetch a pool's off-chain metadata and verify its registered hash.

        Args:
            url (str): The registered metadata url.
            metadata_hash (str): The registered blake2b-256 hash, hex encoded.

        Raises:
            :class:`pccontext.exceptions.CardanoCLIError`: When the document
                cannot be fetched, or its hash does not match.
        """
        try:
            response = requests.get(url, timeout=self._METADATA_TIMEOUT)
            response.raise_for_status()
        except RequestException as err:
            raise CardanoCLIError(
                command="query pool-state",
                message=f"Unable to fetch off-chain pool metadata from {url}: {err}",
            ) from err

        digest = hashlib.blake2b(response.content, digest_size=32).hexdigest()
        if digest != metadata_hash.lower():
            raise CardanoCLIError(
                command="query pool-state",
                message=(
                    f"Off-chain pool metadata at {url} hashes to {digest}, but "
                    f"{metadata_hash.lower()} is registered on-chain"
                ),
            )
