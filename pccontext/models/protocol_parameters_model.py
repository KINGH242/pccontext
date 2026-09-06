from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, Union

from pycardano import ALONZO_COINS_PER_UTXO_WORD
from pycardano import ProtocolParameters as PyCardanoProtocolParameters

from pccontext.models import BaseModel
from pccontext.utils import dump_json_file

__all__ = [
    "CostModels",
    "DRepVotingThresholds",
    "ExecutionUnitPrices",
    "MaxExecutionUnits",
    "PoolVotingThresholds",
    "ProtocolVersion",
    "ProtocolParameters",
]


@dataclass(frozen=True)
class CostModels(BaseModel):
    plutus_v1: Optional[Union[Dict[Union[str, int], int], List[int]]] = field(
        default=None, metadata={"aliases": ["plutus_v1", "PlutusV1", "plutus:v1"]}
    )
    plutus_v2: Optional[Union[Dict[Union[str, int], int], List[int]]] = field(
        default=None, metadata={"aliases": ["plutus_v2", "PlutusV2", "plutus:v2"]}
    )
    plutus_v3: Optional[Union[Dict[Union[str, int], int], List[int]]] = field(
        default=None, metadata={"aliases": ["plutus_v3", "PlutusV3", "plutus:v3"]}
    )

    def to_dict(
        self,
    ) -> Dict[str, Optional[Union[Dict[Union[str, int], int], List[int]]]]:
        """
        Serialize the cost models
        :return: The serialized cost models
        """
        return {
            "PlutusV1": (
                list(self.plutus_v1.values())
                if isinstance(self.plutus_v1, dict)
                else self.plutus_v1
            ),
            "PlutusV2": (
                list(self.plutus_v2.values())
                if isinstance(self.plutus_v2, dict)
                else self.plutus_v2
            ),
            "PlutusV3": (
                list(self.plutus_v3.values())
                if isinstance(self.plutus_v3, dict)
                else self.plutus_v3
            ),
        }


#: Language names cost models arrive under, mapped onto the ``PlutusV<n>`` keys pycardano's
#: :class:`~pycardano.txbuilder.TransactionBuilder` looks them up by.
PLUTUS_LANGUAGE_ALIASES = {
    "plutus_v1": "PlutusV1",
    "plutusv1": "PlutusV1",
    "plutus:v1": "PlutusV1",
    "plutus_v2": "PlutusV2",
    "plutusv2": "PlutusV2",
    "plutus:v2": "PlutusV2",
    "plutus_v3": "PlutusV3",
    "plutusv3": "PlutusV3",
    "plutus:v3": "PlutusV3",
}


def cost_model_to_pycardano(
    cost_model: Optional[Union[Dict[Union[str, int], int], List[int]]],
) -> Optional[Dict[str, int]]:
    """Put one language's cost model into the shape pycardano serializes.

    :class:`pycardano.plutus.CostModels` emits only the *values* of each language's model, in
    key order -- sorted for Plutus V1, insertion order otherwise. Chain backends hand us the
    costs as a bare list in ledger order, so the keys have to be positional and fixed width;
    that way sorting them lexicographically and iterating them give the same, correct order.

    :param cost_model: A language's costs, either as an ordered list or as a name-keyed dict.
    :return: The costs keyed by zero-padded position, or ``None`` if there were none.
    """
    if cost_model is None:
        return None
    costs = (
        list(cost_model.values()) if isinstance(cost_model, dict) else list(cost_model)
    )
    width = len(str(len(costs) - 1)) if costs else 1
    return {str(position).zfill(width): cost for position, cost in enumerate(costs)}


@dataclass(frozen=True)
class DRepVotingThresholds(BaseModel):
    committee_no_confidence: Optional[float] = field(
        default=None,
        metadata={"aliases": ["committee_no_confidence", "committeeNoConfidence"]},
    )
    committee_normal: Optional[float] = field(
        default=None, metadata={"aliases": ["committee_normal", "committeeNormal"]}
    )
    hard_fork_initiation: Optional[float] = field(
        default=None,
        metadata={"aliases": ["hard_fork_initiation", "hardForkInitiation"]},
    )
    motion_no_confidence: Optional[float] = field(
        default=None,
        metadata={
            "aliases": ["motion_no_confidence", "motionNoConfidence", "noConfidence"]
        },
    )
    pp_economic_group: Optional[float] = field(
        default=None, metadata={"aliases": ["pp_economic_group", "ppEconomicGroup"]}
    )
    pp_gov_group: Optional[float] = field(
        default=None, metadata={"aliases": ["pp_gov_group", "ppGovGroup"]}
    )
    pp_network_group: Optional[float] = field(
        default=None, metadata={"aliases": ["pp_network_group", "ppNetworkGroup"]}
    )
    pp_technical_group: Optional[float] = field(
        default=None, metadata={"aliases": ["pp_technical_group", "ppTechnicalGroup"]}
    )
    treasury_withdrawal: Optional[float] = field(
        default=None,
        metadata={
            "aliases": [
                "treasury_withdrawal",
                "treasuryWithdrawal",
                "treasuryWithdrawals",
            ]
        },
    )
    update_to_constitution: Optional[float] = field(
        default=None,
        metadata={
            "aliases": [
                "update_to_constitution",
                "updateToConstitution",
                "constitution",
            ]
        },
    )

    @classmethod
    def clean_unwanted_fields(cls, init_args: Dict):
        unwanted_fields = ["constitutionalCommittee", "protocolParametersUpdate"]
        for unwanted_field in unwanted_fields:
            init_args.pop(unwanted_field, None)

    @classmethod
    def property_from_dict(
        cls: Type[DRepVotingThresholds],
        value: Dict,
        key: str,
        field_name: str,
        init_args: Dict,
    ):
        """
        Parse the property from a dictionary
        :param value: The value
        :param key: The key
        :param field_name: The field name
        :param init_args: The initialization arguments
        :return: The property
        """
        if key == "constitutionalCommittee":
            init_args["committee_normal"] = float(Fraction(value["default"]))
            init_args["committee_no_confidence"] = float(
                Fraction(value["stateOfNoConfidence"])
            )
        elif key == "protocolParametersUpdate":
            init_args["pp_economic_group"] = float(Fraction(value["economic"]))
            init_args["pp_gov_group"] = float(Fraction(value["governance"]))
            init_args["pp_network_group"] = float(Fraction(value["network"]))
            init_args["pp_technical_group"] = float(Fraction(value["technical"]))


@dataclass(frozen=True)
class ExecutionUnitPrices(BaseModel):
    price_memory: Optional[float] = field(
        default=None, metadata={"aliases": ["price_memory", "priceMemory", "memory"]}
    )
    price_steps: Optional[float] = field(
        default=None, metadata={"aliases": ["price_steps", "priceSteps", "cpu"]}
    )


@dataclass(frozen=True)
class MaxExecutionUnits(BaseModel):
    memory: Optional[int] = field(
        default=None, metadata={"aliases": ["memory", "exUnitsMem"]}
    )
    steps: Optional[int] = field(
        default=None, metadata={"aliases": ["steps", "exUnitsSteps", "cpu"]}
    )


@dataclass(frozen=True)
class PoolVotingThresholds(BaseModel):
    committee_no_confidence: Optional[float] = field(
        default=None,
        metadata={"aliases": ["committee_no_confidence", "committeeNoConfidence"]},
    )
    committee_normal: Optional[float] = field(
        default=None, metadata={"aliases": ["committee_normal", "committeeNormal"]}
    )
    hard_fork_initiation: Optional[float] = field(
        default=None,
        metadata={"aliases": ["hard_fork_initiation", "hardForkInitiation"]},
    )
    motion_no_confidence: Optional[float] = field(
        default=None,
        metadata={
            "aliases": ["motion_no_confidence", "motionNoConfidence", "noConfidence"]
        },
    )
    pp_security_group: Optional[float] = field(
        default=None, metadata={"aliases": ["pp_security_group", "ppSecurityGroup"]}
    )

    @classmethod
    def clean_unwanted_fields(cls, init_args: Dict):
        unwanted_fields = ["constitutionalCommittee"]
        for unwanted_field in unwanted_fields:
            init_args.pop(unwanted_field, None)

    @classmethod
    def property_from_dict(
        cls: Type[PoolVotingThresholds],
        value: Dict,
        key: str,
        field_name: str,
        init_args: Dict,
    ):
        """
        Parse the property from a dictionary
        :param value: The value
        :param key: The key
        :param field_name: The field name
        :param init_args: The initialization arguments
        :return: The property
        """
        if key == "constitutionalCommittee":
            init_args["committee_normal"] = float(Fraction(value["default"]))
            init_args["committee_no_confidence"] = float(
                Fraction(value["stateOfNoConfidence"])
            )


@dataclass(frozen=True)
class ProtocolVersion(BaseModel):
    major: Optional[int] = None
    minor: Optional[int] = None


@dataclass(frozen=True)
class ProtocolParameters(BaseModel, PyCardanoProtocolParameters):
    collateral_percent: Optional[int] = field(
        default=None,
        metadata={"aliases": ["collateral_percent", "collateralPercentage"]},
    )
    committee_max_term_length: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "committee_max_term_length",
                "committeeMaxTermLength",
                "constitutionalCommitteeMaxTermLength",
            ]
        },
    )
    committee_min_size: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "committee_min_size",
                "committeeMinSize",
                "constitutionalCommitteeMinSize",
            ]
        },
    )
    cost_models: Optional[
        Union[CostModels, Dict[str, Union[Dict[Union[str, int], int], list]]]
    ] = field(
        default=None,
        metadata={
            "aliases": [
                "cost_models",
                "costModels",
                "plutusCostModels",
                "cost_models_raw",
            ]
        },
    )
    d_rep_activity: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "d_rep_activity",
                "drep_activity",
                "dRepActivity",
                "delegateRepresentativeMaxIdleTime",
            ]
        },
    )
    d_rep_deposit: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "d_rep_deposit",
                "drep_deposit",
                "dRepDeposit",
                "delegateRepresentativeDeposit",
            ]
        },
    )
    d_rep_voting_thresholds: Optional[DRepVotingThresholds] = field(
        default=None,
        metadata={
            "aliases": [
                "d_rep_voting_thresholds",
                "dRepVotingThresholds",
                "delegateRepresentativeVotingThresholds",
            ]
        },
    )
    dvt_motion_no_confidence: Optional[float] = field(
        default=None,
        metadata={"aliases": ["dvt_motion_no_confidence", "dvtMotionNoConfidence"]},
    )
    dvt_committee_normal: Optional[float] = field(
        default=None,
        metadata={"aliases": ["dvt_committee_normal", "dvtCommitteeNormal"]},
    )
    dvt_committee_no_confidence: Optional[float] = field(
        default=None,
        metadata={
            "aliases": ["dvt_committee_no_confidence", "dvtCommitteeNoConfidence"]
        },
    )
    dvt_update_to_constitution: Optional[float] = field(
        default=None,
        metadata={"aliases": ["dvt_update_to_constitution", "dvtUpdateToConstitution"]},
    )
    dvt_hard_fork_initiation: Optional[float] = field(
        default=None,
        metadata={"aliases": ["dvt_hard_fork_initiation", "dvtHardForkInitiation"]},
    )
    dvt_p_p_network_group: Optional[float] = field(
        default=None,
        metadata={
            "aliases": [
                "dvt_p_p_network_group",
                "dvtPPNetworkGroup",
                "dvt_ppnetwork_group",
            ]
        },
    )
    dvt_p_p_economic_group: Optional[float] = field(
        default=None,
        metadata={
            "aliases": [
                "dvt_p_p_economic_group",
                "dvtPPEconomicGroup",
                "dvt_ppeconomic_group",
            ]
        },
    )
    dvt_p_p_technical_group: Optional[float] = field(
        default=None,
        metadata={
            "aliases": [
                "dvt_p_p_technical_group",
                "dvtPPTechnicalGroup",
                "dvt_pptechnical_group",
            ]
        },
    )
    dvt_p_p_gov_group: Optional[float] = field(
        default=None,
        metadata={"aliases": ["dvt_p_p_gov_group", "dvtPPGovGroup", "dvt_ppgov_group"]},
    )
    dvt_treasury_withdrawal: Optional[float] = field(
        default=None,
        metadata={"aliases": ["dvt_treasury_withdrawal", "dvtTreasuryWithdrawal"]},
    )
    execution_unit_prices: Optional[ExecutionUnitPrices] = field(
        default=None,
        metadata={
            "aliases": [
                "execution_unit_prices",
                "executionUnitPrices",
                "scriptExecutionPrices",
            ]
        },
    )
    gov_action_deposit: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "gov_action_deposit",
                "govActionDeposit",
                "governanceActionDeposit",
            ]
        },
    )
    gov_action_lifetime: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "gov_action_lifetime",
                "govActionLifetime",
                "governanceActionLifetime",
            ]
        },
    )
    max_block_size: Optional[int] = field(
        default=None, metadata={"aliases": ["max_block_size", "maxBlockBodySize"]}
    )
    max_block_execution_units: Optional[MaxExecutionUnits] = field(
        default=None,
        metadata={
            "aliases": [
                "max_block_execution_units",
                "maxBlockExecutionUnits",
                "maxExecutionUnitsPerBlock",
            ]
        },
    )
    max_block_ex_mem: Optional[int] = field(
        default=None,
        metadata={"aliases": ["max_block_ex_mem", "maxBlockExecutionUnitsMemory"]},
    )
    max_block_ex_steps: Optional[int] = field(
        default=None,
        metadata={"aliases": ["max_block_ex_steps", "maxBlockExecutionUnitsSteps"]},
    )
    max_block_header_size: Optional[int] = field(
        default=None,
        metadata={
            "aliases": ["max_block_header_size", "maxBlockHeaderSize", "max_bh_size"]
        },
    )
    max_collateral_inputs: Optional[int] = field(
        default=None,
        metadata={"aliases": ["max_collateral_inputs", "maxCollateralInputs"]},
    )
    max_reference_scripts_size: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "max_reference_scripts_size",
                "maxReferenceScriptsSize",
                "maximum_reference_scripts_size",
            ]
        },
    )
    max_tx_execution_units: Optional[MaxExecutionUnits] = field(
        default=None,
        metadata={
            "aliases": [
                "max_tx_execution_units",
                "maxTxExecutionUnits",
                "maxExecutionUnitsPerTransaction",
            ]
        },
    )
    max_tx_ex_mem: Optional[int] = field(
        default=None,
        metadata={"aliases": ["max_tx_ex_mem", "maxTxExecutionUnitsMemory"]},
    )
    max_tx_ex_steps: Optional[int] = field(
        default=None,
        metadata={"aliases": ["max_tx_ex_steps", "maxTxExecutionUnitsSteps"]},
    )
    max_tx_size: Optional[int] = field(
        default=None,
        metadata={"aliases": ["max_tx_size", "maxTxSize", "maxTransactionSize"]},
    )
    max_val_size: Optional[int] = field(
        default=None, metadata={"aliases": ["max_val_size", "maxValueSize"]}
    )
    min_fee_coefficient: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "min_fee_coefficient",
                "txFeePerByte",
                "min_fee_a",
                "minFeeCoefficient",
            ]
        },
    )
    min_fee_constant: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "min_fee_constant",
                "min_fee_b",
                "minFeeConstant",
                "min_fee_constant",
            ]
        },
    )
    min_fee_ref_script_cost_per_byte: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "min_fee_reference_scripts",
                "min_fee_ref_script_cost_per_byte",
                "minFeeRefScriptCostPerByte",
                "minFeeReferenceScripts",
            ]
        },
    )
    min_pool_cost: Optional[int] = field(
        default=None,
        metadata={"aliases": ["min_pool_cost", "minPoolCost", "minStakePoolCost"]},
    )
    min_utxo: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "min_utxo",
                "utxoCostPerByte",
                "utxoCostPerByte",
                # "coins_per_utxo_size",
                # "coins_per_utxo_word",
            ]
        },
    )
    min_utxo_deposit_constant: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "min_utxo_deposit_constant",
                "minUtxoDepositConstant",
            ]
        },
    )
    min_utxo_value: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "min_utxo_value",
                "minUTxOValue",
                "minUtxoDepositCoefficient",
                "min_utxo_deposit_coefficient",
                # "utxoCostPerByte",
                # "coins_per_utxo_size",
                # "coins_per_utxo_word",
            ]
        },
    )
    monetary_expansion: Optional[float] = field(
        default=None,
        metadata={
            "aliases": [
                "monetary_expansion",
                "monetaryExpansion",
                "rho",
                "monetary_expand_rate",
            ]
        },
    )
    pool_influence: Optional[float] = field(
        default=None,
        metadata={
            "aliases": [
                "pool_influence",
                "poolPledgeInfluence",
                "a0",
                "influence",
                "stakePoolPledgeInfluence",
            ]
        },
    )
    pool_retire_max_epoch: Optional[int] = field(
        default=18,
        metadata={
            "aliases": [
                "pool_retire_max_epoch",
                "poolRetireMaxEpoch",
                "e_max",
                "max_epoch",
                "stakePoolRetirementEpochBound",
            ]
        },
    )
    pool_voting_thresholds: Optional[PoolVotingThresholds] = field(
        default=None,
        metadata={
            "aliases": [
                "pool_voting_thresholds",
                "poolVotingThresholds",
                "stakePoolVotingThresholds",
            ]
        },
    )
    pvt_motion_no_confidence: Optional[float] = field(
        default=None,
        metadata={"aliases": ["pvt_motion_no_confidence", "pvtMotionNoConfidence"]},
    )
    pvt_committee_normal: Optional[float] = field(
        default=None,
        metadata={"aliases": ["pvt_committee_normal", "pvtCommitteeNormal"]},
    )
    pvt_committee_no_confidence: Optional[float] = field(
        default=None,
        metadata={
            "aliases": ["pvt_committee_no_confidence", "pvtCommitteeNoConfidence"]
        },
    )
    pvt_hard_fork_initiation: Optional[float] = field(
        default=None,
        metadata={"aliases": ["pvt_hard_fork_initiation", "pvtHardForkInitiation"]},
    )
    pvt_pp_security_group: Optional[float] = field(
        default=None,
        metadata={
            "aliases": [
                "pvt_pp_security_group",
                "pvtpp_security_group",
                "pvt_p_p_security_group",
                "pvtppSecurityGroup",
            ]
        },
    )
    protocol_version: Optional[ProtocolVersion] = field(
        default=None,
        metadata={"aliases": ["protocol_version", "protocolVersion", "version"]},
    )
    protocol_major_version: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "protocol_major_version",
                "protocolVersionMajor",
                "protocol_major_ver",
                "protocol_major",
            ]
        },
    )
    protocol_minor_version: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "protocol_minor_version",
                "protocolVersionMinor",
                "protocol_minor_ver",
                "protocol_minor",
            ]
        },
    )
    key_deposit: Optional[int] = field(
        default=None,
        metadata={
            "aliases": ["key_deposit", "stakeAddressDeposit", "stakeCredentialDeposit"]
        },
    )
    pool_deposit: Optional[int] = field(
        default=None, metadata={"aliases": ["pool_deposit", "stakePoolDeposit"]}
    )
    pool_target_num: Optional[int] = field(
        default=500,
        metadata={
            "aliases": [
                "pool_target_num",
                "stakePoolTargetNum",
                "n_opt",
                "optimal_pool_count",
                "desiredNumberOfStakePools",
            ]
        },
    )
    treasury_expansion: Optional[float] = field(
        default=None,
        metadata={
            "aliases": [
                "treasury_expansion",
                "treasuryCut",
                "tau",
                "treasury_growth_rate",
                "treasuryExpansion",
            ]
        },
    )
    tx_fee_fixed: Optional[int] = field(
        default=None,
        metadata={"aliases": ["tx_fee_fixed", "txFeeFixed"]},
    )
    tx_fee_per_byte: Optional[int] = field(
        default=None, metadata={"aliases": ["tx_fee_per_byte", "txFeePerByte"]}
    )
    decentralization_param: Optional[float] = field(
        default=None,
        metadata={
            "aliases": [
                "decentralization_param",
                "decentralisation_param",
                "decentralization",
                "decentralisation",
            ]
        },
    )
    extra_entropy: Optional[str] = field(
        default=None, metadata={"aliases": ["extra_entropy", "extraPraosEntropy"]}
    )
    price_mem: Optional[float] = field(
        default=None,
        metadata={"aliases": ["price_mem", "executionUnitPricesPriceMemory"]},
    )
    price_step: Optional[float] = field(
        default=None,
        metadata={"aliases": ["price_step", "executionUnitPricesPriceSteps"]},
    )
    coins_per_utxo_word: Optional[int] = field(
        default=ALONZO_COINS_PER_UTXO_WORD,
        metadata={"aliases": ["coins_per_utxo_word", "coinsPerUtxoWord"]},
    )
    coins_per_utxo_byte: Optional[int] = field(
        default=0,
        metadata={
            "aliases": [
                "coins_per_utxo_byte",
                "coinsPerUtxoByte",
                "coins_per_utxo_size",
            ]
        },
    )
    utxo_cost_per_byte: Optional[int] = field(
        default=None, metadata={"aliases": ["utxo_cost_per_byte", "utxoCostPerByte"]}
    )
    epoch: Optional[int] = field(
        default=None, metadata={"aliases": ["epoch", "epoch_no", "epochNo"]}
    )
    nonce: Optional[str] = field(default=None, metadata={"aliases": ["nonce"]})
    block_hash: Optional[str] = field(
        default=None, metadata={"aliases": ["block_hash"]}
    )

    def __post_init__(self):
        if self.protocol_version is None:
            object.__setattr__(
                self,
                "protocol_version",
                ProtocolVersion(
                    major=self.protocol_major_version, minor=self.protocol_minor_version
                ),
            )
        elif (
            self.protocol_major_version is None and self.protocol_minor_version is None
        ):
            object.__setattr__(
                self, "protocol_major_version", self.protocol_version.major
            )
            object.__setattr__(
                self, "protocol_minor_version", self.protocol_version.minor
            )

        if not self.execution_unit_prices:
            object.__setattr__(
                self,
                "execution_unit_prices",
                ExecutionUnitPrices(
                    price_memory=self.price_mem, price_steps=self.price_step
                ),
            )
        elif self.price_mem is None and self.price_step is None:
            object.__setattr__(
                self, "price_mem", self.execution_unit_prices.price_memory
            )
            object.__setattr__(
                self, "price_step", self.execution_unit_prices.price_steps
            )

        if not self.max_tx_execution_units:
            object.__setattr__(
                self,
                "max_tx_execution_units",
                MaxExecutionUnits(
                    memory=self.max_tx_ex_mem, steps=self.max_tx_ex_steps
                ),
            )
        elif self.max_tx_ex_mem is None and self.max_tx_ex_steps is None:
            object.__setattr__(
                self, "max_tx_ex_mem", self.max_tx_execution_units.memory
            )
            object.__setattr__(
                self, "max_tx_ex_steps", self.max_tx_execution_units.steps
            )

        if not self.max_block_execution_units:
            object.__setattr__(
                self,
                "max_block_execution_units",
                MaxExecutionUnits(
                    memory=self.max_block_ex_mem, steps=self.max_block_ex_steps
                ),
            )
        elif self.max_block_ex_mem is None and self.max_block_ex_steps is None:
            object.__setattr__(
                self, "max_block_ex_mem", self.max_block_execution_units.memory
            )
            object.__setattr__(
                self, "max_block_ex_steps", self.max_block_execution_units.steps
            )

        if self.coins_per_utxo_byte is None:
            object.__setattr__(
                self,
                "coins_per_utxo_byte",
                (self.utxo_cost_per_byte or self.coins_per_utxo_word / 8),
            )

        if self.min_fee_coefficient is None:
            object.__setattr__(
                self,
                "min_fee_coefficient",
                self.tx_fee_per_byte,
            )

        if self.min_fee_constant is None:
            object.__setattr__(
                self,
                "min_fee_constant",
                self.tx_fee_fixed,
            )

        if self.pool_voting_thresholds is None:
            object.__setattr__(
                self,
                "pool_voting_thresholds",
                PoolVotingThresholds(
                    committee_no_confidence=self.pvt_committee_no_confidence,
                    committee_normal=self.pvt_committee_normal,
                    hard_fork_initiation=self.pvt_hard_fork_initiation,
                    motion_no_confidence=self.pvt_motion_no_confidence,
                    pp_security_group=self.pvt_pp_security_group,
                ),
            )
        elif (
            self.pvt_committee_no_confidence is None
            and self.pvt_committee_normal is None
            and self.pvt_hard_fork_initiation is None
            and self.pvt_motion_no_confidence is None
            and self.pvt_pp_security_group is None
        ):
            object.__setattr__(
                self,
                "pvt_committee_no_confidence",
                self.pool_voting_thresholds.committee_no_confidence,
            )
            object.__setattr__(
                self,
                "pvt_committee_normal",
                self.pool_voting_thresholds.committee_normal,
            )
            object.__setattr__(
                self,
                "pvt_hard_fork_initiation",
                self.pool_voting_thresholds.hard_fork_initiation,
            )
            object.__setattr__(
                self,
                "pvt_motion_no_confidence",
                self.pool_voting_thresholds.motion_no_confidence,
            )
            object.__setattr__(
                self,
                "pvt_pp_security_group",
                self.pool_voting_thresholds.pp_security_group,
            )

        if self.d_rep_voting_thresholds is None:
            object.__setattr__(
                self,
                "d_rep_voting_thresholds",
                DRepVotingThresholds(
                    committee_no_confidence=self.dvt_committee_no_confidence,
                    committee_normal=self.dvt_committee_normal,
                    hard_fork_initiation=self.dvt_hard_fork_initiation,
                    motion_no_confidence=self.dvt_motion_no_confidence,
                    pp_economic_group=self.dvt_p_p_economic_group,
                    pp_gov_group=self.dvt_p_p_gov_group,
                    pp_network_group=self.dvt_p_p_network_group,
                    pp_technical_group=self.dvt_p_p_technical_group,
                    treasury_withdrawal=self.dvt_treasury_withdrawal,
                    update_to_constitution=self.dvt_update_to_constitution,
                ),
            )
        elif (
            self.dvt_committee_no_confidence is None
            and self.dvt_committee_normal is None
            and self.dvt_hard_fork_initiation is None
            and self.dvt_motion_no_confidence is None
            and self.dvt_p_p_network_group is None
            and self.dvt_p_p_economic_group is None
            and self.dvt_p_p_technical_group is None
            and self.dvt_p_p_gov_group is None
            and self.dvt_treasury_withdrawal is None
            and self.dvt_update_to_constitution is None
        ):
            object.__setattr__(
                self,
                "dvt_committee_no_confidence",
                self.d_rep_voting_thresholds.committee_no_confidence,
            )
            object.__setattr__(
                self,
                "dvt_committee_normal",
                self.d_rep_voting_thresholds.committee_normal,
            )
            object.__setattr__(
                self,
                "dvt_hard_fork_initiation",
                self.d_rep_voting_thresholds.hard_fork_initiation,
            )
            object.__setattr__(
                self,
                "dvt_motion_no_confidence",
                self.d_rep_voting_thresholds.motion_no_confidence,
            )
            object.__setattr__(
                self,
                "dvt_p_p_network_group",
                self.d_rep_voting_thresholds.pp_network_group,
            )
            object.__setattr__(
                self,
                "dvt_p_p_economic_group",
                self.d_rep_voting_thresholds.pp_economic_group,
            )
            object.__setattr__(
                self,
                "dvt_p_p_technical_group",
                self.d_rep_voting_thresholds.pp_technical_group,
            )
            object.__setattr__(
                self,
                "dvt_p_p_gov_group",
                self.d_rep_voting_thresholds.pp_gov_group,
            )
            object.__setattr__(
                self,
                "dvt_treasury_withdrawal",
                self.d_rep_voting_thresholds.treasury_withdrawal,
            )
            object.__setattr__(
                self,
                "dvt_update_to_constitution",
                self.d_rep_voting_thresholds.update_to_constitution,
            )

    @classmethod
    def property_from_dict(
        cls: Type[ProtocolParameters],
        value: Dict,
        key: str,
        field_name: str,
        init_args: Dict,
    ):
        """
        Parse the property from a dictionary
        :param value: The value
        :param key: The key
        :param field_name: The field name
        :param init_args: The initialization arguments
        :return: The property
        """
        if field_name == "cost_models":
            return CostModels.from_dict(value)
        elif field_name == "min_fee_ref_script_cost_per_byte":
            return value["base"]
        elif field_name in {
            "d_rep_deposit",
            "gov_action_deposit",
            "min_fee_constant",
            "min_pool_costs",
            "min_utxo_deposit_constant",
            "key_deposit",
            "pool_deposit",
            "min_pool_cost",
        }:
            return value["ada"]["lovelace"]
        elif field_name in {
            "max_reference_scripts_size",
            "max_block_size",
            "max_block_header_size",
            "max_tx_size",
            "max_val_size",
            "tx_fee_fixed",
        }:
            return value["bytes"]
        elif field_name == "d_rep_voting_thresholds":
            return DRepVotingThresholds.from_dict(value)
        elif field_name == "execution_unit_prices":
            return ExecutionUnitPrices.from_dict(value)
        elif field_name in {"max_block_execution_units", "max_tx_execution_units"}:
            return MaxExecutionUnits.from_dict(value)
        elif field_name == "pool_voting_thresholds":
            return PoolVotingThresholds.from_dict(value)
        elif field_name == "protocol_version":
            return ProtocolVersion.from_dict(value)

    def dump_protocol_parameters(self, params_file: Path) -> None:
        """
        Dump the protocol parameters to a json file
        :param params_file: The json file to dump the protocol parameters
        """
        cost_models: Dict = {}
        if self.cost_models:
            if isinstance(self.cost_models, CostModels):
                cost_models = self.cost_models.to_dict()
            else:
                cost_models = self.cost_models

        protocol_parameters: Dict[str, Any] = {
            "collateralPercentage": self.collateral_percent,
            "committeeMaxTermLength": self.committee_max_term_length,
            "committeeMinSize": self.committee_min_size,
            "costModels": cost_models,
            "dRepActivity": self.d_rep_activity,
            "dRepDeposit": self.d_rep_deposit,
            "dRepVotingThresholds": (
                self.d_rep_voting_thresholds.to_dict()
                if self.d_rep_voting_thresholds
                else None
            ),
            "executionUnitPrices": (
                self.execution_unit_prices.to_dict()
                if self.execution_unit_prices
                else None
            ),
            "extraPraosEntropy": self.extra_entropy or None,
            "govActionDeposit": self.gov_action_deposit,
            "govActionLifetime": self.gov_action_lifetime,
            "maxBlockBodySize": self.max_block_size,
            "maxBlockExecutionUnits": {
                "memory": (
                    self.max_block_execution_units.memory
                    if self.max_block_execution_units
                    else None
                ),
                "steps": (
                    self.max_block_execution_units.steps
                    if self.max_block_execution_units
                    else None
                ),
            },
            "maxBlockHeaderSize": self.max_block_header_size,
            "maxCollateralInputs": self.max_collateral_inputs,
            "maxTxExecutionUnits": {
                "memory": (
                    self.max_tx_execution_units.memory
                    if self.max_tx_execution_units
                    else None
                ),
                "steps": (
                    self.max_tx_execution_units.steps
                    if self.max_tx_execution_units
                    else None
                ),
            },
            "maxTxSize": self.max_tx_size,
            "maxValueSize": self.max_val_size,
            "minFeeRefScriptCostPerByte": self.min_fee_ref_script_cost_per_byte,
            "minPoolCost": self.min_pool_cost,
            "minUTxOValue": self.min_utxo_value or None,
            "monetaryExpansion": (
                float(self.monetary_expansion) if self.monetary_expansion else None
            ),
            "poolPledgeInfluence": (
                float(self.pool_influence) if self.pool_influence else None
            ),
            "poolRetireMaxEpoch": self.pool_retire_max_epoch,
            "poolVotingThresholds": (
                self.pool_voting_thresholds.to_dict()
                if self.pool_voting_thresholds
                else None
            ),
            "protocolVersion": (
                self.protocol_version.to_dict() if self.protocol_version else None
            ),
            "stakeAddressDeposit": self.key_deposit,
            "stakePoolDeposit": self.pool_deposit,
            "stakePoolTargetNum": self.pool_target_num,
            "treasuryCut": (
                float(self.treasury_expansion) if self.treasury_expansion else None
            ),
            "txFeeFixed": self.tx_fee_fixed,
            "txFeePerByte": self.tx_fee_per_byte,
            "utxoCostPerByte": self.utxo_cost_per_byte,
        }
        dump_json_file(params_file, protocol_parameters)

    def to_pycardano(self) -> PyCardanoProtocolParameters:
        """
        Convert the protocol parameters to PyCardano protocol parameters
        :return: The PyCardano protocol parameters
        """
        raw_cost_models: Dict = {}
        if self.cost_models:
            if isinstance(self.cost_models, CostModels):
                raw_cost_models = self.cost_models.to_dict()
            elif isinstance(self.cost_models, dict):
                raw_cost_models = self.cost_models

        cost_models: Dict = {}
        for language, model in raw_cost_models.items():
            costs = cost_model_to_pycardano(model)
            if costs:
                name = str(language)
                cost_models[PLUTUS_LANGUAGE_ALIASES.get(name.lower(), name)] = costs

        return PyCardanoProtocolParameters(
            min_fee_constant=self.min_fee_constant,
            min_fee_coefficient=self.min_fee_coefficient,
            max_block_size=self.max_block_size,
            max_tx_size=self.max_tx_size,
            max_block_header_size=self.max_block_header_size,
            key_deposit=self.key_deposit,
            pool_deposit=self.pool_deposit,
            pool_influence=(
                Fraction(self.pool_influence) if self.pool_influence else None
            ),
            monetary_expansion=(
                Fraction(self.monetary_expansion) if self.monetary_expansion else None
            ),
            treasury_expansion=(
                Fraction(self.treasury_expansion) if self.treasury_expansion else None
            ),
            decentralization_param=(
                Fraction(self.decentralization_param)
                if self.decentralization_param
                else None
            ),
            extra_entropy=self.extra_entropy,
            protocol_major_version=self.protocol_major_version,
            protocol_minor_version=self.protocol_minor_version,
            min_utxo=self.min_utxo,
            min_pool_cost=self.min_pool_cost,
            price_mem=Fraction(self.price_mem) if self.price_mem else None,
            price_step=Fraction(self.price_step) if self.price_step else None,
            max_tx_ex_mem=self.max_tx_ex_mem,
            max_tx_ex_steps=self.max_tx_ex_steps,
            max_block_ex_mem=self.max_block_ex_mem,
            max_block_ex_steps=self.max_block_ex_steps,
            max_val_size=self.max_val_size,
            collateral_percent=self.collateral_percent,
            max_collateral_inputs=self.max_collateral_inputs,
            coins_per_utxo_word=self.coins_per_utxo_word,
            coins_per_utxo_byte=self.coins_per_utxo_byte or self.utxo_cost_per_byte,
            cost_models=cost_models,
            maximum_reference_scripts_size=self.max_reference_scripts_size,
            min_fee_reference_scripts=self.min_fee_ref_script_cost_per_byte,
        )
