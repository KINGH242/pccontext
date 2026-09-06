from decimal import Decimal
from unittest.mock import patch

import pytest
from pycardano import (
    MultiHostName,
    Network,
    SingleHostAddr,
    SingleHostName,
    TransactionInput,
)

from pccontext.backend.koios import KoiosChainContext
from pccontext.enums import Era, PoolStatus
from pccontext.exceptions import PoolMetadataError

# A real /tip response. Koios sends more keys than ChainTip models, which is
# the point: the extra ones must be dropped rather than raise.
TIP = {
    "hash": "328de7e9c2879b0b2f50c0815cdd351c3c55b0e5c22c172edc86ccc5ae0113c6",
    "epoch_no": 653,
    "era": "Conway",
    "abs_slot": 197120824,
    "epoch_slot": 388024,
    "block_height": 13905256,
    "block_no": 13905256,
    "block_time": 1757116315,
}

POOL_INFO = {
    "pool_id_bech32": "pool1z5uqdk7dzdxaae5633fqfcu2eqzy3a3rgtuvy087fdld7yws0xt",
    "pool_id_hex": "153806dbcd134ddee69a8c5204e38ac80448f62342f8c23cfe4b7edf",
    "vrf_key_hash": (
        "0220a5d08adbfe9554b52d7b2993be5892ac3ff340e674a377dea3e22ad1778b"
    ),
    "pledge": "484000000000",
    "fixed_cost": "170000000",
    "margin": 0.02,
    "reward_addr": "stake1uy89kzrdlpaz5rzu8x95r4qnlpqhd3f8mf09edjp73vcs3qhktrtm",
    "owners": ["stake1uy89kzrdlpaz5rzu8x95r4qnlpqhd3f8mf09edjp73vcs3qhktrtm"],
    "relays": [
        {
            "dns": "octaluso.dyndns.org",
            "srv": None,
            "ipv4": None,
            "ipv6": None,
            "port": 3002,
        }
    ],
    "meta_url": "https://raw.githubusercontent.com/Octalus/cardano/master/p.json",
    "meta_hash": ("ca7d12decf886e31f5226b5946c62edc81a7e40af95ce7cd6465122e309d5626"),
    "op_cert_counter": 29,
    "pool_status": "registered",
    "retiring_epoch": None,
    "live_pledge": "484395278587",
    "live_stake": "54450172755242",
    "active_stake": "59775432464682",
    "sigma": 0.00234,
}


@pytest.fixture
def chain_context():
    with (
        patch("koios_python.URLs.get_tip", return_value=[TIP]),
        patch(
            "koios_python.URLs.get_epoch_info",
            return_value=[{"epoch_no": 653, "end_time": 99999999999}],
        ),
    ):
        return KoiosChainContext()


def test_koios_chain_context():
    with patch("koios_python.URLs.get_tip"), patch("koios_python.URLs.get_epoch_info"):
        chain_context = KoiosChainContext(api_key="api_key")
    assert chain_context.network == Network.MAINNET


class TestIdentity:
    def test_name_and_type(self, chain_context):
        from pccontext.enums import ContextType

        assert chain_context.name == "Koios"
        assert chain_context.context_type == ContextType.ONLINE


class TestChainState:
    def test_era(self, chain_context):
        with patch("koios_python.URLs.get_tip", return_value=[TIP]):
            assert chain_context.era == Era.CONWAY

    def test_era_is_none_for_an_unknown_name(self, chain_context):
        with patch("koios_python.URLs.get_tip", return_value=[{"era": "Martian"}]):
            assert chain_context.era is None

    def test_era_is_none_when_absent(self, chain_context):
        with patch("koios_python.URLs.get_tip", return_value=[{}]):
            assert chain_context.era is None

    def test_chain_tip(self, chain_context):
        with patch("koios_python.URLs.get_tip", return_value=[TIP]):
            tip = chain_context.chain_tip
        assert tip.slot == 197120824
        assert tip.block == 13905256
        assert tip.epoch == 653
        assert tip.era == Era.CONWAY
        assert tip.hash == TIP["hash"]

    def test_chain_tip_ignores_unmodelled_keys(self, chain_context):
        """epoch_slot and block_time have no field; they must not raise."""
        with patch("koios_python.URLs.get_tip", return_value=[TIP]):
            assert chain_context.chain_tip.slot == 197120824


class TestUtxo:
    UTXO_ROW = {
        "tx_hash": "54f054011b9dc179182b4b1ca8261b054d7e16915d153d170503939d1dc57608",
        "tx_index": 0,
        "address": (
            "addr1qxzrmgjxqgfmvwykts6u3uuynyme66mz66uc3dtwsx2uncmh2g0kgte48r0"
            "vvfl22u52j9f328yh8sfm5744wn29tfuqf87tt6"
        ),
        "value": "431177674",
        "asset_list": [],
        "datum_hash": None,
        "inline_datum": None,
        "reference_script": None,
        "is_spent": False,
    }

    def test_returns_utxo_and_spent_flag(self, chain_context):
        with patch("koios_python.URLs.get_utxo_info", return_value=[self.UTXO_ROW]):
            result = chain_context.utxo(
                TransactionInput.from_primitive([self.UTXO_ROW["tx_hash"], 0])
            )
        assert result is not None
        utxo, is_spent = result
        assert is_spent is False
        assert utxo.output.amount.coin == 431177674

    def test_reports_spent_utxos(self, chain_context):
        """Unlike a live-UTxO-set backend, Koios can say a UTxO was spent."""
        row = dict(self.UTXO_ROW, is_spent=True)
        with patch("koios_python.URLs.get_utxo_info", return_value=[row]):
            result = chain_context.utxo(
                TransactionInput.from_primitive([row["tx_hash"], 0])
            )
        assert result is not None
        assert result[1] is True

    def test_coin_is_an_int_not_a_string(self, chain_context):
        """Koios sends lovelace as a string. Leaving it that way puts a str in
        Value.coin, which breaks fee arithmetic in the transaction builder."""
        with patch("koios_python.URLs.get_utxo_info", return_value=[self.UTXO_ROW]):
            utxo, _ = chain_context.utxo(
                TransactionInput.from_primitive([self.UTXO_ROW["tx_hash"], 0])
            )
        assert isinstance(utxo.output.amount.coin, int)

    def test_returns_none_when_unknown(self, chain_context):
        with patch("koios_python.URLs.get_utxo_info", return_value=[]):
            assert (
                chain_context.utxo(
                    TransactionInput.from_primitive([self.UTXO_ROW["tx_hash"], 0])
                )
                is None
            )


class TestStakePools:
    def test_stake_pools(self, chain_context):
        with patch("koios_python.URLs.get_pool_list", return_value=[POOL_INFO]):
            pools = chain_context.stake_pools()
        assert len(pools) == 1

    def test_stake_pools_skips_rows_without_a_hex_id(self, chain_context):
        with patch("koios_python.URLs.get_pool_list", return_value=[{"ticker": "X"}]):
            assert chain_context.stake_pools() == []

    def test_stake_pool_info_maps_stake_and_status(self, chain_context):
        with patch("koios_python.URLs.get_pool_info", return_value=[POOL_INFO]):
            info = chain_context.stake_pool_info(POOL_INFO["pool_id_bech32"])
        assert info.status == PoolStatus.REGISTERED
        assert info.live_stake == 54450172755242
        assert info.active_stake == 59775432464682
        assert info.live_pledge == 484395278587
        assert info.opcert_counter == 29
        assert info.active_size == Decimal("0.00234")
        # Koios has no live-stake fraction, so this stays unset rather than
        # being computed from a total the endpoint does not return.
        assert info.live_size is None

    def test_stake_pool_info_builds_pool_params(self, chain_context):
        with patch("koios_python.URLs.get_pool_info", return_value=[POOL_INFO]):
            params = chain_context.stake_pool_info(
                POOL_INFO["pool_id_bech32"]
            ).pool_params
        assert params is not None
        assert params.pledge == 484000000000
        assert params.cost == 170000000
        assert len(params.pool_owners) == 1
        assert params.pool_metadata.url == POOL_INFO["meta_url"]

    def test_retiring_pool_carries_its_epoch(self, chain_context):
        row = dict(POOL_INFO, pool_status="retiring", retiring_epoch=700)
        with patch("koios_python.URLs.get_pool_info", return_value=[row]):
            info = chain_context.stake_pool_info(row["pool_id_bech32"])
        assert info.status == PoolStatus.RETIRING
        assert info.retiring_epoch == 700

    def test_unknown_pool_raises(self, chain_context):
        with patch("koios_python.URLs.get_pool_info", return_value=[]):
            with pytest.raises(ValueError, match="not found"):
                chain_context.stake_pool_info("pool1nope")

    @pytest.mark.parametrize(
        "relay,expected",
        [
            (
                {"dns": "a.example", "ipv4": None, "ipv6": None, "port": 3001},
                SingleHostName,
            ),
            (
                {"dns": None, "ipv4": "1.2.3.4", "ipv6": None, "port": 3001},
                SingleHostAddr,
            ),
            (
                {"dns": "a.example", "ipv4": None, "ipv6": None, "port": None},
                MultiHostName,
            ),
        ],
    )
    def test_relay_shapes(self, chain_context, relay, expected):
        row = dict(POOL_INFO, relays=[relay])
        with patch("koios_python.URLs.get_pool_info", return_value=[row]):
            params = chain_context.stake_pool_info(row["pool_id_bech32"]).pool_params
        assert isinstance(params.relays[0], expected)


class TestStrictMetadata:
    def test_strict_raises_when_hash_mismatches(self, chain_context):
        class FakeResponse:
            content = b"not the registered document"

            def raise_for_status(self):
                return None

        with (
            patch("koios_python.URLs.get_pool_info", return_value=[POOL_INFO]),
            patch("pccontext.backend.koios.requests.get", return_value=FakeResponse()),
        ):
            with pytest.raises(PoolMetadataError, match="hash mismatch"):
                chain_context.stake_pool_info(POOL_INFO["pool_id_bech32"], strict=True)

    def test_non_strict_tolerates_bad_metadata(self, chain_context):
        """The default call still returns on-chain parameters."""
        with patch("koios_python.URLs.get_pool_info", return_value=[POOL_INFO]):
            info = chain_context.stake_pool_info(POOL_INFO["pool_id_bech32"])
        assert info.live_stake == 54450172755242

    def test_strict_raises_when_no_metadata_registered(self, chain_context):
        row = dict(POOL_INFO, meta_url=None, meta_hash=None)
        with patch("koios_python.URLs.get_pool_info", return_value=[row]):
            with pytest.raises(PoolMetadataError, match="no off-chain metadata"):
                chain_context.stake_pool_info(row["pool_id_bech32"], strict=True)


class TestKesPeriodInfo:
    def test_reports_on_chain_counter_and_next(self, chain_context):
        from pycardano import PoolKeyHash, PoolOperator

        pool = PoolOperator(PoolKeyHash(bytes.fromhex(POOL_INFO["pool_id_hex"])))
        with patch("koios_python.URLs.get_pool_info", return_value=[POOL_INFO]):
            info = chain_context.kes_period_info(pool=pool)
        assert info.on_chain_op_cert_count == 29
        assert info.next_chain_op_cert_count == 30
        # Koios cannot see a local certificate file.
        assert info.on_disk_op_cert_count is None
        assert info.on_disk_kes_start is None

    def test_requires_a_pool(self, chain_context):
        with pytest.raises(ValueError, match="pool operator must be provided"):
            chain_context.kes_period_info()


class TestTreasury:
    def test_treasury(self, chain_context):
        with patch(
            "koios_python.URLs.get_totals",
            return_value=[{"epoch_no": 653, "treasury": "1348927208648520"}],
        ):
            assert chain_context.treasury() == 1348927208648520

    def test_missing_totals_raises(self, chain_context):
        with patch("koios_python.URLs.get_totals", return_value=[]):
            with pytest.raises(ValueError, match="no totals"):
                chain_context.treasury()


class TestUnsupported:
    """Koios' governance endpoints are not wrapped by koios-python 2.0.0, so
    these must keep raising rather than return a misleading empty result."""

    @pytest.mark.parametrize(
        "method,args",
        [
            ("drep_info", (None,)),
            ("gov_action_info", (None,)),
            ("gov_action_votes", (None,)),
            ("gov_actions_all", ()),
            ("committee_member_info", ()),
            ("committee_state", ()),
            ("drep_stake_distribution", ()),
            ("spo_stake_distribution", ()),
        ],
    )
    def test_governance_queries_raise(self, chain_context, method, args):
        with pytest.raises(NotImplementedError, match="Koios"):
            getattr(chain_context, method)(*args)
