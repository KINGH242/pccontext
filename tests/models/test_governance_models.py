"""Tests for the pool, governance and committee models."""

from decimal import Decimal

import pytest

from pccontext.enums import (
    CommitteeMemberStatus,
    DRepStatus,
    Era,
    GovActionStatus,
    PoolStatus,
)
from pccontext.models import (
    ChainTip,
    CommitteeMemberInfo,
    CommitteeStateInfo,
    DRepInfo,
    DRepStakeEntry,
    GovActionInfo,
    GovActionVotes,
    KESPeriodInfo,
    SPOStakeEntry,
    StakePoolInfo,
)


class TestGovActionStatus:
    """Status is derived, not stored, so the precedence between the epoch
    fields is the thing worth pinning down."""

    def test_open_action_has_no_status(self):
        assert GovActionInfo(proposed_in=10).status is None

    @pytest.mark.parametrize(
        "field,expected",
        [
            ("enacted_epoch", GovActionStatus.ENACTED),
            ("ratified_epoch", GovActionStatus.RATIFIED),
            ("dropped_epoch", GovActionStatus.DROPPED),
            ("expired_epoch", GovActionStatus.EXPIRED),
        ],
    )
    def test_single_epoch_field_sets_status(self, field, expected):
        assert GovActionInfo(**{field: 42}).status == expected

    def test_enacted_takes_precedence_over_ratified(self):
        """An action that is ratified and then enacted has both epochs set;
        enacted is the later, more specific state."""
        info = GovActionInfo(ratified_epoch=10, enacted_epoch=12)
        assert info.status == GovActionStatus.ENACTED

    def test_epoch_zero_is_not_treated_as_absent(self):
        assert GovActionInfo(enacted_epoch=0).status == GovActionStatus.ENACTED


class TestGovActionVotes:
    def test_vote_lists_default_to_empty(self):
        votes = GovActionVotes()
        assert votes.committee_votes == []
        assert votes.drep_votes == []
        assert votes.stake_pool_votes == []

    def test_vote_lists_are_not_shared_between_instances(self):
        first = GovActionVotes()
        second = GovActionVotes()
        assert first.committee_votes is not second.committee_votes

    def test_status_matches_gov_action_info(self):
        votes = GovActionVotes(ratified_epoch=7)
        assert votes.status == GovActionStatus.RATIFIED
        assert votes.status == votes.as_gov_action_info().status

    def test_as_gov_action_info_carries_lifecycle_fields(self):
        votes = GovActionVotes(
            proposed_in=1,
            expires_after=2,
            ratified_epoch=3,
            enacted_epoch=4,
            dropped_epoch=5,
            expired_epoch=6,
        )
        info = votes.as_gov_action_info()
        assert isinstance(info, GovActionInfo)
        assert (info.proposed_in, info.expires_after) == (1, 2)
        assert (info.ratified_epoch, info.enacted_epoch) == (3, 4)
        assert (info.dropped_epoch, info.expired_epoch) == (5, 6)


class TestAliasParsing:
    """Backends spell these fields differently; the aliases are what make one
    model usable across all of them."""

    @pytest.mark.parametrize(
        "payload,expected_slot,expected_hash",
        [
            ({"slot": 1, "hash": "aa"}, 1, "aa"),
            ({"slot_no": 2, "block_hash": "bb"}, 2, "bb"),
            ({"slotNo": 3, "headerHash": "cc"}, 3, "cc"),
            ({"absSlot": 4, "id": "dd"}, 4, "dd"),
        ],
    )
    def test_chain_tip_aliases(self, payload, expected_slot, expected_hash):
        tip = ChainTip.from_json(payload)
        assert tip.slot == expected_slot
        assert tip.hash == expected_hash

    def test_chain_tip_accepts_era(self):
        assert ChainTip(era=Era.CONWAY).era == Era.CONWAY

    @pytest.mark.parametrize(
        "payload,expected",
        [
            ({"stake": 10}, 10),
            ({"votingPower": 20}, 20),
            ({"voting_power": 30}, 30),
            ({"amount": 40}, 40),
        ],
    )
    def test_drep_info_stake_aliases(self, payload, expected):
        assert DRepInfo.from_json(payload).stake == expected

    def test_kes_period_info_cli_aliases(self):
        info = KESPeriodInfo.from_json(
            {
                "qKesStartKesInterval": 700,
                "qKesExpectedOperationalCertificateNumber": 9,
            }
        )
        assert info.on_disk_kes_start == 700
        assert info.next_chain_op_cert_count == 9

    def test_spo_stake_entry_aliases(self):
        assert SPOStakeEntry.from_json({"poolId": "pool1x", "amount": 5}).pool_id == (
            "pool1x"
        )


class TestModelDefaults:
    def test_stake_pool_info_carries_retiring_epoch(self):
        info = StakePoolInfo(status=PoolStatus.RETIRING, retiring_epoch=500)
        assert info.status == PoolStatus.RETIRING
        assert info.retiring_epoch == 500

    def test_stake_pool_info_accepts_fractional_sizes(self):
        info = StakePoolInfo(live_size=Decimal("0.0125"))
        assert info.live_size == Decimal("0.0125")

    def test_drep_info_defaults_to_inactive_with_no_stake(self):
        info = DRepInfo()
        assert info.active is False
        assert info.stake == 0
        assert info.status is None

    def test_drep_status_values(self):
        assert DRepStatus("not_registered") == DRepStatus.NOT_REGISTERED

    def test_committee_member_without_hot_credential(self):
        """A member that has not authorized a hot credential — which is also
        how a resigned member appears — is representable."""
        member = CommitteeMemberInfo(
            expiration=400, status=CommitteeMemberStatus.ACTIVE
        )
        assert member.hot_credential is None
        assert member.expiration == 400

    def test_committee_state_defaults_to_no_members(self):
        state = CommitteeStateInfo()
        assert state.members == []
        assert state.threshold is None

    def test_committee_state_holds_members(self):
        state = CommitteeStateInfo(
            members=[CommitteeMemberInfo(expiration=1)], threshold=0.67
        )
        assert len(state.members) == 1
        assert state.threshold == pytest.approx(0.67)

    def test_drep_stake_entry_defaults(self):
        assert DRepStakeEntry().stake == 0


class TestEnumSerialization:
    """`BaseModel.to_dict` listed the enums it knew about individually, so
    TransactionType and HistoryType fell through to `json.dumps` and raised.
    That broke `OfflineTransferFileContext.submit_tx_cbor`, which is the whole
    point of the offline context."""

    def test_transaction_type_is_serializable(self):
        from pccontext.enums import TransactionType
        from pccontext.models import OfflineTransfer, OfflineTransferTransaction
        from pccontext.models.offline_transfer_model import TransactionJSON

        transfer = OfflineTransfer(
            transactions=[
                OfflineTransferTransaction(
                    type=TransactionType.TRANSACTION,
                    tx_json=TransactionJSON(
                        "Witnessed Tx ConwayEra", "Generated by PyCardano", "00"
                    ),
                )
            ]
        )
        assert TransactionType.TRANSACTION.value in transfer.to_json()

    def test_history_type_is_serializable(self):
        from pccontext.enums import HistoryType
        from pccontext.models import OfflineTransfer, OfflineTransferHistory

        action = HistoryType.SAVE_TRANSACTION.value("abc")
        transfer = OfflineTransfer(history=[OfflineTransferHistory(action=action)])
        assert "abc" in transfer.to_json()

    def test_new_status_enums_serialize_by_value(self):
        info = StakePoolInfo(status=PoolStatus.RETIRING, retiring_epoch=1)
        assert '"retiring"' in info.to_json()


class TestKesAliasesAreUnambiguous:
    """cardano-cli reports the on-chain and on-disk counters under two similar
    keys. Aliasing both onto one field made the mapping depend on field
    declaration order, so the two must stay disjoint."""

    CLI_OUTPUT = {
        "qKesNodeStateOperationalCertificateNumber": 29,
        "qKesOnDiskOperationalCertificateNumber": 30,
        "qKesExpectedOperationalCertificateNumber": 30,
        "qKesStartKesInterval": 700,
        "qKesCurrentKesPeriod": 745,
    }

    def test_counters_do_not_cross(self):
        info = KESPeriodInfo.from_json(self.CLI_OUTPUT)
        assert info.on_chain_op_cert_count == 29
        assert info.on_disk_op_cert_count == 30
        assert info.next_chain_op_cert_count == 30
        assert info.on_disk_kes_start == 700

    def test_alias_sets_are_disjoint(self):
        fields = KESPeriodInfo.__dataclass_fields__
        seen = {}
        for name, f in fields.items():
            for alias in f.metadata.get("aliases", []):
                assert (
                    alias not in seen
                ), f"alias {alias!r} maps to both {seen[alias]!r} and {name!r}"
                seen[alias] = name
