import contextlib
from fractions import Fraction
from unittest.mock import patch

import pytest
from pycardano import (
    Address,
    Anchor,
    AnchorDataHash,
    AssetName,
    CommitteeHotCredential,
    DRep,
    DRepKind,
    GovActionId,
    MultiAsset,
    PoolKeyHash,
    PoolMetadata,
    PoolMetadataHash,
    PoolOperator,
    RewardAccountHash,
    ScriptHash,
    SingleHostAddr,
    TransactionId,
    TransactionInput,
    TransactionOutput,
    Value,
    VerificationKeyHash,
    Vote,
    VrfKeyHash,
)
from yaci_client.models import (
    AddressUtxo,
    Amt,
    BlockDto,
    DRepRegistration,
    DRepRegistrationType,
    EpochNo,
    GovActionProposal,
    GovActionProposalType,
    JsonNode,
    PoolRegistration,
    PoolRetirement,
    ProtocolParamsDto,
)
from yaci_client.models import Relay as YaciRelay
from yaci_client.models import (
    Utxo,
    VotingProcedure,
    VotingProcedureVote,
    VotingProcedureVoterType,
)

from pccontext import ProtocolParameters
from pccontext.enums import DRepStatus, Era, PoolStatus
from pccontext.models import ChainTip, CommitteeVote, DRepVote, StakePoolVote


class TestCardanoCliChainContext:
    def test_epoch(self, yaci_devkit_chain_context):
        with patch(
            "yaci_client.api.local_epoch_service.get_latest_epoch.sync",
            return_value=EpochNo(epoch=100),
        ):
            assert yaci_devkit_chain_context.epoch == 100

    def test_protocol_param(self, yaci_devkit_chain_context, yaci_protocol_parameters):
        with patch(
            "yaci_client.api.local_epoch_service.get_latest_protocol_params.sync",
            return_value=ProtocolParamsDto.from_dict(yaci_protocol_parameters),
        ):
            protocol_param = yaci_devkit_chain_context.protocol_param
            expected_protocol_param = ProtocolParameters.from_json(
                yaci_protocol_parameters
            )
            assert protocol_param == expected_protocol_param.to_pycardano()

    def test_utxo(self, yaci_devkit_chain_context, yaci_utxos):
        with patch(
            "yaci_client.api.address_service.get_utxos_1.sync",
            return_value=[Utxo(**utxo) for utxo in yaci_utxos],
        ):
            results = yaci_devkit_chain_context.utxos(
                "addr_test1qraen6hr9zs5yae8cxnhlkh7rk2nfl7rnpg0xvmel3a0xf70v3kz6ee7mtq86x6gmrnw8j7kuf485902akkr7tlcx24qemz34a"
            )

        assert results[0].input == TransactionInput.from_primitive(
            ["a6ce90a9a5ef8ef73858effdae375ba50f302d3c6c8b587a15eaa8fa98ddf741", 0]
        )
        assert results[0].output == TransactionOutput(
            address=Address.from_primitive(
                "addr_test1qraen6hr9zs5yae8cxnhlkh7rk2nfl7rnpg0xvmel3a0xf70v3kz6ee7mtq86x6gmrnw8j7kuf485902akkr7tlcx24qemz34a"
            ),
            amount=Value(coin=10000000000, multi_asset=MultiAsset()),
        )


POOL_ID_HEX = "cc30497f4ff962f4c1dca54cceefe39f86f1d7179668009f8eb71e59"
POOL_ID_BECH32 = "pool1escyjl60l930fswu54xvamlrn7r0r4chje5qp8uwku09j7x68x6"
VRF_KEY_HASH = "b2" * 32
OWNER_KEY_HASH = "cf646c2d673edac07d1b48d8e6e3cbd6e26a7a15eaedac3f2ff832aa"
REWARD_ADDRESS = "stake_test1ur8kgmpdvuld4srardyd3ehre0twy6n6zh4wmtpl9lur92sac2pth"
DREP_KEY_HASH = "aa" * 28
DREP_SCRIPT_HASH = "bb" * 28
CC_HOT_KEY_HASH = "cc" * 28
TX_HASH = "a6ce90a9a5ef8ef73858effdae375ba50f302d3c6c8b587a15eaa8fa98ddf741"
ADDRESS = (
    "addr_test1qraen6hr9zs5yae8cxnhlkh7rk2nfl7rnpg0xvmel3a0xf70v3kz6ee7mtq86x6"
    "gmrnw8j7kuf485902akkr7tlcx24qemz34a"
)


def _proposal(index=0, epoch=12):
    return GovActionProposal(
        tx_hash=TX_HASH,
        index=index,
        epoch=epoch,
        deposit=100000000000,
        return_address=REWARD_ADDRESS,
        type=GovActionProposalType.INFO_ACTION,
        details=JsonNode.from_dict({"tag": "InfoAction"}),
        anchor_url="https://example.com/info.json",
        anchor_hash="dd" * 32,
    )


class TestYaciDevkitChainState:
    def test_era(self, yaci_devkit_chain_context):
        with patch(
            "yaci_client.api.block_service.get_latest_block.sync",
            return_value=BlockDto(era=7),
        ):
            assert yaci_devkit_chain_context.era is Era.CONWAY

    def test_era_unknown_index_is_none(self, yaci_devkit_chain_context):
        """An era index outside the known range must not be guessed at."""
        with patch(
            "yaci_client.api.block_service.get_latest_block.sync",
            return_value=BlockDto(era=99),
        ):
            assert yaci_devkit_chain_context.era is None

    def test_chain_tip(self, yaci_devkit_chain_context):
        with patch(
            "yaci_client.api.block_service.get_latest_block.sync",
            return_value=BlockDto(
                slot=4242, hash_="ab" * 32, number=77, height=77, epoch=3, era=7
            ),
        ):
            tip = yaci_devkit_chain_context.chain_tip

        assert tip == ChainTip(
            slot=4242, hash="ab" * 32, block=77, epoch=3, era=Era.CONWAY
        )
        # Yaci reports no distance from the node's own tip.
        assert tip.sync_progress is None

    def test_chain_tip_raises_when_no_block(self, yaci_devkit_chain_context):
        with patch(
            "yaci_client.api.block_service.get_latest_block.sync", return_value=None
        ):
            with pytest.raises(ValueError):
                _ = yaci_devkit_chain_context.chain_tip


class TestYaciDevkitUtxo:
    ADDRESS_UTXO = AddressUtxo(
        tx_hash=TX_HASH,
        output_index=1,
        owner_addr=ADDRESS,
        lovelace_amount=1500000,
        amounts=[
            Amt(unit="lovelace", quantity=1500000),
            Amt(unit="d0" * 28 + "abcdef", quantity=7),
        ],
    )

    def test_utxo_unspent(self, yaci_devkit_chain_context):
        tx_input = TransactionInput.from_primitive([TX_HASH, 1])
        with (
            patch(
                "yaci_client.api.transaction_service.get_utxo.sync",
                return_value=self.ADDRESS_UTXO,
            ),
            patch(
                "yaci_client.api.address_service.get_utxos_1.sync",
                return_value=[Utxo(tx_hash=TX_HASH, output_index=1)],
            ),
        ):
            result = yaci_devkit_chain_context.utxo(tx_input)

        assert result is not None
        utxo, spent = result
        assert spent is False
        assert utxo.input == tx_input
        assert utxo.output.address == Address.from_primitive(ADDRESS)
        assert utxo.output.amount.coin == 1500000
        policy = ScriptHash(bytes.fromhex("d0" * 28))
        assert (
            utxo.output.amount.multi_asset[policy][AssetName(bytes.fromhex("abcdef"))]
            == 7
        )

    def test_utxo_spent(self, yaci_devkit_chain_context):
        """Yaci keeps spent outputs, so absence from the live set means spent."""
        tx_input = TransactionInput.from_primitive([TX_HASH, 1])
        with (
            patch(
                "yaci_client.api.transaction_service.get_utxo.sync",
                return_value=self.ADDRESS_UTXO,
            ),
            patch("yaci_client.api.address_service.get_utxos_1.sync", return_value=[]),
        ):
            result = yaci_devkit_chain_context.utxo(tx_input)

        assert result is not None
        assert result[1] is True

    def test_utxo_unknown(self, yaci_devkit_chain_context):
        with patch(
            "yaci_client.api.transaction_service.get_utxo.sync", return_value=None
        ):
            assert (
                yaci_devkit_chain_context.utxo(
                    TransactionInput.from_primitive([TX_HASH, 9])
                )
                is None
            )


class TestYaciDevkitStakePools:
    REGISTRATION = PoolRegistration(
        pool_id=POOL_ID_HEX,
        pool_id_bech32=POOL_ID_BECH32,
        vrf_key_hash=VRF_KEY_HASH,
        pledge=100000000,
        cost=340000000,
        margin=0.03,
        reward_account_bech32=REWARD_ADDRESS,
        pool_owners=[OWNER_KEY_HASH],
        relays=[YaciRelay(ipv4="10.0.0.1", port=3001)],
        metadata_url="https://example.com/pool.json",
        metadata_hash="ee" * 32,
        slot=10,
        cert_index=0,
    )

    def test_stake_pools_excludes_retired(self, yaci_devkit_chain_context):
        with (
            patch(
                "yaci_client.api.local_epoch_service.get_latest_epoch.sync",
                return_value=EpochNo(epoch=20),
            ),
            patch(
                "yaci_client.api.pool_service.get_pool_registrations.sync",
                return_value=[self.REGISTRATION],
            ),
            patch(
                "yaci_client.api.pool_service.get_retirements.sync",
                return_value=[
                    PoolRetirement(pool_id=POOL_ID_HEX, retirement_epoch=15, slot=20)
                ],
            ),
        ):
            assert yaci_devkit_chain_context.stake_pools() == []

    def test_stake_pools_keeps_retiring_and_deduplicates(
        self, yaci_devkit_chain_context
    ):
        """A pool re-registering must appear once, and a future retirement keeps it."""
        later = PoolRegistration(
            pool_id=POOL_ID_HEX,
            vrf_key_hash=VRF_KEY_HASH,
            pledge=200000000,
            slot=30,
            cert_index=0,
        )
        with (
            patch(
                "yaci_client.api.local_epoch_service.get_latest_epoch.sync",
                return_value=EpochNo(epoch=10),
            ),
            patch(
                "yaci_client.api.pool_service.get_pool_registrations.sync",
                return_value=[later, self.REGISTRATION],
            ),
            patch(
                "yaci_client.api.pool_service.get_retirements.sync",
                return_value=[
                    PoolRetirement(pool_id=POOL_ID_HEX, retirement_epoch=15, slot=40)
                ],
            ),
        ):
            pools = yaci_devkit_chain_context.stake_pools()

        assert pools == [PoolOperator(PoolKeyHash(bytes.fromhex(POOL_ID_HEX)))]

    def test_stake_pool_info(self, yaci_devkit_chain_context):
        with (
            patch(
                "yaci_client.api.local_epoch_service.get_latest_epoch.sync",
                return_value=EpochNo(epoch=10),
            ),
            patch(
                "yaci_client.api.pool_service.get_pool_registrations.sync",
                return_value=[self.REGISTRATION],
            ),
            patch("yaci_client.api.pool_service.get_retirements.sync", return_value=[]),
        ):
            info = yaci_devkit_chain_context.stake_pool_info(POOL_ID_BECH32)

        assert info.status is PoolStatus.REGISTERED
        assert info.retiring_epoch is None
        # Yaci indexes certificates, not ledger state: no stake figures at all.
        assert info.live_stake is None
        assert info.active_stake is None
        assert info.opcert_counter is None

        params = info.pool_params
        assert params.operator == PoolKeyHash(bytes.fromhex(POOL_ID_HEX))
        assert params.vrf_keyhash == VrfKeyHash(bytes.fromhex(VRF_KEY_HASH))
        assert params.pledge == 100000000
        assert params.cost == 340000000
        assert params.margin == Fraction(3, 100)
        assert params.reward_account == RewardAccountHash(
            bytes(Address.decode(REWARD_ADDRESS).to_primitive())
        )
        assert params.pool_owners == [
            VerificationKeyHash(bytes.fromhex(OWNER_KEY_HASH))
        ]
        assert params.relays == [SingleHostAddr(port=3001, ipv4="10.0.0.1")]
        assert params.pool_metadata == PoolMetadata(
            url="https://example.com/pool.json",
            pool_metadata_hash=PoolMetadataHash(bytes.fromhex("ee" * 32)),
        )

    def test_stake_pool_info_retiring(self, yaci_devkit_chain_context):
        with (
            patch(
                "yaci_client.api.local_epoch_service.get_latest_epoch.sync",
                return_value=EpochNo(epoch=10),
            ),
            patch(
                "yaci_client.api.pool_service.get_pool_registrations.sync",
                return_value=[self.REGISTRATION],
            ),
            patch(
                "yaci_client.api.pool_service.get_retirements.sync",
                return_value=[
                    PoolRetirement(pool_id=POOL_ID_HEX, retirement_epoch=15, slot=20)
                ],
            ),
        ):
            info = yaci_devkit_chain_context.stake_pool_info(POOL_ID_HEX)

        assert info.status is PoolStatus.RETIRING
        assert info.retiring_epoch == 15

    def test_stake_pool_info_unknown_pool(self, yaci_devkit_chain_context):
        with (
            patch(
                "yaci_client.api.pool_service.get_pool_registrations.sync",
                return_value=[],
            ),
            patch("yaci_client.api.pool_service.get_retirements.sync", return_value=[]),
        ):
            with pytest.raises(ValueError):
                yaci_devkit_chain_context.stake_pool_info(POOL_ID_BECH32)


class TestYaciDevkitDRepInfo:
    DREP = DRep(
        DRepKind.VERIFICATION_KEY_HASH,
        VerificationKeyHash(bytes.fromhex(DREP_KEY_HASH)),
    )

    @staticmethod
    def _patches(registrations=(), updates=(), deregistrations=()):
        return (
            patch(
                "yaci_client.api.d_rep_service.get_d_rep_registrations.sync",
                return_value=list(registrations),
            ),
            patch(
                "yaci_client.api.d_rep_service.get_d_rep_updates.sync",
                return_value=list(updates),
            ),
            patch(
                "yaci_client.api.d_rep_service.get_d_rep_de_registrations.sync",
                return_value=list(deregistrations),
            ),
        )

    def test_registered_drep(self, yaci_devkit_chain_context):
        registration = DRepRegistration(
            drep_hash=DREP_KEY_HASH,
            type=DRepRegistrationType.REG_DREP_CERT,
            deposit=500000000,
            slot=10,
            cert_index=0,
        )
        update = DRepRegistration(
            drep_hash=DREP_KEY_HASH,
            type=DRepRegistrationType.UPDATE_DREP_CERT,
            slot=20,
            cert_index=0,
            anchor_url="https://example.com/drep.json",
            anchor_hash="ff" * 32,
        )
        with contextlib.ExitStack() as stack:
            for p in self._patches([registration], [update]):
                stack.enter_context(p)
            info = yaci_devkit_chain_context.drep_info(self.DREP)

        assert info.status is DRepStatus.REGISTERED
        assert info.active is True
        # The deposit is carried by the registration, not the later update.
        assert info.deposit == 500000000
        assert info.anchor == Anchor(
            url="https://example.com/drep.json",
            data_hash=AnchorDataHash(bytes.fromhex("ff" * 32)),
        )
        # Yaci indexes certificates and never sees voting power, so the figure
        # is unknown rather than zero. This is the case the optional field
        # exists for: reporting 0 here would claim every DRep has no support.
        assert info.stake is None
        assert info.expiry is None

    def test_retired_drep(self, yaci_devkit_chain_context):
        registration = DRepRegistration(
            drep_hash=DREP_KEY_HASH,
            type=DRepRegistrationType.REG_DREP_CERT,
            slot=10,
            cert_index=0,
        )
        deregistration = DRepRegistration(
            drep_hash=DREP_KEY_HASH,
            type=DRepRegistrationType.UNREG_DREP_CERT,
            slot=30,
            cert_index=0,
        )
        with contextlib.ExitStack() as stack:
            for p in self._patches([registration], [], [deregistration]):
                stack.enter_context(p)
            info = yaci_devkit_chain_context.drep_info(self.DREP)

        assert info.status is DRepStatus.RETIRED
        assert info.active is False

    def test_unknown_drep(self, yaci_devkit_chain_context):
        with contextlib.ExitStack() as stack:
            for p in self._patches():
                stack.enter_context(p)
            info = yaci_devkit_chain_context.drep_info(self.DREP)

        assert info.status is DRepStatus.NOT_REGISTERED
        assert info.active is False

    def test_predefined_drep_needs_no_request(self, yaci_devkit_chain_context):
        info = yaci_devkit_chain_context.drep_info(DRep(DRepKind.ALWAYS_ABSTAIN))
        assert info.status is DRepStatus.NOT_REGISTERED


class TestYaciDevkitGovernance:
    GOV_ACTION_ID = GovActionId(
        transaction_id=TransactionId(bytes.fromhex(TX_HASH)), gov_action_index=0
    )

    VOTES = [
        VotingProcedure(
            voter_type=VotingProcedureVoterType.CONSTITUTIONAL_COMMITTEE_HOT_KEY_HASH,
            voter_hash=CC_HOT_KEY_HASH,
            vote=VotingProcedureVote.YES,
            slot=10,
            index=0,
        ),
        VotingProcedure(
            voter_type=VotingProcedureVoterType.DREP_KEY_HASH,
            voter_hash=DREP_KEY_HASH,
            vote=VotingProcedureVote.NO,
            slot=11,
            index=0,
        ),
        VotingProcedure(
            voter_type=VotingProcedureVoterType.DREP_SCRIPT_HASH,
            voter_hash=DREP_SCRIPT_HASH,
            vote=VotingProcedureVote.ABSTAIN,
            slot=12,
            index=0,
        ),
        VotingProcedure(
            voter_type=VotingProcedureVoterType.STAKING_POOL_KEY_HASH,
            voter_hash=POOL_ID_HEX,
            vote=VotingProcedureVote.YES,
            slot=13,
            index=0,
        ),
    ]

    def test_gov_action_info(self, yaci_devkit_chain_context):
        with (
            patch(
                "yaci_client.api.gov_action_proposal_service.get_gov_action_proposal_by_tx.sync",
                return_value=[_proposal(index=1), _proposal(index=0)],
            ),
            patch(
                "yaci_client.api.local_epoch_service.get_latest_protocol_params.sync",
                return_value=ProtocolParamsDto(gov_action_lifetime=6),
            ),
        ):
            info = yaci_devkit_chain_context.gov_action_info(self.GOV_ACTION_ID)

        assert info.gov_action_id == self.GOV_ACTION_ID
        assert info.gov_action == {"tag": "InfoAction"}
        assert info.proposed_in == 12
        assert info.expires_after == 18
        # Yaci has no governance state, so no outcome epoch is ever set.
        assert info.ratified_epoch is None
        assert info.enacted_epoch is None
        assert info.dropped_epoch is None
        assert info.expired_epoch is None
        assert info.status is None

    def test_gov_action_info_unknown(self, yaci_devkit_chain_context):
        with patch(
            "yaci_client.api.gov_action_proposal_service.get_gov_action_proposal_by_tx.sync",
            return_value=[_proposal(index=5)],
        ):
            with pytest.raises(ValueError):
                yaci_devkit_chain_context.gov_action_info(self.GOV_ACTION_ID)

    def test_gov_action_votes_split_by_voter_class(self, yaci_devkit_chain_context):
        with (
            patch(
                "yaci_client.api.gov_action_proposal_service.get_gov_action_proposal_by_tx.sync",
                return_value=[_proposal()],
            ),
            patch(
                "yaci_client.api.gov_action_proposal_service."
                "get_voting_procedures_for_gov_action_proposal.sync",
                return_value=self.VOTES,
            ),
            patch(
                "yaci_client.api.local_epoch_service.get_latest_protocol_params.sync",
                return_value=ProtocolParamsDto(gov_action_lifetime=6),
            ),
        ):
            votes = yaci_devkit_chain_context.gov_action_votes(self.GOV_ACTION_ID)

        assert votes.gov_action_id == self.GOV_ACTION_ID
        assert votes.deposit == 100000000000
        assert votes.deposit_return_addr == REWARD_ADDRESS
        assert votes.anchor == Anchor(
            url="https://example.com/info.json",
            data_hash=AnchorDataHash(bytes.fromhex("dd" * 32)),
        )

        assert votes.committee_votes == [
            CommitteeVote(
                voter=CommitteeHotCredential(
                    VerificationKeyHash(bytes.fromhex(CC_HOT_KEY_HASH))
                ),
                vote=Vote.YES,
            )
        ]
        assert votes.drep_votes == [
            DRepVote(
                voter=DRep(
                    DRepKind.VERIFICATION_KEY_HASH,
                    VerificationKeyHash(bytes.fromhex(DREP_KEY_HASH)),
                ),
                vote=Vote.NO,
            ),
            DRepVote(
                voter=DRep(
                    DRepKind.SCRIPT_HASH, ScriptHash(bytes.fromhex(DREP_SCRIPT_HASH))
                ),
                vote=Vote.ABSTAIN,
            ),
        ]
        assert votes.stake_pool_votes == [
            StakePoolVote(voter=POOL_ID_BECH32, vote=Vote.YES)
        ]

    def test_gov_action_votes_keeps_only_a_voter_s_latest_vote(
        self, yaci_devkit_chain_context
    ):
        recast = VotingProcedure(
            voter_type=VotingProcedureVoterType.DREP_KEY_HASH,
            voter_hash=DREP_KEY_HASH,
            vote=VotingProcedureVote.YES,
            slot=99,
            index=0,
        )
        with (
            patch(
                "yaci_client.api.gov_action_proposal_service.get_gov_action_proposal_by_tx.sync",
                return_value=[_proposal()],
            ),
            patch(
                "yaci_client.api.gov_action_proposal_service."
                "get_voting_procedures_for_gov_action_proposal.sync",
                return_value=[self.VOTES[1], recast],
            ),
            patch(
                "yaci_client.api.local_epoch_service.get_latest_protocol_params.sync",
                return_value=ProtocolParamsDto(gov_action_lifetime=6),
            ),
        ):
            votes = yaci_devkit_chain_context.gov_action_votes(self.GOV_ACTION_ID)

        assert len(votes.drep_votes) == 1
        assert votes.drep_votes[0].vote is Vote.YES

    def test_gov_actions_all(self, yaci_devkit_chain_context):
        with (
            patch(
                "yaci_client.api.gov_action_proposal_service.get_gov_action_proposal_list.sync",
                return_value=[_proposal(index=0), _proposal(index=1)],
            ),
            patch(
                "yaci_client.api.gov_action_proposal_service."
                "get_voting_procedures_for_gov_action_proposal.sync",
                return_value=[],
            ),
            patch(
                "yaci_client.api.local_epoch_service.get_latest_protocol_params.sync",
                return_value=ProtocolParamsDto(gov_action_lifetime=6),
            ),
        ):
            actions = yaci_devkit_chain_context.gov_actions_all()

        assert [a.gov_action_id.gov_action_index for a in actions] == [0, 1]
        assert all(a.drep_votes == [] for a in actions)


class TestYaciDevkitUnsupportedQueries:
    """Queries Yaci genuinely cannot answer must keep raising, not return empties."""

    def test_treasury(self, yaci_devkit_chain_context):
        with pytest.raises(NotImplementedError):
            yaci_devkit_chain_context.treasury()

    def test_kes_period_info(self, yaci_devkit_chain_context):
        with pytest.raises(NotImplementedError):
            yaci_devkit_chain_context.kes_period_info()

    def test_committee_state(self, yaci_devkit_chain_context):
        with pytest.raises(NotImplementedError):
            yaci_devkit_chain_context.committee_state()

    def test_committee_member_info(self, yaci_devkit_chain_context):
        with pytest.raises(NotImplementedError):
            yaci_devkit_chain_context.committee_member_info()

    def test_drep_stake_distribution(self, yaci_devkit_chain_context):
        with pytest.raises(NotImplementedError):
            yaci_devkit_chain_context.drep_stake_distribution()

    def test_spo_stake_distribution(self, yaci_devkit_chain_context):
        with pytest.raises(NotImplementedError):
            yaci_devkit_chain_context.spo_stake_distribution()


class TestClientIsReusable:
    """The generated yaci-client's __exit__ closes the underlying httpx client,
    and httpx refuses to reopen a closed one:

        RuntimeError: Cannot reopen a client instance, once it has been closed.

    Every query used to run inside `with self.api as client:`, so a context
    could serve exactly one request in its lifetime. These guard the fix.
    """

    def test_two_sequential_queries_on_one_context(self, yaci_devkit_chain_context):
        with patch(
            "yaci_client.api.block_service.get_latest_block.sync",
            return_value=BlockDto(era=7),
        ):
            assert yaci_devkit_chain_context.era is Era.CONWAY
            # The second call is the one that used to fail.
            assert yaci_devkit_chain_context.era is Era.CONWAY

    def test_the_underlying_httpx_client_is_never_closed(
        self, yaci_devkit_chain_context
    ):
        with patch(
            "yaci_client.api.block_service.get_latest_block.sync",
            return_value=BlockDto(era=7),
        ):
            _ = yaci_devkit_chain_context.era
        assert not yaci_devkit_chain_context.api.get_httpx_client().is_closed

    def test_no_query_enters_the_client_as_a_context_manager(self):
        """`with self.api` is what closed it; nothing may reintroduce that."""
        import inspect

        from pccontext.backend import yaci_devkit

        source = inspect.getsource(yaci_devkit)
        assert "with self.api as" not in source
