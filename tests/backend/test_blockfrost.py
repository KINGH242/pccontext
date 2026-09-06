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
    TransactionInput,
)
from pycardano.network import Network as PyCardanoNetwork

from pccontext.backend.blockfrost import BlockFrostChainContext
from pccontext.enums import Network, PoolStatus
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


# -- Queries Blockfrost cannot answer -------------------------------------


def test_unimplemented_queries_raise(context):
    """Blockfrost cannot answer these, so they must keep raising rather than
    return an empty or invented answer."""
    gov_action_id = GovActionId(
        transaction_id=bytes.fromhex(TX_HASH), gov_action_index=0
    )

    with pytest.raises(NotImplementedError):
        _ = context.era
    with pytest.raises(NotImplementedError):
        context.drep_info(MagicMock())
    with pytest.raises(NotImplementedError):
        context.gov_action_info(gov_action_id)
    with pytest.raises(NotImplementedError):
        context.gov_action_votes(gov_action_id)
    with pytest.raises(NotImplementedError):
        context.gov_actions_all()
    with pytest.raises(NotImplementedError):
        context.committee_member_info()
    with pytest.raises(NotImplementedError):
        context.committee_state()
    with pytest.raises(NotImplementedError):
        context.drep_stake_distribution()
