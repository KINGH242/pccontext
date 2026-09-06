from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cbor2
import pytest
from blockfrost import ApiError, ApiUrls
from pycardano import (
    GovActionId,
    MultiHostName,
    PoolOperator,
    SingleHostAddr,
    SingleHostName,
    TransactionId,
    TransactionInput,
    Vote,
)
from pycardano.network import Network as PyCardanoNetwork

from pccontext.backend.blockfrost import BlockFrostChainContext
from pccontext.enums import (
    CommitteeMemberStatus,
    DRepStatus,
    Era,
    GovActionStatus,
    Network,
    PoolStatus,
)
from pccontext.exceptions import BlockfrostError, PoolMetadataError

POOL_ID = "pool1escyjl60l930fswu54xvamlrn7r0r4chje5qp8uwku09j7x68x6"
POOL_HEX = "cc30497f4ff962f4c1dca54cceefe39f86f1d7179668009f8eb71e59"
REWARD_ACCOUNT = "stake1uyehkck0lajq8gr28t9uxnuvgcqrc6070x3k9r8048z8y5gh6ffgw"
OWNER_KEY_HASH = "337b62cfff6403a06a3acbc34f8c46003c69fe79a3628cefa9c47251"
VRF_KEY = "aa" * 32
METADATA_HASH = "bb" * 32
PAYMENT_ADDRESS = "addr1v8xrqjtlfluk9axpmjj5enh0uw0cduwhz7txsqyl36m3ukgqdsn8w"
TX_HASH = "cd" * 32
BLOCK_HASH = "ef" * 32
POLICY_ID = "1c" * 28


def _ns(value):
    """Recursively turn dicts into namespaces, the way the SDK hands them back."""
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_ns(item) for item in value]
    return value


def _api_error(status_code: int) -> ApiError:
    response = MagicMock()
    response.json.return_value = {
        "status_code": status_code,
        "error": "Not Found",
        "message": "The requested component has not been found.",
    }
    return ApiError(response)


def _pool_payload(retirement=None):
    return _ns(
        {
            "pool_id": POOL_ID,
            "hex": POOL_HEX,
            "vrf_key": VRF_KEY,
            "declared_pledge": "100000000000",
            "live_pledge": "120000000000",
            "live_stake": "64000000000000",
            "live_size": 0.0021,
            "active_stake": "63000000000000",
            "active_size": 0.002,
            "margin_cost": 0.03,
            "fixed_cost": "170000000",
            "reward_account": REWARD_ACCOUNT,
            "owners": [REWARD_ACCOUNT],
            "registration": [TX_HASH],
            "retirement": retirement or [],
        }
    )


@pytest.fixture
def context():
    """A chain context whose BlockFrostApi is a mock, ready to be stubbed."""
    with patch("pccontext.backend.blockfrost.BlockFrostApi") as mock_api:
        api = MagicMock()
        api.epoch_latest.return_value = _ns({"epoch": 500, "end_time": 1 << 40})
        mock_api.return_value = api
        yield BlockFrostChainContext(
            "project_id", base_url=ApiUrls.mainnet.value, network=Network.MAINNET
        )


@patch("pccontext.backend.blockfrost.BlockFrostApi")
def test_blockfrost_chain_context(mock_api):
    mock_api.return_value = MagicMock()
    chain_context = BlockFrostChainContext(
        "project_id", base_url=ApiUrls.mainnet.value, network=Network.MAINNET
    )
    assert chain_context.network == PyCardanoNetwork.MAINNET

    chain_context = BlockFrostChainContext(
        "project_id", base_url=ApiUrls.preprod.value, network=Network.PREPROD
    )
    assert chain_context.network == PyCardanoNetwork.TESTNET

    chain_context = BlockFrostChainContext(
        "project_id", base_url=ApiUrls.preview.value, network=Network.PREVIEW
    )
    assert chain_context.network == PyCardanoNetwork.TESTNET


# -- Chain tip ------------------------------------------------------------


def test_chain_tip(context):
    context.api.block_latest.return_value = _ns(
        {
            "slot": 123456789,
            "hash": BLOCK_HASH,
            "height": 10203040,
            "epoch": 500,
            "epoch_slot": 4242,
        }
    )

    tip = context.chain_tip

    assert tip.slot == 123456789
    assert tip.hash == BLOCK_HASH
    assert tip.block == 10203040
    assert tip.epoch == 500
    # Blockfrost reports neither of these, and they must not be invented.
    assert tip.era is None
    assert tip.sync_progress is None


def test_chain_tip_wraps_api_errors(context):
    context.api.block_latest.side_effect = _api_error(500)

    with pytest.raises(BlockfrostError):
        _ = context.chain_tip


# -- UTxO -----------------------------------------------------------------


def _tx_utxos_payload(consumed_by_tx=None):
    return _ns(
        {
            "hash": TX_HASH,
            "inputs": [],
            "outputs": [
                {
                    "address": PAYMENT_ADDRESS,
                    "amount": [{"unit": "lovelace", "quantity": "5000000"}],
                    "output_index": 0,
                    "data_hash": None,
                    "inline_datum": None,
                    "reference_script_hash": None,
                    "consumed_by_tx": None,
                },
                {
                    "address": PAYMENT_ADDRESS,
                    "amount": [
                        {"unit": "lovelace", "quantity": "2000000"},
                        {"unit": POLICY_ID + "74657374", "quantity": "42"},
                    ],
                    "output_index": 1,
                    "data_hash": None,
                    "inline_datum": None,
                    "reference_script_hash": None,
                    "consumed_by_tx": consumed_by_tx,
                },
            ],
        }
    )


def test_utxo_returns_unspent_output(context):
    context.api.transaction_utxos.return_value = _tx_utxos_payload()

    result = context.utxo(TransactionInput.from_primitive([TX_HASH, 0]))

    assert result is not None
    utxo, is_spent = result
    assert is_spent is False
    assert str(utxo.input.transaction_id) == TX_HASH
    assert utxo.input.index == 0
    assert utxo.output.amount.coin == 5000000
    assert str(utxo.output.address) == PAYMENT_ADDRESS


def test_utxo_reports_spent_output_and_multi_asset(context):
    context.api.transaction_utxos.return_value = _tx_utxos_payload(
        consumed_by_tx="ab" * 32
    )

    utxo, is_spent = context.utxo(TransactionInput.from_primitive([TX_HASH, 1]))

    assert is_spent is True
    assert utxo.output.amount.coin == 2000000
    assets = utxo.output.amount.multi_asset
    assert len(assets) == 1
    policy = next(iter(assets))
    assert str(policy) == POLICY_ID
    assert list(assets[policy].values()) == [42]


def test_utxo_returns_none_for_unknown_index(context):
    context.api.transaction_utxos.return_value = _tx_utxos_payload()

    assert context.utxo(TransactionInput.from_primitive([TX_HASH, 7])) is None


def test_utxo_returns_none_for_unknown_transaction(context):
    context.api.transaction_utxos.side_effect = _api_error(404)

    assert context.utxo(TransactionInput.from_primitive([TX_HASH, 0])) is None


def test_utxo_wraps_other_api_errors(context):
    context.api.transaction_utxos.side_effect = _api_error(500)

    with pytest.raises(BlockfrostError):
        context.utxo(TransactionInput.from_primitive([TX_HASH, 0]))


# -- Stake pools ----------------------------------------------------------


def test_stake_pools(context):
    context.api.pools.return_value = [POOL_ID]

    pools = context.stake_pools()

    assert pools == [PoolOperator.from_primitive(POOL_ID)]
    assert pools[0].encode() == POOL_ID
    context.api.pools.assert_called_once_with(gather_pages=True)


def test_stake_pools_wraps_api_errors(context):
    context.api.pools.side_effect = _api_error(500)

    with pytest.raises(BlockfrostError):
        context.stake_pools()


def _stub_pool_calls(context, retirement=None, metadata=None, relays=None):
    context.api.pool.return_value = _pool_payload(retirement)
    context.api.pool_relays.return_value = _ns(
        relays
        if relays is not None
        else [
            {
                "ipv4": "1.2.3.4",
                "ipv6": None,
                "dns": None,
                "dns_srv": None,
                "port": 3001,
            },
            {
                "ipv4": None,
                "ipv6": None,
                "dns": "relay.example",
                "dns_srv": None,
                "port": 3002,
            },
            {
                "ipv4": None,
                "ipv6": None,
                "dns": None,
                "dns_srv": "_relay.example",
                "port": None,
            },
            {"ipv4": None, "ipv6": None, "dns": None, "dns_srv": None, "port": None},
        ]
    )
    context.api.pool_metadata.return_value = _ns(
        metadata
        if metadata is not None
        else {
            "pool_id": POOL_ID,
            "hex": POOL_HEX,
            "url": "https://example.com/pool.json",
            "hash": METADATA_HASH,
            "ticker": "TEST",
            "name": "Test Pool",
            "description": "A pool",
            "homepage": "https://example.com",
        }
    )
    context.api.pool_blocks.return_value = [BLOCK_HASH]
    context.api.block.return_value = _ns({"op_cert_counter": "9"})


def test_stake_pool_info_maps_registered_pool(context):
    _stub_pool_calls(context)

    info = context.stake_pool_info(POOL_ID)

    params = info.pool_params
    assert params.operator.payload.hex() == POOL_HEX
    assert params.vrf_keyhash.payload.hex() == VRF_KEY
    assert params.pledge == 100000000000
    assert params.cost == 170000000
    assert params.margin == Fraction(3, 100)
    assert params.reward_account.payload.hex().endswith(OWNER_KEY_HASH)
    assert [owner.payload.hex() for owner in params.pool_owners] == [OWNER_KEY_HASH]
    assert params.pool_metadata.url == "https://example.com/pool.json"
    assert params.pool_metadata.pool_metadata_hash.payload.hex() == METADATA_HASH

    # The unaddressable fourth relay is dropped rather than guessed at.
    assert len(params.relays) == 3
    assert isinstance(params.relays[0], SingleHostAddr)
    assert params.relays[0].ipv4 == "1.2.3.4"
    assert isinstance(params.relays[1], SingleHostName)
    assert params.relays[1].dns_name == "relay.example"
    assert isinstance(params.relays[2], MultiHostName)
    assert params.relays[2].dns_name == "_relay.example"

    assert info.live_pledge == 120000000000
    assert info.live_stake == 64000000000000
    assert info.live_size == Decimal("0.0021")
    assert info.active_stake == 63000000000000
    assert info.active_size == Decimal("0.002")
    assert info.opcert_counter == 9
    assert info.status == PoolStatus.REGISTERED
    assert info.retiring_epoch is None


def test_stake_pool_info_reports_retiring_pool(context):
    _stub_pool_calls(context, retirement=["ff" * 32])
    context.api.transaction_pool_retires.return_value = _ns(
        [{"cert_index": 0, "pool_id": POOL_ID, "retiring_epoch": 505}]
    )

    info = context.stake_pool_info(POOL_ID)

    assert info.status == PoolStatus.RETIRING
    assert info.retiring_epoch == 505


def test_stake_pool_info_reports_retired_pool(context):
    _stub_pool_calls(context, retirement=["ff" * 32])
    context.api.transaction_pool_retires.return_value = _ns(
        [{"cert_index": 0, "pool_id": POOL_ID, "retiring_epoch": 400}]
    )

    info = context.stake_pool_info(POOL_ID)

    assert info.status == PoolStatus.RETIRED
    assert info.retiring_epoch is None


def test_stake_pool_info_without_minted_blocks_has_no_opcert_counter(context):
    _stub_pool_calls(context)
    context.api.pool_blocks.return_value = []

    assert context.stake_pool_info(POOL_ID).opcert_counter is None


def test_stake_pool_info_tolerates_missing_metadata(context):
    _stub_pool_calls(context)
    context.api.pool_metadata.side_effect = _api_error(404)

    info = context.stake_pool_info(POOL_ID)

    assert info.pool_params.pool_metadata is None
    assert info.status == PoolStatus.REGISTERED


def test_stake_pool_info_strict_raises_on_missing_metadata(context):
    _stub_pool_calls(context)
    context.api.pool_metadata.side_effect = _api_error(404)

    with pytest.raises(PoolMetadataError):
        context.stake_pool_info(POOL_ID, strict=True)


def test_stake_pool_info_strict_raises_on_unresolved_metadata(context):
    _stub_pool_calls(
        context,
        metadata={
            "pool_id": POOL_ID,
            "hex": POOL_HEX,
            "url": "https://example.com/pool.json",
            "hash": METADATA_HASH,
            "ticker": None,
            "name": None,
            "description": None,
            "homepage": None,
        },
    )

    with pytest.raises(PoolMetadataError):
        context.stake_pool_info(POOL_ID, strict=True)

    # The same payload is tolerated when strict is off.
    assert context.stake_pool_info(POOL_ID).pool_params.pool_metadata is not None


def test_stake_pool_info_wraps_api_errors(context):
    context.api.pool.side_effect = _api_error(404)

    with pytest.raises(BlockfrostError):
        context.stake_pool_info(POOL_ID)


# -- KES period -----------------------------------------------------------

OP_CERT_CBOR = cbor2.dumps([[b"\x00" * 32, 7, 500, b"\x00" * 64], b"\x11" * 32]).hex()


def test_kes_period_info_from_latest_minted_block(context):
    context.api.pool_blocks.return_value = [BLOCK_HASH]
    context.api.block.return_value = _ns({"op_cert_counter": "6"})

    info = context.kes_period_info(pool=PoolOperator.from_primitive(POOL_ID))

    assert info.on_chain_op_cert_count == 6
    assert info.next_chain_op_cert_count == 7
    assert info.on_disk_op_cert_count is None
    assert info.on_disk_kes_start is None
    context.api.pool_blocks.assert_called_once_with(POOL_ID, count=1, order="desc")


def test_kes_period_info_with_op_cert(context):
    context.api.pool_blocks.return_value = [BLOCK_HASH]
    context.api.block.return_value = _ns({"op_cert_counter": "6"})

    info = context.kes_period_info(
        pool=PoolOperator.from_primitive(POOL_ID), op_cert=OP_CERT_CBOR
    )

    assert info.on_chain_op_cert_count == 6
    assert info.on_disk_op_cert_count == 7
    assert info.on_disk_kes_start == 500
    assert info.next_chain_op_cert_count == 7


def test_kes_period_info_accepts_raw_cbor_bytes(context):
    context.api.pool_blocks.return_value = [BLOCK_HASH]
    context.api.block.return_value = _ns({"op_cert_counter": "6"})

    info = context.kes_period_info(
        pool=PoolOperator.from_primitive(POOL_ID),
        op_cert=bytes.fromhex(OP_CERT_CBOR),
    )

    assert info.on_disk_op_cert_count == 7


def test_kes_period_info_rejects_malformed_op_cert(context):
    context.api.pool_blocks.return_value = [BLOCK_HASH]
    context.api.block.return_value = _ns({"op_cert_counter": "6"})

    with pytest.raises(BlockfrostError):
        context.kes_period_info(
            pool=PoolOperator.from_primitive(POOL_ID), op_cert="not-cbor"
        )


def test_kes_period_info_requires_a_pool(context):
    with pytest.raises(ValueError):
        context.kes_period_info()


def test_kes_period_info_without_minted_blocks_raises(context):
    context.api.pool_blocks.return_value = []

    with pytest.raises(BlockfrostError):
        context.kes_period_info(pool=PoolOperator.from_primitive(POOL_ID))


# -- Treasury -------------------------------------------------------------


def test_treasury(context):
    context.api.network.return_value = _ns(
        {
            "supply": {
                "max": "45000000000000000",
                "total": "38000000000000000",
                "circulating": "36000000000000000",
                "locked": "6000000000000",
                "treasury": "1234567890123",
                "reserves": "8000000000000000",
            },
            "stake": {"live": "23000000000000000", "active": "22000000000000000"},
        }
    )

    assert context.treasury() == 1234567890123


def test_treasury_wraps_api_errors(context):
    context.api.network.side_effect = _api_error(500)

    with pytest.raises(BlockfrostError):
        context.treasury()


# -- Stake distributions --------------------------------------------------


def test_spo_stake_distribution(context):
    context.api.pools_extended.return_value = _ns(
        [
            {
                "pool_id": POOL_ID,
                "hex": POOL_HEX,
                "active_stake": "63000000000000",
                "live_stake": "64000000000000",
            },
            {
                "pool_id": "pool1" + "q" * 51,
                "hex": "00" * 28,
                "active_stake": "0",
                "live_stake": "0",
            },
        ]
    )

    entries = context.spo_stake_distribution()

    assert [(e.pool_id, e.stake) for e in entries] == [
        (POOL_ID, 63000000000000),
        ("pool1" + "q" * 51, 0),
    ]
    context.api.pools_extended.assert_called_once_with(gather_pages=True)


def test_spo_stake_distribution_wraps_api_errors(context):
    context.api.pools_extended.side_effect = _api_error(500)

    with pytest.raises(BlockfrostError):
        context.spo_stake_distribution()


# -- Governance (blockfrost-python 0.7.0) ---------------------------------


# A valid bech32 DRep id, produced by pycardano so it round-trips.
DREP_ID = "drep1ygqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq7vlc9n"


def _drep():
    """A real DRep whose bech32 id round-trips through pycardano."""
    from pycardano import DRep

    return DRep.decode(DREP_ID)


class TestDRepInfo:
    def test_maps_registration_and_stake(self, context):
        context.api.governance_drep.return_value = _ns(
            {
                "drep_id": DREP_ID,
                "amount": "123456789",
                "active": True,
                "active_epoch": 500,
                "retired": False,
                "expired": False,
            }
        )
        context.api.governance_drep_metadata.return_value = _ns(
            {"url": "https://example.com/drep.json", "hash": "ab" * 32}
        )

        info = context.drep_info(_drep())

        assert info.active is True
        assert info.stake == 123456789
        assert info.status == DRepStatus.REGISTERED
        assert info.anchor is not None
        assert info.anchor.url == "https://example.com/drep.json"
        # Blockfrost reports neither, so neither is guessed.
        assert info.deposit is None
        assert info.expiry is None

    def test_retired_takes_precedence_over_active(self, context):
        """A retired DRep is not active; retirement is the more specific fact."""
        context.api.governance_drep.return_value = _ns(
            {"drep_id": DREP_ID, "amount": "0", "active": False, "retired": True}
        )
        context.api.governance_drep_metadata.side_effect = _api_error(404)

        assert context.drep_info(_drep()).status == DRepStatus.RETIRED

    def test_unknown_drep_is_not_registered(self, context):
        context.api.governance_drep.side_effect = _api_error(404)
        info = context.drep_info(_drep())
        assert info.status == DRepStatus.NOT_REGISTERED
        assert info.stake == 0

    def test_missing_metadata_is_not_an_error(self, context):
        context.api.governance_drep.return_value = _ns(
            {"drep_id": DREP_ID, "amount": "1", "active": True, "retired": False}
        )
        context.api.governance_drep_metadata.side_effect = _api_error(404)
        assert context.drep_info(_drep()).anchor is None

    def test_api_failure_is_wrapped(self, context):
        context.api.governance_drep.side_effect = _api_error(500)
        with pytest.raises(BlockfrostError):
            context.drep_info(_drep())


class TestDRepStakeDistribution:
    def test_maps_every_drep(self, context):
        context.api.governance_dreps.return_value = [
            _ns({"drep_id": DREP_ID, "amount": "500"}),
            _ns({"drep_id": DREP_ID, "amount": "1500"}),
        ]
        entries = context.drep_stake_distribution()
        assert [e.stake for e in entries] == [500, 1500]
        assert entries[0].drep is not None

    def test_unparseable_id_keeps_the_row(self, context):
        """One bad id should not lose the whole distribution."""
        context.api.governance_dreps.return_value = [
            _ns({"drep_id": "not-a-drep", "amount": "42"})
        ]
        entries = context.drep_stake_distribution()
        assert len(entries) == 1
        assert entries[0].drep is None
        assert entries[0].stake == 42

    def test_api_failure_is_wrapped(self, context):
        context.api.governance_dreps.side_effect = _api_error(500)
        with pytest.raises(BlockfrostError):
            context.drep_stake_distribution()


def _proposal(**overrides):
    base = {
        "id": "gov_action1abc",
        "tx_hash": TX_HASH,
        "cert_index": 0,
        "governance_type": "info_action",
        "governance_description": {"tag": "InfoAction"},
        "deposit": "100000000000",
        "return_address": "stake_test1abc",
        "ratified_epoch": None,
        "enacted_epoch": None,
        "dropped_epoch": None,
        "expired_epoch": None,
        "expiration": 520,
    }
    base.update(overrides)
    return _ns(base)


class TestGovActionInfo:
    def test_maps_lifecycle_epochs(self, context):
        context.api.governance_proposal_by_gov_action_id.return_value = _proposal(
            ratified_epoch=510, enacted_epoch=512
        )
        gov_id = GovActionId(
            transaction_id=TransactionId(bytes.fromhex(TX_HASH)), gov_action_index=0
        )

        info = context.gov_action_info(gov_id)

        assert info.expires_after == 520
        assert info.ratified_epoch == 510
        assert info.enacted_epoch == 512
        assert info.status == GovActionStatus.ENACTED
        # Blockfrost does not report the proposing epoch.
        assert info.proposed_in is None

    def test_open_action_has_no_status(self, context):
        context.api.governance_proposal_by_gov_action_id.return_value = _proposal()
        gov_id = GovActionId(
            transaction_id=TransactionId(bytes.fromhex(TX_HASH)), gov_action_index=0
        )
        assert context.gov_action_info(gov_id).status is None

    def test_api_failure_is_wrapped(self, context):
        context.api.governance_proposal_by_gov_action_id.side_effect = _api_error(500)
        gov_id = GovActionId(
            transaction_id=TransactionId(bytes.fromhex(TX_HASH)), gov_action_index=0
        )
        with pytest.raises(BlockfrostError):
            context.gov_action_info(gov_id)


class TestGovActionVotes:
    VOTES = [
        _ns(
            {
                "voter_role": "constitutional_committee",
                "voter": "cc_hot1x",
                "vote": "yes",
                "counted": True,
            }
        ),
        _ns({"voter_role": "drep", "voter": DREP_ID, "vote": "no", "counted": True}),
        _ns(
            {"voter_role": "spo", "voter": "pool1x", "vote": "abstain", "counted": True}
        ),
    ]

    def test_splits_votes_by_role(self, context):
        context.api.governance_proposal_by_gov_action_id.return_value = _proposal()
        context.api.governance_proposal_votes_by_gov_action_id.return_value = self.VOTES
        gov_id = GovActionId(
            transaction_id=TransactionId(bytes.fromhex(TX_HASH)), gov_action_index=0
        )

        votes = context.gov_action_votes(gov_id)

        assert len(votes.committee_votes) == 1
        assert len(votes.drep_votes) == 1
        assert len(votes.stake_pool_votes) == 1
        assert votes.drep_votes[0].vote == Vote.NO
        assert votes.stake_pool_votes[0].vote == Vote.ABSTAIN
        assert votes.stake_pool_votes[0].voter == "pool1x"
        assert votes.deposit == 100000000000

    def test_no_votes_yields_empty_lists(self, context):
        context.api.governance_proposal_by_gov_action_id.return_value = _proposal()
        context.api.governance_proposal_votes_by_gov_action_id.return_value = []
        gov_id = GovActionId(
            transaction_id=TransactionId(bytes.fromhex(TX_HASH)), gov_action_index=0
        )
        votes = context.gov_action_votes(gov_id)
        assert votes.committee_votes == []
        assert votes.drep_votes == []

    def test_unknown_role_is_skipped(self, context):
        context.api.governance_proposal_by_gov_action_id.return_value = _proposal()
        context.api.governance_proposal_votes_by_gov_action_id.return_value = [
            _ns({"voter_role": "martian", "voter": "x", "vote": "yes"})
        ]
        gov_id = GovActionId(
            transaction_id=TransactionId(bytes.fromhex(TX_HASH)), gov_action_index=0
        )
        votes = context.gov_action_votes(gov_id)
        assert not (votes.committee_votes or votes.drep_votes or votes.stake_pool_votes)


class TestGovActionsAll:
    def test_fetches_detail_and_votes_per_proposal(self, context):
        context.api.governance_proposals.return_value = [
            _ns({"tx_hash": TX_HASH, "cert_index": 0}),
            _ns({"tx_hash": TX_HASH, "cert_index": 1}),
        ]
        context.api.governance_proposal_by_gov_action_id.return_value = _proposal()
        context.api.governance_proposal_votes_by_gov_action_id.return_value = []

        results = context.gov_actions_all()

        assert len(results) == 2
        assert context.api.governance_proposal_by_gov_action_id.call_count == 2

    def test_skips_rows_without_an_identifier(self, context):
        context.api.governance_proposals.return_value = [_ns({"governance_type": "x"})]
        assert context.gov_actions_all() == []

    def test_api_failure_is_wrapped(self, context):
        context.api.governance_proposals.side_effect = _api_error(500)
        with pytest.raises(BlockfrostError):
            context.gov_actions_all()


# -- Queries Blockfrost cannot answer -------------------------------------


COMMITTEE = {
    "gov_action_id": "gov_action1abc",
    "is_dissolved": False,
    "quorum": {"numerator": 2, "denominator": 3},
    "members": [
        {
            "cc_cold_hex": "34" * 28,
            "cc_cold_has_script": False,
            "cc_hot_hex": "56" * 28,
            "cc_hot_has_script": False,
            "status": "authorized",
            "expiration_epoch": 726,
        },
        {
            "cc_cold_hex": "78" * 28,
            "cc_cold_has_script": True,
            "cc_hot_hex": None,
            "cc_hot_has_script": None,
            "status": "resigned",
            "expiration_epoch": 500,
        },
        {
            "cc_cold_hex": "9a" * 28,
            "cc_cold_has_script": False,
            "cc_hot_hex": "bc" * 28,
            "cc_hot_has_script": False,
            "status": "authorized",
            "expiration_epoch": 500,
        },
    ],
}


def _committee_ns():
    return _ns(COMMITTEE)


class TestCommittee:
    """Backed by /governance/committee, which blockfrost-python wraps as of the
    governance-committee branch."""

    def test_members_and_threshold(self, context):
        context.api.governance_committee.return_value = _committee_ns()
        state = context.committee_state()
        assert len(state.members) == 3
        assert state.threshold == pytest.approx(2 / 3)

    def test_status_mapping(self, context):
        """A term runs to the end of its expiration epoch, so at epoch 500 a
        member expiring in 500 is still serving; 726 is well ahead."""
        context.api.governance_committee.return_value = _committee_ns()
        members = context.committee_state().members
        assert members[0].status == CommitteeMemberStatus.ACTIVE
        assert members[1].status == CommitteeMemberStatus.UNRECOGNIZED
        # expiration 500 against the fixture's epoch 500 -> still serving
        assert members[2].status == CommitteeMemberStatus.ACTIVE

    def test_expired_once_past_the_term(self, context):
        info = dict(COMMITTEE)
        info["members"] = [dict(COMMITTEE["members"][0], expiration_epoch=499)]
        context.api.governance_committee.return_value = _ns(info)
        assert (
            context.committee_state().members[0].status == CommitteeMemberStatus.EXPIRED
        )

    def test_resigned_member_has_no_hot_credential(self, context):
        context.api.governance_committee.return_value = _committee_ns()
        assert context.committee_state().members[1].hot_credential is None

    def test_dissolved_committee(self, context):
        context.api.governance_committee.return_value = _ns(
            {"is_dissolved": True, "quorum": None, "members": []}
        )
        state = context.committee_state()
        assert state.members == []
        assert state.threshold is None

    def test_lookup_by_cold_credential(self, context):
        context.api.governance_committee.return_value = _committee_ns()
        target = context.committee_state().members[0]
        found = context.committee_member_info(cold=target.cold_credential)
        assert found.cold_credential == target.cold_credential

    def test_lookup_by_hot_credential(self, context):
        context.api.governance_committee.return_value = _committee_ns()
        target = context.committee_state().members[0]
        found = context.committee_member_info(hot=target.hot_credential)
        assert found.hot_credential == target.hot_credential

    def test_requires_a_credential(self, context):
        with pytest.raises(ValueError, match="cold or hot"):
            context.committee_member_info()

    def test_no_match_raises(self, context):
        from pycardano import CommitteeColdCredential, VerificationKeyHash

        context.api.governance_committee.return_value = _committee_ns()
        stranger = CommitteeColdCredential(VerificationKeyHash(b"\xff" * 28))
        with pytest.raises(ValueError, match="No committee member matched"):
            context.committee_member_info(cold=stranger)

    def test_api_failure_is_wrapped(self, context):
        context.api.governance_committee.side_effect = _api_error(500)
        with pytest.raises(BlockfrostError):
            context.committee_state()


class TestEra:
    """`/network/eras` returns one summary per era in order but names none of
    them, so the era is the last summary's position in the Byron->Conway
    sequence — the same derivation the Ogmios client uses."""

    @pytest.mark.parametrize(
        "count,expected",
        [
            (1, Era.BYRON),
            (2, Era.SHELLEY),
            (5, Era.ALONZO),
            (6, Era.BABBAGE),
            (7, Era.CONWAY),
        ],
    )
    def test_era_from_summary_count(self, context, count, expected):
        context.api.network_eras.return_value = [_ns({}) for _ in range(count)]
        assert context.era == expected

    def test_no_eras_reported(self, context):
        context.api.network_eras.return_value = []
        assert context.era is None

    def test_unknown_future_era(self, context):
        """A hard fork adding an era this library does not know about must not
        be silently reported as Conway."""
        context.api.network_eras.return_value = [_ns({}) for _ in range(8)]
        assert context.era is None

    def test_api_failure_is_wrapped(self, context):
        context.api.network_eras.side_effect = _api_error(500)
        with pytest.raises(BlockfrostError):
            _ = context.era
