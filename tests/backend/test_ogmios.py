from datetime import datetime
from fractions import Fraction
from unittest.mock import patch

from ogmios.statequery import (
    QueryEraSummaries,
    QueryGenesisConfiguration,
    QueryNetworkTip,
    QueryProtocolParameters,
    QueryUtxo,
)
from pycardano import Address, TransactionOutput
from pycardano.transaction import MultiAsset, TransactionInput, Value

from pccontext.backend.ogmios import ALONZO_COINS_PER_UTXO_WORD
from pccontext.models import GenesisParameters


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
