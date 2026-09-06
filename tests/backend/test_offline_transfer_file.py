import copy
import json
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction

import pytest
from freezegun import freeze_time
from pycardano import (
    CommitteeColdCredential,
    CommitteeHotCredential,
    DRep,
    DRepKind,
    GovActionId,
    Network,
    PoolKeyHash,
    PoolOperator,
    PoolParams,
    RewardAccountHash,
    Transaction,
    TransactionBody,
    TransactionId,
    TransactionInput,
    TransactionWitnessSet,
    VerificationKeyHash,
    Vote,
    VrfKeyHash,
)

from pccontext import GenesisParameters, OfflineTransferFileContext, ProtocolParameters
from pccontext.enums import (
    CommitteeMemberStatus,
    ContextType,
    DRepStatus,
    Era,
    PoolStatus,
)
from pccontext.exceptions import OfflineTransferFileError
from pccontext.models import (
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
    SPOStakeEntry,
    StakePoolInfo,
    StakePoolVote,
)


def test_offline_chain_context(offline_transfer_file):
    chain_context = OfflineTransferFileContext(
        offline_transfer_file=offline_transfer_file
    )
    assert isinstance(chain_context.network, Network)


def test_protocol_param(offline_transfer_file, cli_protocol_parameters_json):
    chain_context = OfflineTransferFileContext(
        offline_transfer_file=offline_transfer_file
    )
    expected_protocol_params = ProtocolParameters.from_json(
        cli_protocol_parameters_json
    )
    assert chain_context.protocol_param == expected_protocol_params.to_pycardano()


def test_genesis(offline_transfer_file, fake_genesis_parameters_json):
    chain_context = OfflineTransferFileContext(
        offline_transfer_file=offline_transfer_file
    )
    expected_genesis = GenesisParameters.from_json(fake_genesis_parameters_json)
    assert chain_context.genesis_param == expected_genesis.to_pycardano()


@freeze_time("2024-11-2")
def test_epoch(offline_transfer_file):
    chain_context = OfflineTransferFileContext(
        offline_transfer_file=offline_transfer_file
    )
    assert chain_context.epoch == 519


def test_era_is_an_era_enum(offline_transfer_file):
    chain_context = OfflineTransferFileContext(
        offline_transfer_file=offline_transfer_file
    )
    assert chain_context.era is None or isinstance(chain_context.era, Era)


def test_submit_tx_envelope_uses_era_name(offline_transfer_file, monkeypatch):
    """The envelope type must embed the era's name, not the Era enum's repr.

    `f"{Era.CONWAY}"` yields "Era.CONWAY", which produced the malformed type
    "Witnessed Tx Era.CONWAYEra".
    """
    written = {}

    chain_context = OfflineTransferFileContext(
        offline_transfer_file=offline_transfer_file
    )
    monkeypatch.setattr(
        type(chain_context),
        "era",
        property(lambda self: Era.CONWAY),
    )
    monkeypatch.setattr(
        "pccontext.backend.offline_transfer_file.dump_file",
        lambda path, contents: written.update(path=path, contents=contents),
    )

    tx = Transaction(
        TransactionBody(inputs=[], outputs=[], fee=0), TransactionWitnessSet()
    )
    chain_context.submit_tx_cbor(tx.to_cbor_hex())

    assert "Era." not in written["contents"]
    assert "Witnessed Tx ConwayEra" in written["contents"]


# ---------------------------------------------------------------------------
# Pool and governance queries served from the captured sections
# ---------------------------------------------------------------------------


COLD_HASH = bytes(range(28))
HOT_HASH = bytes(range(1, 29))
POOL_HASH = bytes(range(2, 30))
TX_HASH = bytes(range(32))


@pytest.fixture
def gov_action_id():
    return GovActionId(transaction_id=TransactionId(TX_HASH), gov_action_index=0)


@pytest.fixture
def pool_operator():
    return PoolOperator(PoolKeyHash(POOL_HASH))


@pytest.fixture
def pool_params():
    return PoolParams(
        operator=PoolKeyHash(POOL_HASH),
        vrf_keyhash=VrfKeyHash(bytes(range(32))),
        pledge=1_000_000,
        cost=340_000_000,
        margin=Fraction(1, 50),
        reward_account=RewardAccountHash(bytes(range(29))),
        pool_owners=[VerificationKeyHash(COLD_HASH)],
        relays=[],
        pool_metadata=None,
    )


@pytest.fixture
def drep():
    return DRep(DRepKind.VERIFICATION_KEY_HASH, VerificationKeyHash(COLD_HASH))


@pytest.fixture
def cold_credential():
    return CommitteeColdCredential(VerificationKeyHash(COLD_HASH))


@pytest.fixture
def hot_credential():
    return CommitteeHotCredential(VerificationKeyHash(HOT_HASH))


@pytest.fixture
def populated_transfer(
    fake_offline_transfer,
    gov_action_id,
    pool_operator,
    pool_params,
    drep,
    cold_credential,
    hot_credential,
):
    """A transfer file carrying every pool and governance section."""
    transfer = OfflineTransfer.from_json(copy.deepcopy(fake_offline_transfer))
    return replace(
        transfer,
        stake_pools=[pool_operator],
        stake_pool_infos=[
            StakePoolInfo(
                pool_params=pool_params,
                live_stake=5_000_000,
                active_stake=4_000_000,
                active_size=Decimal("0.01"),
                status=PoolStatus.REGISTERED,
            )
        ],
        kes_period_infos=[
            KESPeriodInfo(on_chain_op_cert_count=3, on_disk_op_cert_count=4)
        ],
        treasury=1_234_567,
        drep_infos=[
            DRepInfo(drep=drep, active=True, stake=99, status=DRepStatus.REGISTERED)
        ],
        gov_action_infos=[
            GovActionInfo(
                gov_action_id=gov_action_id,
                gov_action={"tag": "InfoAction"},
                proposed_in=500,
                expires_after=520,
            )
        ],
        committee_member_infos=[
            CommitteeMemberInfo(
                cold_credential=cold_credential,
                hot_credential=hot_credential,
                expiration=10_000,
                status=CommitteeMemberStatus.ACTIVE,
            )
        ],
        gov_action_votes=[
            GovActionVotes(
                gov_action_id=gov_action_id,
                committee_votes=[CommitteeVote(voter=hot_credential, vote=Vote.YES)],
                drep_votes=[DRepVote(voter=drep, vote=Vote.NO)],
                stake_pool_votes=[
                    StakePoolVote(voter=pool_operator.encode(), vote=Vote.ABSTAIN)
                ],
                deposit=100_000_000,
                proposed_in=500,
            )
        ],
        drep_stake_entries=[DRepStakeEntry(drep=drep, stake=42)],
        spo_stake_entries=[SPOStakeEntry(pool_id=pool_operator.encode(), stake=84)],
        committee_state=CommitteeStateInfo(
            members=[
                CommitteeMemberInfo(
                    cold_credential=cold_credential,
                    hot_credential=hot_credential,
                    expiration=10_000,
                    status=CommitteeMemberStatus.ACTIVE,
                )
            ],
            threshold=0.6,
        ),
    )


@pytest.fixture
def populated_context(populated_transfer, tmp_path):
    path = tmp_path / "offline-transfer-populated.json"
    path.write_text(populated_transfer.to_json(), encoding="utf-8")
    return OfflineTransferFileContext(offline_transfer_file=path)


@pytest.fixture
def legacy_context(fake_offline_transfer, tmp_path):
    """A context over a file written before the new sections existed."""
    path = tmp_path / "offline-transfer-legacy.json"
    path.write_text(json.dumps(fake_offline_transfer), encoding="utf-8")
    return OfflineTransferFileContext(offline_transfer_file=path)


def test_context_type_is_offline(populated_context):
    assert populated_context.context_type == ContextType.OFFLINE


@freeze_time("2024-11-2")
def test_chain_tip_is_derived_not_observed(populated_context):
    """Slot and epoch are computed from genesis; a block was never seen."""
    tip = populated_context.chain_tip

    assert tip.epoch == populated_context.epoch
    assert tip.slot == populated_context.last_block_slot
    assert tip.era == populated_context.era
    assert tip.hash is None
    assert tip.block is None
    assert tip.sync_progress is None


def test_utxo_resolves_a_captured_input(populated_context, fake_offline_transfer):
    captured = fake_offline_transfer["addresses"][0]["utxos"][0]["input"]
    tx_input = TransactionInput(
        transaction_id=TransactionId.from_primitive(captured["transaction_id"]),
        index=captured["index"],
    )

    result = populated_context.utxo(tx_input)

    assert result is not None
    utxo, is_spent = result
    assert utxo.input == tx_input
    # The file records what was unspent at capture time and cannot observe a
    # later spend, so it never reports True.
    assert is_spent is False


def test_utxo_returns_none_for_an_uncaptured_input(populated_context):
    tx_input = TransactionInput(
        transaction_id=TransactionId(bytes(range(1, 33))), index=7
    )

    assert populated_context.utxo(tx_input) is None


def test_stake_pools(populated_context, pool_operator):
    assert populated_context.stake_pools() == [pool_operator]


def test_stake_pool_info(populated_context, pool_operator, pool_params):
    info = populated_context.stake_pool_info(pool_operator.encode())

    assert info.pool_params == pool_params
    assert info.live_stake == 5_000_000
    assert info.status == PoolStatus.REGISTERED


def test_stake_pool_info_ignores_strict(populated_context, pool_operator):
    """Verifying metadata needs the network, so strict cannot change anything."""
    assert populated_context.stake_pool_info(
        pool_operator.encode(), strict=True
    ) == populated_context.stake_pool_info(pool_operator.encode())


def test_stake_pool_info_unknown_pool_raises(populated_context):
    other = PoolOperator(PoolKeyHash(bytes(range(5, 33))))

    with pytest.raises(OfflineTransferFileError, match="was not captured"):
        populated_context.stake_pool_info(other.encode())


def test_kes_period_info(populated_context):
    info = populated_context.kes_period_info()

    assert info.on_chain_op_cert_count == 3
    assert info.on_disk_op_cert_count == 4


def test_treasury(populated_context):
    assert populated_context.treasury() == 1_234_567


def test_drep_info(populated_context, drep):
    info = populated_context.drep_info(drep)

    assert info.drep == drep
    assert info.active is True
    assert info.stake == 99
    assert info.status == DRepStatus.REGISTERED


def test_drep_info_unknown_drep_raises(populated_context):
    other = DRep(DRepKind.VERIFICATION_KEY_HASH, VerificationKeyHash(HOT_HASH))

    with pytest.raises(OfflineTransferFileError, match="not captured"):
        populated_context.drep_info(other)


def test_gov_action_info(populated_context, gov_action_id):
    info = populated_context.gov_action_info(gov_action_id)

    assert info.gov_action_id == gov_action_id
    assert info.proposed_in == 500
    assert info.expires_after == 520


def test_gov_action_info_falls_back_to_the_votes_section(
    populated_transfer, gov_action_id, tmp_path
):
    """A capture that stored only the votes can still answer the lifecycle."""
    path = tmp_path / "votes-only.json"
    path.write_text(
        replace(populated_transfer, gov_action_infos=[]).to_json(), encoding="utf-8"
    )
    context = OfflineTransferFileContext(offline_transfer_file=path)

    info = context.gov_action_info(gov_action_id)

    assert info.gov_action_id == gov_action_id
    assert info.proposed_in == 500


def test_gov_action_votes(populated_context, gov_action_id, drep, hot_credential):
    votes = populated_context.gov_action_votes(gov_action_id)

    assert votes.gov_action_id == gov_action_id
    assert votes.committee_votes == [CommitteeVote(voter=hot_credential, vote=Vote.YES)]
    assert votes.drep_votes == [DRepVote(voter=drep, vote=Vote.NO)]
    assert votes.stake_pool_votes[0].vote == Vote.ABSTAIN
    assert votes.deposit == 100_000_000


def test_gov_action_votes_unknown_action_raises(populated_context):
    other = GovActionId(
        transaction_id=TransactionId(bytes(range(1, 33))), gov_action_index=4
    )

    with pytest.raises(OfflineTransferFileError, match="were not captured"):
        populated_context.gov_action_votes(other)


def test_gov_actions_all(populated_context, gov_action_id):
    actions = populated_context.gov_actions_all()

    assert [action.gov_action_id for action in actions] == [gov_action_id]


def test_committee_member_info_by_cold_credential(
    populated_context, cold_credential, hot_credential
):
    member = populated_context.committee_member_info(cold=cold_credential)

    assert member.hot_credential == hot_credential
    assert member.status == CommitteeMemberStatus.ACTIVE


def test_committee_member_info_by_hot_credential(
    populated_context, cold_credential, hot_credential
):
    member = populated_context.committee_member_info(hot=hot_credential)

    assert member.cold_credential == cold_credential


def test_committee_member_info_requires_a_credential(populated_context):
    with pytest.raises(ValueError, match="cold or hot"):
        populated_context.committee_member_info()


def test_committee_member_info_unknown_credential_raises(populated_context):
    with pytest.raises(OfflineTransferFileError, match="No captured committee member"):
        populated_context.committee_member_info(
            cold=CommitteeColdCredential(VerificationKeyHash(bytes(range(5, 33))))
        )


def test_committee_state(populated_context, cold_credential):
    state = populated_context.committee_state()

    assert state.threshold == 0.6
    assert [member.cold_credential for member in state.members] == [cold_credential]


@freeze_time("2024-11-2")
def test_committee_member_expires_once_the_chain_is_past_its_term(
    populated_transfer, cold_credential, tmp_path
):
    """A term runs to the END of its expiration epoch.

    The capture recorded the member as ACTIVE; the epoch derived from genesis
    is 519. Expiring in 519 is still serving, expiring in 518 is not.
    """
    serving = replace(
        populated_transfer,
        committee_state=CommitteeStateInfo(
            members=[
                CommitteeMemberInfo(
                    cold_credential=cold_credential,
                    expiration=519,
                    status=CommitteeMemberStatus.ACTIVE,
                )
            ],
            threshold=0.6,
        ),
    )
    expired = replace(
        populated_transfer,
        committee_state=CommitteeStateInfo(
            members=[
                CommitteeMemberInfo(
                    cold_credential=cold_credential,
                    expiration=518,
                    status=CommitteeMemberStatus.ACTIVE,
                )
            ],
            threshold=0.6,
        ),
    )

    def context_for(transfer, name):
        path = tmp_path / name
        path.write_text(transfer.to_json(), encoding="utf-8")
        return OfflineTransferFileContext(offline_transfer_file=path)

    assert (
        context_for(serving, "serving.json").committee_state().members[0].status
        == CommitteeMemberStatus.ACTIVE
    )
    assert (
        context_for(expired, "expired.json").committee_state().members[0].status
        == CommitteeMemberStatus.EXPIRED
    )


def test_drep_stake_distribution(populated_context, drep):
    assert populated_context.drep_stake_distribution() == [
        DRepStakeEntry(drep=drep, stake=42)
    ]


def test_spo_stake_distribution(populated_context, pool_operator):
    assert populated_context.spo_stake_distribution() == [
        SPOStakeEntry(pool_id=pool_operator.encode(), stake=84)
    ]


# ---------------------------------------------------------------------------
# A file written before the new sections existed
# ---------------------------------------------------------------------------


def test_legacy_file_still_loads(legacy_context, fake_offline_transfer):
    """Backwards compatibility: no new sections, no failure to load."""
    assert legacy_context.offline_transfer.addresses
    assert legacy_context.era is None or isinstance(legacy_context.era, Era)


@pytest.mark.parametrize(
    "query, section",
    [
        (lambda ctx: ctx.stake_pools(), "stake_pools"),
        (lambda ctx: ctx.stake_pool_info("pool1"), "stake_pool_infos"),
        (lambda ctx: ctx.kes_period_info(), "kes_period_infos"),
        (lambda ctx: ctx.treasury(), "treasury"),
        (lambda ctx: ctx.gov_actions_all(), "gov_action_votes"),
        (lambda ctx: ctx.committee_state(), "committee_state"),
        (lambda ctx: ctx.drep_stake_distribution(), "drep_stake_entries"),
        (lambda ctx: ctx.spo_stake_distribution(), "spo_stake_entries"),
    ],
)
def test_legacy_file_names_the_missing_section(legacy_context, query, section):
    """ "No section" is reported as a gap in the file, never as an empty chain."""
    with pytest.raises(OfflineTransferFileError, match=f"no '{section}' section"):
        query(legacy_context)


def test_legacy_file_missing_gov_action_infos(legacy_context, gov_action_id):
    with pytest.raises(OfflineTransferFileError, match="no 'gov_action_infos' section"):
        legacy_context.gov_action_info(gov_action_id)


def test_legacy_file_missing_committee_sections(legacy_context, cold_credential):
    with pytest.raises(
        OfflineTransferFileError, match="no 'committee_member_infos' section"
    ):
        legacy_context.committee_member_info(cold=cold_credential)


def test_legacy_file_missing_drep_infos(legacy_context, drep):
    with pytest.raises(OfflineTransferFileError, match="no 'drep_infos' section"):
        legacy_context.drep_info(drep)


def test_captured_but_empty_section_is_not_an_error(populated_transfer, tmp_path):
    """An empty section is a fact about the chain, not a gap in the file."""
    path = tmp_path / "empty-sections.json"
    path.write_text(
        replace(
            populated_transfer,
            stake_pools=[],
            gov_action_votes=[],
            drep_stake_entries=[],
            committee_state=CommitteeStateInfo(members=[], threshold=0.6),
        ).to_json(),
        encoding="utf-8",
    )
    context = OfflineTransferFileContext(offline_transfer_file=path)

    assert context.stake_pools() == []
    assert context.gov_actions_all() == []
    assert context.drep_stake_distribution() == []
    assert context.committee_state().members == []
