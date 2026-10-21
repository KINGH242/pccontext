import copy
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any, Callable, Dict, List, Union

import pydantic
import pyogmios
import pytest
from pycardano import (
    Address,
    Anchor,
    AnchorDataHash,
    CommitteeColdCredential,
    CommitteeHotCredential,
    DatumHash,
    DRep,
    DRepKind,
    GovActionId,
    MultiHostName,
    PlutusV1Script,
    PlutusV2Script,
    PlutusV3Script,
    PoolMetadata,
    PoolMetadataHash,
    PoolOperator,
    RawCBOR,
    RewardAccountHash,
    ScriptHash,
    SingleHostAddr,
    SingleHostName,
    TransactionId,
    TransactionOutput,
    VerificationKeyHash,
    Vote,
)
from pycardano.backend.base import GenesisParameters as PyCardanoGenesisParameters
from pycardano.nativescript import (
    InvalidBefore,
    InvalidHereAfter,
    ScriptAll,
    ScriptAny,
    ScriptNofK,
    ScriptPubkey,
)
from pycardano.network import Network
from pycardano.plutus import ExecutionUnits
from pycardano.transaction import MultiAsset, TransactionInput, Value
from pyogmios.errors import (
    EvaluateTransactionError,
    MissingSignatoriesError,
    UnavailableInCurrentEraError,
)

from pccontext.backend.ogmios import ALONZO_COINS_PER_UTXO_WORD, OgmiosChainContext
from pccontext.enums import CommitteeMemberStatus, DRepStatus, Era, PoolStatus
from pccontext.exceptions import OgmiosError
from pccontext.models import (
    CommitteeVote,
    DRepStakeEntry,
    DRepVote,
    SPOStakeEntry,
    StakePoolVote,
)

Result = Union[Any, Callable[[Any], Any]]


class FakeOgmios:
    """A pyogmios transport that answers each method with a canned v7 response.

    Requests go through pyogmios' own parameter validation and the canned
    results through its response parsing, exactly as on the wire. Each request
    is recorded, and ``connects`` counts how often the connection was opened.
    """

    stateful = True

    def __init__(self) -> None:
        self.results: Dict[str, Result] = {}
        self.errors: Dict[str, Dict[str, Any]] = {}
        self.sent: List[Dict[str, Any]] = []
        self.connects = 0
        self.closed = False

    async def connect(self) -> None:
        self.connects += 1

    async def close(self) -> None:
        self.closed = True

    async def request(self, message: Dict[str, Any], timeout: Any) -> Dict[str, Any]:
        self.sent.append(message)
        method = message["method"]
        response: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "id": message.get("id"),
        }
        if method in self.errors:
            response["error"] = self.errors[method]
            return response
        if method not in self.results:
            raise AssertionError(f"unexpected request: {method}")
        result = self.results[method]
        response["result"] = result(message.get("params")) if callable(result) else copy.deepcopy(result)
        return response

    def requests(self, method: str) -> List[Dict[str, Any]]:
        return [m for m in self.sent if m["method"] == method]


@pytest.fixture
def fake_ogmios() -> FakeOgmios:
    return FakeOgmios()


@pytest.fixture
def context(fake_ogmios):
    client = pyogmios.Client(transport=fake_ogmios, check_version="off")
    with OgmiosChainContext(network=Network.TESTNET, client=client) as ctx:
        yield ctx


ADDRESS = "addr_test1qraen6hr9zs5yae8cxnhlkh7rk2nfl7rnpg0xvmel3a0xf70v3kz6ee7mtq86x6gmrnw8j7kuf485902akkr7tlcx24qemz34a"
TX_ID = "3a42f652bd8dee788577e8c39b6217db3df659c33b10a2814c20fb66089ca167"
TIP = {
    "slot": 137467329,
    "id": "8231935154b93fc54c6f7d3f91a50ecd40860a039a7166bae68a5ed5ba719d49",
}
POLICY_ID = "53abd3b2432d7edfd7c59a11e577c872a898847e230e46c63c42938c"
KEY_HASH_A = "32829603ccd47f947389960a0736b1c7ed63015d7040dc4f7801601e"
KEY_HASH_B = "a2a3b82a7f5cd8706b8d185d72944cd755b0d1342a7421c2b208f58f"
DATUM_HASH = "c5dc5a2ff9a2a2ab1a3e0ef8a3d1fd5ef9da6a32a6e9fdba26b7c9e2f0a96a11"
INLINE_DATUM = "d8799f4100ff"


def era_summaries(count: int) -> List[Dict[str, Any]]:
    """``count`` era summaries, the way Ogmios lists one per era since Byron."""
    return [
        {
            "start": {"time": {"seconds": era}, "slot": era, "epoch": era},
            "end": {"time": {"seconds": era + 1}, "slot": era + 1, "epoch": era + 1},
            "parameters": {
                "epochLength": 432000,
                "slotLength": {"milliseconds": 1000},
                "safeZone": 129600,
            },
        }
        for era in range(count)
    ]


def utxo_item(index: int = 1, **output: Any) -> Dict[str, Any]:
    item = {
        "transaction": {"id": TX_ID},
        "index": index,
        "address": ADDRESS,
        "value": {"ada": {"lovelace": 9858539}},
    }
    item.update(output)
    return item


class TestOgmiosConnection:
    def test_queries_share_one_long_lived_connection(self, context, fake_ogmios):
        fake_ogmios.results["queryLedgerState/epoch"] = 507
        fake_ogmios.results["queryNetwork/tip"] = TIP

        for _ in range(3):
            assert context.epoch == 507
        assert context.last_block_slot == TIP["slot"]

        assert len(fake_ogmios.sent) == 4
        assert fake_ogmios.connects == 1

    def test_close_closes_the_connection(self, fake_ogmios):
        client = pyogmios.Client(transport=fake_ogmios, check_version="off")
        context = OgmiosChainContext(client=client)
        fake_ogmios.results["queryLedgerState/epoch"] = 1

        context.epoch
        context.close()

        assert fake_ogmios.closed

    def test_url_from_host_and_port(self):
        assert OgmiosChainContext("ogmios.local", 1338).url == "ws://ogmios.local:1338"
        assert OgmiosChainContext("ogmios.example.com", 443, secure=True).url == "wss://ogmios.example.com:443"

    def test_the_client_is_created_lazily(self):
        context = OgmiosChainContext("localhost", 1337)
        assert context._ogmios is None
        assert context.name == "Ogmios"


class TestOgmiosProtocolParameters:
    def test_protocol_param(self, context, fake_ogmios, ogmios_protocol_parameters):
        fake_ogmios.results["queryLedgerState/protocolParameters"] = ogmios_protocol_parameters

        protocol_param = context.protocol_param
        params = ogmios_protocol_parameters

        assert protocol_param.collateral_percent == params["collateralPercentage"]
        # pycardano indexes each language's costs by key, so they arrive as an ordered
        # mapping rather than the bare list ogmios reports.
        assert {language: list(costs.values()) for language, costs in protocol_param.cost_models.items()} == {
            "PlutusV1": params["plutusCostModels"]["plutus:v1"],
            "PlutusV2": params["plutusCostModels"]["plutus:v2"],
            "PlutusV3": params["plutusCostModels"]["plutus:v3"],
        }

        # Ratios are parsed exactly with Fraction.
        assert protocol_param.price_mem == Fraction(577, 10000)
        assert protocol_param.price_step == Fraction(721, 10000000)
        assert protocol_param.pool_influence == Fraction(3, 10)
        assert protocol_param.monetary_expansion == Fraction(3, 1000)
        assert protocol_param.treasury_expansion == Fraction(1, 5)

        assert protocol_param.max_block_size == params["maxBlockBodySize"]["bytes"]
        assert protocol_param.max_block_header_size == params["maxBlockHeaderSize"]["bytes"]
        assert protocol_param.max_tx_size == params["maxTransactionSize"]["bytes"]
        assert protocol_param.max_tx_ex_mem == params["maxExecutionUnitsPerTransaction"]["memory"]
        assert protocol_param.max_tx_ex_steps == params["maxExecutionUnitsPerTransaction"]["cpu"]
        assert protocol_param.max_block_ex_mem == params["maxExecutionUnitsPerBlock"]["memory"]
        assert protocol_param.max_block_ex_steps == params["maxExecutionUnitsPerBlock"]["cpu"]
        assert protocol_param.max_collateral_inputs == params["maxCollateralInputs"]
        assert protocol_param.max_val_size == params["maxValueSize"]["bytes"]
        assert protocol_param.min_fee_constant == params["minFeeConstant"]["ada"]["lovelace"]
        assert protocol_param.min_fee_coefficient == params["minFeeCoefficient"]
        assert protocol_param.min_pool_cost == params["minStakePoolCost"]["ada"]["lovelace"]
        assert protocol_param.key_deposit == params["stakeCredentialDeposit"]["ada"]["lovelace"]
        assert protocol_param.pool_deposit == params["stakePoolDeposit"]["ada"]["lovelace"]
        assert protocol_param.protocol_major_version == params["version"]["major"]
        assert protocol_param.protocol_minor_version == params["version"]["minor"]
        assert protocol_param.coins_per_utxo_word == ALONZO_COINS_PER_UTXO_WORD
        assert protocol_param.coins_per_utxo_byte == params["minUtxoDepositCoefficient"]

        # The v7 reference-script fee and size limit reach pycardano as is.
        assert protocol_param.min_fee_reference_scripts == {
            "range": 25600,
            "base": 15.0,
            "multiplier": 1.2,
        }
        assert protocol_param.maximum_reference_scripts_size == {
            "bytes": params["maxReferenceScriptsSizePerTransaction"]["bytes"]
        }

    def test_governance_parameters(self, context, fake_ogmios, ogmios_protocol_parameters):
        fake_ogmios.results["queryLedgerState/protocolParameters"] = ogmios_protocol_parameters

        params = context._fetch_protocol_param()

        assert params.d_rep_deposit == 500000000
        assert params.d_rep_activity == 20
        assert params.gov_action_deposit == 100000000000
        assert params.gov_action_lifetime == 6
        assert params.committee_min_size == 7
        assert params.committee_max_term_length == 146
        assert params.dvt_motion_no_confidence == 0.67
        assert params.dvt_committee_normal == 0.67
        assert params.dvt_committee_no_confidence == 0.6
        assert params.dvt_update_to_constitution == 0.75
        assert params.dvt_hard_fork_initiation == 0.6
        assert params.dvt_p_p_network_group == 0.67
        assert params.dvt_p_p_economic_group == 0.67
        assert params.dvt_p_p_technical_group == 0.67
        assert params.dvt_p_p_gov_group == 0.75
        assert params.dvt_treasury_withdrawal == 0.67
        assert params.pvt_motion_no_confidence == 0.51
        assert params.pvt_pp_security_group == 0.51
        assert params.pool_target_num == 500
        assert params.pool_retire_max_epoch == 18

    def test_protocol_param_is_cached_until_the_tip_moves(self, context, fake_ogmios, ogmios_protocol_parameters):
        fake_ogmios.results["queryLedgerState/protocolParameters"] = ogmios_protocol_parameters
        fake_ogmios.results["queryNetwork/tip"] = TIP

        context.protocol_param
        # The first tip check moves the last known slot up from 0, so it refetches.
        context.protocol_param
        # The tip has not moved since, and within the refetch interval it is not
        # even checked.
        context.protocol_param
        context._last_chain_tip_fetch = 0
        context.protocol_param

        assert len(fake_ogmios.requests("queryLedgerState/protocolParameters")) == 2


class TestOgmiosGenesisParameters:
    def test_genesis_param(self, context, fake_ogmios, ogmios_genesis_shelley_config):
        fake_ogmios.results["queryNetwork/genesisConfiguration"] = ogmios_genesis_shelley_config

        genesis_param = context.genesis_param

        assert fake_ogmios.sent[0]["params"] == {"era": "shelley"}
        assert type(genesis_param) is PyCardanoGenesisParameters
        assert genesis_param == PyCardanoGenesisParameters(
            active_slots_coefficient=Fraction(1, 20),
            update_quorum=5,
            max_lovelace_supply=45000000000000000,
            network_magic=764824073,
            epoch_length=432000,
            system_start=int(datetime(2017, 9, 23, 21, 44, 51, tzinfo=UTC).timestamp()),
            slots_per_kes_period=129600,
            slot_length=1,
            max_kes_evolutions=62,
            security_param=2160,
        )
        # The chain tip is checked once per expected block interval.
        assert context._refetch_chain_tip_interval == 20

    def test_genesis_param_is_fetched_once(self, context, fake_ogmios, ogmios_genesis_shelley_config):
        fake_ogmios.results["queryNetwork/genesisConfiguration"] = ogmios_genesis_shelley_config

        context.genesis_param
        context.genesis_param

        assert len(fake_ogmios.sent) == 1


class TestOgmiosUtxos:
    def test_utxos(self, context, fake_ogmios, ogmios_utxos_response):
        fake_ogmios.results["queryLedgerState/utxo"] = ogmios_utxos_response["result"]
        fake_ogmios.results["queryNetwork/tip"] = TIP

        results = context.utxos(ADDRESS)

        assert fake_ogmios.requests("queryLedgerState/utxo")[0]["params"] == {"addresses": [ADDRESS]}
        assert results[0].input == TransactionInput.from_primitive([TX_ID, 1])
        assert results[0].output == TransactionOutput(address=Address.from_primitive(ADDRESS), amount=9858539)
        assert results[2].output.amount == Value(
            coin=7094260,
            multi_asset=MultiAsset.from_primitive(
                {
                    policy: assets
                    for policy, assets in ogmios_utxos_response["result"][2]["value"].items()
                    if policy != "ada"
                }
            ),
        )

    def test_utxos_are_cached_per_slot(self, context, fake_ogmios, ogmios_utxos_response):
        fake_ogmios.results["queryLedgerState/utxo"] = ogmios_utxos_response["result"]
        fake_ogmios.results["queryNetwork/tip"] = TIP

        context.utxos(ADDRESS)
        context.utxos(ADDRESS)

        assert len(fake_ogmios.requests("queryLedgerState/utxo")) == 1

    def test_utxo_by_tx_id(self, context, fake_ogmios):
        fake_ogmios.results["queryLedgerState/utxo"] = [utxo_item()]

        result = context.utxo_by_tx_id(TX_ID, 1)

        assert fake_ogmios.sent[0]["params"] == {"outputReferences": [{"transaction": {"id": TX_ID}, "index": 1}]}
        assert result.input == TransactionInput.from_primitive([TX_ID, 1])
        assert result.output.amount == 9858539

    def test_utxo_by_tx_id_missing(self, context, fake_ogmios):
        fake_ogmios.results["queryLedgerState/utxo"] = []
        assert context.utxo_by_tx_id(TX_ID, 9) is None

    def test_native_assets(self, context, fake_ogmios):
        fake_ogmios.results["queryLedgerState/utxo"] = [
            utxo_item(
                value={
                    "ada": {"lovelace": 2000000},
                    POLICY_ID: {"444f4c4c59": 87000, "": 1},
                }
            )
        ]

        utxo = context.utxo_by_tx_id(TX_ID, 1)

        assert utxo.output.amount == Value(
            2000000,
            MultiAsset.from_primitive({POLICY_ID: {"444f4c4c59": 87000, "": 1}}),
        )

    def test_datum_hash(self, context, fake_ogmios):
        fake_ogmios.results["queryLedgerState/utxo"] = [utxo_item(datumHash=DATUM_HASH)]

        output = context.utxo_by_tx_id(TX_ID, 1).output

        assert output.datum_hash == DatumHash(bytes.fromhex(DATUM_HASH))
        assert output.datum is None

    def test_inline_datum(self, context, fake_ogmios):
        fake_ogmios.results["queryLedgerState/utxo"] = [utxo_item(datum=INLINE_DATUM)]

        output = context.utxo_by_tx_id(TX_ID, 1).output

        assert output.datum == RawCBOR(bytes.fromhex(INLINE_DATUM))
        assert output.datum_hash is None

    @pytest.mark.parametrize(
        "language, script_type",
        [
            ("plutus:v1", PlutusV1Script),
            ("plutus:v2", PlutusV2Script),
            ("plutus:v3", PlutusV3Script),
        ],
    )
    def test_plutus_scripts(self, context, fake_ogmios, language, script_type):
        cbor = "4e4d01000033222220051200120011"
        fake_ogmios.results["queryLedgerState/utxo"] = [utxo_item(script={"language": language, "cbor": cbor})]

        script = context.utxo_by_tx_id(TX_ID, 1).output.script

        assert type(script) is script_type
        assert script == script_type(bytes.fromhex(cbor))

    def test_plutus_v4_is_rejected(self, context, fake_ogmios):
        fake_ogmios.results["queryLedgerState/utxo"] = [utxo_item(script={"language": "plutus:v4", "cbor": "4100"})]

        with pytest.raises(OgmiosError, match="plutus:v4"):
            context.utxo_by_tx_id(TX_ID, 1)

    def test_native_script(self, context, fake_ogmios):
        fake_ogmios.results["queryLedgerState/utxo"] = [
            utxo_item(
                script={
                    "language": "native",
                    "json": {
                        "clause": "all",
                        "from": [
                            {"clause": "signature", "from": KEY_HASH_A},
                            {
                                "clause": "any",
                                "from": [
                                    {"clause": "signature", "from": KEY_HASH_B},
                                    {"clause": "after", "slot": 42},
                                ],
                            },
                            {
                                "clause": "some",
                                "atLeast": 1,
                                "from": [
                                    {"clause": "signature", "from": KEY_HASH_A},
                                    {"clause": "before", "slot": 1000},
                                ],
                            },
                        ],
                    },
                }
            )
        ]

        script = context.utxo_by_tx_id(TX_ID, 1).output.script

        assert script == ScriptAll(
            [
                ScriptPubkey(VerificationKeyHash(bytes.fromhex(KEY_HASH_A))),
                ScriptAny(
                    [
                        ScriptPubkey(VerificationKeyHash(bytes.fromhex(KEY_HASH_B))),
                        InvalidBefore(42),
                    ]
                ),
                ScriptNofK(
                    1,
                    [
                        ScriptPubkey(VerificationKeyHash(bytes.fromhex(KEY_HASH_A))),
                        InvalidHereAfter(1000),
                    ],
                ),
            ]
        )

    def test_native_script_matches_its_on_chain_hash(self, context, fake_ogmios):
        """A 2-of-5 multisig reference script on preview (c06d3baa…#1)."""
        signers = [
            "b6c9e7360ffc7f9da79bccbdd0d030341c5e97021a20636684b113c9",
            "4e9ad0e3aa9e718136e44f0e66a00b7fd90b933705732eb4bbf572c4",
            "2ae10dbd88c3010cb03a33f271308e8f6cd686b7b1a9a6d4a8f1ad00",
            "806297b669a2c4316487fbbaf59719a062938d14a99c629a0a42c9e6",
            "7b6baf6dc907d9e43bf1892816d5d6315d5cfa6b510a9b64401ea726",
        ]
        fake_ogmios.results["queryLedgerState/utxo"] = [
            utxo_item(
                script={
                    "language": "native",
                    "json": {
                        "clause": "some",
                        "atLeast": 2,
                        "from": [{"clause": "signature", "from": signer} for signer in signers],
                    },
                }
            )
        ]

        script = context.utxo_by_tx_id(TX_ID, 1).output.script

        # The ledger's hash of the script, as Koios reports it.
        assert script.hash() == ScriptHash(bytes.fromhex("10b049f9fa44adf1670075d9e3e0297efed2a876c5660d39fed44c1f"))

    def test_native_script_guard_clause_is_rejected(self, context, fake_ogmios):
        fake_ogmios.results["queryLedgerState/utxo"] = [
            utxo_item(
                script={
                    "language": "native",
                    "json": {"clause": "guard", "from": KEY_HASH_A},
                }
            )
        ]

        with pytest.raises(OgmiosError, match="'guard'"):
            context.utxo_by_tx_id(TX_ID, 1)


class TestOgmiosTransactions:
    def test_submit_tx_cbor_returns_the_transaction_id(self, context, fake_ogmios):
        fake_ogmios.results["submitTransaction"] = {"transaction": {"id": TX_ID}}

        assert context.submit_tx_cbor(bytes.fromhex("84a0a0f5f6")) == TX_ID
        assert fake_ogmios.sent[0]["params"] == {"transaction": {"cbor": "84a0a0f5f6"}}

    def test_submit_tx_cbor_accepts_hex(self, context, fake_ogmios):
        fake_ogmios.results["submitTransaction"] = {"transaction": {"id": TX_ID}}

        assert context.submit_tx_cbor("84a0a0f5f6") == TX_ID

    def test_a_rejected_submission_raises_the_typed_error(self, context, fake_ogmios):
        fake_ogmios.errors["submitTransaction"] = {
            "code": 3101,
            "message": "Some signatures are missing.",
            "data": {"missingSignatures": [KEY_HASH_A]},
        }

        with pytest.raises(MissingSignatoriesError) as error:
            context.submit_tx_cbor("84a0a0f5f6")

        assert error.value.code == 3101

    def test_evaluate_tx_cbor_maps_purposes_to_redeemer_tags(self, context, fake_ogmios):
        purposes = ["spend", "mint", "publish", "withdraw", "vote", "propose"]
        fake_ogmios.results["evaluateTransaction"] = [
            {
                "validator": {"purpose": purpose, "index": index},
                "budget": {"memory": 1000 + index, "cpu": 2000 + index},
            }
            for index, purpose in enumerate(purposes)
        ]

        result = context.evaluate_tx_cbor("84a0a0f5f6")

        assert result == {
            "spend:0": ExecutionUnits(mem=1000, steps=2000),
            "mint:1": ExecutionUnits(mem=1001, steps=2001),
            "certificate:2": ExecutionUnits(mem=1002, steps=2002),
            "withdrawal:3": ExecutionUnits(mem=1003, steps=2003),
            "voting:4": ExecutionUnits(mem=1004, steps=2004),
            "proposing:5": ExecutionUnits(mem=1005, steps=2005),
        }

    def test_evaluate_guard_purpose_is_rejected(self, context, fake_ogmios):
        fake_ogmios.results["evaluateTransaction"] = [
            {
                "validator": {"purpose": "guard", "index": 0},
                "budget": {"memory": 1, "cpu": 1},
            }
        ]

        with pytest.raises(OgmiosError, match="'guard'"):
            context.evaluate_tx_cbor("84a0a0f5f6")

    def test_a_failed_evaluation_raises_the_typed_error(self, context, fake_ogmios):
        fake_ogmios.errors["evaluateTransaction"] = {
            "code": 3010,
            "message": "Some scripts of the transactions terminated with error(s).",
            "data": [],
        }

        with pytest.raises(EvaluateTransactionError):
            context.evaluate_tx_cbor("84a0a0f5f6")


COMMITTEE_COLD_KEY_HASH = "cc30497f4ff962f4c1dca54cceefe39f86f1d7179668009f8eb71e59"
COMMITTEE_HOT_SCRIPT_HASH = "1ba48f0e0a1e0a1b6b2e4a0f5c9d3e2f1a0b9c8d7e6f5a4b3c2d1e0f"
COMMITTEE_RESIGNED_HASH = "3fb0f2a4d1c8e7b6a59483726150fedcba9876543210abcdef012345"

POOL_ID = "pool1escyjl60l930fswu54xvamlrn7r0r4chje5qp8uwku09j7x68x6"
POOL_KEY_HASH = "cc30497f4ff962f4c1dca54cceefe39f86f1d7179668009f8eb71e59"
OTHER_POOL_ID = "pool1pu5jlj4q9w9jlxeu370a3c9myx47md5j5m2str0naunn2q3lkdy"
REWARD_ACCOUNT = "stake_test1urxrqjtlfluk9axpmjj5enh0uw0cduwhz7txsqyl36m3ukgmd6hlp"

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
def ogmios_stake_pools_performances():
    """A ``queryLedgerState/stakePoolsPerformances`` result."""
    return {
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
                "parameters": {
                    "cost": {"ada": {"lovelace": 170000000}},
                    "margin": "3/100",
                    "pledge": {"ada": {"lovelace": 100000000000}},
                },
            },
            OTHER_POOL_ID: {
                "id": OTHER_POOL_ID,
                "stake": {"ada": {"lovelace": 600000000000}},
                "ownerStake": {"ada": {"lovelace": 5000000000}},
                "approximatePerformance": 0.98,
                "parameters": {
                    "cost": {"ada": {"lovelace": 340000000}},
                    "margin": "1/100",
                    "pledge": {"ada": {"lovelace": 5000000000}},
                },
            },
        },
    }


@pytest.fixture
def ogmios_constitutional_committee():
    return {
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
    }


@pytest.fixture
def ogmios_operational_certificates():
    """A real ``queryLedgerState/operationalCertificates`` result."""
    return {
        "pool1ssvpmsymcz8nd6tu3wgdhy93ajw0yrdauh9gp3djxvda5g6nqma": 0,
        "pool14cwzrv0mtr68kp44t9fn5wplk9ku20g6rv98sxggd3azg60qukm": 6,
        "pool18ut2jlv66s0dh70pp4za2pu42dg57jynflkj9fexamcfqcsmc5q": 0,
        "pool1d4nsv4wa0h3cvdkzuj7trx9d3gz93cj4hkslhekhq0wmcdpwmps": 10,
        "pool1sqva3m6zhvwf9kmuek7gsayxyknzv68ltgqqpeptmdgrqp2lmkf": 4,
        OPCERT_POOL_ID: 12,
    }


@pytest.fixture
def ogmios_delegate_representatives():
    """A real ``queryLedgerState/delegateRepresentatives`` result.

    Extended with one script-credential DRep, so the script branch of the
    credential filter is covered by the same shape the ledger returns.
    """
    return [
        {
            "from": "verificationKey",
            "id": DREP_KEY_HASH,
            "deposit": {"ada": {"lovelace": 500000000}},
            "type": "registered",
            "stake": {"ada": {"lovelace": 0}},
            "mandate": {"epoch": 1068},
            "metadata": {"hash": DREP_METADATA_HASH, "url": DREP_METADATA_URL},
            "delegators": [],
        },
        {
            "from": "script",
            "id": DREP_SCRIPT_HASH,
            "deposit": {"ada": {"lovelace": 500000000}},
            "type": "registered",
            "stake": {"ada": {"lovelace": 123456789}},
            "mandate": {"epoch": 1100},
            "delegators": [],
        },
        {
            "stake": {"ada": {"lovelace": 46115228289209}},
            "type": "abstain",
            "delegators": [],
        },
        {
            "stake": {"ada": {"lovelace": 15049380877790}},
            "type": "noConfidence",
            "delegators": [],
        },
    ]


@pytest.fixture
def ogmios_governance_proposals():
    """A real ``queryLedgerState/governanceProposals`` result.

    Extended with a constitutional committee vote, a stake pool vote and a
    genesis delegate vote, so every voter class is exercised; the two DRep
    votes are as returned.
    """
    return [
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
                    "issuer": {"role": "stakePoolOperator", "id": POOL_ID},
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
                "withdrawals": {GOV_RETURN_ACCOUNT: {"ada": {"lovelace": 889000000}}},
                "guardrails": {"hash": "fa24fb305126805cf2164c161d852a0e7330cf988f1fe558cf7d4a64"},
            },
            "deposit": {"ada": {"lovelace": 100000000000}},
            "returnAccount": GOV_RETURN_ACCOUNT,
            "proposal": {"index": 0, "transaction": {"id": GOV_ACTION_TX_ID}},
            "metadata": {"url": GOV_METADATA_URL, "hash": GOV_METADATA_HASH},
            "since": {"epoch": 1021},
            "until": {"epoch": 1051},
        }
    ]


class TestOgmiosChainStateQueries:
    @pytest.mark.parametrize("count, era", [(7, Era.CONWAY), (6, Era.BABBAGE), (2, Era.SHELLEY)])
    def test_era(self, context, fake_ogmios, count, era):
        fake_ogmios.results["queryLedgerState/eraSummaries"] = era_summaries(count)
        assert context.era == era

    def test_an_era_this_library_does_not_know(self, context, fake_ogmios):
        # Dijkstra is known to Ogmios but not (yet) to pccontext's Era enum.
        fake_ogmios.results["queryLedgerState/eraSummaries"] = era_summaries(8)
        assert context.era is None

    def test_chain_tip(self, context, fake_ogmios):
        fake_ogmios.results["queryNetwork/tip"] = TIP
        fake_ogmios.results["queryNetwork/blockHeight"] = 11223344
        fake_ogmios.results["queryLedgerState/epoch"] = 507
        fake_ogmios.results["queryLedgerState/eraSummaries"] = era_summaries(7)

        chain_tip = context.chain_tip

        assert chain_tip.slot == TIP["slot"]
        assert chain_tip.hash == TIP["id"]
        assert chain_tip.block == 11223344
        assert chain_tip.epoch == 507
        assert chain_tip.era == Era.CONWAY
        # Ogmios reports sync progress on its HTTP health endpoint, not over
        # JSON-RPC, so the backend leaves it unset rather than guessing.
        assert chain_tip.sync_progress is None

    def test_chain_tip_at_origin(self, context, fake_ogmios):
        fake_ogmios.results["queryNetwork/tip"] = "origin"
        fake_ogmios.results["queryNetwork/blockHeight"] = "origin"
        fake_ogmios.results["queryLedgerState/epoch"] = 0
        fake_ogmios.results["queryLedgerState/eraSummaries"] = era_summaries(1)

        chain_tip = context.chain_tip

        assert chain_tip.slot == 0
        assert chain_tip.hash is None
        assert chain_tip.block == 0
        assert chain_tip.era == Era.BYRON

    def test_utxo(self, context, fake_ogmios):
        fake_ogmios.results["queryLedgerState/utxo"] = [utxo_item()]

        result = context.utxo(TransactionInput.from_primitive([TX_ID, 1]))

        assert result is not None
        utxo, is_spent = result
        assert utxo.input == TransactionInput.from_primitive([TX_ID, 1])
        # The live UTxO set only holds unspent outputs.
        assert is_spent is False

    def test_utxo_missing_returns_none(self, context, fake_ogmios):
        fake_ogmios.results["queryLedgerState/utxo"] = []
        assert context.utxo(TransactionInput.from_primitive([TX_ID, 9])) is None


class TestOgmiosStakeAddressInfo:
    def test_stake_address_info(self, context, fake_ogmios):
        credential = Address.from_primitive(REWARD_ACCOUNT).staking_part.payload.hex()
        fake_ogmios.results["queryLedgerState/rewardAccountSummaries"] = [
            {
                "from": "verificationKey",
                "credential": credential,
                "stakePool": {"id": POOL_ID},
                "delegateRepresentative": {
                    "type": "registered",
                    "from": "verificationKey",
                    "id": DREP_KEY_HASH,
                },
                "rewards": {"ada": {"lovelace": 8866777660814}},
                "deposit": {"ada": {"lovelace": 2000000}},
            }
        ]

        [info] = context.stake_address_info(REWARD_ACCOUNT)

        assert fake_ogmios.sent[0]["params"] == {"keys": [REWARD_ACCOUNT]}
        assert info.address == REWARD_ACCOUNT
        assert info.delegation_deposit == 2000000
        assert info.reward_account_balance == 8866777660814
        assert info.stake_delegation == POOL_ID
        assert (
            info.delegate_representative
            == DRep(
                DRepKind.VERIFICATION_KEY_HASH,
                VerificationKeyHash(bytes.fromhex(DREP_KEY_HASH)),
            ).encode()
        )

    def test_a_script_stake_address(self, context, fake_ogmios):
        script_address = str(
            Address(
                staking_part=ScriptHash(bytes.fromhex(DREP_SCRIPT_HASH)),
                network=Network.TESTNET,
            )
        )
        fake_ogmios.results["queryLedgerState/rewardAccountSummaries"] = [
            {
                "from": "script",
                "credential": DREP_SCRIPT_HASH,
                "delegateRepresentative": {"type": "abstain"},
                "rewards": {"ada": {"lovelace": 0}},
                "deposit": {"ada": {"lovelace": 2000000}},
            }
        ]

        [info] = context.stake_address_info(script_address)

        assert fake_ogmios.sent[0]["params"] == {"scripts": [script_address]}
        assert info.stake_delegation is None
        assert info.delegate_representative == "drep_always_abstain"

    def test_an_unregistered_stake_address(self, context, fake_ogmios):
        fake_ogmios.results["queryLedgerState/rewardAccountSummaries"] = []
        assert context.stake_address_info(REWARD_ACCOUNT) == []


class TestOgmiosStakePoolQueries:
    def test_stake_pools(self, context, fake_ogmios, ogmios_stake_pool):
        fake_ogmios.results["queryLedgerState/stakePools"] = {POOL_ID: ogmios_stake_pool}

        pools = context.stake_pools()

        # Every pool: the filter is left out, since an empty one selects none.
        assert "params" not in fake_ogmios.sent[0]
        assert pools == [PoolOperator.from_primitive(POOL_ID)]

    def test_stake_pool_info(
        self,
        context,
        fake_ogmios,
        ogmios_stake_pool,
        ogmios_stake_pools_performances,
    ):
        fake_ogmios.results["queryLedgerState/stakePools"] = {POOL_ID: ogmios_stake_pool}
        fake_ogmios.results["queryLedgerState/stakePoolsPerformances"] = ogmios_stake_pools_performances

        info = context.stake_pool_info(POOL_ID)

        assert fake_ogmios.sent[0]["params"] == {"stakePools": [{"id": POOL_ID}]}
        params = info.pool_params
        assert params is not None
        assert params.operator == PoolOperator.from_primitive(POOL_ID).pool_key_hash
        assert params.pledge == 100000000000
        assert params.cost == 170000000
        assert params.margin == Fraction(3, 100)
        assert params.reward_account == RewardAccountHash(bytes(Address.from_primitive(REWARD_ACCOUNT).to_primitive()))
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

    def test_stake_pool_info_without_performances(self, context, fake_ogmios, ogmios_stake_pool):
        fake_ogmios.results["queryLedgerState/stakePools"] = {POOL_ID: ogmios_stake_pool}
        fake_ogmios.errors["queryLedgerState/stakePoolsPerformances"] = {
            "code": 2002,
            "message": "unavailable in current era",
        }

        info = context.stake_pool_info(POOL_ID)

        assert info.pool_params is not None
        assert info.active_stake is None
        assert info.active_size is None
        assert info.live_pledge is None

    def test_stake_pool_info_not_found(self, context, fake_ogmios):
        fake_ogmios.results["queryLedgerState/stakePools"] = {}

        with pytest.raises(OgmiosError, match="Stake pool not found"):
            context.stake_pool_info(POOL_ID)

    def test_spo_stake_distribution(self, context, fake_ogmios, ogmios_stake_pools_performances):
        fake_ogmios.results["queryLedgerState/stakePoolsPerformances"] = ogmios_stake_pools_performances

        assert context.spo_stake_distribution() == [
            SPOStakeEntry(pool_id=POOL_ID, stake=200000000000),
            SPOStakeEntry(pool_id=OTHER_POOL_ID, stake=600000000000),
        ]


class TestOgmiosKesPeriodInfo:
    def test_kes_period_info(self, context, fake_ogmios, ogmios_operational_certificates):
        fake_ogmios.results["queryLedgerState/operationalCertificates"] = ogmios_operational_certificates

        info = context.kes_period_info(pool=PoolOperator.from_primitive(OPCERT_POOL_ID))

        # The query takes no parameters, so none are sent.
        assert "params" not in fake_ogmios.sent[0]
        assert info.on_chain_op_cert_count == 12
        assert info.next_chain_op_cert_count == 13
        # Ogmios sees no local certificate file.
        assert info.on_disk_op_cert_count is None
        assert info.on_disk_kes_start is None

    def test_kes_period_info_ignores_the_operational_certificate(
        self, context, fake_ogmios, ogmios_operational_certificates
    ):
        fake_ogmios.results["queryLedgerState/operationalCertificates"] = ogmios_operational_certificates

        info = context.kes_period_info(
            pool=PoolOperator.from_primitive(OPCERT_POOL_ID),
            op_cert=b"\xde\xad\xbe\xef",
        )

        assert info.on_disk_op_cert_count is None

    def test_kes_period_info_requires_a_pool(self, context):
        with pytest.raises(OgmiosError, match="pool operator must be provided"):
            context.kes_period_info()

    def test_kes_period_info_for_a_pool_without_a_counter(self, context, fake_ogmios, ogmios_operational_certificates):
        fake_ogmios.results["queryLedgerState/operationalCertificates"] = ogmios_operational_certificates

        with pytest.raises(OgmiosError, match="No operational certificate counter"):
            context.kes_period_info(pool=PoolOperator.from_primitive(POOL_ID))


class TestOgmiosTreasuryAndCommitteeQueries:
    def test_treasury(self, context, fake_ogmios):
        fake_ogmios.results["queryLedgerState/treasuryAndReserves"] = {
            "treasury": {"ada": {"lovelace": 1234567890}},
            "reserves": {"ada": {"lovelace": 9876543210}},
        }

        assert context.treasury() == 1234567890

    def test_committee_state(self, context, fake_ogmios, ogmios_constitutional_committee):
        fake_ogmios.results["queryLedgerState/constitutionalCommittee"] = ogmios_constitutional_committee

        state = context.committee_state()

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

    def test_committee_state_without_quorum(self, context, fake_ogmios, ogmios_constitutional_committee):
        ogmios_constitutional_committee["quorum"] = None
        fake_ogmios.results["queryLedgerState/constitutionalCommittee"] = ogmios_constitutional_committee

        assert context.committee_state().threshold is None

    def test_committee_state_without_a_committee(self, context, fake_ogmios):
        fake_ogmios.results["queryLedgerState/constitutionalCommittee"] = None

        state = context.committee_state()

        assert state.members == []
        assert state.threshold is None

    def test_committee_member_info_by_cold_credential(self, context, fake_ogmios, ogmios_constitutional_committee):
        fake_ogmios.results["queryLedgerState/constitutionalCommittee"] = ogmios_constitutional_committee
        cold = CommitteeColdCredential(credential=VerificationKeyHash(bytes.fromhex(COMMITTEE_COLD_KEY_HASH)))

        member = context.committee_member_info(cold=cold)

        assert member.cold_credential == cold
        assert member.expiration == 580

    def test_committee_member_info_by_hot_credential(self, context, fake_ogmios, ogmios_constitutional_committee):
        fake_ogmios.results["queryLedgerState/constitutionalCommittee"] = ogmios_constitutional_committee
        hot = CommitteeHotCredential(credential=ScriptHash(bytes.fromhex(COMMITTEE_HOT_SCRIPT_HASH)))

        member = context.committee_member_info(hot=hot)

        assert member.hot_credential == hot
        assert member.cold_credential == CommitteeColdCredential(
            credential=VerificationKeyHash(bytes.fromhex(COMMITTEE_COLD_KEY_HASH))
        )

    def test_committee_member_info_requires_a_credential(self, context):
        with pytest.raises(OgmiosError, match="cold or a hot committee credential"):
            context.committee_member_info()

    def test_committee_member_info_not_found(self, context, fake_ogmios, ogmios_constitutional_committee):
        fake_ogmios.results["queryLedgerState/constitutionalCommittee"] = ogmios_constitutional_committee

        with pytest.raises(OgmiosError, match="Committee member not found"):
            context.committee_member_info(
                cold=CommitteeColdCredential(credential=VerificationKeyHash(bytes.fromhex("11" * 28)))
            )


class TestOgmiosErrors:
    def test_ogmios_errors_are_raised_as_typed_exceptions(self, context, fake_ogmios):
        fake_ogmios.errors["queryLedgerState/operationalCertificates"] = {
            "code": 2002,
            "message": "unavailable in current era",
        }

        with pytest.raises(UnavailableInCurrentEraError):
            context.kes_period_info(pool=PoolOperator.from_primitive(POOL_ID))

    def test_a_malformed_result_is_rejected(self, context, fake_ogmios):
        fake_ogmios.results["queryLedgerState/governanceProposals"] = [{"votes": [], "action": {"type": "information"}}]

        with pytest.raises(pydantic.ValidationError):
            context.gov_actions_all()


class TestOgmiosDRepQueries:
    def test_drep_info_for_a_registered_key_hash_drep(self, context, fake_ogmios, ogmios_delegate_representatives):
        fake_ogmios.results["queryLedgerState/delegateRepresentatives"] = ogmios_delegate_representatives
        fake_ogmios.results["queryLedgerState/epoch"] = 1000
        drep = DRep(
            DRepKind.VERIFICATION_KEY_HASH,
            VerificationKeyHash(bytes.fromhex(DREP_KEY_HASH)),
        )

        info = context.drep_info(drep)

        assert fake_ogmios.requests("queryLedgerState/delegateRepresentatives")[0]["params"] == {
            "keys": [DREP_KEY_HASH]
        }
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

    def test_drep_info_after_the_mandate_lapses(self, context, fake_ogmios, ogmios_delegate_representatives):
        fake_ogmios.results["queryLedgerState/delegateRepresentatives"] = ogmios_delegate_representatives
        fake_ogmios.results["queryLedgerState/epoch"] = 1069
        drep = DRep(
            DRepKind.VERIFICATION_KEY_HASH,
            VerificationKeyHash(bytes.fromhex(DREP_KEY_HASH)),
        )

        info = context.drep_info(drep)

        assert info.active is False
        # A lapsed registration is still a registration.
        assert info.status == DRepStatus.REGISTERED

    def test_drep_info_for_a_script_hash_drep(self, context, fake_ogmios, ogmios_delegate_representatives):
        fake_ogmios.results["queryLedgerState/delegateRepresentatives"] = ogmios_delegate_representatives
        fake_ogmios.results["queryLedgerState/epoch"] = 1000
        drep = DRep(DRepKind.SCRIPT_HASH, ScriptHash(bytes.fromhex(DREP_SCRIPT_HASH)))

        info = context.drep_info(drep)

        assert fake_ogmios.requests("queryLedgerState/delegateRepresentatives")[0]["params"] == {
            "scripts": [DREP_SCRIPT_HASH]
        }
        assert info.stake == 123456789
        assert info.expiry == 1100
        assert info.active is True
        assert info.anchor is None

    def test_drep_info_for_an_unknown_drep(self, context, fake_ogmios):
        # A filtered query still returns the two predefined options, and never
        # a registered entry for a DRep the ledger does not know.
        fake_ogmios.results["queryLedgerState/delegateRepresentatives"] = [
            {"type": "abstain", "stake": {"ada": {"lovelace": 1}}, "delegators": []},
            {
                "type": "noConfidence",
                "stake": {"ada": {"lovelace": 2}},
                "delegators": [],
            },
        ]
        drep = DRep(
            DRepKind.VERIFICATION_KEY_HASH,
            VerificationKeyHash(bytes.fromhex("11" * 28)),
        )

        info = context.drep_info(drep)

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
        self, context, fake_ogmios, ogmios_delegate_representatives, kind, stake
    ):
        fake_ogmios.results["queryLedgerState/delegateRepresentatives"] = ogmios_delegate_representatives

        info = context.drep_info(DRep(kind))

        # The predefined options are always returned, so no filter is sent.
        assert "params" not in fake_ogmios.sent[0]
        assert info.stake == stake
        assert info.status == DRepStatus.REGISTERED
        assert info.deposit is None

    def test_drep_info_when_a_predefined_option_is_missing(self, context, fake_ogmios):
        fake_ogmios.results["queryLedgerState/delegateRepresentatives"] = []

        with pytest.raises(OgmiosError, match="did not report the abstain"):
            context.drep_info(DRep(DRepKind.ALWAYS_ABSTAIN))

    def test_drep_stake_distribution(self, context, fake_ogmios, ogmios_delegate_representatives):
        fake_ogmios.results["queryLedgerState/delegateRepresentatives"] = ogmios_delegate_representatives

        distribution = context.drep_stake_distribution()

        assert "params" not in fake_ogmios.sent[0]
        assert distribution == [
            DRepStakeEntry(
                drep=DRep(
                    DRepKind.VERIFICATION_KEY_HASH,
                    VerificationKeyHash(bytes.fromhex(DREP_KEY_HASH)),
                ),
                stake=0,
            ),
            DRepStakeEntry(
                drep=DRep(DRepKind.SCRIPT_HASH, ScriptHash(bytes.fromhex(DREP_SCRIPT_HASH))),
                stake=123456789,
            ),
            DRepStakeEntry(drep=DRep(DRepKind.ALWAYS_ABSTAIN), stake=46115228289209),
            DRepStakeEntry(drep=DRep(DRepKind.ALWAYS_NO_CONFIDENCE), stake=15049380877790),
        ]


class TestOgmiosGovernanceProposalQueries:
    @property
    def gov_action_id(self) -> GovActionId:
        return GovActionId(
            transaction_id=TransactionId(bytes.fromhex(GOV_ACTION_TX_ID)),
            gov_action_index=0,
        )

    def test_gov_action_info(self, context, fake_ogmios, ogmios_governance_proposals):
        fake_ogmios.results["queryLedgerState/governanceProposals"] = ogmios_governance_proposals

        info = context.gov_action_info(self.gov_action_id)

        # The query is filtered on the action's reference.
        assert fake_ogmios.sent[0]["params"] == {"proposals": [{"transaction": {"id": GOV_ACTION_TX_ID}, "index": 0}]}
        assert info.gov_action_id == self.gov_action_id
        assert info.proposed_in == 1021
        assert info.expires_after == 1051
        # Ogmios describes the action as JSON, which is passed through as sent.
        assert info.gov_action == ogmios_governance_proposals[0]["action"]
        # Only live proposals are returned, so nothing has resolved.
        assert info.ratified_epoch is None
        assert info.enacted_epoch is None
        assert info.dropped_epoch is None
        assert info.expired_epoch is None
        assert info.status is None

    def test_gov_action_votes(self, context, fake_ogmios, ogmios_governance_proposals):
        fake_ogmios.results["queryLedgerState/governanceProposals"] = ogmios_governance_proposals

        votes = context.gov_action_votes(self.gov_action_id)

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
                voter=CommitteeHotCredential(ScriptHash(bytes.fromhex(COMMITTEE_HOT_SCRIPT_HASH))),
                vote=Vote.YES,
            )
        ]
        # The genesis delegate vote has no voter class here and is dropped.
        assert votes.stake_pool_votes == [StakePoolVote(voter=POOL_ID, vote=Vote.ABSTAIN)]

    def test_gov_actions_all(self, context, fake_ogmios, ogmios_governance_proposals):
        fake_ogmios.results["queryLedgerState/governanceProposals"] = ogmios_governance_proposals

        actions = context.gov_actions_all()

        # The proposal list already carries the votes: one request, no filter.
        assert len(fake_ogmios.sent) == 1
        assert "params" not in fake_ogmios.sent[0]
        assert len(actions) == 1
        assert actions[0].gov_action_id == self.gov_action_id
        assert len(actions[0].drep_votes) == 2

    def test_gov_action_not_found(self, context, fake_ogmios):
        fake_ogmios.results["queryLedgerState/governanceProposals"] = []
        missing = GovActionId(transaction_id=TransactionId(bytes.fromhex("aa" * 32)), gov_action_index=0)

        with pytest.raises(OgmiosError, match="Governance action not found"):
            context.gov_action_info(missing)
