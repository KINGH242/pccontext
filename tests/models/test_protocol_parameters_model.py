from fractions import Fraction

from pccontext.models.protocol_parameters_model import (
    ProtocolParameters,
    cost_model_to_pycardano,
)


def test_from_json_blockfrost(blockfrost_protocol_parameters):
    protocol_params = ProtocolParameters.from_json(blockfrost_protocol_parameters)
    assert protocol_params.price_mem == float(
        blockfrost_protocol_parameters["price_mem"]
    )
    assert protocol_params.price_step == float(
        blockfrost_protocol_parameters["price_step"]
    )
    assert protocol_params.max_tx_ex_mem == int(
        blockfrost_protocol_parameters["max_tx_ex_mem"]
    )
    assert protocol_params.max_tx_ex_steps == int(
        blockfrost_protocol_parameters["max_tx_ex_steps"]
    )
    assert protocol_params.max_block_ex_mem == int(
        blockfrost_protocol_parameters["max_block_ex_mem"]
    )
    assert protocol_params.max_block_ex_steps == int(
        blockfrost_protocol_parameters["max_block_ex_steps"]
    )
    assert protocol_params.max_val_size == int(
        blockfrost_protocol_parameters["max_val_size"]
    )
    assert protocol_params.collateral_percent == int(
        blockfrost_protocol_parameters["collateral_percent"]
    )
    assert protocol_params.max_collateral_inputs == int(
        blockfrost_protocol_parameters["max_collateral_inputs"]
    )
    assert protocol_params.min_utxo == int(
        blockfrost_protocol_parameters["coins_per_utxo_size"]
    )
    assert protocol_params.coins_per_utxo_word == int(
        blockfrost_protocol_parameters["coins_per_utxo_word"]
    )
    assert protocol_params.pvt_motion_no_confidence == float(
        blockfrost_protocol_parameters["pvt_motion_no_confidence"]
    )
    assert protocol_params.pvt_committee_normal == float(
        blockfrost_protocol_parameters["pvt_committee_normal"]
    )
    assert protocol_params.pvt_committee_no_confidence == float(
        blockfrost_protocol_parameters["pvt_committee_no_confidence"]
    )
    assert protocol_params.pvt_hard_fork_initiation == float(
        blockfrost_protocol_parameters["pvt_hard_fork_initiation"]
    )
    assert protocol_params.dvt_motion_no_confidence == float(
        blockfrost_protocol_parameters["dvt_motion_no_confidence"]
    )
    assert protocol_params.dvt_committee_normal == float(
        blockfrost_protocol_parameters["dvt_committee_normal"]
    )
    assert protocol_params.dvt_committee_no_confidence == float(
        blockfrost_protocol_parameters["dvt_committee_no_confidence"]
    )
    assert protocol_params.dvt_update_to_constitution == float(
        blockfrost_protocol_parameters["dvt_update_to_constitution"]
    )
    assert protocol_params.dvt_hard_fork_initiation == float(
        blockfrost_protocol_parameters["dvt_hard_fork_initiation"]
    )
    assert protocol_params.dvt_p_p_network_group == float(
        blockfrost_protocol_parameters["dvt_p_p_network_group"]
    )
    assert protocol_params.dvt_p_p_economic_group == float(
        blockfrost_protocol_parameters["dvt_p_p_economic_group"]
    )
    assert protocol_params.dvt_p_p_technical_group == float(
        blockfrost_protocol_parameters["dvt_p_p_technical_group"]
    )
    assert protocol_params.dvt_p_p_gov_group == float(
        blockfrost_protocol_parameters["dvt_p_p_gov_group"]
    )
    assert protocol_params.dvt_treasury_withdrawal == float(
        blockfrost_protocol_parameters["dvt_treasury_withdrawal"]
    )
    assert protocol_params.committee_min_size == int(
        blockfrost_protocol_parameters["committee_min_size"]
    )
    assert protocol_params.committee_max_term_length == int(
        blockfrost_protocol_parameters["committee_max_term_length"]
    )
    assert protocol_params.gov_action_lifetime == int(
        blockfrost_protocol_parameters["gov_action_lifetime"]
    )
    assert protocol_params.gov_action_deposit == int(
        blockfrost_protocol_parameters["gov_action_deposit"]
    )
    assert protocol_params.d_rep_deposit == int(
        blockfrost_protocol_parameters["drep_deposit"]
    )
    assert protocol_params.d_rep_activity == int(
        blockfrost_protocol_parameters["drep_activity"]
    )
    assert protocol_params.pvt_pp_security_group == float(
        blockfrost_protocol_parameters["pvtpp_security_group"]
    )
    assert protocol_params.min_fee_ref_script_cost_per_byte == int(
        blockfrost_protocol_parameters["min_fee_reference_scripts"]
    )


def test_from_json_koios(koios_protocol_parameters):
    protocol_params = ProtocolParameters.from_json(koios_protocol_parameters)

    assert protocol_params.price_mem == float(koios_protocol_parameters[0]["price_mem"])
    assert protocol_params.price_step == float(
        koios_protocol_parameters[0]["price_step"]
    )
    assert protocol_params.max_tx_ex_mem == int(
        koios_protocol_parameters[0]["max_tx_ex_mem"]
    )
    assert protocol_params.max_tx_ex_steps == int(
        koios_protocol_parameters[0]["max_tx_ex_steps"]
    )
    assert protocol_params.max_block_ex_mem == int(
        koios_protocol_parameters[0]["max_block_ex_mem"]
    )
    assert protocol_params.max_block_ex_steps == int(
        koios_protocol_parameters[0]["max_block_ex_steps"]
    )
    assert protocol_params.max_val_size == int(
        koios_protocol_parameters[0]["max_val_size"]
    )
    assert protocol_params.collateral_percent == int(
        koios_protocol_parameters[0]["collateral_percent"]
    )
    assert protocol_params.max_collateral_inputs == int(
        koios_protocol_parameters[0]["max_collateral_inputs"]
    )
    assert protocol_params.coins_per_utxo_byte == int(
        koios_protocol_parameters[0]["coins_per_utxo_size"]
    )
    assert protocol_params.pvt_motion_no_confidence == float(
        koios_protocol_parameters[0]["pvt_motion_no_confidence"]
    )
    assert protocol_params.pvt_committee_normal == float(
        koios_protocol_parameters[0]["pvt_committee_normal"]
    )
    assert protocol_params.pvt_committee_no_confidence == float(
        koios_protocol_parameters[0]["pvt_committee_no_confidence"]
    )
    assert protocol_params.pvt_hard_fork_initiation == float(
        koios_protocol_parameters[0]["pvt_hard_fork_initiation"]
    )
    assert protocol_params.dvt_motion_no_confidence == float(
        koios_protocol_parameters[0]["dvt_motion_no_confidence"]
    )
    assert protocol_params.dvt_committee_normal == float(
        koios_protocol_parameters[0]["dvt_committee_normal"]
    )
    assert protocol_params.dvt_committee_no_confidence == float(
        koios_protocol_parameters[0]["dvt_committee_no_confidence"]
    )
    assert protocol_params.dvt_update_to_constitution == float(
        koios_protocol_parameters[0]["dvt_update_to_constitution"]
    )
    assert protocol_params.dvt_hard_fork_initiation == float(
        koios_protocol_parameters[0]["dvt_hard_fork_initiation"]
    )
    assert protocol_params.dvt_p_p_network_group == float(
        koios_protocol_parameters[0]["dvt_p_p_network_group"]
    )
    assert protocol_params.dvt_p_p_economic_group == float(
        koios_protocol_parameters[0]["dvt_p_p_economic_group"]
    )
    assert protocol_params.dvt_p_p_technical_group == float(
        koios_protocol_parameters[0]["dvt_p_p_technical_group"]
    )
    assert protocol_params.dvt_p_p_gov_group == float(
        koios_protocol_parameters[0]["dvt_p_p_gov_group"]
    )
    assert protocol_params.dvt_treasury_withdrawal == float(
        koios_protocol_parameters[0]["dvt_treasury_withdrawal"]
    )
    assert protocol_params.committee_min_size == int(
        koios_protocol_parameters[0]["committee_min_size"]
    )
    assert protocol_params.committee_max_term_length == int(
        koios_protocol_parameters[0]["committee_max_term_length"]
    )
    assert protocol_params.gov_action_lifetime == int(
        koios_protocol_parameters[0]["gov_action_lifetime"]
    )
    assert protocol_params.gov_action_deposit == int(
        koios_protocol_parameters[0]["gov_action_deposit"]
    )
    assert protocol_params.d_rep_deposit == int(
        koios_protocol_parameters[0]["drep_deposit"]
    )
    assert protocol_params.d_rep_activity == int(
        koios_protocol_parameters[0]["drep_activity"]
    )
    assert protocol_params.pvt_pp_security_group == float(
        koios_protocol_parameters[0]["pvtpp_security_group"]
    )
    assert protocol_params.min_fee_ref_script_cost_per_byte == int(
        koios_protocol_parameters[0]["min_fee_reference_scripts"]
    )


def test_from_json_ogmios(ogmios_protocol_parameters):
    protocol_params = ProtocolParameters.from_json(ogmios_protocol_parameters)
    assert protocol_params.collateral_percent == int(
        ogmios_protocol_parameters["collateralPercentage"]
    )
    assert protocol_params.committee_max_term_length == int(
        ogmios_protocol_parameters["constitutionalCommitteeMaxTermLength"]
    )
    assert protocol_params.committee_min_size == int(
        ogmios_protocol_parameters["constitutionalCommitteeMinSize"]
    )
    assert protocol_params.d_rep_deposit == int(
        ogmios_protocol_parameters["delegateRepresentativeDeposit"]["ada"]["lovelace"]
    )
    assert protocol_params.d_rep_activity == int(
        ogmios_protocol_parameters["delegateRepresentativeMaxIdleTime"]
    )
    assert protocol_params.dvt_committee_normal == float(
        Fraction(
            ogmios_protocol_parameters["delegateRepresentativeVotingThresholds"][
                "constitutionalCommittee"
            ]["default"]
        )
    )
    assert protocol_params.dvt_committee_no_confidence == float(
        Fraction(
            ogmios_protocol_parameters["delegateRepresentativeVotingThresholds"][
                "constitutionalCommittee"
            ]["stateOfNoConfidence"]
        )
    )
    assert protocol_params.dvt_motion_no_confidence == float(
        Fraction(
            ogmios_protocol_parameters["delegateRepresentativeVotingThresholds"][
                "noConfidence"
            ]
        )
    )
    assert protocol_params.dvt_update_to_constitution == float(
        Fraction(
            ogmios_protocol_parameters["delegateRepresentativeVotingThresholds"][
                "constitution"
            ]
        )
    )
    assert protocol_params.dvt_hard_fork_initiation == float(
        Fraction(
            ogmios_protocol_parameters["delegateRepresentativeVotingThresholds"][
                "hardForkInitiation"
            ]
        )
    )
    assert protocol_params.dvt_p_p_network_group == float(
        Fraction(
            ogmios_protocol_parameters["delegateRepresentativeVotingThresholds"][
                "protocolParametersUpdate"
            ]["network"]
        )
    )
    assert protocol_params.dvt_p_p_economic_group == float(
        Fraction(
            ogmios_protocol_parameters["delegateRepresentativeVotingThresholds"][
                "protocolParametersUpdate"
            ]["economic"]
        )
    )
    assert protocol_params.dvt_p_p_technical_group == float(
        Fraction(
            ogmios_protocol_parameters["delegateRepresentativeVotingThresholds"][
                "protocolParametersUpdate"
            ]["technical"]
        )
    )
    assert protocol_params.dvt_p_p_gov_group == float(
        Fraction(
            ogmios_protocol_parameters["delegateRepresentativeVotingThresholds"][
                "protocolParametersUpdate"
            ]["governance"]
        )
    )
    assert protocol_params.dvt_treasury_withdrawal == float(
        Fraction(
            ogmios_protocol_parameters["delegateRepresentativeVotingThresholds"][
                "treasuryWithdrawals"
            ]
        )
    )
    assert protocol_params.pool_target_num == int(
        ogmios_protocol_parameters["desiredNumberOfStakePools"]
    )
    assert protocol_params.gov_action_deposit == int(
        ogmios_protocol_parameters["governanceActionDeposit"]["ada"]["lovelace"]
    )
    assert protocol_params.gov_action_lifetime == int(
        ogmios_protocol_parameters["governanceActionLifetime"]
    )
    assert protocol_params.max_block_size == int(
        ogmios_protocol_parameters["maxBlockBodySize"]["bytes"]
    )
    assert protocol_params.max_block_header_size == int(
        ogmios_protocol_parameters["maxBlockHeaderSize"]["bytes"]
    )
    assert protocol_params.max_collateral_inputs == int(
        ogmios_protocol_parameters["maxCollateralInputs"]
    )
    assert protocol_params.max_block_ex_mem == int(
        ogmios_protocol_parameters["maxExecutionUnitsPerBlock"]["memory"]
    )
    assert protocol_params.max_block_ex_steps == int(
        ogmios_protocol_parameters["maxExecutionUnitsPerBlock"]["cpu"]
    )
    assert protocol_params.max_tx_ex_mem == int(
        ogmios_protocol_parameters["maxExecutionUnitsPerTransaction"]["memory"]
    )
    assert protocol_params.max_tx_ex_steps == int(
        ogmios_protocol_parameters["maxExecutionUnitsPerTransaction"]["cpu"]
    )
    assert protocol_params.max_reference_scripts_size == int(
        ogmios_protocol_parameters["maxReferenceScriptsSize"]["bytes"]
    )
    assert protocol_params.max_tx_size == int(
        ogmios_protocol_parameters["maxTransactionSize"]["bytes"]
    )
    assert protocol_params.max_val_size == int(
        ogmios_protocol_parameters["maxValueSize"]["bytes"]
    )
    assert protocol_params.min_fee_coefficient == int(
        ogmios_protocol_parameters["minFeeCoefficient"]
    )
    assert protocol_params.min_fee_constant == int(
        ogmios_protocol_parameters["minFeeConstant"]["ada"]["lovelace"]
    )
    assert protocol_params.min_fee_ref_script_cost_per_byte == int(
        ogmios_protocol_parameters["minFeeReferenceScripts"]["base"]
    )
    assert protocol_params.min_pool_cost == int(
        ogmios_protocol_parameters["minStakePoolCost"]["ada"]["lovelace"]
    )
    assert protocol_params.min_utxo_value == int(
        ogmios_protocol_parameters["minUtxoDepositCoefficient"]
    )
    assert protocol_params.min_utxo_deposit_constant == int(
        ogmios_protocol_parameters["minUtxoDepositConstant"]["ada"]["lovelace"]
    )
    assert protocol_params.monetary_expansion == float(
        Fraction(ogmios_protocol_parameters["monetaryExpansion"])
    )
    assert (
        protocol_params.cost_models.plutus_v1
        == ogmios_protocol_parameters["plutusCostModels"]["plutus:v1"]
    )
    assert (
        protocol_params.cost_models.plutus_v2
        == ogmios_protocol_parameters["plutusCostModels"]["plutus:v2"]
    )
    assert (
        protocol_params.cost_models.plutus_v3
        == ogmios_protocol_parameters["plutusCostModels"]["plutus:v3"]
    )
    assert protocol_params.execution_unit_prices.price_memory == float(
        Fraction(ogmios_protocol_parameters["scriptExecutionPrices"]["memory"])
    )
    assert protocol_params.execution_unit_prices.price_steps == float(
        Fraction(ogmios_protocol_parameters["scriptExecutionPrices"]["cpu"])
    )
    assert protocol_params.key_deposit == int(
        ogmios_protocol_parameters["stakeCredentialDeposit"]["ada"]["lovelace"]
    )
    assert protocol_params.pool_deposit == int(
        ogmios_protocol_parameters["stakePoolDeposit"]["ada"]["lovelace"]
    )
    assert protocol_params.pool_influence == float(
        Fraction(ogmios_protocol_parameters["stakePoolPledgeInfluence"])
    )
    assert protocol_params.pool_retire_max_epoch == int(
        ogmios_protocol_parameters["stakePoolRetirementEpochBound"]
    )
    assert protocol_params.pvt_motion_no_confidence == float(
        Fraction(
            ogmios_protocol_parameters["stakePoolVotingThresholds"]["noConfidence"]
        )
    )
    assert protocol_params.pvt_committee_normal == float(
        Fraction(
            ogmios_protocol_parameters["stakePoolVotingThresholds"][
                "constitutionalCommittee"
            ]["default"]
        )
    )
    assert protocol_params.pvt_committee_no_confidence == float(
        Fraction(
            ogmios_protocol_parameters["stakePoolVotingThresholds"][
                "constitutionalCommittee"
            ]["stateOfNoConfidence"]
        )
    )
    assert protocol_params.pvt_hard_fork_initiation == float(
        Fraction(
            ogmios_protocol_parameters["stakePoolVotingThresholds"][
                "hardForkInitiation"
            ]
        )
    )
    assert protocol_params.treasury_expansion == float(
        Fraction(ogmios_protocol_parameters["treasuryExpansion"])
    )
    assert protocol_params.protocol_major_version == int(
        ogmios_protocol_parameters["version"]["major"]
    )
    assert protocol_params.protocol_minor_version == int(
        ogmios_protocol_parameters["version"]["minor"]
    )


def test_from_json_cli(cli_protocol_parameters_json):
    protocol_params = ProtocolParameters.from_json(cli_protocol_parameters_json)
    assert protocol_params.price_mem == float(
        cli_protocol_parameters_json["executionUnitPrices"]["priceMemory"]
    )
    assert protocol_params.price_step == float(
        cli_protocol_parameters_json["executionUnitPrices"]["priceSteps"]
    )
    assert protocol_params.max_tx_ex_mem == int(
        cli_protocol_parameters_json["maxTxExecutionUnits"]["memory"]
    )
    assert protocol_params.max_tx_ex_steps == int(
        cli_protocol_parameters_json["maxTxExecutionUnits"]["steps"]
    )
    assert protocol_params.max_block_ex_mem == int(
        cli_protocol_parameters_json["maxBlockExecutionUnits"]["memory"]
    )
    assert protocol_params.max_block_ex_steps == int(
        cli_protocol_parameters_json["maxBlockExecutionUnits"]["steps"]
    )
    assert protocol_params.max_val_size == int(
        cli_protocol_parameters_json["maxValueSize"]
    )
    assert protocol_params.collateral_percent == int(
        cli_protocol_parameters_json["collateralPercentage"]
    )
    assert protocol_params.max_collateral_inputs == int(
        cli_protocol_parameters_json["maxCollateralInputs"]
    )
    assert protocol_params.coins_per_utxo_byte == int(
        cli_protocol_parameters_json["coinsPerUtxoByte"]
    )
    assert protocol_params.pvt_motion_no_confidence == float(
        cli_protocol_parameters_json["poolVotingThresholds"]["motionNoConfidence"]
    )
    assert protocol_params.pvt_committee_normal == float(
        cli_protocol_parameters_json["poolVotingThresholds"]["committeeNormal"]
    )
    assert protocol_params.pvt_committee_no_confidence == float(
        cli_protocol_parameters_json["poolVotingThresholds"]["committeeNoConfidence"]
    )
    assert protocol_params.pvt_hard_fork_initiation == float(
        cli_protocol_parameters_json["poolVotingThresholds"]["hardForkInitiation"]
    )
    assert protocol_params.pvt_pp_security_group == float(
        cli_protocol_parameters_json["poolVotingThresholds"]["ppSecurityGroup"]
    )
    assert protocol_params.dvt_motion_no_confidence == float(
        cli_protocol_parameters_json["dRepVotingThresholds"]["motionNoConfidence"]
    )
    assert protocol_params.dvt_committee_normal == float(
        cli_protocol_parameters_json["dRepVotingThresholds"]["committeeNormal"]
    )
    assert protocol_params.dvt_committee_no_confidence == float(
        cli_protocol_parameters_json["dRepVotingThresholds"]["committeeNoConfidence"]
    )
    assert protocol_params.dvt_update_to_constitution == float(
        cli_protocol_parameters_json["dRepVotingThresholds"]["updateToConstitution"]
    )
    assert protocol_params.dvt_hard_fork_initiation == float(
        cli_protocol_parameters_json["dRepVotingThresholds"]["hardForkInitiation"]
    )
    assert protocol_params.dvt_p_p_network_group == float(
        cli_protocol_parameters_json["dRepVotingThresholds"]["ppNetworkGroup"]
    )
    assert protocol_params.dvt_p_p_economic_group == float(
        cli_protocol_parameters_json["dRepVotingThresholds"]["ppEconomicGroup"]
    )
    assert protocol_params.dvt_p_p_technical_group == float(
        cli_protocol_parameters_json["dRepVotingThresholds"]["ppTechnicalGroup"]
    )
    assert protocol_params.dvt_p_p_gov_group == float(
        cli_protocol_parameters_json["dRepVotingThresholds"]["ppGovGroup"]
    )
    assert protocol_params.dvt_treasury_withdrawal == float(
        cli_protocol_parameters_json["dRepVotingThresholds"]["treasuryWithdrawal"]
    )
    assert protocol_params.committee_min_size == int(
        cli_protocol_parameters_json["committeeMinSize"]
    )
    assert protocol_params.committee_max_term_length == int(
        cli_protocol_parameters_json["committeeMaxTermLength"]
    )
    assert protocol_params.gov_action_lifetime == int(
        cli_protocol_parameters_json["govActionLifetime"]
    )
    assert protocol_params.gov_action_deposit == int(
        cli_protocol_parameters_json["govActionDeposit"]
    )
    assert protocol_params.d_rep_deposit == int(
        cli_protocol_parameters_json["dRepDeposit"]
    )
    assert protocol_params.d_rep_activity == int(
        cli_protocol_parameters_json["dRepActivity"]
    )
    assert protocol_params.min_fee_ref_script_cost_per_byte == int(
        cli_protocol_parameters_json["minFeeRefScriptCostPerByte"]
    )


def test_to_dict(cli_protocol_parameters_json):
    protocol_params = ProtocolParameters.from_json(cli_protocol_parameters_json)
    result = protocol_params.to_dict()
    assert isinstance(result, dict)


def test_to_json(cli_protocol_parameters_json):
    protocol_params = ProtocolParameters.from_json(cli_protocol_parameters_json)
    result = protocol_params.to_json()
    assert isinstance(result, str)


def test_cost_model_to_pycardano_keys_a_list_by_position():
    costs = cost_model_to_pycardano([10, 20, 30])

    assert list(costs.items()) == [("0", 10), ("1", 20), ("2", 30)]


def test_cost_model_to_pycardano_keys_sort_into_ledger_order():
    """CostModels sorts keys for Plutus V1, so positional keys must be fixed width."""
    model = list(range(350))

    costs = cost_model_to_pycardano(model)

    assert [costs[key] for key in sorted(costs)] == model
    assert list(costs.values()) == model


def test_cost_model_to_pycardano_keeps_dict_order():
    costs = cost_model_to_pycardano({"addInteger-cpu": 1, "addInteger-mem": 2})

    assert list(costs.values()) == [1, 2]


def test_cost_model_to_pycardano_without_a_model():
    assert cost_model_to_pycardano(None) is None


def test_to_pycardano_cost_models_are_indexable(cli_protocol_parameters_json):
    """pycardano reads each language's costs as a mapping, not as a bare list."""
    protocol_params = ProtocolParameters.from_json(cli_protocol_parameters_json)

    cost_models = protocol_params.to_pycardano().cost_models

    assert set(cost_models) <= {"PlutusV1", "PlutusV2", "PlutusV3"}
    for costs in cost_models.values():
        assert isinstance(costs, dict)
        assert [costs[key] for key in sorted(costs)] == list(costs.values())


def test_to_pycardano_normalises_language_names():
    protocol_params = ProtocolParameters(cost_models={"plutus:v3": [1, 2, 3]})

    cost_models = protocol_params.to_pycardano().cost_models

    assert list(cost_models) == ["PlutusV3"]
    assert list(cost_models["PlutusV3"].values()) == [1, 2, 3]
