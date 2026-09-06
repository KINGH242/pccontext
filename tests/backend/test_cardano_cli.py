import copy
import hashlib
import json
from decimal import Decimal
from fractions import Fraction

import pytest
from pycardano import (
    Address,
    CommitteeColdCredential,
    CommitteeHotCredential,
    DatumHash,
    DRep,
    DRepKind,
    ExecutionUnits,
    GovActionId,
    HardForkInitiationAction,
    InfoAction,
    MultiAsset,
    NewConstitution,
    NoConfidence,
    ParameterChangeAction,
    PlutusData,
    PlutusV2Script,
    RawPlutusData,
    Redeemer,
    RedeemerTag,
    ScriptHash,
    Transaction,
    TransactionBody,
    TransactionId,
    TransactionInput,
    TransactionWitnessSet,
    TreasuryWithdrawalsAction,
    VerificationKeyHash,
    Vote,
)
from pycardano.exception import CardanoCliError, TransactionFailedException
from requests import RequestException

from pccontext import CardanoCliChainContext
from pccontext.backend import cardano_cli
from pccontext.enums import (
    CommitteeMemberStatus,
    DRepStatus,
    Era,
    GovActionStatus,
    PoolStatus,
)
from pccontext.exceptions import CardanoCLIError
from pccontext.models import GenesisParameters, ProtocolParameters


class _Action(PlutusData):
    """A minimal redeemer payload; the contents never matter to the cost parser."""

    CONSTR_ID = 0


def _tx_with_redeemers(*specs) -> str:
    """Build a transaction carrying `(tag, index)` redeemers and return its cbor hex."""
    redeemers = []
    for tag, index in specs:
        redeemer = Redeemer(_Action())
        redeemer.tag = tag
        redeemer.index = index
        redeemer.ex_units = ExecutionUnits(0, 0)
        redeemers.append(redeemer)
    witness_set = TransactionWitnessSet(redeemer=redeemers or None)
    body = TransactionBody(inputs=[], outputs=[], fee=0)
    return Transaction(body, witness_set).to_cbor_hex()


def _stub_costs(chain_context, payload):
    """Point the context's cli at `payload`, and record the commands it runs."""
    commands = []
    original = chain_context._run_command

    def run(cmd):
        commands.append(cmd)
        if "calculate-plutus-script-cost" in cmd:
            if isinstance(payload, Exception):
                raise payload
            return json.dumps(payload)
        return original(cmd)

    chain_context._run_command = run
    return commands


class TestCardanoCliChainContext:
    def test_protocol_param(self, chain_context, query_protocol_parameters_result):
        expected_protocol_params = ProtocolParameters.from_json(
            query_protocol_parameters_result
        ).to_pycardano()
        assert chain_context.protocol_param == expected_protocol_params

    def test_genesis(self, chain_context, config_file):
        expected_genesis = GenesisParameters.from_config_file(config_file)
        assert chain_context.genesis_param == expected_genesis
        assert chain_context.genesis_param.alonzo_genesis is not None
        assert chain_context.genesis_param.byron_genesis is not None
        assert chain_context.genesis_param.conway_genesis is not None
        assert chain_context.genesis_param.shelley_genesis is not None

    def test_version(self, chain_context):
        assert (
            chain_context.version()
            == "cardano-cli 8.1.2 - linux-x86_64 - ghc-8.10\ngit rev d2d90b48c5577b4412d5c9c9968b55f8ab4b9767"
        )

    def test_utxo(self, chain_context):
        results = chain_context.utxos(
            "addr_test1qqmnh90jyfaajul4h2mawrxz4rfx04hpaadstm6y8wr90kyhf4dqfm247jlvna83g5wx9veaymzl6g9t833grknh3yhqxhzh4n"
        )

        assert results[0].input == TransactionInput.from_primitive(
            ["fbaa018740241abb935240051134914389c3f94647d8bd6c30cb32d3fdb799bf", 0]
        )
        assert results[0].output.amount.coin == 708864940

        assert (
            str(results[0].output.address)
            == "addr1x8nz307k3sr60gu0e47cmajssy4fmld7u493a4xztjrll0aj764lvrxdayh2ux30fl0ktuh27csgmpevdu89jlxppvrswgxsta"
        )

        assert results[0].output.datum == RawPlutusData.from_dict(
            {
                "constructor": 0,
                "fields": [
                    {
                        "constructor": 0,
                        "fields": [
                            {
                                "bytes": "2e11e7313e00ccd086cfc4f1c3ebed4962d31b481b6a153c23601c0f"
                            },
                            {"bytes": "636861726c69335f6164615f6e6674"},
                        ],
                    },
                    {"constructor": 0, "fields": [{"bytes": ""}, {"bytes": ""}]},
                    {
                        "constructor": 0,
                        "fields": [
                            {
                                "bytes": "8e51398904a5d3fc129fbf4f1589701de23c7824d5c90fdb9490e15a"
                            },
                            {"bytes": "434841524c4933"},
                        ],
                    },
                    {
                        "constructor": 0,
                        "fields": [
                            {
                                "bytes": "d8d46a3e430fab5dc8c5a0a7fc82abbf4339a89034a8c804bb7e6012"
                            },
                            {"bytes": "636861726c69335f6164615f6c71"},
                        ],
                    },
                    {"int": 997},
                    {
                        "list": [
                            {
                                "bytes": "4dd98a2ef34bc7ac3858bbcfdf94aaa116bb28ca7e01756140ba4d19"
                            }
                        ]
                    },
                    {"int": 10000000000},
                ],
            }
        )

        assert results[0].output.amount.multi_asset == MultiAsset.from_primitive(
            {
                "2e11e7313e00ccd086cfc4f1c3ebed4962d31b481b6a153c23601c0f": {
                    "636861726c69335f6164615f6e6674": 1
                },
                "8e51398904a5d3fc129fbf4f1589701de23c7824d5c90fdb9490e15a": {
                    "434841524c4933": 1367726755
                },
                "d8d46a3e430fab5dc8c5a0a7fc82abbf4339a89034a8c804bb7e6012": {
                    "636861726c69335f6164615f6c71": 9223372035870126880
                },
            }
        )

        assert results[1].output.script == PlutusV2Script(
            bytes.fromhex(
                "5915f7010000323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232223232323232323232323232323232323232323232323232323232533533355333573460ee0082646464646424446666600201000e00c00a0086eb4d5d09aba25005375a6ae854010dd69aba15004375a6ae854010dd69aba1307d00515333573460ec008264646464646464244466666600401401201000e00a0086eb4d5d09aba2002375a6ae84004d5d128029bad35742a0086eb4d5d0a8021bad35742a0086eb4d5d0983e8028a999ab9a307500413212223003004375a6ae84c1f40141b08c8c8cc0d0ccc0d409803c040cc0d0cc0f0cc128068028cdc0806241a01e66068660786a02a0e4018660686607e01c90001981a1981f806a400066068666606c01e02001402e66068660786609403402c90011981a1981e1982500d004a400466068660786609402e01290011981a1a9a80d911103a911a80091912999aa999a80310a999a80210a999a804109802815098020148a999a802909802815098020148328338a999a803909802014898018140a999a802109802014898018140320a999a80190328318320a999a80190a999a803909802014898018140a999a802109802014898018140320330a999a803109801814098010138a999a801909801814098010138318a99a80083403503503412999a80110a999a80310a999a8021099981d0160010008b0b0b0330a999a80290a999a8019099981c8158010008b0b0b0328319981a1981f2805a40046606866080a0160fe66068607a02666068607a028607a02260d866610202444a666ae68cdc38011b8d004100113300333700004900119b803370400290400219b8e00400248001200033080012253350011622135002225333573466e3c00922011c91835de0e7ae8228a3e79823e8e066897f9c40e1b85c7a88c173a3e9001533500116221350022253350031002221613006003353353308001221225333573466e200052000130434910350543600153350021304349103505437002215333573460f80062004266a600c0d800266e0400d20020663501922222222222200c0012235001206a222223232322323303b33303c02d0160173303b3304333051021011337020269068079981d99823003a4000660766608c00c90001981d999981e80b00b80880f1981d998219982881080ea40046607666086660a204202090011981d998219982880f00824004660766608aa02490011981d99823a809043009981d982200d1981d982200d9981d982200c1981d998231aa80083824000660766608c6aa0020d29000198231aa800833a4000264a66aa66a66082002050264a66a66084002052260e4666080605000460500026aa008444a66a6608a002058266e0ccdc119b820063500107235500806f337046a0020de6aa0100e42c0d66aa0060d20d4420022c6aa0040de2646464a66a6a002446a00844666609a008006004002266607e660e401290011a800911a9982100280e111983b19b82004002337040060020022a66a6a002446a00844666605c008006004002266607e6a004446a6608460a400a60a403a44660ec66e08010008cdc10018009983900424004004266607e660e4012900119839004240040026a004446a038446a60a66608603c00c44660ee66e08cdc119b8200e0060040023370466e08c20c0401400c004d4c138cc0f800406088cc1c8cdc1004001183f00099981f801280080b899999982499837001a400400202c02e02802a660da00290011111911191981c19981c81500980a1981c1982180324000660706608600a90001981c199981d00980a00700d9981c198201982700f00d2400466070660806609c03c01a90011981c198201982700d806a40046607066084a01e90011981c198222807841809981c182080b9981c182080c1981c182080a9981c198219aa800835a4000660866aa0020d0900009919191919299aa99a99821000816099299a99821800816898399983a1a8010261a8008260361a801911a99821a80200e911983b99b82004002337040060020d6420022c6a004446a6608460a4a00660a403a44660ec66e08010008cdc1001800899982080300180ca999ab9a307d00116133070337046a0040d800800266e08008d40041a0cccccc124cc1b801520020030160170140153306b001480084480044c0f92410350543500135744a00226ae8940044d5d1183d001183d0009baa0173306235013223333500106920010690694890e4d7565736c69537761705f634c5000330614891c6e3af9667763e915c9b3a901d3092625d515c2ad6d575eac92582aa8003500c05a13500a06635007223500a2235009225333573460e40082c264a666ae68cdc399b8200330720013370466e04c1c8004cdc119b820070044800800854cd4cccc0f520004800801c01854cd4cccc0f401c0180140104d4cccccc104cc19802520023306600848008cc19801c018cc198014010cc19800c0080340f8585858cdc10028021981e8050019981e0048009a8030329a8028319a8021111102b1a801911110299a80110319a8009111102d1a80191112999a8010b10981d80090a99a9a8059111111111111983f11299a8008309109a801112999ab9a3371e004026260d80022600c0060044260780022c660d844a66a0022c4426a00444a666ae68cdc780101e8a99a981f091199820911a801112999ab9a306f0011330060040031003001003162213500222533500313305f0410022216130060030013500120535335303612233303922533535002222253335002053205620561330040020011001001003162215335001100222163500222222222222200a35001222205e3500104c5333573460b860ca00226464642466002006004607c6ae84d5d11833001a999ab9a305d3066001132323232323232323232323232323232323232323232321233333333333300101801601401201000e00c0090070050030023058357426ae88008ccc141d710009aba10013574400466609c0a040026ae84004d5d100119826bae357420026ae8800d4ccd5cd1836183a80089919191909198008020012999ab9a306f30780011330623304875a6ae84c1dc004c11cd5d09aba2307700106637546ae84d5d1183b001a999ab9a306d30760011323212330010030023046357426ae88c1d8008cc119d69aba1307500106437546ae84c1d000418cdd51aba10013574400466608e096eb4d5d08009aba200233046048357420026ae88008ccc10dd70211aba100135744004666082eb8100d5d08009aba20023304003c357420026ae88008cc0f80e4d5d08009aba230660023303c0373574260ca0020a86ea8d5d098320008299baa00123500122533533330270020014800120021533533330063370a004002002900024004266e00cdc2001000a4004266e1000800458cc129200048009262222333573466e24cdc100200099b82002003026047330474800120023333333300d017225333573466e1c0080040ec54ccd5cd19b8900200103c03e22333573466e2000800410c08806c068064894ccd5cd19b8900200110011002225333573466e2400800440084004cccccccc03088d401088888888d402888d402c894cd4cc0300100084ccd404417000c00412ccc00400800c894ccd4cccc00c0100140080040fc0fc104894ccd4cccc00c0100140080041040fc104894ccd4cccc00c0100140080040fc1040fc894ccd4cccc00c0100140080041041040fc894ccd4cccc00c010014008004400440084004894ccd4cccc00c0100140080044008400440088888d400888d400c8c894ccd4ccc05402401400c4ccc0540200100040080084ccc04c01c00c004cccccccc02801400802002401801c00c010cccccccc02401000401c02001401800800c894ccd5cd19b8f00200103615333573466e440080040dc0e4894ccd5cd19b9100200110011002225333573466e440080044008400488ccd5cd19b8f00200103b01a22333573466e440080040640e888ccd5cd19b9000200101803922333573466e400080040e005c88ccd5cd19b91002001037016222222221233333333001009008007006005004003002235001041225335002100103123500103e223232223232323253350041533550071333573460a2a0060740320020022a66a0060022a66aa00c2666ae68c13d40080e406000454cd400854cd540144ccd5cd1827a80081c00b8999ab9a3050500103801713335734609ea00207002e26666aa660a64422444a66a00226a006074442666a00a07e6008004666aa600e08000a0080020726607844666a0140740020046a01006a4466e00005200233305322253350011002221350022233007333305a22225335001100222135002225333573460b0002266601000e00c006266601000e6609866603000e00400200c00600400c00200606e0049000199ab9a3371266034002004900000a81b09a801912999ab9a3371e00491010015333573466e3c00522100034003003135001225333573466e3c009221001333573466e3c00522010003401303133034222300330020012001222123330010040030022235002223500322330383370266e08010004cdc100100199b82003001223500222350032233330100040030020012223500322350042235005223553335734608c0082c2646464246600200600466e0800800ccdc019b823370400e00800466e0800c004cdc100280201c91199ab9a3370e00400205801646a0024464a666ae68cdc38019a8008170999ab9a3370e0046a00205605a018054a666ae68c0f80044c01d24010350543300132330323370800600266e10008004ccc1208894ccd5cd1820800880109980180099b850020015333573466e2000920001303c00210025333573466e2000520001303c001100122333573466e200080040240a888ccd5cd19b8900200100802922333573466e240080040a001c94cd5ce0008b1111199ab9a3371066e08010004cdc100100181400391299a9999801801000a40009001099b84002001162222333573466e20cdc100200099b82002003005026101f22222232323232353300c004533357346078a0022c26605e601666e08d400c0ad4009400488d402088d4c044cc0cccdc124008004607e002446606a66e08018008cdc1002800899192999ab9a3371066e080040040084cdc0000a40042002601600266e08d400809d40044c8c8c8ccc11c8894ccd5cd19b8900148000520021337040046600600466e040052002480514ccd5cd19b89480000044004520003370200aa666ae68cdc48008010800880118189a80101518181a8008131a800911a804911a805111a80491198089981a19b820080083370400e00e6606866e08cdc119b8248020018010008cdc119b823040005003001350052235300b005223500a223500a2233010330333370401000c66e0801c014cc0cccdc100200119b8200300125333573466e200052000161533357346064002290000a999ab9a303300114800854ccd5cd181a0008a40042666078444a666ae68cdc400080109980180099b833370066e0c010004005200410020013370066e0c00520044800888d400888d400c88cc0a4cdc019b820040013370400400666e0800c0048d4004894ccd5cd18190010b099812800801111a800911981e1119a800a4000446a00444a666ae68cdc78010040998211119a800a4000446a00444a666ae68cdc7801006880089803001800898030018021192999ab9a302f303800113232323232323232323232323232123333333300100f00d00b009007005003002375a6ae84d5d10011a999807bad75a6ae84004894ccd5cd181e8008b0998180010009aba20023533300d75aeb4d5d0800912999ab9a303b0011613302e002001357440046a666016eb5d69aba1001225333573460720022c2660580040026ae88008dd69aba1001357440046eb4d5d08009aba200233300575ceb8d5d08009aba2303800233300375ceb8d5d0981b8008131baa00122232533357346060607200226604660086ae84c0e0004c00cd5d09aba2303800102737540029111c909133088303c49f3a30f1cc8ed553a73857a29779f6c6561cd8093f00233500101f019223035225335001100322133006002300400123253335734605600202e2a666ae68c0a8004054084c0c8dd50009119192999ab9a302d00101215333573460580022604060086ae84c0cc00854ccd5cd181580080a01118198009baa001232533357346050606200226464246600200600460086ae84d5d1181880118061aba1303000101f3754002464a666ae68c09cc0c00044c8c8c8c8c8c8c8c8c848cccc00402401c00c008cc02dd71aba135744008a666ae68c0c00044c84888c008010d5d0981b0010a999ab9a302f00113212223001004375c6ae84c0d800854ccd5cd181700080a012981b0009baa357420026ae88008ccc021d70039aba1001357446062006a666ae68c0a0c0c40044c8c848cc00400c008cc01402cd5d09aba23031002300b35742606000203e6ea8d5d0981780080f1baa0012232325333573460500022603460086ae84c0c000854ccd5cd181480080980f98180009baa0013300175ceb4888cc0bc88cccd55cf800900b1191980e9980e180398190009803181880098021aba20033574200402e6eac00488cc0b488cccd55cf800900a11980d18029aba100230033574400402a6eb00048c8c94ccd5cd181300089909111180200298021aba1302b002153335734604a00226424444600400a600a6ae84c0ac00854ccd5cd181200089909111180080298039aba1302b002153335734604600226424444600600a6eb8d5d0981580100d18158009baa0012323253335734605000222444402e2a666ae68c09c0044407c54ccd5cd18130008991909111111198008048041bad357426ae88c0ac00cdd71aba1302a002153335734604a0022646424444444660040120106eb8d5d09aba2302b003375c6ae84c0a800854ccd5cd18120008991909111111198030048041bae357426ae88c0ac00cc010d5d098150010a999ab9a302300113212222222300700830043574260540042a666ae68c0880044c848888888c014020c010d5d0981500100c98150009baa0012323253335734604400226464646424466600200c0080066eb4d5d09aba2002375a6ae84004d5d118150019bad3574260520042a666ae68c0840044c8488c00800cc010d5d0981480100c18148009baa0012323253335734604200226424460020066eb8d5d098140010a999ab9a30200011321223002003375c6ae84c0a000805cc0a0004dd50009192999ab9a301e3027001132321233001003002375a6ae84d5d1181380118019aba130260010153754002464a666ae68c074c0980044dd71aba1302500101437540022201622002444002220024440042200244002200220024400424002444006424460040064424660020060044424466002008006424446006008602844a666ae68c030004520001337009001180119b840014805054cd5ce2481035054310016253357389201024c680016222222220052222222200622222222007222222220082222222004370290001b8248008dc3a40006e1d2002370e90021b8748018dc3a40106e1d200a370e9006241413802aae7955ce9191800800911980198010010009"
            )
        )
        assert results[1].output.datum_hash == DatumHash.from_primitive(
            "55fe36f482e21ff6ae2caf2e33c3565572b568852dccd3f317ddecb91463d780"
        )

    def test_submit_tx(self, chain_context):
        results = chain_context.submit_tx("testcborhexfromtransaction")

        assert (
            results
            == "270be16fa17cdb3ef683bf2c28259c978d4b7088792074f177c8efda247e23f7"
        )

    def test_epoch(self, chain_context):
        assert chain_context.epoch == 98

    def test_stake_address_info(self, chain_context):
        stake_address_info = chain_context.stake_address_info(
            "stake_test1upyz3gk6mw5he20apnwfn96cn9rscgvmmsxc9r86dh0k66gswf59n"
        )

        assert len(stake_address_info) == 1
        assert (
            stake_address_info[0].address
            == "stake_test1upyz3gk6mw5he20apnwfn96cn9rscgvmmsxc9r86dh0k66gswf59n"
        )
        assert stake_address_info[0].delegation_deposit == 1000000000000
        assert stake_address_info[0].reward_account_balance == 1000000
        assert (
            stake_address_info[0].stake_delegation
            == "pool1q8m9x2zsux7va6w892g38tvchnzahvcd9tykqf3ygnmwta8k2v59pcduem5uw253zwke30x9mwes62kfvqnzg38kuh6q966kg7"
        )
        assert stake_address_info[0].vote_delegation == "always-abstain"

    def test_redeemer_keys_are_in_canonical_order(self):
        cbor = _tx_with_redeemers(
            (RedeemerTag.MINT, 1), (RedeemerTag.SPEND, 0), (RedeemerTag.SPEND, 2)
        )

        assert CardanoCliChainContext._redeemer_keys(cbor) == [
            "spend:0",
            "spend:2",
            "mint:1",
        ]

    def test_redeemer_keys_without_redeemers(self):
        assert CardanoCliChainContext._redeemer_keys(_tx_with_redeemers()) == []

    def test_evaluate_tx_cbor_pairs_costs_positionally(self, chain_context):
        """cardano-cli reports a script hash and a cost, with no redeemer pointer."""
        cbor = _tx_with_redeemers((RedeemerTag.MINT, 1), (RedeemerTag.SPEND, 0))
        commands = _stub_costs(
            chain_context,
            [
                {
                    "scriptHash": "aa" * 28,
                    "executionUnits": {"memory": 1700, "steps": 476468},
                    "lovelaceCost": 123,
                },
                {
                    "scriptHash": "bb" * 28,
                    "executionUnits": {"memory": 22, "steps": 33},
                    "lovelaceCost": 4,
                },
            ],
        )

        assert chain_context.evaluate_tx_cbor(cbor) == {
            "spend:0": ExecutionUnits(1700, 476468),
            "mint:1": ExecutionUnits(22, 33),
        }

        cost_command = next(
            cmd for cmd in commands if "calculate-plutus-script-cost" in cmd
        )
        assert cost_command[:4] == [
            "latest",
            "transaction",
            "calculate-plutus-script-cost",
            "online",
        ]
        assert "--tx-file" in cost_command

    def test_evaluate_tx_cbor_uses_reported_purpose(self, chain_context):
        """When the output names the redeemer itself, order stops mattering."""
        cbor = _tx_with_redeemers((RedeemerTag.MINT, 1), (RedeemerTag.SPEND, 0))
        _stub_costs(
            chain_context,
            [
                {
                    "executionUnits": {"memory": 9, "steps": 8},
                    "purpose": "mint",
                    "index": 1,
                },
                {
                    "executionUnits": {"memory": 7, "steps": 6},
                    "purpose": "spend",
                    "index": 0,
                },
            ],
        )

        assert chain_context.evaluate_tx_cbor(cbor) == {
            "mint:1": ExecutionUnits(9, 8),
            "spend:0": ExecutionUnits(7, 6),
        }

    def test_evaluate_tx_cbor_translates_purpose_aliases(self, chain_context):
        cbor = _tx_with_redeemers((RedeemerTag.WITHDRAWAL, 0))
        _stub_costs(
            chain_context,
            [
                {
                    "executionUnits": {"memory": 1, "steps": 2},
                    "purpose": "withdraw",
                    "index": 0,
                }
            ],
        )

        assert chain_context.evaluate_tx_cbor(cbor) == {
            "withdrawal:0": ExecutionUnits(1, 2)
        }

    def test_evaluate_tx_cbor_without_redeemers_skips_the_cli(self, chain_context):
        commands = _stub_costs(chain_context, [])

        assert chain_context.evaluate_tx_cbor(_tx_with_redeemers()) == {}
        assert not any("calculate-plutus-script-cost" in cmd for cmd in commands)

    def test_evaluate_tx_cbor_rejects_a_failed_script(self, chain_context):
        cbor = _tx_with_redeemers((RedeemerTag.SPEND, 0))
        _stub_costs(
            chain_context, [{"scriptHash": "aa" * 28, "error": "validation failed"}]
        )

        with pytest.raises(TransactionFailedException):
            chain_context.evaluate_tx_cbor(cbor)

    def test_evaluate_tx_cbor_rejects_more_costs_than_redeemers(self, chain_context):
        cbor = _tx_with_redeemers((RedeemerTag.SPEND, 0))
        _stub_costs(
            chain_context,
            [
                {"executionUnits": {"memory": 1, "steps": 2}},
                {"executionUnits": {"memory": 3, "steps": 4}},
            ],
        )

        with pytest.raises(TransactionFailedException):
            chain_context.evaluate_tx_cbor(cbor)

    def test_evaluate_tx_cbor_rejects_unparseable_output(self, chain_context):
        cbor = _tx_with_redeemers((RedeemerTag.SPEND, 0))
        original = chain_context._run_command

        def run(cmd):
            if "calculate-plutus-script-cost" in cmd:
                return "not json"
            return original(cmd)

        chain_context._run_command = run

        with pytest.raises(TransactionFailedException):
            chain_context.evaluate_tx_cbor(cbor)

    def test_evaluate_tx_cbor_reports_an_unsupported_cli(self, chain_context):
        """Older cardano-cli releases have no such command; say so, don't blame the tx."""
        cbor = _tx_with_redeemers((RedeemerTag.SPEND, 0))
        original = chain_context._run_command

        def run(cmd):
            if "calculate-plutus-script-cost" in cmd:
                raise CardanoCliError(
                    "Invalid argument `calculate-plutus-script-cost'\n\nUsage: cardano-cli"
                )
            return original(cmd)

        chain_context._run_command = run

        with pytest.raises(CardanoCLIError) as excinfo:
            chain_context.evaluate_tx_cbor(cbor)

        assert "calculate-plutus-script-cost" in excinfo.value.message
        assert "cardano-cli 8.1.2" in excinfo.value.message

    def test_evaluate_tx_cbor_reports_an_incompatible_option(self, chain_context):
        cbor = _tx_with_redeemers((RedeemerTag.SPEND, 0))
        original = chain_context._run_command

        def run(cmd):
            if "calculate-plutus-script-cost" in cmd:
                raise CardanoCliError(
                    "Invalid option `--socket-path'\n\nUsage: cardano-cli"
                )
            return original(cmd)

        chain_context._run_command = run

        with pytest.raises(CardanoCLIError):
            chain_context.evaluate_tx_cbor(cbor)

    def test_evaluate_tx_cbor_surfaces_a_real_cli_failure(self, chain_context):
        """A cli that understood the command but could not evaluate is a tx failure."""
        cbor = _tx_with_redeemers((RedeemerTag.SPEND, 0))
        original = chain_context._run_command

        def run(cmd):
            if "calculate-plutus-script-cost" in cmd:
                raise CardanoCliError("TxOutRefNotFound: unknown transaction input")
            return original(cmd)

        chain_context._run_command = run

        with pytest.raises(TransactionFailedException, match="TxOutRefNotFound"):
            chain_context.evaluate_tx_cbor(cbor)


POOL_HASH = "dd0b5f0c8db566f23b3ac2ffd63c4b5ea2afe1d2ca7c9810b1827e2f"
POOL_ID = "pool1m5947rydk4n0ywe6ctlav0ztt632lcwjef7fsy93sflz7ctcx6z"
OTHER_POOL_HASH = "0f292fcaa02b8b2f9b3c8f9fd8e0bb21abedb692a6d5058df3ef2735"
OTHER_POOL_ID = "pool1pu5jlj4q9w9jlxeu370a3c9myx47md5j5m2str0naunn2q3lkdy"
OWNER_HASH = "89218aeaab042f371399f159a08168b43a23f7c3b3db5c3a4c77a18e"
VRF_HASH = "adbafc4eae2ee532f0f0dc47e502debbfd1436bd16abfafe24e2af6db4bd149d"
METADATA_URL = "https://meta.example.com/pool.json"
METADATA_BODY = b'{"name":"Test Pool","ticker":"TEST"}'
METADATA_HASH = hashlib.blake2b(METADATA_BODY, digest_size=32).hexdigest()

DREP_KEY_HASH = "b02f7b335aebf284bbdc20bdc3b59e4e183ae2cfc47ad2d8bc19a241"
DREP_SCRIPT_HASH = "5a5ba42f130741d62384c390cfc84d9ceecc8a4bef38059ff18ba74b"
ANCHOR_HASH = "35aeb21ba4be07cf9fda041b635f107ef978238b3fccae9be1b571518ce9d1b7"
COLD_SCRIPT_HASH = "13493790d9b03483a1e1e684ea4faf1ee48a58f402574e7f2246f4d4"
HOT_KEY_HASH = "68bb0b4276021f82364056aa9f4d38ba5ac59b26c166cbeaa9408746"
RETURN_ADDR_HASH = "9139e5c0a42f0f2389634c3dd18dc621f5594c5ba825d9a8883c6627"
WITHDRAWAL_HASH = "b02f7b335aebf284bbdc20bdc3b59e4e183ae2cfc47ad2d8bc19a241"
ACTION_TX_ID = "2dd15e0ef6e6a17841cb9541c27724072ce4d4b79b91e58432fbaa32d9572531"

GOV_ACTION_ID = GovActionId(
    transaction_id=TransactionId(bytes.fromhex(ACTION_TX_ID)),
    gov_action_index=1,
)

POOL_STATE = {
    POOL_HASH: {
        "futurePoolParams": None,
        "poolParams": {
            "spsCost": 340000000,
            "spsDeposit": 500000000,
            "spsMargin": 0.05,
            "spsMetadata": {"hash": METADATA_HASH, "url": METADATA_URL},
            "spsOwners": [OWNER_HASH],
            "spsPledge": 10000000000,
            "spsRelays": [
                {
                    "single host address": {
                        "IPv4": "1.2.3.4",
                        "IPv6": None,
                        "port": 3001,
                    }
                },
                {
                    "single host name": {
                        "dnsName": "relay1.example.com",
                        "port": 3002,
                    }
                },
            ],
            "spsRewardAccount": {
                "credential": {"keyHash": OWNER_HASH},
                "network": "Testnet",
            },
            "spsVrf": VRF_HASH,
        },
        "retiring": None,
    }
}

STAKE_SNAPSHOT = {
    "pools": {
        POOL_HASH: {
            "stakeMark": 5000000000000,
            "stakeSet": 4900000000000,
            "stakeGo": 4800000000000,
        }
    },
    "total": {
        "stakeMark": 25000000000000000,
        "stakeSet": 24900000000000000,
        "stakeGo": 24800000000000000,
    },
}

PROTOCOL_STATE = {
    "epochNonce": "de" * 32,
    "lastSlot": 123456789,
    "oCertCounters": {POOL_HASH: 7},
}

COMMITTEE_STATE = {
    "committee": {
        f"scriptHash-{COLD_SCRIPT_HASH}": {
            "expiration": 653,
            "hotCredsAuthStatus": {
                "contents": {"keyHash": HOT_KEY_HASH},
                "tag": "MemberAuthorized",
            },
            "nextEpochChange": {"tag": "NoChangeExpected"},
            "status": "Active",
        }
    },
    "epoch": 623,
    "threshold": {"denominator": 3, "numerator": 2},
}

GOV_STATE = {
    "proposals": [
        {
            "actionId": {"txId": ACTION_TX_ID, "govActionIx": 1},
            "proposedIn": 90,
            "expiresAfter": 120,
            "committeeVotes": {f"keyHash-{HOT_KEY_HASH}": "VoteYes"},
            "dRepVotes": {f"keyHash-{DREP_KEY_HASH}": "Abstain"},
            "stakePoolVotes": {f"keyHash-{OTHER_POOL_HASH}": "VoteNo"},
            "proposalProcedure": {
                "deposit": 100000000000,
                "returnAddr": {
                    "credential": {"keyHash": RETURN_ADDR_HASH},
                    "network": "Testnet",
                },
                "anchor": {"url": "https://anchor.test", "dataHash": ANCHOR_HASH},
                "govAction": {
                    "tag": "TreasuryWithdrawals",
                    "contents": [
                        [[{"keyHash": WITHDRAWAL_HASH}, 20000000]],
                        None,
                    ],
                },
            },
        }
    ],
    "nextRatifyState": {"enactedGovActions": [], "expiredGovActions": []},
}


def _stub_cli(chain_context, responses):
    """Answer the cli from `responses`, keyed by a token of the command."""
    commands = []
    original = chain_context._run_command

    def run(cmd):
        commands.append(cmd)
        for marker, output in responses.items():
            if marker in cmd:
                if isinstance(output, Exception):
                    raise output
                return output if isinstance(output, str) else json.dumps(output)
        return original(cmd)

    chain_context._run_command = run
    return commands


class _FakeResponse:
    """The slice of `requests.Response` the metadata check touches."""

    def __init__(self, content: bytes, error=None):
        self.content = content
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error


class TestCardanoCliChainState:
    def test_chain_tip(self, chain_context):
        tip = chain_context.chain_tip

        assert tip.slot == 41008115
        assert tip.block == 1460093
        assert (
            tip.hash
            == "c1bda7b2975dd3bf9969a57d92528ba7d60383b6e1c4a37b68379c4f4330e790"
        )
        assert tip.epoch == 98
        assert tip.era == Era.BABBAGE
        assert tip.sync_progress == 100.0

    def test_utxo_resolves_a_live_input(self, chain_context):
        tx_in = TransactionInput.from_primitive(
            ["fbaa018740241abb935240051134914389c3f94647d8bd6c30cb32d3fdb799bf", 0]
        )
        _stub_cli(
            chain_context,
            {
                "--tx-in": {
                    "fbaa018740241abb935240051134914389c3f94647d8bd6c30cb32d3fdb799bf#0": {
                        "address": "addr1v9p0rc57dzkz7gg97dmsns8hngsuxl956xe6myjldaug7hse4elc6",
                        "datum": None,
                        "inlineDatum": None,
                        "referenceScript": None,
                        "value": {"lovelace": 708864940},
                    }
                }
            },
        )

        result = chain_context.utxo(tx_in)

        assert result is not None
        utxo, is_spent = result
        assert utxo.input == tx_in
        assert utxo.output.amount.coin == 708864940
        # A node only holds the live set, so anything it returns is unspent.
        assert is_spent is False

    def test_utxo_returns_none_when_absent(self, chain_context):
        _stub_cli(chain_context, {"--tx-in": {}})

        assert (
            chain_context.utxo(
                TransactionInput.from_primitive(["aa" * 32, 3]),
            )
            is None
        )

    def test_utxo_rejects_unparseable_output(self, chain_context):
        _stub_cli(chain_context, {"--tx-in": "cardano-cli: not json"})

        with pytest.raises(CardanoCLIError):
            chain_context.utxo(TransactionInput.from_primitive(["aa" * 32, 0]))


class TestCardanoCliStakePools:
    def test_stake_pools(self, chain_context):
        _stub_cli(chain_context, {"stake-pools": f"{POOL_ID}\n{OTHER_POOL_ID}\n"})

        pools = chain_context.stake_pools()

        assert [pool.encode() for pool in pools] == [POOL_ID, OTHER_POOL_ID]

    def test_stake_pools_accepts_json_output(self, chain_context):
        _stub_cli(chain_context, {"stake-pools": [POOL_ID]})

        assert [pool.encode() for pool in chain_context.stake_pools()] == [POOL_ID]

    def test_stake_pools_rejects_an_undecodable_id(self, chain_context):
        _stub_cli(chain_context, {"stake-pools": "not-a-pool-id\n"})

        with pytest.raises(CardanoCLIError):
            chain_context.stake_pools()

    def test_stake_pool_info(self, chain_context):
        commands = _stub_cli(
            chain_context,
            {
                "pool-state": POOL_STATE,
                "stake-snapshot": STAKE_SNAPSHOT,
                "protocol-state": PROTOCOL_STATE,
            },
        )

        info = chain_context.stake_pool_info(POOL_ID)

        assert info.pool_params is not None
        assert info.pool_params.operator.payload.hex() == POOL_HASH
        assert info.pool_params.pledge == 10000000000
        assert info.pool_params.cost == 340000000
        assert info.pool_params.margin == Fraction(1, 20)
        assert info.pool_params.vrf_keyhash.payload.hex() == VRF_HASH
        # Testnet key-hash reward accounts carry the 0xE0 header byte.
        assert info.pool_params.reward_account.payload.hex() == f"e0{OWNER_HASH}"
        assert [owner.payload.hex() for owner in info.pool_params.pool_owners] == [
            OWNER_HASH
        ]
        assert info.pool_params.relays is not None
        assert info.pool_params.relays[0].ipv4 == "1.2.3.4"
        assert info.pool_params.relays[0].port == 3001
        assert info.pool_params.relays[1].dns_name == "relay1.example.com"
        assert info.pool_params.pool_metadata is not None
        assert info.pool_params.pool_metadata.url == METADATA_URL
        assert (
            info.pool_params.pool_metadata.pool_metadata_hash.payload.hex()
            == METADATA_HASH
        )

        assert info.active_stake == 4900000000000
        assert info.active_size == Decimal(4900000000000) / Decimal(24900000000000000)
        assert info.opcert_counter == 7
        assert info.status == PoolStatus.REGISTERED
        assert info.retiring_epoch is None
        # The node reports snapshots, never a live figure.
        assert info.live_stake is None
        assert info.live_pledge is None

        pool_state_command = next(cmd for cmd in commands if "pool-state" in cmd)
        assert pool_state_command[:4] == [
            "query",
            "pool-state",
            "--stake-pool-id",
            POOL_ID,
        ]

    def test_stake_pool_info_reports_a_retiring_pool(self, chain_context):
        pool_state = copy.deepcopy(POOL_STATE)
        pool_state[POOL_HASH]["retiring"] = 512
        _stub_cli(
            chain_context,
            {
                "pool-state": pool_state,
                "stake-snapshot": STAKE_SNAPSHOT,
                "protocol-state": PROTOCOL_STATE,
            },
        )

        info = chain_context.stake_pool_info(POOL_ID)

        assert info.status == PoolStatus.RETIRING
        assert info.retiring_epoch == 512

    def test_stake_pool_info_rejects_an_unregistered_pool(self, chain_context):
        _stub_cli(chain_context, {"pool-state": {}})

        with pytest.raises(CardanoCLIError, match="not registered"):
            chain_context.stake_pool_info(POOL_ID)

    def test_stake_pool_info_strict_verifies_the_metadata_hash(
        self, chain_context, monkeypatch
    ):
        fetched = []

        def fake_get(url, timeout=None):
            fetched.append((url, timeout))
            return _FakeResponse(METADATA_BODY)

        monkeypatch.setattr(cardano_cli.requests, "get", fake_get)
        _stub_cli(
            chain_context,
            {
                "pool-state": POOL_STATE,
                "stake-snapshot": STAKE_SNAPSHOT,
                "protocol-state": PROTOCOL_STATE,
            },
        )

        info = chain_context.stake_pool_info(POOL_ID, strict=True)

        assert fetched and fetched[0][0] == METADATA_URL
        assert info.pool_params is not None
        assert info.pool_params.pool_metadata is not None

    def test_stake_pool_info_strict_rejects_a_hash_mismatch(
        self, chain_context, monkeypatch
    ):
        monkeypatch.setattr(
            cardano_cli.requests,
            "get",
            lambda url, timeout=None: _FakeResponse(b"something else"),
        )
        _stub_cli(
            chain_context,
            {
                "pool-state": POOL_STATE,
                "stake-snapshot": STAKE_SNAPSHOT,
                "protocol-state": PROTOCOL_STATE,
            },
        )

        with pytest.raises(CardanoCLIError, match="registered on-chain"):
            chain_context.stake_pool_info(POOL_ID, strict=True)

    def test_stake_pool_info_tolerates_metadata_problems_when_lenient(
        self, chain_context, monkeypatch
    ):
        def fail(url, timeout=None):
            raise RequestException("connection refused")

        monkeypatch.setattr(cardano_cli.requests, "get", fail)
        _stub_cli(
            chain_context,
            {
                "pool-state": POOL_STATE,
                "stake-snapshot": STAKE_SNAPSHOT,
                "protocol-state": PROTOCOL_STATE,
            },
        )

        info = chain_context.stake_pool_info(POOL_ID)

        assert info.pool_params is not None
        assert info.pool_params.pool_metadata is not None
        assert info.pool_params.pool_metadata.url == METADATA_URL

    def test_stake_pool_info_strict_rejects_an_unreachable_url(
        self, chain_context, monkeypatch
    ):
        def fail(url, timeout=None):
            raise RequestException("connection refused")

        monkeypatch.setattr(cardano_cli.requests, "get", fail)
        _stub_cli(
            chain_context,
            {
                "pool-state": POOL_STATE,
                "stake-snapshot": STAKE_SNAPSHOT,
                "protocol-state": PROTOCOL_STATE,
            },
        )

        with pytest.raises(CardanoCLIError, match="Unable to fetch"):
            chain_context.stake_pool_info(POOL_ID, strict=True)


class TestCardanoCliKesPeriodInfo:
    kes_output = """✓ The operational certificate counter agrees with the node protocol state counter
{
    "qKesCurrentKesPeriod": 404,
    "qKesEndKesInterval": 465,
    "qKesKesKeyExpiry": "2026-02-01T00:00:00Z",
    "qKesNodeStateOperationalCertificateNumber": 6,
    "qKesOnDiskOperationalCertificateNumber": 7,
    "qKesRemainingSlotsInKesPeriod": 3000,
    "qKesStartKesInterval": 336
}"""

    def test_kes_period_info(self, chain_context):
        commands = _stub_cli(chain_context, {"kes-period-info": self.kes_output})

        info = chain_context.kes_period_info(op_cert=b"\xaa\xbb")

        assert info.on_chain_op_cert_count == 6
        assert info.on_disk_op_cert_count == 7
        # No expected counter in this output, so it is the on-chain one plus one.
        assert info.next_chain_op_cert_count == 7
        assert info.on_disk_kes_start == 336

        command = next(cmd for cmd in commands if "kes-period-info" in cmd)
        assert "--op-cert-file" in command

    def test_kes_period_info_uses_the_expected_counter(self, chain_context):
        _stub_cli(
            chain_context,
            {
                "kes-period-info": {
                    "qKesNodeStateOperationalCertificateNumber": 6,
                    "qKesOnDiskOperationalCertificateNumber": 7,
                    "qKesExpectedOperationalCertificateNumber": 8,
                    "qKesStartKesInterval": 336,
                }
            },
        )

        assert (
            chain_context.kes_period_info(op_cert="aabb").next_chain_op_cert_count == 8
        )

    def test_kes_period_info_needs_an_operational_certificate(self, chain_context):
        with pytest.raises(CardanoCLIError, match="op_cert"):
            chain_context.kes_period_info()


class TestCardanoCliTreasury:
    def test_treasury(self, chain_context):
        _stub_cli(chain_context, {"treasury": "1000000000000000\n"})

        assert chain_context.treasury() == 1000000000000000

    def test_treasury_accepts_json_output(self, chain_context):
        _stub_cli(chain_context, {"treasury": {"lovelace": 42}})

        assert chain_context.treasury() == 42

    def test_treasury_rejects_unparseable_output(self, chain_context):
        _stub_cli(chain_context, {"treasury": "no balance here"})

        with pytest.raises(CardanoCLIError):
            chain_context.treasury()


class TestCardanoCliGovernance:
    def test_drep_info(self, chain_context):
        commands = _stub_cli(
            chain_context,
            {
                "drep-state": [
                    [
                        {"keyHash": DREP_KEY_HASH},
                        {
                            "anchor": {
                                "dataHash": ANCHOR_HASH,
                                "url": "https://anchor.test",
                            },
                            "deposit": 500000000,
                            "expiry": 639,
                            "stake": 305554989074,
                        },
                    ]
                ]
            },
        )
        drep = DRep(
            kind=DRepKind.VERIFICATION_KEY_HASH,
            credential=VerificationKeyHash(bytes.fromhex(DREP_KEY_HASH)),
        )

        info = chain_context.drep_info(drep)

        assert info.drep == drep
        assert info.active is True
        assert info.status == DRepStatus.REGISTERED
        assert info.deposit == 500000000
        assert info.expiry == 639
        assert info.stake == 305554989074
        assert info.anchor is not None
        assert info.anchor.url == "https://anchor.test"
        assert info.anchor.data_hash.payload.hex() == ANCHOR_HASH

        command = next(cmd for cmd in commands if "drep-state" in cmd)
        assert command[2:4] == ["--drep-key-hash", DREP_KEY_HASH]

    def test_drep_info_queries_a_script_drep_by_script_hash(self, chain_context):
        commands = _stub_cli(chain_context, {"drep-state": []})
        drep = DRep(
            kind=DRepKind.SCRIPT_HASH,
            credential=ScriptHash(bytes.fromhex(DREP_SCRIPT_HASH)),
        )

        info = chain_context.drep_info(drep)

        assert info.status == DRepStatus.NOT_REGISTERED
        assert info.active is False
        assert info.stake == 0

        command = next(cmd for cmd in commands if "drep-state" in cmd)
        assert command[2:4] == ["--drep-script-hash", DREP_SCRIPT_HASH]

    def test_drep_info_reads_a_predefined_drep_from_the_distribution(
        self, chain_context
    ):
        _stub_cli(
            chain_context,
            {
                "drep-stake-distribution": {
                    "drep-alwaysAbstain": 8784205971620742,
                    "drep-alwaysNoConfidence": 194879536262091,
                }
            },
        )

        info = chain_context.drep_info(DRep(kind=DRepKind.ALWAYS_ABSTAIN))

        assert info.stake == 8784205971620742
        assert info.status == DRepStatus.REGISTERED

    def test_drep_stake_distribution(self, chain_context):
        _stub_cli(
            chain_context,
            {
                "drep-stake-distribution": {
                    "drep-alwaysAbstain": 8784205971620742,
                    f"drep-keyHash-{DREP_KEY_HASH}": 12121160278,
                    f"drep-scriptHash-{DREP_SCRIPT_HASH}": 194458026737,
                    "drep-nonsense": 1,
                }
            },
        )

        entries = chain_context.drep_stake_distribution()

        assert len(entries) == 3
        by_stake = {entry.stake: entry.drep for entry in entries}
        assert by_stake[8784205971620742] == DRep(kind=DRepKind.ALWAYS_ABSTAIN)
        assert by_stake[12121160278] == DRep(
            kind=DRepKind.VERIFICATION_KEY_HASH,
            credential=VerificationKeyHash(bytes.fromhex(DREP_KEY_HASH)),
        )
        assert by_stake[194458026737] == DRep(
            kind=DRepKind.SCRIPT_HASH,
            credential=ScriptHash(bytes.fromhex(DREP_SCRIPT_HASH)),
        )

    def test_spo_stake_distribution(self, chain_context):
        _stub_cli(
            chain_context,
            {
                "spo-stake-distribution": {
                    f"keyHash-{POOL_HASH}": 1234567890,
                    OTHER_POOL_HASH: 9876543210,
                }
            },
        )

        entries = chain_context.spo_stake_distribution()

        assert {(entry.pool_id, entry.stake) for entry in entries} == {
            (POOL_ID, 1234567890),
            (OTHER_POOL_ID, 9876543210),
        }

    def test_spo_stake_distribution_accepts_pair_output(self, chain_context):
        _stub_cli(
            chain_context,
            {"spo-stake-distribution": [[f"keyHash-{POOL_HASH}", 5]]},
        )

        entries = chain_context.spo_stake_distribution()

        assert [(entry.pool_id, entry.stake) for entry in entries] == [(POOL_ID, 5)]

    def test_gov_action_info(self, chain_context):
        _stub_cli(chain_context, {"gov-state": GOV_STATE})

        info = chain_context.gov_action_info(GOV_ACTION_ID)

        assert info.gov_action_id == GOV_ACTION_ID
        assert info.proposed_in == 90
        assert info.expires_after == 120
        assert info.status is None
        assert isinstance(info.gov_action, TreasuryWithdrawalsAction)
        assert dict(info.gov_action.withdrawals) == {
            bytes.fromhex(f"e0{WITHDRAWAL_HASH}"): 20000000
        }

    def test_gov_action_info_reports_a_ratified_action(self, chain_context):
        gov_state = copy.deepcopy(GOV_STATE)
        gov_state["nextRatifyState"]["enactedGovActions"] = [
            {"actionId": {"txId": ACTION_TX_ID, "govActionIx": 1}}
        ]
        _stub_cli(chain_context, {"gov-state": gov_state})

        info = chain_context.gov_action_info(GOV_ACTION_ID)

        assert info.ratified_epoch == 98
        assert info.status == GovActionStatus.RATIFIED

    def test_gov_action_info_reports_an_action_that_left_the_proposal_set(
        self, chain_context
    ):
        _stub_cli(chain_context, {"gov-state": {"proposals": []}})

        info = chain_context.gov_action_info(GOV_ACTION_ID)

        assert info.status == GovActionStatus.DROPPED
        assert info.dropped_epoch == 98
        # The node no longer says what was proposed; do not invent it.
        assert info.gov_action is None

    def test_gov_action_votes(self, chain_context):
        _stub_cli(chain_context, {"gov-state": GOV_STATE})

        votes = chain_context.gov_action_votes(GOV_ACTION_ID)

        assert votes.gov_action_id == GOV_ACTION_ID
        assert votes.deposit == 100000000000
        assert votes.deposit_return_addr == str(
            Address.from_primitive(bytes.fromhex(f"e0{RETURN_ADDR_HASH}"))
        )
        assert votes.anchor is not None
        assert votes.anchor.url == "https://anchor.test"

        assert len(votes.committee_votes) == 1
        assert votes.committee_votes[0].vote == Vote.YES
        assert votes.committee_votes[0].voter == CommitteeHotCredential(
            VerificationKeyHash(bytes.fromhex(HOT_KEY_HASH))
        )

        assert len(votes.drep_votes) == 1
        assert votes.drep_votes[0].vote == Vote.ABSTAIN
        assert votes.drep_votes[0].voter == DRep(
            kind=DRepKind.VERIFICATION_KEY_HASH,
            credential=VerificationKeyHash(bytes.fromhex(DREP_KEY_HASH)),
        )

        assert len(votes.stake_pool_votes) == 1
        assert votes.stake_pool_votes[0].vote == Vote.NO
        assert votes.stake_pool_votes[0].voter == OTHER_POOL_ID

    def test_gov_action_votes_rejects_an_unknown_action(self, chain_context):
        _stub_cli(chain_context, {"gov-state": {"proposals": []}})

        with pytest.raises(CardanoCLIError, match="not found in gov-state"):
            chain_context.gov_action_votes(GOV_ACTION_ID)

    def test_gov_actions_all(self, chain_context):
        _stub_cli(chain_context, {"gov-state": GOV_STATE})

        actions = chain_context.gov_actions_all()

        assert len(actions) == 1
        assert actions[0].gov_action_id == GOV_ACTION_ID

    def test_gov_actions_all_is_empty_when_nothing_is_proposed(self, chain_context):
        _stub_cli(chain_context, {"gov-state": {"proposals": []}})

        assert chain_context.gov_actions_all() == []

    def test_gov_action_votes_dates_an_expiry_the_node_has_not_processed(
        self, chain_context
    ):
        gov_state = copy.deepcopy(GOV_STATE)
        gov_state["proposals"][0]["expiresAfter"] = 97
        _stub_cli(chain_context, {"gov-state": gov_state})

        votes = chain_context.gov_action_votes(GOV_ACTION_ID)

        assert votes.expired_epoch == 98
        assert votes.status == GovActionStatus.EXPIRED

    def test_parse_gov_action_variants(self, chain_context):
        parse = chain_context._parse_gov_action

        assert isinstance(parse({"tag": "InfoAction", "contents": []}), InfoAction)

        no_confidence = parse(
            {
                "tag": "NoConfidence",
                "contents": [{"txId": ACTION_TX_ID, "govActionIx": 1}],
            }
        )
        assert isinstance(no_confidence, NoConfidence)
        assert no_confidence.gov_action_id == GOV_ACTION_ID

        hard_fork = parse(
            {
                "tag": "HardForkInitiation",
                "contents": [None, {"major": 10, "minor": 1}],
            }
        )
        assert isinstance(hard_fork, HardForkInitiationAction)
        assert tuple(hard_fork.protocol_version) == (10, 1)

        constitution = parse(
            {
                "tag": "NewConstitution",
                "contents": [
                    None,
                    {
                        "anchor": {
                            "url": "https://constitution.test",
                            "dataHash": ANCHOR_HASH,
                        },
                        "script": COLD_SCRIPT_HASH,
                    },
                ],
            }
        )
        assert isinstance(constitution, NewConstitution)
        assert constitution.constitution[0].url == "https://constitution.test"
        assert constitution.constitution[1] == ScriptHash(
            bytes.fromhex(COLD_SCRIPT_HASH)
        )

        parameter_change = parse(
            {
                "tag": "ParameterChange",
                "contents": [
                    None,
                    {
                        "txFeePerByte": 44,
                        "maxTxSize": 16384,
                        "monetaryExpansion": 0.003,
                        "maxTxExecutionUnits": {"memory": 14000000, "steps": 10**10},
                        "executionUnitPrices": {
                            "priceMemory": 0.0577,
                            "priceSteps": 0.0000721,
                        },
                        "costModels": {"PlutusV3": [1, 2, 3]},
                    },
                    None,
                ],
            }
        )
        assert isinstance(parameter_change, ParameterChangeAction)
        update = parameter_change.protocol_param_update
        assert update.min_fee_a == 44
        assert update.max_transaction_size == 16384
        assert update.expansion_rate == Fraction(3, 1000)
        assert update.max_tx_ex_units == ExecutionUnits(14000000, 10**10)
        assert update.execution_costs is not None
        assert update.execution_costs.mem_price == Fraction(577, 10000)
        assert update.cost_models == {"PlutusV3": [1, 2, 3]}
        assert update.min_pool_cost is None

    def test_parse_gov_action_keeps_an_unmappable_variant_verbatim(self, chain_context):
        # pycardano cannot hold an UpdateCommittee's member map (its committee
        # credentials are unhashable), so the cli's own object is returned.
        raw = {
            "tag": "UpdateCommittee",
            "contents": [None, [], {f"keyHash-{HOT_KEY_HASH}": 700}, [2, 3]],
        }

        assert chain_context._parse_gov_action(raw) is raw

    def test_committee_member_info_by_cold_credential(self, chain_context):
        commands = _stub_cli(chain_context, {"committee-state": COMMITTEE_STATE})
        cold = CommitteeColdCredential(ScriptHash(bytes.fromhex(COLD_SCRIPT_HASH)))

        info = chain_context.committee_member_info(cold=cold)

        assert info.cold_credential == cold
        assert info.hot_credential == CommitteeHotCredential(
            VerificationKeyHash(bytes.fromhex(HOT_KEY_HASH))
        )
        assert info.expiration == 653
        assert info.status == CommitteeMemberStatus.ACTIVE

        command = next(cmd for cmd in commands if "committee-state" in cmd)
        assert command[2:4] == ["--cold-script-hash", COLD_SCRIPT_HASH]

    def test_committee_member_info_by_hot_credential(self, chain_context):
        commands = _stub_cli(chain_context, {"committee-state": COMMITTEE_STATE})
        hot = CommitteeHotCredential(VerificationKeyHash(bytes.fromhex(HOT_KEY_HASH)))

        info = chain_context.committee_member_info(hot=hot)

        assert info.cold_credential == CommitteeColdCredential(
            ScriptHash(bytes.fromhex(COLD_SCRIPT_HASH))
        )
        assert info.hot_credential == hot

        command = next(cmd for cmd in commands if "committee-state" in cmd)
        assert command[2:4] == ["--hot-key-hash", HOT_KEY_HASH]

    def test_committee_member_info_needs_a_credential(self, chain_context):
        with pytest.raises(CardanoCLIError, match="cold or a hot credential"):
            chain_context.committee_member_info()

    def test_committee_member_info_rejects_an_unknown_member(self, chain_context):
        _stub_cli(chain_context, {"committee-state": {"committee": {}}})

        with pytest.raises(CardanoCLIError, match="No committee member matches"):
            chain_context.committee_member_info(
                cold=CommitteeColdCredential(
                    ScriptHash(bytes.fromhex(COLD_SCRIPT_HASH))
                )
            )

    def test_committee_state(self, chain_context):
        _stub_cli(chain_context, {"committee-state": COMMITTEE_STATE})

        state = chain_context.committee_state()

        assert state.threshold == pytest.approx(2 / 3)
        assert len(state.members) == 1
        member = state.members[0]
        assert member.cold_credential == CommitteeColdCredential(
            ScriptHash(bytes.fromhex(COLD_SCRIPT_HASH))
        )
        assert member.hot_credential == CommitteeHotCredential(
            VerificationKeyHash(bytes.fromhex(HOT_KEY_HASH))
        )
        assert member.expiration == 653
        assert member.status == CommitteeMemberStatus.ACTIVE

    def test_committee_state_reports_an_unauthorized_member(self, chain_context):
        payload = copy.deepcopy(COMMITTEE_STATE)
        payload["committee"][f"scriptHash-{COLD_SCRIPT_HASH}"]["hotCredsAuthStatus"] = {
            "tag": "MemberNotAuthorized"
        }
        _stub_cli(chain_context, {"committee-state": payload})

        state = chain_context.committee_state()

        assert state.members[0].hot_credential is None
