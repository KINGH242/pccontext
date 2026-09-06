from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar, Union

from pycardano import (
    Anchor,
    CommitteeColdCredential,
    CommitteeHotCredential,
    DRep,
    GovActionId,
    PoolOperator,
    PoolParams,
    Vote,
)

from pccontext.enums import (
    CommitteeMemberStatus,
    DRepStatus,
    Era,
    HistoryType,
    Network,
    PoolStatus,
    TransactionType,
)
from pccontext.models import BaseModel
from pccontext.utils import DATE_FORMAT_2, check_file_exists, dump_file, load_json_file

from .address_info_model import AddressInfo
from .committee_model import CommitteeMemberInfo, CommitteeStateInfo
from .drep_info_model import DRepInfo
from .genesis_parameters_model import GenesisParameters
from .gov_action_info_model import GovActionInfo
from .gov_action_votes_model import (
    CommitteeVote,
    DRepVote,
    GovActionVotes,
    StakePoolVote,
)
from .kes_period_info_model import KESPeriodInfo
from .protocol_parameters_model import ProtocolParameters
from .stake_distribution_model import DRepStakeEntry, SPOStakeEntry
from .stake_pool_info_model import StakePoolInfo
from .token_metadata_model import TokenMetadata

__all__ = [
    "OfflineTransferGeneral",
    "OfflineTransferProtocol",
    "OfflineTransferHistory",
    "OfflineTransferFile",
    "OfflineTransferTransaction",
    "OfflineTransfer",
    "TransactionJSON",
]

# --------------------------------------------------------------------------
# Codecs for the pool and governance sections
#
# The chain-query return models hold :mod:`pycardano` values — ``PoolParams``,
# ``DRep``, committee credentials, ``Anchor`` — that have no JSON form of their
# own, so :meth:`BaseModel.to_dict` would leave them in the result as opaque
# objects that :func:`json.dumps` then rejects. Each is wrapped as its CBOR hex
# instead, which is exact and reversible. Identifiers that already have a
# canonical text form — a bech32 pool ID, a bech32 governance action ID — are
# stored in that form because a human reads the transfer file.
# --------------------------------------------------------------------------

C = TypeVar("C")
E = TypeVar("E", bound=Enum)


def _to_cbor_hex(value: Optional[Any]) -> Optional[str]:
    """CBOR-encode a pycardano value to a hex string.

    Args:
        value (Optional[Any]): The value to encode, or ``None``.

    Returns:
        Optional[str]: The CBOR hex, or ``None`` if ``value`` is ``None``.
    """
    return None if value is None else value.to_cbor_hex()


def _from_cbor_hex(cls: Type[C], value: Optional[Any]) -> Optional[C]:
    """Decode a CBOR hex string back into a pycardano value.

    Args:
        cls (Type[C]): The pycardano class to decode into.
        value (Optional[Any]): The CBOR hex string. A value that is already an
            instance of ``cls`` is returned unchanged, so a section built in
            memory round-trips as readily as one loaded from disk.

    Returns:
        Optional[C]: The decoded value, or ``None`` if it could not be decoded.
    """
    if value is None or isinstance(value, cls):
        return value
    with contextlib.suppress(Exception):
        return cls.from_cbor(value)  # type: ignore[attr-defined]
    return None


def _enum_value(value: Optional[Enum]) -> Optional[Any]:
    """Return an enum member's value, passing ``None`` through."""
    return None if value is None else value.value


def _enum_from(cls: Type[E], value: Optional[Any]) -> Optional[E]:
    """Rebuild an enum member from its value, tolerating an unknown one.

    Args:
        cls (Type[E]): The enum class.
        value (Optional[Any]): The stored value, or an already-built member.

    Returns:
        Optional[E]: The member, or ``None`` when the value is absent or not a
        member of ``cls``.
    """
    if value is None or isinstance(value, cls):
        return value
    with contextlib.suppress(ValueError):
        return cls(str(value).lower())
    return None


def _as_int(value: Optional[Any]) -> Optional[int]:
    """Coerce a stored number to ``int``, or ``None`` if it is not one."""
    if value is None:
        return None
    with contextlib.suppress(TypeError, ValueError):
        return int(value)
    return None


def _as_decimal(value: Optional[Any]) -> Optional[Decimal]:
    """Coerce a stored number to ``Decimal``, or ``None`` if it is not one."""
    if value is None:
        return None
    with contextlib.suppress(ArithmeticError, TypeError, ValueError):
        return Decimal(str(value))
    return None


def _vote_to_name(vote: Optional[Vote]) -> Optional[str]:
    """Store a vote by name — ``"YES"`` reads better than ``1``."""
    return None if vote is None else vote.name


def _vote_from_name(value: Optional[Any]) -> Optional[Vote]:
    """Rebuild a :class:`Vote` from the name stored by :func:`_vote_to_name`."""
    if value is None or isinstance(value, Vote):
        return value
    with contextlib.suppress(KeyError):
        return Vote[str(value).upper()]
    return None


def _pool_operator_to_id(pool: Union[PoolOperator, str]) -> Optional[str]:
    """Encode a pool operator as its bech32 pool ID."""
    if isinstance(pool, str):
        return pool
    with contextlib.suppress(Exception):
        return pool.encode()
    return None


def _pool_operator_from_id(value: Union[PoolOperator, str]) -> Optional[PoolOperator]:
    """Decode a bech32 pool ID back into a :class:`PoolOperator`."""
    if isinstance(value, PoolOperator):
        return value
    with contextlib.suppress(Exception):
        return PoolOperator.decode(value)
    return None


def _gov_action_id_to_str(gov_action_id: Optional[GovActionId]) -> Optional[str]:
    """Encode a governance action ID as its bech32 ``gov_action1…`` form."""
    if gov_action_id is None:
        return None
    with contextlib.suppress(Exception):
        return gov_action_id.encode()
    return None


def _gov_action_id_from_str(value: Optional[Any]) -> Optional[GovActionId]:
    """Decode a bech32 governance action ID."""
    if value is None or isinstance(value, GovActionId):
        return value
    with contextlib.suppress(Exception):
        return GovActionId.decode(value)
    return None


def _stake_pool_info_to_dict(info: StakePoolInfo) -> Dict:
    """Encode a :class:`StakePoolInfo` for the transfer file."""
    return {
        "pool_params": _to_cbor_hex(info.pool_params),
        "live_pledge": info.live_pledge,
        "live_stake": info.live_stake,
        "live_size": None if info.live_size is None else str(info.live_size),
        "active_stake": info.active_stake,
        "active_size": None if info.active_size is None else str(info.active_size),
        "opcert_counter": info.opcert_counter,
        "status": _enum_value(info.status),
        "retiring_epoch": info.retiring_epoch,
    }


def _stake_pool_info_from_dict(value: Dict) -> StakePoolInfo:
    """Decode a :class:`StakePoolInfo` from the transfer file."""
    return StakePoolInfo(
        pool_params=_from_cbor_hex(PoolParams, value.get("pool_params")),
        live_pledge=_as_int(value.get("live_pledge")),
        live_stake=_as_int(value.get("live_stake")),
        live_size=_as_decimal(value.get("live_size")),
        active_stake=_as_int(value.get("active_stake")),
        active_size=_as_decimal(value.get("active_size")),
        opcert_counter=_as_int(value.get("opcert_counter")),
        status=_enum_from(PoolStatus, value.get("status")),
        retiring_epoch=_as_int(value.get("retiring_epoch")),
    )


def _drep_info_to_dict(info: DRepInfo) -> Dict:
    """Encode a :class:`DRepInfo` for the transfer file."""
    return {
        "drep": _to_cbor_hex(info.drep),
        "active": info.active,
        "anchor": _to_cbor_hex(info.anchor),
        "deposit": info.deposit,
        "stake": info.stake,
        "expiry": info.expiry,
        "status": _enum_value(info.status),
    }


def _drep_info_from_dict(value: Dict) -> DRepInfo:
    """Decode a :class:`DRepInfo` from the transfer file."""
    return DRepInfo(
        drep=_from_cbor_hex(DRep, value.get("drep")),
        active=bool(value.get("active", False)),
        anchor=_from_cbor_hex(Anchor, value.get("anchor")),
        deposit=_as_int(value.get("deposit")),
        stake=_as_int(value.get("stake")) or 0,
        expiry=_as_int(value.get("expiry")),
        status=_enum_from(DRepStatus, value.get("status")),
    )


def _gov_action_lifecycle_to_dict(info: Union[GovActionInfo, GovActionVotes]) -> Dict:
    """Encode the lifecycle epochs shared by an action and its vote aggregate."""
    return {
        "gov_action_id": _gov_action_id_to_str(info.gov_action_id),
        "gov_action": info.gov_action,
        "proposed_in": info.proposed_in,
        "expires_after": info.expires_after,
        "ratified_epoch": info.ratified_epoch,
        "enacted_epoch": info.enacted_epoch,
        "dropped_epoch": info.dropped_epoch,
        "expired_epoch": info.expired_epoch,
    }


def _gov_action_lifecycle_from_dict(value: Dict) -> Dict:
    """Decode the lifecycle epochs into keyword arguments."""
    return {
        "gov_action_id": _gov_action_id_from_str(value.get("gov_action_id")),
        "gov_action": value.get("gov_action"),
        "proposed_in": _as_int(value.get("proposed_in")),
        "expires_after": _as_int(value.get("expires_after")),
        "ratified_epoch": _as_int(value.get("ratified_epoch")),
        "enacted_epoch": _as_int(value.get("enacted_epoch")),
        "dropped_epoch": _as_int(value.get("dropped_epoch")),
        "expired_epoch": _as_int(value.get("expired_epoch")),
    }


def _gov_action_info_to_dict(info: GovActionInfo) -> Dict:
    """Encode a :class:`GovActionInfo` for the transfer file."""
    return _gov_action_lifecycle_to_dict(info)


def _gov_action_info_from_dict(value: Dict) -> GovActionInfo:
    """Decode a :class:`GovActionInfo` from the transfer file."""
    return GovActionInfo(**_gov_action_lifecycle_from_dict(value))


def _committee_vote_to_dict(vote: CommitteeVote) -> Dict:
    """Encode one constitutional committee vote."""
    return {
        "voter": _to_cbor_hex(vote.voter),
        "vote": _vote_to_name(vote.vote),
        "anchor": _to_cbor_hex(vote.anchor),
    }


def _committee_vote_from_dict(value: Dict) -> CommitteeVote:
    """Decode one constitutional committee vote."""
    return CommitteeVote(
        voter=_from_cbor_hex(CommitteeHotCredential, value.get("voter")),
        vote=_vote_from_name(value.get("vote")),
        anchor=_from_cbor_hex(Anchor, value.get("anchor")),
    )


def _drep_vote_to_dict(vote: DRepVote) -> Dict:
    """Encode one DRep vote."""
    return {
        "voter": _to_cbor_hex(vote.voter),
        "vote": _vote_to_name(vote.vote),
        "anchor": _to_cbor_hex(vote.anchor),
    }


def _drep_vote_from_dict(value: Dict) -> DRepVote:
    """Decode one DRep vote."""
    return DRepVote(
        voter=_from_cbor_hex(DRep, value.get("voter")),
        vote=_vote_from_name(value.get("vote")),
        anchor=_from_cbor_hex(Anchor, value.get("anchor")),
    )


def _stake_pool_vote_to_dict(vote: StakePoolVote) -> Dict:
    """Encode one stake pool vote; the voter is already a bech32 pool ID."""
    return {
        "voter": vote.voter,
        "vote": _vote_to_name(vote.vote),
        "anchor": _to_cbor_hex(vote.anchor),
    }


def _stake_pool_vote_from_dict(value: Dict) -> StakePoolVote:
    """Decode one stake pool vote."""
    return StakePoolVote(
        voter=value.get("voter"),
        vote=_vote_from_name(value.get("vote")),
        anchor=_from_cbor_hex(Anchor, value.get("anchor")),
    )


def _gov_action_votes_to_dict(votes: GovActionVotes) -> Dict:
    """Encode a :class:`GovActionVotes` for the transfer file."""
    result = _gov_action_lifecycle_to_dict(votes)
    result.update(
        {
            "committee_votes": [
                _committee_vote_to_dict(v) for v in votes.committee_votes
            ],
            "drep_votes": [_drep_vote_to_dict(v) for v in votes.drep_votes],
            "stake_pool_votes": [
                _stake_pool_vote_to_dict(v) for v in votes.stake_pool_votes
            ],
            "deposit": votes.deposit,
            "deposit_return_addr": votes.deposit_return_addr,
            "anchor": _to_cbor_hex(votes.anchor),
        }
    )
    return result


def _gov_action_votes_from_dict(value: Dict) -> GovActionVotes:
    """Decode a :class:`GovActionVotes` from the transfer file.

    An absent vote list decodes to an empty one: a captured proposal that no
    committee member has voted on is indistinguishable, on the chain itself,
    from one whose committee votes were simply not written down.
    """
    return GovActionVotes(
        committee_votes=[
            _committee_vote_from_dict(v) for v in (value.get("committee_votes") or [])
        ],
        drep_votes=[_drep_vote_from_dict(v) for v in (value.get("drep_votes") or [])],
        stake_pool_votes=[
            _stake_pool_vote_from_dict(v) for v in (value.get("stake_pool_votes") or [])
        ],
        deposit=_as_int(value.get("deposit")),
        deposit_return_addr=value.get("deposit_return_addr"),
        anchor=_from_cbor_hex(Anchor, value.get("anchor")),
        **_gov_action_lifecycle_from_dict(value),
    )


def _committee_member_info_to_dict(member: CommitteeMemberInfo) -> Dict:
    """Encode a :class:`CommitteeMemberInfo` for the transfer file."""
    return {
        "cold_credential": _to_cbor_hex(member.cold_credential),
        "hot_credential": _to_cbor_hex(member.hot_credential),
        "expiration": member.expiration,
        "status": _enum_value(member.status),
    }


def _committee_member_info_from_dict(value: Dict) -> CommitteeMemberInfo:
    """Decode a :class:`CommitteeMemberInfo` from the transfer file."""
    return CommitteeMemberInfo(
        cold_credential=_from_cbor_hex(
            CommitteeColdCredential, value.get("cold_credential")
        ),
        hot_credential=_from_cbor_hex(
            CommitteeHotCredential, value.get("hot_credential")
        ),
        expiration=_as_int(value.get("expiration")),
        status=_enum_from(CommitteeMemberStatus, value.get("status")),
    )


def _committee_state_to_dict(state: CommitteeStateInfo) -> Dict:
    """Encode a :class:`CommitteeStateInfo` for the transfer file."""
    return {
        "members": [_committee_member_info_to_dict(m) for m in state.members],
        "threshold": state.threshold,
    }


def _committee_state_from_dict(value: Dict) -> CommitteeStateInfo:
    """Decode a :class:`CommitteeStateInfo` from the transfer file."""
    threshold = value.get("threshold")
    return CommitteeStateInfo(
        members=[
            _committee_member_info_from_dict(m) for m in (value.get("members") or [])
        ],
        threshold=None if threshold is None else float(threshold),
    )


def _drep_stake_entry_to_dict(entry: DRepStakeEntry) -> Dict:
    """Encode one row of the DRep stake distribution."""
    return {"drep": _to_cbor_hex(entry.drep), "stake": entry.stake}


def _drep_stake_entry_from_dict(value: Dict) -> DRepStakeEntry:
    """Decode one row of the DRep stake distribution."""
    return DRepStakeEntry(
        drep=_from_cbor_hex(DRep, value.get("drep")),
        stake=_as_int(value.get("stake")) or 0,
    )


def _spo_stake_entry_to_dict(entry: SPOStakeEntry) -> Dict:
    """Encode one row of the stake pool stake distribution."""
    return {"pool_id": entry.pool_id, "stake": entry.stake}


def _spo_stake_entry_from_dict(value: Dict) -> SPOStakeEntry:
    """Decode one row of the stake pool stake distribution."""
    return SPOStakeEntry(
        pool_id=value.get("pool_id"),
        stake=_as_int(value.get("stake")) or 0,
    )


@dataclass(frozen=True)
class OfflineTransferGeneral(BaseModel):
    """
    Offline transfer json file general property model class
    """

    offline_cli_version: Optional[str] = field(
        default=None,
        metadata={"aliases": ["offline_cli_version", "offlineCliVersion"]},
    )
    online_cli_version: Optional[str] = field(
        default=None,
        metadata={"aliases": ["online_cli_version", "onlineCliVersion"]},
    )
    online_node_version: Optional[str] = field(
        default=None,
        metadata={"aliases": ["online_node_version", "onlineNodeVersion"]},
    )


@dataclass(frozen=True)
class OfflineTransferProtocol(BaseModel):
    """
    Offline transfer json file protocol property model class
    """

    protocol_parameters: Optional[ProtocolParameters] = None
    genesis_parameters: Optional[GenesisParameters] = None
    era: Optional[Era] = None
    network: Optional[Network] = None

    @classmethod
    def property_from_dict(
        cls: Type[OfflineTransferProtocol],
        value: Dict,
        key: str,
        field_name: str,
        init_args: Dict,
    ):
        """
        Parse the property from a dictionary
        :param value: The value
        :param key: The key
        :param field_name: The field name
        :param init_args: The initialization arguments
        :return: The property
        """
        if field_name == "protocol_parameters":
            return ProtocolParameters.from_dict(value)
        elif field_name == "genesis_parameters":
            return GenesisParameters.from_dict(value)


@dataclass(frozen=True)
class OfflineTransferHistory(BaseModel):
    """
    Offline transfer json file history property model class
    """

    date: Optional[str] = field(
        default=datetime.now(timezone.utc).strftime(DATE_FORMAT_2)
    )
    action: Optional[str] = None


@dataclass(frozen=True)
class OfflineTransferFile(BaseModel):
    """
    Offline transfer json file property model class
    """

    name: Optional[str] = None
    date: Optional[str] = field(
        default=datetime.now(timezone.utc).strftime(DATE_FORMAT_2)
    )
    size: Optional[int] = None
    base64: Optional[bytes] = None


@dataclass(frozen=True)
class TransactionJSON(BaseModel):
    """
    Offline transfer json file property model class
    """

    type: Optional[str] = None
    description: Optional[str] = None
    cborHex: Optional[str] = None


@dataclass(frozen=True)
class OfflineTransferTransaction(BaseModel):
    """
    Offline transfer json transaction property model class
    """

    type: Optional[TransactionType] = None
    date: Optional[str] = field(
        default=datetime.now(timezone.utc).strftime(DATE_FORMAT_2)
    )
    era: Optional[Era] = None
    stake_address: Optional[str] = field(
        default=None,
        metadata={"aliases": ["stake_address", "stakeAddress"]},
    )
    from_address: Optional[str] = field(
        default=None,
        metadata={"aliases": ["from_address", "fromAddress"]},
    )
    from_name: Optional[str] = field(
        default=None,
        metadata={"aliases": ["from_name", "fromName"]},
    )
    to_address: Optional[str] = field(
        default=None,
        metadata={"aliases": ["to_address", "toAddress"]},
    )
    to_name: Optional[str] = field(
        default=None,
        metadata={"aliases": ["to_name", "toName"]},
    )
    tx_json: Optional[TransactionJSON] = field(
        default=None,
        metadata={"aliases": ["tx_json", "txJson"]},
    )

    @classmethod
    def property_from_dict(
        cls: Type[OfflineTransferTransaction],
        value: Dict,
        key: str,
        field_name: str,
        init_args: Dict,
    ):
        """
        Parse the property from a dictionary
        :param value: The value
        :param key: The key
        :param field_name: The field name
        :param init_args: The initialization arguments
        :return: The property
        """
        if field_name == "tx_json":
            return TransactionJSON.from_dict(value)


@dataclass(frozen=True)
class OfflineTransfer(BaseModel):
    """
    Offline transfer json file model class

    The pool and governance sections below are optional and default to ``None``,
    which means *the capture did not include this section* — as opposed to an
    empty list, which means *the section was captured and the chain had nothing
    in it*. A transfer file written before those sections existed therefore
    still loads, with every one of them ``None``; the offline chain context
    turns that into an error naming the missing section rather than pretending
    the chain is empty.
    """

    general: Optional[OfflineTransferGeneral] = None
    protocol: Optional[OfflineTransferProtocol] = None
    history: List[OfflineTransferHistory] = field(default_factory=list)
    files: List[OfflineTransferFile] = field(default_factory=list)
    transactions: List[OfflineTransferTransaction] = field(default_factory=list)
    addresses: List[AddressInfo] = field(default_factory=list)
    token_meta_server: List[TokenMetadata] = field(
        default_factory=list,
        metadata={"aliases": ["token_meta_server", "tokenMetaServer"]},
    )

    stake_pools: Optional[List[PoolOperator]] = None
    """Every stake pool registered on the chain, as bech32 pool IDs on disk."""

    stake_pool_infos: Optional[List[StakePoolInfo]] = None
    """Registered parameters and stake figures, one entry per captured pool."""

    kes_period_infos: Optional[List[KESPeriodInfo]] = None
    """KES period information captured for the operator's own pools."""

    treasury: Optional[int] = None
    """The treasury balance in lovelace, as of the capture's epoch."""

    drep_infos: Optional[List[DRepInfo]] = None
    """Registration and voting power, one entry per captured DRep."""

    gov_action_infos: Optional[List[GovActionInfo]] = None
    """Lifecycle information, one entry per captured governance action."""

    committee_member_infos: Optional[List[CommitteeMemberInfo]] = None
    """Individually captured committee members.

    This is the per-member lookup table; :attr:`committee_state` is the
    committee taken as a whole. A capture may hold either, both or neither.
    """

    gov_action_votes: Optional[List[GovActionVotes]] = None
    """Governance actions with the votes recorded against them."""

    drep_stake_entries: Optional[List[DRepStakeEntry]] = None
    """The DRep stake distribution for the capture's epoch."""

    spo_stake_entries: Optional[List[SPOStakeEntry]] = None
    """The stake pool stake distribution for the capture's epoch."""

    committee_state: Optional[CommitteeStateInfo] = None
    """The constitutional committee as a whole, including its quorum threshold."""

    def __post_init__(self):
        if self.general is None:
            object.__setattr__(self, "general", OfflineTransferGeneral())

        if self.protocol is None:
            object.__setattr__(self, "protocol", OfflineTransferProtocol())

        # Pool IDs are stored in their bech32 text form rather than as objects,
        # so they arrive here as strings and are widened to PoolOperator once,
        # on load, instead of on every stake_pools() call.
        if self.stake_pools is not None:
            object.__setattr__(
                self,
                "stake_pools",
                [
                    pool
                    for pool in (_pool_operator_from_id(p) for p in self.stake_pools)
                    if pool is not None
                ],
            )

        # if self.addresses is not None:
        #     object.__setattr__(self, "addresses", [AddressInfo()])

    @classmethod
    def property_from_dict(
        cls: Type[OfflineTransfer],
        value: Dict,
        key: str,
        field_name: str,
        init_args: Dict,
    ):
        """
        Parse the property from a dictionary
        :param value: The value
        :param key: The key
        :param field_name: The field name
        :param init_args: The initialization arguments
        :return: The property
        """
        if field_name == "general":
            return OfflineTransferGeneral.from_dict(value)
        elif field_name == "protocol":
            return OfflineTransferProtocol.from_dict(value)
        elif field_name == "history":
            return OfflineTransferHistory.from_dict(value)
        elif field_name == "files":
            return OfflineTransferFile.from_dict(value)
        elif field_name == "transactions":
            return OfflineTransferTransaction.from_dict(value)
        elif field_name == "addresses":
            return AddressInfo.from_dict(value)
        elif field_name == "token_meta_server":
            return TokenMetadata.from_dict(value)
        elif field_name == "stake_pool_infos":
            return _stake_pool_info_from_dict(value)
        elif field_name == "kes_period_infos":
            return KESPeriodInfo.from_dict(value)
        elif field_name == "drep_infos":
            return _drep_info_from_dict(value)
        elif field_name == "gov_action_infos":
            return _gov_action_info_from_dict(value)
        elif field_name == "committee_member_infos":
            return _committee_member_info_from_dict(value)
        elif field_name == "gov_action_votes":
            return _gov_action_votes_from_dict(value)
        elif field_name == "drep_stake_entries":
            return _drep_stake_entry_from_dict(value)
        elif field_name == "spo_stake_entries":
            return _spo_stake_entry_from_dict(value)
        elif field_name == "committee_state":
            return _committee_state_from_dict(value)

    def to_dict(self) -> Dict:
        """Convert the model to a dictionary.

        The pool and governance sections are re-encoded here because the values
        they hold — ``PoolParams``, ``DRep``, committee credentials, ``Anchor``
        — are pycardano objects with no JSON form of their own. A section that
        is ``None`` stays absent from the result, so a file that never carried
        one is not given an empty one by being loaded and saved again.

        Returns:
            Dict: The dictionary, ready for :func:`json.dumps`.
        """
        result = super().to_dict()

        encoders: Dict[str, Any] = {
            "stake_pools": _pool_operator_to_id,
            "stake_pool_infos": _stake_pool_info_to_dict,
            "kes_period_infos": KESPeriodInfo.to_dict,
            "drep_infos": _drep_info_to_dict,
            "gov_action_infos": _gov_action_info_to_dict,
            "committee_member_infos": _committee_member_info_to_dict,
            "gov_action_votes": _gov_action_votes_to_dict,
            "drep_stake_entries": _drep_stake_entry_to_dict,
            "spo_stake_entries": _spo_stake_entry_to_dict,
        }
        for name, encode in encoders.items():
            section = getattr(self, name)
            if section is not None:
                result[name] = [encode(entry) for entry in section]

        if self.committee_state is not None:
            result["committee_state"] = _committee_state_to_dict(self.committee_state)

        return result

    @staticmethod
    def new(offline_file_path: Path) -> OfflineTransfer:
        """
        Build a fresh new offlineJSON with the current protocolParameters in it

        :param offline_file_path: The offline file path
        :return: None
        """

        offline_json = {
            "general": {
                "online_cli_version": None,
                "online_node_version": None,
            },
            "protocol": {
                "protocol_parameters": None,
                "era": None,
            },
            "history": [
                {
                    "date": datetime.now(timezone.utc),
                    "action": HistoryType.NEW.value,
                }
            ],
        }

        new_offline_transfer = OfflineTransfer.from_json(offline_json)

        dump_file(
            offline_file_path,
            new_offline_transfer.to_json(),
        )

        return new_offline_transfer

    @staticmethod
    def check(offline_transfer_file: Path) -> None:
        """
        Check that the offlineTransfer.json file exist
        :param offline_transfer_file: The offline transfer file
        :return: None
        """
        try:
            check_file_exists(offline_transfer_file)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Offline transfer file is not a file or does not exist: "
                f"{offline_transfer_file.as_posix()}"
            )
            # print(
            #     f"[yellow]Offline transfer file is not a file or does not exist: "
            #     f"{offline_transfer_file.as_posix()}\n"
            #     f"Creating a new one...[/yellow]"
            # )
            # OfflineTransfer.new(offline_transfer_file)

    @staticmethod
    def load(offline_transfer_file: Path) -> OfflineTransfer:
        """
        Load the offline transfer file
        :param offline_transfer_file: The offline transfer file
        :return: The offline transfer file
        """
        OfflineTransfer.check(offline_transfer_file)
        return OfflineTransfer.from_json(load_json_file(offline_transfer_file))
