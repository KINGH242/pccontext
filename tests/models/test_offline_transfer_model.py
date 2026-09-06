import json
from decimal import Decimal
from fractions import Fraction

import pytest
from pycardano import (
    Anchor,
    AnchorDataHash,
    CommitteeColdCredential,
    CommitteeHotCredential,
    DRep,
    DRepKind,
    GovActionId,
    PoolKeyHash,
    PoolMetadata,
    PoolMetadataHash,
    PoolOperator,
    PoolParams,
    RewardAccountHash,
    SingleHostName,
    TransactionId,
    VerificationKeyHash,
    Vote,
    VrfKeyHash,
)

from pccontext.enums import CommitteeMemberStatus, DRepStatus, Era, Network, PoolStatus
from pccontext.models import (
    AddressInfo,
    CommitteeMemberInfo,
    CommitteeStateInfo,
    CommitteeVote,
    DRepInfo,
    DRepStakeEntry,
    DRepVote,
    GovActionInfo,
    GovActionVotes,
    KESPeriodInfo,
    OfflineTransfer,
    OfflineTransferFile,
    OfflineTransferGeneral,
    OfflineTransferHistory,
    OfflineTransferProtocol,
    OfflineTransferTransaction,
    ProtocolParameters,
    SPOStakeEntry,
    StakePoolInfo,
    StakePoolVote,
    TokenMetadata,
)
from pccontext.models.offline_transfer_model import TransactionJSON


def test_offline_transfer_general(fake_offline_transfer_general):
    # Act
    offline_transfer_general = OfflineTransferGeneral.from_json(
        fake_offline_transfer_general
    )

    # Assert
    assert offline_transfer_general is not None
    assert (
        offline_transfer_general.offline_cli_version
        == fake_offline_transfer_general["offline_cli_version"]
    )
    assert (
        offline_transfer_general.online_cli_version
        == fake_offline_transfer_general["online_cli_version"]
    )
    assert (
        offline_transfer_general.online_node_version
        == fake_offline_transfer_general["online_node_version"]
    )


def test_offline_transfer_protocol(fake_offline_transfer_protocol):
    # Act
    offline_transfer_protocol = OfflineTransferProtocol.from_json(
        fake_offline_transfer_protocol
    )

    # Assert
    assert offline_transfer_protocol is not None
    assert (
        offline_transfer_protocol.protocol_parameters
        == ProtocolParameters.from_json(
            fake_offline_transfer_protocol["protocol_parameters"]
        )
    )
    assert offline_transfer_protocol.era == Era(
        fake_offline_transfer_protocol["era"].lower()
    )
    assert offline_transfer_protocol.network == Network(
        fake_offline_transfer_protocol["network"].lower()
    )


def test_offline_transfer_history(fake_offline_transfer_history):
    # Act
    offline_transfer_history = OfflineTransferHistory.from_json(
        fake_offline_transfer_history
    )

    # Assert
    assert offline_transfer_history is not None
    assert offline_transfer_history.date == fake_offline_transfer_history["date"]
    assert offline_transfer_history.action == fake_offline_transfer_history["action"]


def test_offline_transfer_history_to_json(fake_offline_transfer_history):
    # Act
    offline_transfer_history = OfflineTransferHistory.from_json(
        fake_offline_transfer_history
    )

    json_output = offline_transfer_history.to_json()

    # Assert
    assert json_output is not None
    assert json_output == json.dumps(fake_offline_transfer_history, sort_keys=True)


def test_offline_transfer_file(fake_offline_transfer_file):
    # Act
    offline_transfer_file = OfflineTransferFile.from_json(fake_offline_transfer_file)

    # Assert
    assert offline_transfer_file is not None
    assert offline_transfer_file.name == fake_offline_transfer_file["name"]
    assert offline_transfer_file.date == fake_offline_transfer_file["date"]
    assert offline_transfer_file.size == fake_offline_transfer_file["size"]
    assert offline_transfer_file.base64 == fake_offline_transfer_file["base64"]


def test_offline_transfer_transaction(fake_offline_transfer_transaction):
    # Act
    offline_transfer_transaction = OfflineTransferTransaction.from_json(
        fake_offline_transfer_transaction
    )

    # Assert
    assert offline_transfer_transaction is not None
    assert (
        offline_transfer_transaction.type == fake_offline_transfer_transaction["type"]
    )
    assert (
        offline_transfer_transaction.date == fake_offline_transfer_transaction["date"]
    )
    assert (
        offline_transfer_transaction.stake_address
        == fake_offline_transfer_transaction["stake_address"]
    )
    assert (
        offline_transfer_transaction.from_address
        == fake_offline_transfer_transaction["from_address"]
    )
    assert (
        offline_transfer_transaction.from_name
        == fake_offline_transfer_transaction["from_name"]
    )
    assert (
        offline_transfer_transaction.to_address
        == fake_offline_transfer_transaction["to_address"]
    )
    assert (
        offline_transfer_transaction.to_name
        == fake_offline_transfer_transaction["to_name"]
    )
    assert offline_transfer_transaction.tx_json == TransactionJSON.from_dict(
        fake_offline_transfer_transaction["tx_json"]
    )


def test_offline_transfer(fake_offline_transfer):
    # Act
    offline_transfer = OfflineTransfer.from_json(fake_offline_transfer)

    # Assert
    assert offline_transfer is not None
    assert (
        offline_transfer.general.offline_cli_version
        == fake_offline_transfer["general"]["offline_cli_version"]
    )
    assert (
        offline_transfer.general.online_cli_version
        == fake_offline_transfer["general"]["online_cli_version"]
    )
    assert (
        offline_transfer.general.online_node_version
        == fake_offline_transfer["general"]["online_node_version"]
    )

    assert offline_transfer.protocol.era == Era(
        fake_offline_transfer["protocol"]["era"].lower()
    )
    assert offline_transfer.protocol.network == Network(
        fake_offline_transfer["protocol"]["network"].lower()
    )
    assert (
        offline_transfer.protocol.protocol_parameters
        == ProtocolParameters.from_json(
            fake_offline_transfer["protocol"]["protocol_parameters"]
        )
    )
    assert offline_transfer.history == [
        OfflineTransferHistory.from_json(fake_offline_transfer["history"])
    ]
    assert offline_transfer.files == [
        OfflineTransferFile.from_json(fake_offline_transfer["files"])
    ]
    assert offline_transfer.transactions == [
        OfflineTransferTransaction.from_json(fake_offline_transfer["transactions"])
    ]
    assert offline_transfer.addresses == [
        AddressInfo.from_json(fake_offline_transfer["addresses"])
    ]


def test_offline_transfer_to_json(fake_offline_transfer):
    # Act
    offline_transfer = OfflineTransfer.from_json(fake_offline_transfer)

    json_output = offline_transfer.to_json()

    # Assert
    assert json_output is not None


# ---------------------------------------------------------------------------
# Pool and governance sections
# ---------------------------------------------------------------------------


COLD_HASH = bytes(range(28))
HOT_HASH = bytes(range(1, 29))
POOL_HASH = bytes(range(2, 30))


@pytest.fixture
def populated_transfer():
    """An OfflineTransfer carrying one entry in every new section."""
    pool_operator = PoolOperator(PoolKeyHash(POOL_HASH))
    drep = DRep(DRepKind.VERIFICATION_KEY_HASH, VerificationKeyHash(COLD_HASH))
    cold = CommitteeColdCredential(VerificationKeyHash(COLD_HASH))
    hot = CommitteeHotCredential(VerificationKeyHash(HOT_HASH))
    anchor = Anchor(
        url="https://example.invalid/meta",
        data_hash=AnchorDataHash(bytes(range(32))),
    )
    gov_action_id = GovActionId(
        transaction_id=TransactionId(bytes(range(32))), gov_action_index=2
    )

    return OfflineTransfer(
        stake_pools=[pool_operator],
        stake_pool_infos=[
            StakePoolInfo(
                pool_params=PoolParams(
                    operator=PoolKeyHash(POOL_HASH),
                    vrf_keyhash=VrfKeyHash(bytes(range(32))),
                    pledge=1,
                    cost=2,
                    margin=Fraction(1, 50),
                    reward_account=RewardAccountHash(bytes(range(29))),
                    pool_owners=[VerificationKeyHash(COLD_HASH)],
                    relays=[SingleHostName(port=3001, dns_name="relay.invalid")],
                    pool_metadata=PoolMetadata(
                        url="https://example.invalid/pool",
                        pool_metadata_hash=PoolMetadataHash(bytes(range(32))),
                    ),
                ),
                live_pledge=10,
                live_stake=20,
                live_size=Decimal("0.5"),
                active_stake=30,
                active_size=Decimal("0.25"),
                opcert_counter=4,
                status=PoolStatus.REGISTERED,
                retiring_epoch=None,
            )
        ],
        kes_period_infos=[
            KESPeriodInfo(
                on_chain_op_cert_count=3,
                on_disk_op_cert_count=4,
                next_chain_op_cert_count=5,
                on_disk_kes_start=100,
            )
        ],
        treasury=1_234_567,
        drep_infos=[
            DRepInfo(
                drep=drep,
                active=True,
                anchor=anchor,
                deposit=500,
                stake=99,
                expiry=600,
                status=DRepStatus.REGISTERED,
            )
        ],
        gov_action_infos=[
            GovActionInfo(
                gov_action_id=gov_action_id,
                gov_action={"tag": "InfoAction"},
                proposed_in=500,
                expires_after=520,
                enacted_epoch=510,
            )
        ],
        committee_member_infos=[
            CommitteeMemberInfo(
                cold_credential=cold,
                hot_credential=hot,
                expiration=700,
                status=CommitteeMemberStatus.ACTIVE,
            )
        ],
        gov_action_votes=[
            GovActionVotes(
                gov_action_id=gov_action_id,
                gov_action={"tag": "InfoAction"},
                committee_votes=[
                    CommitteeVote(voter=hot, vote=Vote.YES, anchor=anchor)
                ],
                drep_votes=[DRepVote(voter=drep, vote=Vote.NO)],
                stake_pool_votes=[
                    StakePoolVote(voter=pool_operator.encode(), vote=Vote.ABSTAIN)
                ],
                deposit=100_000_000,
                deposit_return_addr="stake_test1uq",
                anchor=anchor,
                proposed_in=500,
            )
        ],
        drep_stake_entries=[DRepStakeEntry(drep=drep, stake=42)],
        spo_stake_entries=[SPOStakeEntry(pool_id=pool_operator.encode(), stake=84)],
        committee_state=CommitteeStateInfo(
            members=[
                CommitteeMemberInfo(
                    cold_credential=cold, hot_credential=hot, expiration=700
                )
            ],
            threshold=0.6,
        ),
    )


NEW_SECTIONS = [
    "stake_pools",
    "stake_pool_infos",
    "kes_period_infos",
    "treasury",
    "drep_infos",
    "gov_action_infos",
    "committee_member_infos",
    "gov_action_votes",
    "drep_stake_entries",
    "spo_stake_entries",
    "committee_state",
]


@pytest.mark.parametrize("section", NEW_SECTIONS)
def test_new_sections_round_trip_through_json(populated_transfer, section):
    """Every section survives to_json/from_json, CBOR-wrapped values included."""
    reloaded = OfflineTransfer.from_json(json.loads(populated_transfer.to_json()))

    assert getattr(reloaded, section) == getattr(populated_transfer, section)


def test_new_sections_serialise_to_plain_json(populated_transfer):
    """The pycardano values must not leak into to_dict as opaque objects."""
    payload = json.loads(populated_transfer.to_json())

    assert isinstance(payload["stake_pools"][0], str)
    assert isinstance(payload["stake_pool_infos"][0]["pool_params"], str)
    assert isinstance(payload["drep_infos"][0]["drep"], str)
    assert payload["gov_action_votes"][0]["drep_votes"][0]["vote"] == "NO"
    assert payload["committee_state"]["members"][0]["cold_credential"] is not None


@pytest.mark.parametrize("section", NEW_SECTIONS)
def test_file_without_the_new_sections_still_loads(fake_offline_transfer, section):
    """Backwards compatibility: a payload predating the sections loads as None.

    ``None`` means "this capture has no such section", which the offline chain
    context reports as a missing section rather than as an empty chain.
    """
    offline_transfer = OfflineTransfer.from_json(fake_offline_transfer)

    assert getattr(offline_transfer, section) is None


def test_absent_sections_are_not_written_back(fake_offline_transfer):
    """Loading and saving a legacy file must not invent empty sections."""
    payload = OfflineTransfer.from_json(fake_offline_transfer).to_dict()

    for section in NEW_SECTIONS:
        assert section not in payload


def test_a_captured_empty_section_is_kept_distinct_from_an_absent_one():
    """An empty list survives as an empty list, not as an absent section."""
    payload = json.loads(OfflineTransfer(stake_pools=[], drep_infos=[]).to_json())

    assert payload["stake_pools"] == []
    assert payload["drep_infos"] == []

    reloaded = OfflineTransfer.from_json(payload)
    assert reloaded.stake_pools == []
    assert reloaded.drep_infos == []
    assert reloaded.spo_stake_entries is None


def test_unparsable_cbor_in_a_section_does_not_break_loading():
    """A corrupt entry loses that one field rather than failing the whole load."""
    offline_transfer = OfflineTransfer.from_json(
        {"drep_infos": [{"drep": "not-cbor", "stake": 7}]}
    )

    assert offline_transfer.drep_infos[0].drep is None
    assert offline_transfer.drep_infos[0].stake == 7
