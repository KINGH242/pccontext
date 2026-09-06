import json
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from unittest.mock import patch

import pytest
from ogmios.client import Client as OgmiosClient
from ogmios.statequery import (
    QueryBlockHeight,
    QueryConstitutionalCommittee,
    QueryEpoch,
    QueryEraSummaries,
    QueryGenesisConfiguration,
    QueryNetworkTip,
    QueryProtocolParameters,
    QueryRewardsProvenance,
    QueryStakePools,
    QueryTreasuryAndReserves,
    QueryUtxo,
)
from pycardano import (
    Address,
    Anchor,
    AnchorDataHash,
    CommitteeColdCredential,
    CommitteeHotCredential,
    DRep,
    DRepKind,
    GovActionId,
    MultiHostName,
    PoolMetadata,
    PoolMetadataHash,
    PoolOperator,
    RewardAccountHash,
    ScriptHash,
    SingleHostAddr,
    SingleHostName,
    TransactionId,
    TransactionOutput,
    VerificationKeyHash,
    Vote,
)
from pycardano.transaction import MultiAsset, TransactionInput, Value

from pccontext.backend.ogmios import ALONZO_COINS_PER_UTXO_WORD, OgmiosChainContext
from pccontext.enums import CommitteeMemberStatus, DRepStatus, Era, PoolStatus
from pccontext.exceptions import OgmiosError
from pccontext.models import (
    CommitteeVote,
    DRepStakeEntry,
    DRepVote,
    GenesisParameters,
    SPOStakeEntry,
    StakePoolVote,
)


class TestOgmiosChainContext:
    def test_protocol_param(
        self, ogmios_chain_context, ogmios_protocol_parameters_response
    ):
        with (
            patch.object(
                QueryProtocolParameters,
                "execute",
                return_value=QueryProtocolParameters._parse_QueryProtocolParameters_response(
                    ogmios_protocol_parameters_response
                ),
            ),
            patch("ogmios.client.connect"),
        ):
            protocol_param = ogmios_chain_context.protocol_param

            ogmios_protocol_parameters = ogmios_protocol_parameters_response["result"]

            assert (
                protocol_param.collateral_percent
                == ogmios_protocol_parameters["collateralPercentage"]
            )
            # pycardano indexes each language's costs by key, so they arrive as an ordered
            # mapping rather than the bare list ogmios reports.
            assert {
                language: list(costs.values())
                for language, costs in protocol_param.cost_models.items()
            } == {
                "PlutusV1": ogmios_protocol_parameters["plutusCostModels"]["plutus:v1"],
                "PlutusV2": ogmios_protocol_parameters["plutusCostModels"]["plutus:v2"],
                "PlutusV3": ogmios_protocol_parameters["plutusCostModels"]["plutus:v3"],
            }

            assert protocol_param.price_mem == float(
                Fraction(ogmios_protocol_parameters["scriptExecutionPrices"]["memory"])
            )
            assert protocol_param.price_step == float(
                Fraction(ogmios_protocol_parameters["scriptExecutionPrices"]["cpu"])
            )
            assert protocol_param.max_block_size == float(
                ogmios_protocol_parameters["maxBlockBodySize"]["bytes"]
            )
            assert protocol_param.max_block_header_size == float(
                ogmios_protocol_parameters["maxBlockHeaderSize"]["bytes"]
            )
            assert protocol_param.max_tx_size == float(
                ogmios_protocol_parameters["maxTransactionSize"]["bytes"]
            )
            assert protocol_param.max_tx_ex_mem == float(
                ogmios_protocol_parameters["maxExecutionUnitsPerTransaction"]["memory"]
            )
            assert protocol_param.max_tx_ex_steps == float(
                ogmios_protocol_parameters["maxExecutionUnitsPerTransaction"]["cpu"]
            )
            assert protocol_param.max_block_ex_mem == float(
                ogmios_protocol_parameters["maxExecutionUnitsPerBlock"]["memory"]
            )
            assert protocol_param.max_block_ex_steps == float(
                ogmios_protocol_parameters["maxExecutionUnitsPerBlock"]["cpu"]
            )
            assert protocol_param.max_collateral_inputs == float(
                ogmios_protocol_parameters["maxCollateralInputs"]
            )
            assert (
                protocol_param.max_val_size
                == ogmios_protocol_parameters["maxValueSize"]["bytes"]
            )

            assert protocol_param.min_fee_constant == float(
                ogmios_protocol_parameters["minFeeConstant"]["ada"]["lovelace"]
            )
            assert (
                protocol_param.min_fee_coefficient
                == ogmios_protocol_parameters["minFeeCoefficient"]
            )
            assert protocol_param.min_pool_cost == float(
                ogmios_protocol_parameters["minStakePoolCost"]["ada"]["lovelace"]
            )
            assert (
                protocol_param.min_fee_reference_scripts
                == ogmios_protocol_parameters["minFeeReferenceScripts"]
            )
            assert protocol_param.key_deposit == float(
                ogmios_protocol_parameters["stakeCredentialDeposit"]["ada"]["lovelace"]
            )
            assert protocol_param.pool_deposit == float(
                ogmios_protocol_parameters["stakePoolDeposit"]["ada"]["lovelace"]
            )
            assert protocol_param.pool_influence == float(
                Fraction(ogmios_protocol_parameters["stakePoolPledgeInfluence"])
            )
            assert protocol_param.monetary_expansion == float(
                Fraction(ogmios_protocol_parameters["monetaryExpansion"])
            )
            assert protocol_param.treasury_expansion == float(
                Fraction(ogmios_protocol_parameters["treasuryExpansion"])
            )
            assert protocol_param.protocol_major_version == float(
                Fraction(ogmios_protocol_parameters["version"]["major"])
            )
            assert protocol_param.protocol_minor_version == float(
                Fraction(ogmios_protocol_parameters["version"]["minor"])
            )
            assert protocol_param.coins_per_utxo_word == ALONZO_COINS_PER_UTXO_WORD
            assert (
                protocol_param.coins_per_utxo_byte
                == ogmios_protocol_parameters["minUtxoDepositCoefficient"]
            )

    def test_genesis(
        self,
        ogmios_chain_context,
        ogmios_era_summary,
        ogmios_genesis_shelley_config_response,
    ):
        with (
            patch.object(
                QueryGenesisConfiguration,
                "execute",
                return_value=QueryGenesisConfiguration._parse_QueryGenesisConfiguration_response(
                    ogmios_genesis_shelley_config_response
                ),
            ),
            patch.object(
                QueryEraSummaries,
                "execute",
                return_value=(
                    ogmios_era_summary,
                    None,
                ),
            ),
            patch("ogmios.client.connect"),
        ):
            genesis_param = ogmios_chain_context.genesis_param

        assert (
            GenesisParameters(
                active_slots_coefficient=0.05,
                update_quorum=5,
                max_lovelace_supply=45000000000000000,
                network_magic=764824073,
                epoch_length=432000,
                system_start=datetime(2017, 9, 23, 21, 44, 51),
                slots_per_kes_period=129600,
                slot_length=1000,
                max_kes_evolutions=62,
                security_param=2160,
            )
            == genesis_param
        )

    def test_utxo(
        self, ogmios_chain_context, ogmios_network_tip_response, ogmios_utxos_response
    ):
        with (
            patch.object(
                QueryUtxo,
                "execute",
                side_effect=(
                    QueryUtxo._parse_QueryUtxo_response(ogmios_utxos_response),
                    None,
                ),
            ),
            patch("ogmios.client.connect"),
            patch.object(
                QueryNetworkTip,
                "execute",
                side_effect=(
                    QueryNetworkTip._parse_QueryNetworkTip_response(
                        ogmios_network_tip_response
                    ),
                    None,
                ),
            ),
        ):
            results = ogmios_chain_context.utxos(
                "addr_test1qraen6hr9zs5yae8cxnhlkh7rk2nfl7rnpg0xvmel3a0xf70v3kz6ee7mtq86x6gmrnw8j7kuf485902akkr7tlcx24qemz34a"
            )

        assert results[0].input == TransactionInput.from_primitive(
            ["3a42f652bd8dee788577e8c39b6217db3df659c33b10a2814c20fb66089ca167", 1]
        )
        assert results[0].output == TransactionOutput(
            address=Address.from_primitive(
                "addr_test1qraen6hr9zs5yae8cxnhlkh7rk2nfl7rnpg0xvmel3a0xf70v3kz6ee7mtq86x6gmrnw8j7kuf485902akkr7tlcx24qemz34a"
            ),
            amount=Value(coin=9858539, multi_asset=MultiAsset()),
        )

        assert results[1].input == TransactionInput.from_primitive(
            ["c93d5dac64e3267abd2a91b9759e0d08395090d7bd89dfdfecd7ccc566661bcd", 1]
        )
        assert results[1].output == TransactionOutput(
            address=Address.from_primitive(
                "addr_test1qraen6hr9zs5yae8cxnhlkh7rk2nfl7rnpg0xvmel3a0xf70v3kz6ee7mtq86x6gmrnw8j7kuf485902akkr7tlcx24qemz34a"
            ),
            amount=Value(coin=9654079, multi_asset=MultiAsset()),
        )

        assert results[2].input == TransactionInput.from_primitive(
            ["a29b70c94e4713825ae8f8771a09ba20ef0cc2cc4a1ea44b69673923cb745b77", 0]
        )
        assert results[2].output == TransactionOutput(
            address=Address.from_primitive(
                "addr_test1qraen6hr9zs5yae8cxnhlkh7rk2nfl7rnpg0xvmel3a0xf70v3kz6ee7mtq86x6gmrnw8j7kuf485902akkr7tlcx24qemz34a"
            ),
            amount=Value(
                coin=7094260,
                multi_asset=MultiAsset.from_primitive(
                    {
                        "0499adba96c80ed30dc5ac4bc7aa540835838ba219c0ea21c2f1e704": {
                            "5547546f79313336": 1,
                            "5547546f79323135": 1,
                            "5547546f79333131": 1,
                        },
                        "04f57233694aec7d1d594a8dd207fdbd3b63a1246fb637c260ec9a85": {
                            "4465727050617373313533": 1,
                            "44657270506173733236": 1,
                        },
                        "0d4d94a639c1f29f516e20911c1feea0f6b22ff468dcaacc9d02c381": {
                            "24444f55474850617373323839": 1,
                            "24444f55474850617373393239": 1,
                        },
                        "1d5ff173a5897a76d75a56b22ab001cd3d73463b8a14e21b5cfc3d01": {
                            "4c6f737443726f776e313032": 1
                        },
                        "1d8b26107c604d36e24963be3ba26f264245cae0e10c7fa15846efd2": {
                            "466f7878656431343932": 1
                        },
                        "2341201e2508eaebd9acaecbaa7630350cee6ebf437c52cc42bab23e": {
                            "477265656479476f626c696e7331393233": 1,
                            "477265656479476f626c696e7332333939": 1,
                            "477265656479476f626c696e7333323838": 1,
                            "477265656479476f626c696e73333539": 1,
                            "477265656479476f626c696e7334383536": 1,
                            "477265656479476f626c696e7335343833": 1,
                            "477265656479476f626c696e73373230": 1,
                            "477265656479476f626c696e73393634": 1,
                        },
                        "2f8f1726932ca6b46efd9cc6ef4c426304d8dbae74d033a8bc4edef4": {
                            "5269636b526f6c6c323431": 1,
                            "5269636b526f6c6c333335": 1,
                            "5269636b526f6c6c343230": 1,
                        },
                        "430647cb0eb21a64d250d1451c910eac5227666da00cd39eed1854ec": {
                            "417065735249504e465453657269657331353936": 1,
                            "417065735249504e465453657269657331363432": 1,
                            "417065735249504e465453657269657333323531": 1,
                            "417065735249504e4654536572696573393731": 1,
                        },
                        "53abd3b2432d7edfd7c59a11e577c872a898847e230e46c63c42938c": {
                            "444f4c4c59": 87000
                        },
                        "65bdf33f8f7fd4debeb2ad659473749eb4eac177e06650bb75a8fe50": {
                            "4d69746872546f6b656e": 1
                        },
                        "66fade242e56c2ce1b0a5beb20e905378f6e016bd24cf22bc617f2c2": {
                            "6265706570617373313035": 1,
                            "6265706570617373343635": 1,
                        },
                        "6e0dcc39f9cd4189953c170b763913529483a3709bd85c24b19bb234": {
                            "4570737465696e4c697374313334": 1,
                            "4570737465696e4c6973743831": 1,
                        },
                        "7003c12cda07c3ab9acc99ce68cf2a476dc7ea3ba8b35d85cdb096e5": {
                            "506570654275726e50617373323837": 1
                        },
                        "72007ec54b04959442a5cc1b317a7389ae28ade9855deac87d6fec4d": {
                            "41706573522e492e505469636b657450617373313132": 1,
                            "41706573522e492e505469636b657450617373323933": 1,
                        },
                        "792f1fdb68bf6e6fd72aed1bed3f14c9593edbcb2f9bd64f0b55d619": {
                            "4e657266436f696e50617373313130": 1,
                            "4e657266436f696e50617373313330": 1,
                            "4e657266436f696e50617373323139": 1,
                        },
                        "9a6de60bcd6dceef3e84b3d5e012f247236866fc7b4fedd1fd44b2cb": {
                            "486f6d656c65737342756d73313034": 1,
                            "486f6d656c65737342756d73333030": 1,
                            "486f6d656c65737342756d73343135": 1,
                            "486f6d656c65737342756d73343237": 1,
                            "486f6d656c65737342756d733436": 1,
                            "486f6d656c65737342756d73343635": 1,
                        },
                        "b72a07053117e192339ea4fe285f99f91eb80452a7d313bbb0872285": {
                            "4164616e697461343831": 1,
                            "4164616e697461353131": 1,
                        },
                        "d3f429f3702cbc4b0dd2616f88baf6cf5d55d922c4d50bdd4be115ae": {
                            "427562756c6c7331313037": 1,
                            "427562756c6c7331313634": 1,
                            "427562756c6c7331323635": 1,
                            "427562756c6c7331323931": 1,
                            "427562756c6c7332303238": 1,
                        },
                        "d64a52a708f88252f4fb3b16014c81e605b4b5d0aa3480c02fcc2e2f": {
                            "484f415244": 907046382
                        },
                        "e399578b7e763bc181ce8b45aabc65245d9be7c7e1edf68fbeb1d494": {
                            "436861726c657350617373353234": 1
                        },
                    }
                ),
            ),
        )

    def test_utxo_by_tx_id(
        self, ogmios_chain_context, ogmios_network_tip_response, ogmios_utxos_response
    ):
        with (
            patch.object(
                QueryUtxo,
                "execute",
                side_effect=(
                    QueryUtxo._parse_QueryUtxo_response(ogmios_utxos_response),
                    None,
                ),
            ),
            patch("ogmios.client.connect"),
            patch.object(
                QueryNetworkTip,
                "execute",
                side_effect=(
                    QueryNetworkTip._parse_QueryNetworkTip_response(
                        ogmios_network_tip_response
                    ),
                    None,
                ),
            ),
        ):
            results = ogmios_chain_context.utxo_by_tx_id(
                "3a42f652bd8dee788577e8c39b6217db3df659c33b10a2814c20fb66089ca167", 1
            )

        assert results.input == TransactionInput.from_primitive(
            ["3a42f652bd8dee788577e8c39b6217db3df659c33b10a2814c20fb66089ca167", 1]
        )
        assert results.output == TransactionOutput(
            address=Address.from_primitive(
                "addr_test1qraen6hr9zs5yae8cxnhlkh7rk2nfl7rnpg0xvmel3a0xf70v3kz6ee7mtq86x6gmrnw8j7kuf485902akkr7tlcx24qemz34a"
            ),
            amount=Value(coin=9858539, multi_asset=MultiAsset()),
        )


COMMITTEE_COLD_KEY_HASH = "cc30497f4ff962f4c1dca54cceefe39f86f1d7179668009f8eb71e59"
COMMITTEE_HOT_SCRIPT_HASH = "1ba48f0e0a1e0a1b6b2e4a0f5c9d3e2f1a0b9c8d7e6f5a4b3c2d1e0f"
COMMITTEE_RESIGNED_HASH = "3fb0f2a4d1c8e7b6a59483726150fedcba9876543210abcdef012345"

POOL_ID = "pool1escyjl60l930fswu54xvamlrn7r0r4chje5qp8uwku09j7x68x6"
POOL_KEY_HASH = "cc30497f4ff962f4c1dca54cceefe39f86f1d7179668009f8eb71e59"
OTHER_POOL_ID = "pool1pu5jlj4q9w9jlxeu370a3c9myx47md5j5m2str0naunn2q3lkdy"
REWARD_ACCOUNT = "stake_test1urxrqjtlfluk9axpmjj5enh0uw0cduwhz7txsqyl36m3ukgmd6hlp"


@pytest.fixture
def ogmios_stake_pool():
    return {
        "id": POOL_ID,
        "vrfVerificationKeyHash": "ff" * 32,
        "owners": [POOL_KEY_HASH],
        "cost": {"ada": {"lovelace": 170000000}},
        "margin": "3/100",
        "pledge": {"ada": {"lovelace": 100000000000}},
        "rewardAccount": REWARD_ACCOUNT,
        "metadata": {"url": "https://example.com/pool.json", "hash": "ab" * 32},
        "relays": [
            {"type": "ipAddress", "ipv4": "1.2.3.4", "port": 3001},
            {"type": "hostname", "hostname": "relay.example.com", "port": 3002},
            {"type": "hostname", "hostname": "srv.example.com"},
        ],
    }


@pytest.fixture
def ogmios_stake_pools_response(ogmios_stake_pool):
    return {
        "method": "queryLedgerState/stakePools",
        "result": {POOL_ID: ogmios_stake_pool},
    }


@pytest.fixture
def ogmios_rewards_provenance_response():
    return {
        "method": "queryLedgerState/rewardsProvenance",
        "result": {
            "desiredNumberOfStakePools": 500,
            "stakePoolPledgeInfluence": "3/10",
            "totalRewardsInEpoch": {"ada": {"lovelace": 20000000000}},
            "totalStakeInEpoch": {"ada": {"lovelace": 1000000000000}},
            "activeStakeInEpoch": {"ada": {"lovelace": 800000000000}},
            "stakePools": {
                POOL_ID: {
                    "id": POOL_ID,
                    "stake": {"ada": {"lovelace": 200000000000}},
                    "ownerStake": {"ada": {"lovelace": 100000000000}},
                    "approximatePerformance": 1.02,
                    "parameters": {},
                },
                OTHER_POOL_ID: {
                    "id": OTHER_POOL_ID,
                    "stake": {"ada": {"lovelace": 600000000000}},
                    "ownerStake": {"ada": {"lovelace": 5000000000}},
                    "approximatePerformance": 0.98,
                    "parameters": {},
                },
            },
        },
    }


@pytest.fixture
def ogmios_constitutional_committee_response():
    return {
        "method": "queryLedgerState/constitutionalCommittee",
        "result": {
            "members": [
                {
                    "id": COMMITTEE_COLD_KEY_HASH,
                    "from": "verificationKey",
                    "status": "active",
                    "mandate": {"epoch": 580},
                    "delegate": {
                        "status": "authorized",
                        "id": COMMITTEE_HOT_SCRIPT_HASH,
                        "from": "script",
                    },
                },
                {
                    "id": COMMITTEE_RESIGNED_HASH,
                    "from": "script",
                    "status": "expired",
                    "mandate": {"epoch": 420},
                    "delegate": {"status": "resigned"},
                },
            ],
            "quorum": "2/3",
        },
    }


OPCERT_POOL_ID = "pool1397kpa7ylzg4lqrmj3xr28xzq2548c8lafw90qyxvucsslap03v"
DREP_KEY_HASH = "000e058ed523b3c64865089580f1604e13178f5df2bee538e1b96203"
DREP_SCRIPT_HASH = "0c5d713c61a09e05d5f975aabf73f8e699ea7ed004141fd4ece6f8d2"
DREP_METADATA_HASH = "b5f8f69913ca29e453f2ac9fd0d2a906e2f50f75d14ee78d2afb08cbb5a96294"
DREP_METADATA_URL = "https://metadata-govtool.cardanoapi.io/data/Justine"

GOV_ACTION_TX_ID = "910199f3c5a5d58c2342285fc40837a0f7041925580705f3adc083ece0f06d3d"
GOV_RETURN_ACCOUNT = "stake_test1up8xg8ur80nsymvefrlk4dshjyfrze4pep843l289f4n8fgrtrmy4"
GOV_METADATA_HASH = "866a28625ad0a73892c4a7956f4400e59354d7d9281721bb2c15dbe67ef97d3b"
GOV_METADATA_URL = "https://metadata-govtool.cardanoapi.io/data/decumbo"
DREP_VOTER_NO = "ab0d62f6646c980cde6fd65b4a5bb7cbfc8c2b2dabea61f4b46737a5"
DREP_VOTER_YES = "b1186c121f6a75f3ba749aa5b1e50b41b9be1726f3306ece7d77d4c1"


@contextmanager
def ogmios_exchange(*responses):
    """Stand in for the websocket exchange of a hand-rolled ledger-state query.

    The installed ``ogmios`` client binds none of the three queries used below,
    so there is no ``QueryX.execute`` to patch: the backend writes the JSON-RPC
    request itself. This patches the socket instead, yields the list the
    requests are recorded into, and answers each with the next canned response.
    """
    sent = []

    with (
        patch("ogmios.client.connect"),
        patch.object(
            OgmiosClient,
            "send",
            side_effect=lambda request: sent.append(json.loads(request)),
        ),
        patch.object(OgmiosClient, "receive", side_effect=list(responses)),
    ):
        yield sent


@pytest.fixture
def ogmios_operational_certificates_response():
    """A real ``queryLedgerState/operationalCertificates`` response."""
    return {
        "jsonrpc": "2.0",
        "id": "4tKK9",
        "method": "queryLedgerState/operationalCertificates",
        "result": {
            "pool1ssvpmsymcz8nd6tu3wgdhy93ajw0yrdauh9gp3djxvda5g6nqma": 0,
            "pool14cwzrv0mtr68kp44t9fn5wplk9ku20g6rv98sxggd3azg60qukm": 6,
            "pool18ut2jlv66s0dh70pp4za2pu42dg57jynflkj9fexamcfqcsmc5q": 0,
            "pool1d4nsv4wa0h3cvdkzuj7trx9d3gz93cj4hkslhekhq0wmcdpwmps": 10,
            "pool1sqva3m6zhvwf9kmuek7gsayxyknzv68ltgqqpeptmdgrqp2lmkf": 4,
            OPCERT_POOL_ID: 12,
        },
    }


@pytest.fixture
def ogmios_delegate_representatives_response():
    """A real ``queryLedgerState/delegateRepresentatives`` response.

    Extended with one script-credential DRep, so the script branch of the
    credential filter is covered by the same shape the ledger returns.
    """
    return {
        "jsonrpc": "2.0",
        "method": "queryLedgerState/delegateRepresentatives",
        "id": "zXWtP",
        "result": [
            {
                "from": "verificationKey",
                "id": DREP_KEY_HASH,
                "deposit": {"ada": {"lovelace": 500000000}},
                "type": "registered",
                "stake": {"ada": {"lovelace": 0}},
                "mandate": {"epoch": 1068},
                "metadata": {
                    "hash": DREP_METADATA_HASH,
                    "url": DREP_METADATA_URL,
                },
                "delegators": [],
            },
            {
                "from": "script",
                "id": DREP_SCRIPT_HASH,
                "deposit": {"ada": {"lovelace": 500000000}},
                "type": "registered",
                "stake": {"ada": {"lovelace": 123456789}},
                "delegators": [],
            },
            {
                "stake": {"ada": {"lovelace": 46115228289209}},
                "type": "abstain",
            },
            {
                "stake": {"ada": {"lovelace": 15049380877790}},
                "type": "noConfidence",
            },
        ],
    }


@pytest.fixture
def ogmios_governance_proposals_response():
    """A real ``queryLedgerState/governanceProposals`` response.

    Extended with a constitutional committee vote and a stake pool vote, so all
    three voter classes are exercised; the two DRep votes are as returned.
    """
    return {
        "jsonrpc": "2.0",
        "id": "OmNgj",
        "method": "queryLedgerState/governanceProposals",
        "result": [
            {
                "votes": [
                    {
                        "vote": "no",
                        "issuer": {
                            "id": DREP_VOTER_NO,
                            "from": "verificationKey",
                            "role": "delegateRepresentative",
                        },
                    },
                    {
                        "vote": "yes",
                        "issuer": {
                            "role": "delegateRepresentative",
                            "id": DREP_VOTER_YES,
                            "from": "verificationKey",
                        },
                    },
                    {
                        "vote": "yes",
                        "issuer": {
                            "role": "constitutionalCommittee",
                            "id": COMMITTEE_HOT_SCRIPT_HASH,
                            "from": "script",
                        },
                    },
                    {
                        "vote": "abstain",
                        "issuer": {
                            "role": "stakePoolOperator",
                            "id": POOL_ID,
                        },
                    },
                    {
                        "vote": "yes",
                        "issuer": {
                            "role": "genesisDelegate",
                            "id": COMMITTEE_RESIGNED_HASH,
                            "from": "verificationKey",
                        },
                    },
                ],
                "action": {
                    "type": "treasuryWithdrawals",
                    "withdrawals": {
                        GOV_RETURN_ACCOUNT: {"ada": {"lovelace": 889000000}},
                    },
                    "guardrails": {
                        "hash": "fa24fb305126805cf2164c161d852a0e7330cf988f1fe558cf7d4a64"
                    },
                },
                "deposit": {"ada": {"lovelace": 100000000000}},
                "returnAccount": GOV_RETURN_ACCOUNT,
                "proposal": {
                    "index": 0,
                    "transaction": {"id": GOV_ACTION_TX_ID},
                },
                "metadata": {
                    "url": GOV_METADATA_URL,
                    "hash": GOV_METADATA_HASH,
                },
                "since": {"epoch": 1021},
                "until": {"epoch": 1051},
            }
        ],
    }


@pytest.fixture
def ogmios_treasury_response():
    return {
        "method": "queryLedgerState/treasuryAndReserves",
        "result": {
            "treasury": {"ada": {"lovelace": 1234567890}},
            "reserves": {"ada": {"lovelace": 9876543210}},
        },
    }


class TestOgmiosChainStateQueries:
    def test_era(self, ogmios_chain_context, ogmios_era_summary):
        with (
            patch("ogmios.client.connect"),
            patch.object(
                QueryEraSummaries, "execute", return_value=(ogmios_era_summary, None)
            ),
        ):
            assert ogmios_chain_context.era == Era.CONWAY

    def test_chain_tip(
        self, ogmios_chain_context, ogmios_network_tip_response, ogmios_era_summary
    ):
        with (
            patch("ogmios.client.connect"),
            patch.object(
                QueryNetworkTip,
                "execute",
                return_value=QueryNetworkTip._parse_QueryNetworkTip_response(
                    ogmios_network_tip_response
                ),
            ),
            patch.object(
                QueryBlockHeight,
                "execute",
                return_value=QueryBlockHeight._parse_QueryBlockHeight_response(
                    {"method": "queryNetwork/blockHeight", "result": 11223344}
                ),
            ),
            patch.object(
                QueryEpoch,
                "execute",
                return_value=QueryEpoch._parse_QueryEpoch_response(
                    {"method": "queryLedgerState/epoch", "result": 507}
                ),
            ),
            patch.object(
                QueryEraSummaries, "execute", return_value=(ogmios_era_summary, None)
            ),
        ):
            chain_tip = ogmios_chain_context.chain_tip

        assert chain_tip.slot == 137467329
        assert (
            chain_tip.hash
            == "8231935154b93fc54c6f7d3f91a50ecd40860a039a7166bae68a5ed5ba719d49"
        )
        assert chain_tip.block == 11223344
        assert chain_tip.epoch == 507
        assert chain_tip.era == Era.CONWAY
        # Ogmios reports sync progress on its HTTP health endpoint, not over
        # JSON-RPC, so the backend leaves it unset rather than guessing.
        assert chain_tip.sync_progress is None

    def test_utxo(self, ogmios_chain_context, ogmios_utxos_response):
        with (
            patch("ogmios.client.connect"),
            patch.object(
                QueryUtxo,
                "execute",
                return_value=QueryUtxo._parse_QueryUtxo_response(ogmios_utxos_response),
            ),
        ):
            result = ogmios_chain_context.utxo(
                TransactionInput.from_primitive(
                    [
                        "3a42f652bd8dee788577e8c39b6217db3df659c33b10a2814c20fb66089ca167",
                        1,
                    ]
                )
            )

        assert result is not None
        utxo, is_spent = result
        assert utxo.input == TransactionInput.from_primitive(
            ["3a42f652bd8dee788577e8c39b6217db3df659c33b10a2814c20fb66089ca167", 1]
        )
        # The live UTxO set only holds unspent outputs.
        assert is_spent is False

    def test_utxo_missing_returns_none(self, ogmios_chain_context):
        with (
            patch("ogmios.client.connect"),
            patch.object(QueryUtxo, "execute", return_value=([], None)),
        ):
            assert (
                ogmios_chain_context.utxo(
                    TransactionInput.from_primitive(
                        [
                            "3a42f652bd8dee788577e8c39b6217db3df659c33b10a2814c20fb66089ca167",
                            9,
                        ]
                    )
                )
                is None
            )


class TestOgmiosStakePoolQueries:
    def test_stake_pools(self, ogmios_chain_context, ogmios_stake_pools_response):
        # The all-pools query omits the ``stakePools`` filter, so the backend
        # sends the bare request and parses the response itself.
        with (
            patch("ogmios.client.connect"),
            patch.object(
                QueryStakePools,
                "receive",
                return_value=QueryStakePools._parse_QueryStakePools_response(
                    ogmios_stake_pools_response
                ),
            ),
        ):
            pools = ogmios_chain_context.stake_pools()

        assert pools == [PoolOperator.from_primitive(POOL_ID)]

    def test_stake_pool_info(
        self,
        ogmios_chain_context,
        ogmios_stake_pools_response,
        ogmios_rewards_provenance_response,
    ):
        with (
            patch("ogmios.client.connect"),
            patch.object(
                QueryStakePools,
                "execute",
                return_value=QueryStakePools._parse_QueryStakePools_response(
                    ogmios_stake_pools_response
                ),
            ),
            patch.object(
                QueryRewardsProvenance,
                "execute",
                return_value=QueryRewardsProvenance._parse_QueryRewardsProvenance_response(
                    ogmios_rewards_provenance_response
                ),
            ),
        ):
            info = ogmios_chain_context.stake_pool_info(POOL_ID)

        params = info.pool_params
        assert params is not None
        assert params.operator == PoolOperator.from_primitive(POOL_ID).pool_key_hash
        assert params.pledge == 100000000000
        assert params.cost == 170000000
        assert params.margin == Fraction(3, 100)
        assert params.reward_account == RewardAccountHash(
            bytes(Address.from_primitive(REWARD_ACCOUNT).to_primitive())
        )
        assert params.pool_owners == [VerificationKeyHash(bytes.fromhex(POOL_KEY_HASH))]
        assert params.pool_metadata == PoolMetadata(
            url="https://example.com/pool.json",
            pool_metadata_hash=PoolMetadataHash(bytes.fromhex("ab" * 32)),
        )
        # An ipAddress relay, a hostname relay with a port and the SRV-style
        # hostname relay without one map to the three PyCardano relay types.
        assert params.relays == [
            SingleHostAddr(port=3001, ipv4="1.2.3.4", ipv6=None),
            SingleHostName(port=3002, dns_name="relay.example.com"),
            MultiHostName(dns_name="srv.example.com"),
        ]

        assert info.status == PoolStatus.REGISTERED
        assert info.active_stake == 200000000000
        assert info.live_pledge == 100000000000
        assert info.active_size == Decimal(200000000000) / Decimal(800000000000)
        # Neither an operational certificate counter nor a retirement epoch is
        # reachable over Ogmios.
        assert info.opcert_counter is None
        assert info.retiring_epoch is None

    def test_stake_pool_info_without_rewards_provenance(
        self, ogmios_chain_context, ogmios_stake_pools_response
    ):
        with (
            patch("ogmios.client.connect"),
            patch.object(
                QueryStakePools,
                "execute",
                return_value=QueryStakePools._parse_QueryStakePools_response(
                    ogmios_stake_pools_response
                ),
            ),
            patch.object(
                QueryRewardsProvenance, "execute", side_effect=RuntimeError("boom")
            ),
        ):
            info = ogmios_chain_context.stake_pool_info(POOL_ID)

        assert info.pool_params is not None
        assert info.active_stake is None
        assert info.active_size is None
        assert info.live_pledge is None

    def test_stake_pool_info_not_found(self, ogmios_chain_context):
        with (
            patch("ogmios.client.connect"),
            patch.object(QueryStakePools, "execute", return_value=({}, None)),
            pytest.raises(OgmiosError, match="Stake pool not found"),
        ):
            ogmios_chain_context.stake_pool_info(POOL_ID)

    def test_unknown_relay_type_is_rejected(self, ogmios_chain_context):
        with pytest.raises(OgmiosError, match="Unknown stake pool relay type"):
            OgmiosChainContext._relay_from_ogmios({"type": "carrierPigeon"})

    def test_spo_stake_distribution(
        self, ogmios_chain_context, ogmios_rewards_provenance_response
    ):
        with (
            patch("ogmios.client.connect"),
            patch.object(
                QueryRewardsProvenance,
                "execute",
                return_value=QueryRewardsProvenance._parse_QueryRewardsProvenance_response(
                    ogmios_rewards_provenance_response
                ),
            ),
        ):
            distribution = ogmios_chain_context.spo_stake_distribution()

        assert distribution == [
            SPOStakeEntry(pool_id=POOL_ID, stake=200000000000),
            SPOStakeEntry(pool_id=OTHER_POOL_ID, stake=600000000000),
        ]


class TestOgmiosTreasuryAndGovernanceQueries:
    def test_treasury(self, ogmios_chain_context, ogmios_treasury_response):
        with (
            patch("ogmios.client.connect"),
            patch.object(
                QueryTreasuryAndReserves,
                "execute",
                return_value=QueryTreasuryAndReserves._parse_QueryTreasuryAndReserves_response(
                    ogmios_treasury_response
                ),
            ),
        ):
            assert ogmios_chain_context.treasury() == 1234567890

    def test_committee_state(
        self, ogmios_chain_context, ogmios_constitutional_committee_response
    ):
        with (
            patch("ogmios.client.connect"),
            patch.object(
                QueryConstitutionalCommittee,
                "execute",
                return_value=QueryConstitutionalCommittee._parse_QueryConstitutionalCommittee_response(
                    ogmios_constitutional_committee_response
                ),
            ),
        ):
            state = ogmios_chain_context.committee_state()

        assert state.threshold == 2 / 3
        assert len(state.members) == 2

        authorized, resigned = state.members
        assert authorized.cold_credential == CommitteeColdCredential(
            credential=VerificationKeyHash(bytes.fromhex(COMMITTEE_COLD_KEY_HASH))
        )
        assert authorized.hot_credential == CommitteeHotCredential(
            credential=ScriptHash(bytes.fromhex(COMMITTEE_HOT_SCRIPT_HASH))
        )
        assert authorized.expiration == 580
        assert authorized.status == CommitteeMemberStatus.ACTIVE

        assert resigned.cold_credential == CommitteeColdCredential(
            credential=ScriptHash(bytes.fromhex(COMMITTEE_RESIGNED_HASH))
        )
        # A resigned member has no authorized hot credential.
        assert resigned.hot_credential is None
        assert resigned.status == CommitteeMemberStatus.EXPIRED

    def test_committee_state_without_quorum(
        self, ogmios_chain_context, ogmios_constitutional_committee_response
    ):
        ogmios_constitutional_committee_response["result"]["quorum"] = None
        with (
            patch("ogmios.client.connect"),
            patch.object(
                QueryConstitutionalCommittee,
                "execute",
                return_value=QueryConstitutionalCommittee._parse_QueryConstitutionalCommittee_response(
                    ogmios_constitutional_committee_response
                ),
            ),
        ):
            state = ogmios_chain_context.committee_state()

        assert state.threshold is None

    def test_committee_member_info_by_cold_credential(
        self, ogmios_chain_context, ogmios_constitutional_committee_response
    ):
        cold = CommitteeColdCredential(
            credential=VerificationKeyHash(bytes.fromhex(COMMITTEE_COLD_KEY_HASH))
        )
        with (
            patch("ogmios.client.connect"),
            patch.object(
                QueryConstitutionalCommittee,
                "execute",
                return_value=QueryConstitutionalCommittee._parse_QueryConstitutionalCommittee_response(
                    ogmios_constitutional_committee_response
                ),
            ),
        ):
            member = ogmios_chain_context.committee_member_info(cold=cold)

        assert member.cold_credential == cold
        assert member.expiration == 580

    def test_committee_member_info_by_hot_credential(
        self, ogmios_chain_context, ogmios_constitutional_committee_response
    ):
        hot = CommitteeHotCredential(
            credential=ScriptHash(bytes.fromhex(COMMITTEE_HOT_SCRIPT_HASH))
        )
        with (
            patch("ogmios.client.connect"),
            patch.object(
                QueryConstitutionalCommittee,
                "execute",
                return_value=QueryConstitutionalCommittee._parse_QueryConstitutionalCommittee_response(
                    ogmios_constitutional_committee_response
                ),
            ),
        ):
            member = ogmios_chain_context.committee_member_info(hot=hot)

        assert member.hot_credential == hot
        assert member.cold_credential == CommitteeColdCredential(
            credential=VerificationKeyHash(bytes.fromhex(COMMITTEE_COLD_KEY_HASH))
        )

    def test_committee_member_info_requires_a_credential(self, ogmios_chain_context):
        with pytest.raises(OgmiosError, match="cold or a hot committee credential"):
            ogmios_chain_context.committee_member_info()

    def test_committee_member_info_not_found(
        self, ogmios_chain_context, ogmios_constitutional_committee_response
    ):
        with (
            patch("ogmios.client.connect"),
            patch.object(
                QueryConstitutionalCommittee,
                "execute",
                return_value=QueryConstitutionalCommittee._parse_QueryConstitutionalCommittee_response(
                    ogmios_constitutional_committee_response
                ),
            ),
            pytest.raises(OgmiosError, match="Committee member not found"),
        ):
            ogmios_chain_context.committee_member_info(
                cold=CommitteeColdCredential(
                    credential=VerificationKeyHash(bytes.fromhex("11" * 28))
                )
            )


class TestOgmiosRawLedgerStateQueries:
    """The JSON-RPC envelope the backend writes for the unbound queries."""

    def test_error_responses_are_raised(self, ogmios_chain_context):
        response = {
            "jsonrpc": "2.0",
            "method": "queryLedgerState/operationalCertificates",
            "error": {"code": 2002, "message": "unavailable in current era"},
        }
        with (
            ogmios_exchange(response),
            pytest.raises(OgmiosError, match="responded with an error"),
        ):
            ogmios_chain_context._query_operational_certificates()

    def test_a_response_to_another_method_is_rejected(self, ogmios_chain_context):
        response = {
            "jsonrpc": "2.0",
            "method": "queryLedgerState/epoch",
            "result": 42,
        }
        with (
            ogmios_exchange(response),
            pytest.raises(OgmiosError, match="Incorrect method"),
        ):
            ogmios_chain_context._query_operational_certificates()

    def test_a_response_without_a_result_is_rejected(self, ogmios_chain_context):
        response = {
            "jsonrpc": "2.0",
            "method": "queryLedgerState/governanceProposals",
        }
        with (
            ogmios_exchange(response),
            pytest.raises(OgmiosError, match="Failed to parse"),
        ):
            ogmios_chain_context._query_governance_proposals()


class TestOgmiosKesPeriodInfo:
    def test_kes_period_info(
        self, ogmios_chain_context, ogmios_operational_certificates_response
    ):
        with ogmios_exchange(ogmios_operational_certificates_response) as sent:
            info = ogmios_chain_context.kes_period_info(
                pool=PoolOperator.from_primitive(OPCERT_POOL_ID)
            )

        # The query takes no parameters, so none are sent.
        assert sent == [
            {
                "jsonrpc": "2.0",
                "method": "queryLedgerState/operationalCertificates",
            }
        ]
        assert info.on_chain_op_cert_count == 12
        assert info.next_chain_op_cert_count == 13
        # Ogmios sees no local certificate file.
        assert info.on_disk_op_cert_count is None
        assert info.on_disk_kes_start is None

    def test_kes_period_info_ignores_the_operational_certificate(
        self, ogmios_chain_context, ogmios_operational_certificates_response
    ):
        with ogmios_exchange(ogmios_operational_certificates_response):
            info = ogmios_chain_context.kes_period_info(
                pool=PoolOperator.from_primitive(OPCERT_POOL_ID),
                op_cert=b"\xde\xad\xbe\xef",
            )

        assert info.on_disk_op_cert_count is None

    def test_kes_period_info_requires_a_pool(self, ogmios_chain_context):
        with pytest.raises(OgmiosError, match="pool operator must be provided"):
            ogmios_chain_context.kes_period_info()

    def test_kes_period_info_for_a_pool_without_a_counter(
        self, ogmios_chain_context, ogmios_operational_certificates_response
    ):
        with (
            ogmios_exchange(ogmios_operational_certificates_response),
            pytest.raises(OgmiosError, match="No operational certificate counter"),
        ):
            ogmios_chain_context.kes_period_info(
                pool=PoolOperator.from_primitive(POOL_ID)
            )


class TestOgmiosDRepQueries:
    def test_drep_info_for_a_registered_key_hash_drep(
        self, ogmios_chain_context, ogmios_delegate_representatives_response
    ):
        drep = DRep(
            DRepKind.VERIFICATION_KEY_HASH,
            VerificationKeyHash(bytes.fromhex(DREP_KEY_HASH)),
        )
        with (
            ogmios_exchange(ogmios_delegate_representatives_response) as sent,
            patch.object(QueryEpoch, "execute", return_value=(1000, None)),
        ):
            info = ogmios_chain_context.drep_info(drep)

        assert sent == [
            {
                "jsonrpc": "2.0",
                "method": "queryLedgerState/delegateRepresentatives",
                "params": {"keys": [DREP_KEY_HASH]},
            }
        ]
        assert info.drep == drep
        assert info.deposit == 500000000
        assert info.stake == 0
        assert info.expiry == 1068
        assert info.status == DRepStatus.REGISTERED
        assert info.anchor == Anchor(
            url=DREP_METADATA_URL,
            data_hash=AnchorDataHash(bytes.fromhex(DREP_METADATA_HASH)),
        )
        # The mandate has not lapsed at epoch 1000.
        assert info.active is True

    def test_drep_info_after_the_mandate_lapses(
        self, ogmios_chain_context, ogmios_delegate_representatives_response
    ):
        drep = DRep(
            DRepKind.VERIFICATION_KEY_HASH,
            VerificationKeyHash(bytes.fromhex(DREP_KEY_HASH)),
        )
        with (
            ogmios_exchange(ogmios_delegate_representatives_response),
            patch.object(QueryEpoch, "execute", return_value=(1069, None)),
        ):
            info = ogmios_chain_context.drep_info(drep)

        assert info.active is False
        # A lapsed registration is still a registration.
        assert info.status == DRepStatus.REGISTERED

    def test_drep_info_for_a_script_hash_drep(
        self, ogmios_chain_context, ogmios_delegate_representatives_response
    ):
        drep = DRep(DRepKind.SCRIPT_HASH, ScriptHash(bytes.fromhex(DREP_SCRIPT_HASH)))
        with (
            ogmios_exchange(ogmios_delegate_representatives_response) as sent,
            patch.object(QueryEpoch, "execute", return_value=(1000, None)),
        ):
            info = ogmios_chain_context.drep_info(drep)

        assert sent[0]["params"] == {"scripts": [DREP_SCRIPT_HASH]}
        assert info.stake == 123456789
        # No mandate reported means nothing says the registration has lapsed.
        assert info.expiry is None
        assert info.active is True

    def test_drep_info_for_an_unknown_drep(self, ogmios_chain_context):
        # A filtered query still returns the two predefined options, and never
        # a registered entry for a DRep the ledger does not know.
        response = {
            "jsonrpc": "2.0",
            "method": "queryLedgerState/delegateRepresentatives",
            "result": [
                {"type": "abstain", "stake": {"ada": {"lovelace": 1}}},
                {"type": "noConfidence", "stake": {"ada": {"lovelace": 2}}},
            ],
        }
        drep = DRep(
            DRepKind.VERIFICATION_KEY_HASH,
            VerificationKeyHash(bytes.fromhex("11" * 28)),
        )
        with ogmios_exchange(response):
            info = ogmios_chain_context.drep_info(drep)

        assert info.status == DRepStatus.NOT_REGISTERED
        assert info.active is False
        assert info.stake == 0

    @pytest.mark.parametrize(
        "kind, stake",
        [
            (DRepKind.ALWAYS_ABSTAIN, 46115228289209),
            (DRepKind.ALWAYS_NO_CONFIDENCE, 15049380877790),
        ],
    )
    def test_drep_info_for_the_predefined_options(
        self,
        ogmios_chain_context,
        ogmios_delegate_representatives_response,
        kind,
        stake,
    ):
        with ogmios_exchange(ogmios_delegate_representatives_response) as sent:
            info = ogmios_chain_context.drep_info(DRep(kind))

        # The predefined options are always returned, so no filter is sent.
        assert "params" not in sent[0]
        assert info.stake == stake
        assert info.status == DRepStatus.REGISTERED
        assert info.deposit is None

    def test_drep_info_when_a_predefined_option_is_missing(self, ogmios_chain_context):
        response = {
            "jsonrpc": "2.0",
            "method": "queryLedgerState/delegateRepresentatives",
            "result": [],
        }
        with (
            ogmios_exchange(response),
            pytest.raises(OgmiosError, match="did not report the abstain"),
        ):
            ogmios_chain_context.drep_info(DRep(DRepKind.ALWAYS_ABSTAIN))

    def test_drep_stake_distribution(
        self, ogmios_chain_context, ogmios_delegate_representatives_response
    ):
        with ogmios_exchange(ogmios_delegate_representatives_response) as sent:
            distribution = ogmios_chain_context.drep_stake_distribution()

        assert "params" not in sent[0]
        assert distribution == [
            DRepStakeEntry(
                drep=DRep(
                    DRepKind.VERIFICATION_KEY_HASH,
                    VerificationKeyHash(bytes.fromhex(DREP_KEY_HASH)),
                ),
                stake=0,
            ),
            DRepStakeEntry(
                drep=DRep(
                    DRepKind.SCRIPT_HASH, ScriptHash(bytes.fromhex(DREP_SCRIPT_HASH))
                ),
                stake=123456789,
            ),
            DRepStakeEntry(drep=DRep(DRepKind.ALWAYS_ABSTAIN), stake=46115228289209),
            DRepStakeEntry(
                drep=DRep(DRepKind.ALWAYS_NO_CONFIDENCE), stake=15049380877790
            ),
        ]

    def test_drep_stake_distribution_skips_unreadable_credentials(
        self, ogmios_chain_context
    ):
        response = {
            "jsonrpc": "2.0",
            "method": "queryLedgerState/delegateRepresentatives",
            "result": [
                {
                    "type": "registered",
                    "from": "carrierPigeon",
                    "id": DREP_KEY_HASH,
                    "stake": {"ada": {"lovelace": 7}},
                },
                {"type": "abstain", "stake": {"ada": {"lovelace": 9}}},
            ],
        }
        with ogmios_exchange(response):
            distribution = ogmios_chain_context.drep_stake_distribution()

        assert distribution == [
            DRepStakeEntry(drep=DRep(DRepKind.ALWAYS_ABSTAIN), stake=9)
        ]


class TestOgmiosGovernanceProposalQueries:
    @property
    def gov_action_id(self) -> GovActionId:
        return GovActionId(
            transaction_id=TransactionId(bytes.fromhex(GOV_ACTION_TX_ID)),
            gov_action_index=0,
        )

    def test_gov_action_info(
        self, ogmios_chain_context, ogmios_governance_proposals_response
    ):
        with ogmios_exchange(ogmios_governance_proposals_response) as sent:
            info = ogmios_chain_context.gov_action_info(self.gov_action_id)

        assert sent == [
            {
                "jsonrpc": "2.0",
                "method": "queryLedgerState/governanceProposals",
            }
        ]
        assert info.gov_action_id == self.gov_action_id
        assert info.proposed_in == 1021
        assert info.expires_after == 1051
        # Ogmios describes the action as free-form JSON, which is passed through.
        assert info.gov_action["type"] == "treasuryWithdrawals"
        # Only live proposals are returned, so nothing has resolved.
        assert info.ratified_epoch is None
        assert info.enacted_epoch is None
        assert info.dropped_epoch is None
        assert info.expired_epoch is None
        assert info.status is None

    def test_gov_action_votes(
        self, ogmios_chain_context, ogmios_governance_proposals_response
    ):
        with ogmios_exchange(ogmios_governance_proposals_response):
            votes = ogmios_chain_context.gov_action_votes(self.gov_action_id)

        assert votes.gov_action_id == self.gov_action_id
        assert votes.deposit == 100000000000
        assert votes.deposit_return_addr == GOV_RETURN_ACCOUNT
        assert votes.anchor == Anchor(
            url=GOV_METADATA_URL,
            data_hash=AnchorDataHash(bytes.fromhex(GOV_METADATA_HASH)),
        )
        assert votes.proposed_in == 1021
        assert votes.expires_after == 1051

        assert votes.drep_votes == [
            DRepVote(
                voter=DRep(
                    DRepKind.VERIFICATION_KEY_HASH,
                    VerificationKeyHash(bytes.fromhex(DREP_VOTER_NO)),
                ),
                vote=Vote.NO,
            ),
            DRepVote(
                voter=DRep(
                    DRepKind.VERIFICATION_KEY_HASH,
                    VerificationKeyHash(bytes.fromhex(DREP_VOTER_YES)),
                ),
                vote=Vote.YES,
            ),
        ]
        assert votes.committee_votes == [
            CommitteeVote(
                voter=CommitteeHotCredential(
                    ScriptHash(bytes.fromhex(COMMITTEE_HOT_SCRIPT_HASH))
                ),
                vote=Vote.YES,
            )
        ]
        assert votes.stake_pool_votes == [
            StakePoolVote(voter=POOL_ID, vote=Vote.ABSTAIN)
        ]

    def test_gov_actions_all(
        self, ogmios_chain_context, ogmios_governance_proposals_response
    ):
        with ogmios_exchange(ogmios_governance_proposals_response) as sent:
            actions = ogmios_chain_context.gov_actions_all()

        # The proposal list already carries the votes: one request, no follow-up.
        assert len(sent) == 1
        assert len(actions) == 1
        assert actions[0].gov_action_id == self.gov_action_id
        assert len(actions[0].drep_votes) == 2

    def test_gov_actions_all_skips_unreadable_references(self, ogmios_chain_context):
        response = {
            "jsonrpc": "2.0",
            "method": "queryLedgerState/governanceProposals",
            "result": [{"votes": [], "action": {"type": "information"}}],
        }
        with ogmios_exchange(response):
            assert ogmios_chain_context.gov_actions_all() == []

    def test_gov_action_not_found(
        self, ogmios_chain_context, ogmios_governance_proposals_response
    ):
        missing = GovActionId(
            transaction_id=TransactionId(bytes.fromhex("aa" * 32)), gov_action_index=0
        )
        with (
            ogmios_exchange(ogmios_governance_proposals_response),
            pytest.raises(OgmiosError, match="Governance action not found"),
        ):
            ogmios_chain_context.gov_action_info(missing)
