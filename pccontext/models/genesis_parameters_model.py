from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, Optional, Type, Union

from pycardano import GenesisParameters as PyCardanoGenesisParameters

from pccontext.exceptions import CardanoModelError
from pccontext.models import BaseModel

__all__ = ["GenesisParameters"]


@dataclass(frozen=True)
class GenesisParameters(BaseModel, PyCardanoGenesisParameters):
    """
    Genesis parameters dataclass
    """

    alonzo_genesis: Optional[Dict[str, Any]] = field(
        default=None,
        metadata={"aliases": ["alonzo_genesis", "alonzoGenesis", "alonzogenesis"]},
    )
    byron_genesis: Optional[Dict[str, Any]] = field(
        default=None,
        metadata={"aliases": ["byron_genesis", "byronGenesis", "byrongenesis"]},
    )
    conway_genesis: Optional[Dict[str, Any]] = field(
        default=None,
        metadata={"aliases": ["conway_genesis", "conwayGenesis", "conwaygenesis"]},
    )
    shelley_genesis: Optional[Dict[str, Any]] = field(
        default=None,
        metadata={"aliases": ["shelley_genesis", "shelleyGenesis", "shelleygenesis"]},
    )

    era: Optional[str] = field(default="conway", metadata={"aliases": ["era"]})

    active_slots_coefficient: Optional[Union[Fraction, float]] = field(
        default=None,
        metadata={
            "aliases": [
                "active_slots_coefficient",
                "activeSlotsCoeff",
                "activeslotcoeff",
            ]
        },
    )
    epoch_length: Optional[int] = field(
        default=None,
        metadata={"aliases": ["epoch_length", "epochLength", "epochlength"]},
    )
    gen_delegs: Optional[Dict[str, Any]] = field(
        default=None,
        metadata={"aliases": ["gen_delegs", "genDelegs"]},
    )
    initial_funds: Optional[Dict[str, Any]] = field(
        default=None,
        metadata={"aliases": ["initial_funds", "initialFunds"]},
    )
    max_kes_evolutions: Optional[int] = field(
        default=None,
        metadata={"aliases": ["max_kes_evolutions", "maxKESEvolutions", "maxkesrevolutions"]},
    )
    max_lovelace_supply: Optional[int] = field(
        default=None,
        metadata={"aliases": ["max_lovelace_supply", "maxLovelaceSupply", "maxlovelacesupply"]},
    )
    network_id: Optional[str] = field(default=None, metadata={"aliases": ["network_id", "networkId", "networkid"]})
    network_magic: Optional[int] = field(
        default=None,
        metadata={"aliases": ["network_magic", "networkMagic", "networkmagic"]},
    )
    protocol_params: Optional[Dict[str, Any]] = field(
        default=None,
        metadata={"aliases": ["protocol_params", "protocolParams"]},
    )
    security_param: Optional[int] = field(
        default=None,
        metadata={"aliases": ["security_param", "securityParam", "securityparam"]},
    )
    slot_length: Optional[Union[int, float]] = field(
        default=None, metadata={"aliases": ["slot_length", "slotLength", "slotlength"]}
    )
    slots_per_kes_period: Optional[int] = field(
        default=None,
        metadata={
            "aliases": [
                "slots_per_kes_period",
                "slotsPerKESPeriod",
                "slotsperkesperiod",
            ]
        },
    )
    staking: Optional[Dict[str, Any]] = field(
        default=None,
        metadata={"aliases": ["staking"]},
    )
    system_start: Optional[Union[int, datetime]] = field(
        default=None,
        metadata={"aliases": ["system_start", "systemStart", "systemstart"]},
    )
    update_quorum: Optional[int] = field(
        default=None,
        metadata={"aliases": ["update_quorum", "updateQuorum", "updatequorum"]},
    )

    @classmethod
    def property_from_dict(
        cls: Type[GenesisParameters],
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
        return value

    @staticmethod
    def from_config_file(config_file: Path) -> GenesisParameters:
        """
        Create a GenesisParameters object from a config file
        :param config_file: Path to the config file
        :return: GenesisParameters object
        """
        if not config_file.exists() or not config_file.is_file():
            raise CardanoModelError(f"Cardano config file not found: {config_file}")
        with open(config_file, encoding="utf-8") as file:
            config_json = json.load(file)
            alonzo_genesis_file = config_file.parent / config_json["AlonzoGenesisFile"]
            byron_genesis_file = config_file.parent / config_json["ByronGenesisFile"]
            conway_genesis_file = config_file.parent / config_json["ConwayGenesisFile"]
            shelley_genesis_file = config_file.parent / config_json["ShelleyGenesisFile"]

        if not alonzo_genesis_file.exists() or not alonzo_genesis_file.is_file():
            raise CardanoModelError(f"Alonzo Genesis file not found: {alonzo_genesis_file}")
        if not byron_genesis_file.exists() or not byron_genesis_file.is_file():
            raise CardanoModelError(f"Byron Genesis file not found: {byron_genesis_file}")
        if not conway_genesis_file.exists() or not conway_genesis_file.is_file():
            raise CardanoModelError(f"Conway Genesis file not found: {conway_genesis_file}")
        if not shelley_genesis_file.exists() or not shelley_genesis_file.is_file():
            raise CardanoModelError(f"Shelley Genesis file not found: {shelley_genesis_file}")

        with open(alonzo_genesis_file, encoding="utf-8") as alonzo_file:
            alonzo_json = json.load(alonzo_file)
        with open(byron_genesis_file, encoding="utf-8") as byron_file:
            byron_json = json.load(byron_file)
        with open(conway_genesis_file, encoding="utf-8") as conway_file:
            conway_json = json.load(conway_file)
        with open(shelley_genesis_file, encoding="utf-8") as shelley_file:
            shelley_json = json.load(shelley_file)

        return GenesisParameters.from_genesis_files(
            alonzo_genesis=alonzo_json,
            byron_genesis=byron_json,
            conway_genesis=conway_json,
            shelley_genesis=shelley_json,
        )

    @staticmethod
    def from_genesis_files(
        alonzo_genesis: Dict[str, Any],
        byron_genesis: Dict[str, Any],
        conway_genesis: Dict[str, Any],
        shelley_genesis: Dict[str, Any],
    ) -> GenesisParameters:
        """
        Create a GenesisParameters object from genesis files
        :param alonzo_genesis: Alonzo genesis file path
        :param byron_genesis: Byron genesis file
        :param conway_genesis: Conway genesis file path
        :param shelley_genesis: Shelley genesis file path
        :return: GenesisParameters object
        """
        genesis = GenesisParameters.from_json(shelley_genesis)
        return GenesisParameters(
            alonzo_genesis=alonzo_genesis,
            byron_genesis=byron_genesis,
            conway_genesis=conway_genesis,
            shelley_genesis=shelley_genesis,
            era=genesis.era,
            active_slots_coefficient=genesis.active_slots_coefficient,
            epoch_length=genesis.epoch_length,
            gen_delegs=genesis.gen_delegs,
            initial_funds=genesis.initial_funds,
            max_kes_evolutions=genesis.max_kes_evolutions,
            max_lovelace_supply=genesis.max_lovelace_supply,
            network_id=genesis.network_id,
            network_magic=genesis.network_magic,
            protocol_params=genesis.protocol_params,
            security_param=genesis.security_param,
            slot_length=genesis.slot_length,
            slots_per_kes_period=genesis.slots_per_kes_period,
            staking=genesis.staking,
            system_start=genesis.system_start,
            update_quorum=genesis.update_quorum,
        )

    def to_pycardano(self) -> PyCardanoGenesisParameters:
        """
        Convert GenesisParameters to PyCardanoGenesisParameters
        :return: PyCardanoGenesisParameters
        """
        # pycardano declares every field required, but genesis values a backend does not
        # report stay None; pycardano accepts that, so pass the values through as they are.
        fields: Dict[str, Any] = dict(
            active_slots_coefficient=(
                Fraction(self.active_slots_coefficient) if self.active_slots_coefficient else None
            ),
            epoch_length=self.epoch_length,
            max_kes_evolutions=self.max_kes_evolutions,
            max_lovelace_supply=self.max_lovelace_supply,
            network_magic=self.network_magic,
            security_param=self.security_param,
            slot_length=self.slot_length,
            slots_per_kes_period=self.slots_per_kes_period,
            system_start=(
                int(self.system_start.timestamp()) if isinstance(self.system_start, datetime) else self.system_start
            ),
            update_quorum=self.update_quorum,
        )
        return PyCardanoGenesisParameters(**fields)
