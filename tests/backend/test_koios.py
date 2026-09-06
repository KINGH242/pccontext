from decimal import Decimal
from unittest.mock import patch

import pytest
from pycardano import (
    DRep,
    GovActionId,
    MultiHostName,
    Network,
    SingleHostAddr,
    SingleHostName,
    TransactionInput,
    Vote,
)

from pccontext.backend.koios import KoiosChainContext
from pccontext.enums import (
    CommitteeMemberStatus,
    DRepStatus,
    Era,
    GovActionStatus,
    PoolStatus,
)
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


# -- Governance (koios-python fork with the Governance endpoints) ----------

DREP_ID = "drep1ygqzg3ed7rdqeg3343jw0fptqzc3lqtk3rvnnmgq64rj85sxd4sr4"
PROPOSAL_ID = "gov_action105mjyzm3spjppny2m776lwk5jnsuu07uva9tz0yg5u4nkf770rvsql5raht"

COMMITTEE_INFO = {
    "proposal_id": "gov_action1fk4nx9zhkcdcyjaudwjtnkd7gagwyhqtth2zypawkc78gvdxkuzqqtvqdkv",
    "quorum_numerator": 2,
    "quorum_denominator": 3,
    "members": [
        {
            "status": "authorized",
            "cc_cold_hex": "34" * 28,
            "cc_cold_has_script": False,
            "cc_hot_hex": "56" * 28,
            "cc_hot_has_script": False,
            "expiration_epoch": 726,
        },
        {
            "status": "resigned",
            "cc_cold_hex": "78" * 28,
            "cc_cold_has_script": True,
            "cc_hot_hex": None,
            "cc_hot_has_script": None,
            "expiration_epoch": 653,
        },
        {
            "status": "authorized",
            "cc_cold_hex": "9a" * 28,
            "cc_cold_has_script": False,
            "cc_hot_hex": "bc" * 28,
            "cc_hot_has_script": False,
            "expiration_epoch": 600,
        },
    ],
}

PROPOSAL = {
    "proposal_id": PROPOSAL_ID,
    "proposal_tx_hash": "7d" * 32,
    "proposal_index": 0,
    "proposal_type": "TreasuryWithdrawals",
    "proposal_description": {"tag": "TreasuryWithdrawals"},
    "deposit": "100000000000",
    "return_address": "stake1u8453de8xhhqa9c4ftvylkke8we84tmaq5hz75qwfgaaf2qac45ja",
    "meta_url": "https://example.com/proposal.json",
    "meta_hash": "ab" * 32,
    "proposed_epoch": 649,
    "expiration": 656,
    "ratified_epoch": None,
    "enacted_epoch": None,
    "dropped_epoch": None,
    "expired_epoch": None,
}


class TestDRepInfo:
    DREP_ROW = {
        "drep_id": DREP_ID,
        "hex": "00" * 28,
        "has_script": False,
        "drep_status": "registered",
        "deposit": "500000000",
        "active": True,
        "expires_epoch_no": 700,
        "amount": "11547971",
        "meta_url": "https://example.com/drep.json",
        "meta_hash": "cd" * 32,
    }

    def test_maps_registration_and_stake(self, chain_context):
        with patch("koios_python.URLs.get_drep_info", return_value=[self.DREP_ROW]):
            info = chain_context.drep_info(DRep.decode(DREP_ID))
        assert info.status == DRepStatus.REGISTERED
        assert info.active is True
        assert info.stake == 11547971
        assert info.deposit == 500000000
        assert info.expiry == 700
        assert info.anchor is not None
        assert info.anchor.url == "https://example.com/drep.json"

    def test_deregistered_maps_to_retired(self, chain_context):
        row = dict(self.DREP_ROW, drep_status="deregistered", active=False, amount="0")
        with patch("koios_python.URLs.get_drep_info", return_value=[row]):
            info = chain_context.drep_info(DRep.decode(DREP_ID))
        assert info.status == DRepStatus.RETIRED

    def test_unknown_drep_is_not_registered(self, chain_context):
        with patch("koios_python.URLs.get_drep_info", return_value=[]):
            info = chain_context.drep_info(DRep.decode(DREP_ID))
        assert info.status == DRepStatus.NOT_REGISTERED
        assert info.stake == 0

    def test_missing_metadata_yields_no_anchor(self, chain_context):
        row = dict(self.DREP_ROW, meta_url=None, meta_hash=None)
        with patch("koios_python.URLs.get_drep_info", return_value=[row]):
            assert chain_context.drep_info(DRep.decode(DREP_ID)).anchor is None


class TestCommitteeState:
    def test_maps_members_and_threshold(self, chain_context):
        with patch(
            "koios_python.URLs.get_committee_info", return_value=[COMMITTEE_INFO]
        ):
            state = chain_context.committee_state()
        assert len(state.members) == 3
        assert state.threshold == pytest.approx(2 / 3)

    def test_status_mapping(self, chain_context):
        """A term runs to the end of its expiration epoch, so a member whose
        expiration equals the current epoch is still serving."""
        with patch(
            "koios_python.URLs.get_committee_info", return_value=[COMMITTEE_INFO]
        ):
            members = chain_context.committee_state().members

        # epoch 653: expiration 726 -> still serving
        assert members[0].status == CommitteeMemberStatus.ACTIVE
        # resigned, expiration == current epoch -> not a recognised voter
        assert members[1].status == CommitteeMemberStatus.UNRECOGNIZED
        # expiration 600 is behind the chain -> expired
        assert members[2].status == CommitteeMemberStatus.EXPIRED

    def test_member_at_its_expiration_epoch_is_still_active(self, chain_context):
        info = dict(
            COMMITTEE_INFO,
            members=[dict(COMMITTEE_INFO["members"][0], expiration_epoch=653)],
        )
        with patch("koios_python.URLs.get_committee_info", return_value=[info]):
            assert (
                chain_context.committee_state().members[0].status
                == CommitteeMemberStatus.ACTIVE
            )

    def test_script_and_key_credentials(self, chain_context):
        with patch(
            "koios_python.URLs.get_committee_info", return_value=[COMMITTEE_INFO]
        ):
            members = chain_context.committee_state().members
        assert members[0].cold_credential is not None
        assert members[0].hot_credential is not None
        # a resigned member has no hot credential
        assert members[1].hot_credential is None

    def test_empty_response(self, chain_context):
        with patch("koios_python.URLs.get_committee_info", return_value=[]):
            state = chain_context.committee_state()
        assert state.members == []
        assert state.threshold is None


class TestCommitteeMemberInfo:
    def test_lookup_by_cold_credential(self, chain_context):
        with patch(
            "koios_python.URLs.get_committee_info", return_value=[COMMITTEE_INFO]
        ):
            target = chain_context.committee_state().members[0]
            found = chain_context.committee_member_info(cold=target.cold_credential)
        assert found.cold_credential == target.cold_credential

    def test_lookup_by_hot_credential(self, chain_context):
        with patch(
            "koios_python.URLs.get_committee_info", return_value=[COMMITTEE_INFO]
        ):
            target = chain_context.committee_state().members[0]
            found = chain_context.committee_member_info(hot=target.hot_credential)
        assert found.hot_credential == target.hot_credential

    def test_requires_a_credential(self, chain_context):
        with pytest.raises(ValueError, match="cold or hot"):
            chain_context.committee_member_info()

    def test_no_match_raises(self, chain_context):
        from pycardano import CommitteeColdCredential, VerificationKeyHash

        stranger = CommitteeColdCredential(VerificationKeyHash(b"\xff" * 28))
        with patch(
            "koios_python.URLs.get_committee_info", return_value=[COMMITTEE_INFO]
        ):
            with pytest.raises(ValueError, match="No committee member matched"):
                chain_context.committee_member_info(cold=stranger)


class TestGovActions:
    VOTES = [
        {
            "voter_role": "ConstitutionalCommittee",
            "voter_id": "cc_hot1x",
            "vote": "Yes",
        },
        {"voter_role": "DRep", "voter_id": DREP_ID, "vote": "No"},
        {"voter_role": "SPO", "voter_id": "pool1x", "vote": "Abstain"},
    ]

    def test_gov_action_info(self, chain_context):
        with patch("koios_python.URLs.get_proposal_list", return_value=[PROPOSAL]):
            info = chain_context.gov_action_info(GovActionId.decode(PROPOSAL_ID))
        assert info.proposed_in == 649
        assert info.expires_after == 656
        assert info.status is None

    def test_gov_action_info_status_from_epochs(self, chain_context):
        proposal = dict(PROPOSAL, ratified_epoch=650, enacted_epoch=651)
        with patch("koios_python.URLs.get_proposal_list", return_value=[proposal]):
            info = chain_context.gov_action_info(GovActionId.decode(PROPOSAL_ID))
        assert info.status == GovActionStatus.ENACTED

    def test_unknown_action_raises(self, chain_context):
        with patch("koios_python.URLs.get_proposal_list", return_value=[]):
            with pytest.raises(ValueError, match="was not found"):
                chain_context.gov_action_info(GovActionId.decode(PROPOSAL_ID))

    def test_gov_action_votes_split_by_role(self, chain_context):
        with (
            patch("koios_python.URLs.get_proposal_list", return_value=[PROPOSAL]),
            patch("koios_python.URLs.get_proposal_votes", return_value=self.VOTES),
        ):
            votes = chain_context.gov_action_votes(GovActionId.decode(PROPOSAL_ID))

        assert len(votes.committee_votes) == 1
        assert len(votes.drep_votes) == 1
        assert len(votes.stake_pool_votes) == 1
        assert votes.drep_votes[0].vote == Vote.NO
        assert votes.stake_pool_votes[0].vote == Vote.ABSTAIN
        assert votes.deposit == 100000000000
        assert votes.anchor is not None

    def test_unknown_voter_role_is_skipped(self, chain_context):
        with (
            patch("koios_python.URLs.get_proposal_list", return_value=[PROPOSAL]),
            patch(
                "koios_python.URLs.get_proposal_votes",
                return_value=[
                    {"voter_role": "Martian", "voter_id": "x", "vote": "Yes"}
                ],
            ),
        ):
            votes = chain_context.gov_action_votes(GovActionId.decode(PROPOSAL_ID))
        assert not (votes.committee_votes or votes.drep_votes or votes.stake_pool_votes)

    def test_gov_actions_all(self, chain_context):
        with (
            patch(
                "koios_python.URLs.get_proposal_list", return_value=[PROPOSAL, PROPOSAL]
            ),
            patch("koios_python.URLs.get_proposal_votes", return_value=[]),
        ):
            results = chain_context.gov_actions_all()
        assert len(results) == 2


class TestStakeDistributions:
    def test_drep_distribution(self, chain_context):
        rows = [
            {"drep_id": DREP_ID, "epoch_no": 653, "amount": "500"},
            {"drep_id": "not-a-drep", "epoch_no": 653, "amount": "250"},
        ]
        with patch(
            "koios_python.URLs.get_drep_voting_power_history", return_value=rows
        ):
            entries = chain_context.drep_stake_distribution()
        assert [e.stake for e in entries] == [500, 250]
        # an unparseable id keeps its row rather than losing the stake
        assert entries[0].drep is not None
        assert entries[1].drep is None

    def test_spo_distribution(self, chain_context):
        rows = [{"pool_id_bech32": "pool1x", "epoch_no": 653, "amount": "4419361614"}]
        with patch(
            "koios_python.URLs.get_pool_voting_power_history", return_value=rows
        ):
            entries = chain_context.spo_stake_distribution()
        assert entries[0].pool_id == "pool1x"
        assert entries[0].stake == 4419361614

    def test_distribution_is_paginated(self, chain_context):
        """Koios caps a page at the requested Range and reports no total, so a
        full page must be followed by another request. Without this the
        distribution silently stops at 1000 entries."""
        page1 = [{"pool_id_bech32": f"pool{i}", "amount": "1"} for i in range(1000)]
        page2 = [{"pool_id_bech32": "pool_last", "amount": "2"}]
        with patch(
            "koios_python.URLs.get_pool_voting_power_history",
            side_effect=[page1, page2],
        ):
            entries = chain_context.spo_stake_distribution()
        assert len(entries) == 1001
        assert entries[-1].pool_id == "pool_last"

    def test_single_short_page_stops(self, chain_context):
        with patch(
            "koios_python.URLs.get_pool_voting_power_history",
            side_effect=[[{"pool_id_bech32": "pool1x", "amount": "1"}]],
        ):
            assert len(chain_context.spo_stake_distribution()) == 1


class TestUnwrappedEndpointsDegradeGracefully:
    """Released koios-python wraps none of the governance endpoints. Calling
    one would otherwise fail with `AttributeError: 'URLs' object has no
    attribute ...` from inside the client — an install from PyPI would ship
    visibly broken methods. The guard turns that into the NotImplementedError
    the base class documents."""

    @pytest.mark.parametrize(
        "client_method,call",
        [
            ("get_drep_info", lambda c: c.drep_info(DRep.decode(DREP_ID))),
            ("get_committee_info", lambda c: c.committee_state()),
            ("get_drep_voting_power_history", lambda c: c.drep_stake_distribution()),
            ("get_pool_voting_power_history", lambda c: c.spo_stake_distribution()),
            ("get_proposal_list", lambda c: c.gov_actions_all()),
        ],
    )
    def test_missing_endpoint_raises_not_implemented(
        self, chain_context, client_method, call
    ):
        # Simulate a client that does not wrap the endpoint.
        with patch.object(type(chain_context.api), client_method, None, create=True):
            with pytest.raises(NotImplementedError) as exc:
                call(chain_context)
        assert "Koios" in str(exc.value)
        assert client_method in str(exc.value)
