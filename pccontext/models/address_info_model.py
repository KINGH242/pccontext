from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, Union

from pycardano import (
    Address,
    Asset,
    AssetName,
    MultiAsset,
    ScriptHash,
    TransactionId,
    TransactionInput,
    TransactionOutput,
    UTxO,
    Value,
)

from pccontext.enums import AddressType
from pccontext.models import BaseModel
from pccontext.utils import check_ada_handle_format, load_file

from .stake_address_info_model import StakeAddressInfo

__all__ = ["AddressInfo"]


@dataclass(frozen=True)
class AddressInfo(BaseModel):
    """
    Address model class
    """

    address_file: Optional[Path] = field(
        default=None,
        metadata={"aliases": ["address_file", "addressFile"]},
    )
    name: Optional[str] = None
    ada_handle: Optional[str] = field(
        default=None,
        metadata={"aliases": ["ada_handle", "adaHandle"]},
    )
    address: Optional[Union[Address, str]] = None
    base16: Optional[str] = None
    encoding: Optional[str] = None
    era: Optional[str] = None
    type: Optional[AddressType] = None
    total_amount: Optional[int] = field(
        default=None,
        metadata={"aliases": ["total_amount", "totalAmount"]},
    )
    total_asset_count: Optional[int] = field(
        default=None,
        metadata={"aliases": ["total_asset_count", "totalAssetCount"]},
    )
    date: Optional[datetime] = field(
        default=datetime.now(UTC),
        metadata={"aliases": ["total_asset_count", "totalAssetCount"]},
    )
    used: Optional[bool] = False
    utxos: Optional[List[UTxO]] = field(default_factory=list)
    stake_address_info: Optional[List[StakeAddressInfo]] = field(default_factory=list)

    def __post_init__(self):
        if self.address is None and self.address_file is None and self.ada_handle is None:
            raise ValueError("Address needs an address, AdaHandle or a path to the address file")

        if self.address is not None and isinstance(self.address, str):
            object.__setattr__(
                self,
                "address",
                Address.from_primitive(self.address),
            )

        if self.address_file is not None:
            if self.address is None:
                object.__setattr__(
                    self,
                    "address",
                    Address.from_primitive(load_file(self.address_file)),
                )
            if self.name is None:
                object.__setattr__(
                    self,
                    "name",
                    self.address_file.stem,
                )
        if self.name is None:
            object.__setattr__(
                self,
                "name",
                "Unnamed Address" if self.ada_handle is None else self.ada_handle,
            )

        if self.ada_handle is not None:
            validated_handle = check_ada_handle_format(self.ada_handle)
            object.__setattr__(self, "ada_handle", validated_handle)

        if self.address is not None:
            if str(self.address).startswith("addr"):
                object.__setattr__(self, "type", AddressType.PAYMENT)
            elif str(self.address).startswith("stake"):
                object.__setattr__(self, "type", AddressType.STAKE)

    def __str__(self):
        if self.address is not None:
            return self.address
        elif self.ada_handle is not None:
            return self.ada_handle
        else:
            return self.name

    @classmethod
    def property_from_dict(
        cls: Type[AddressInfo],
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
        if field_name == "utxos":
            return AddressInfo._parse_utxos(value)
        elif field_name == "stake_address_info":
            return StakeAddressInfo.from_dict(value)

    @staticmethod
    def _parse_utxos(utxo: Dict) -> UTxO:
        """
        Parse the UTXOs
        :param utxo: The UTXO dictionary
        :return: The parsed UTxO object
        """
        transaction_input = TransactionInput(
            index=utxo["input"]["index"],
            transaction_id=TransactionId.from_primitive(utxo["input"]["transaction_id"]),
        )

        tx_out_address = AddressInfo.from_address(utxo["output"]["address"])

        multi_asset = MultiAsset()
        multi_asset_input = utxo["output"]["amount"]["multi_asset"]
        for policy_id in multi_asset_input:
            policy = ScriptHash.from_primitive(policy_id)

            for asset_name_str in multi_asset_input[policy_id]:
                asset_name = AssetName.from_primitive(asset_name_str.encode())
                amount = multi_asset_input[policy_id][asset_name_str]
                multi_asset.setdefault(policy, Asset())[asset_name] = amount

        transaction_output = TransactionOutput(
            address=tx_out_address.address,
            amount=Value(
                coin=utxo["output"]["amount"]["coin"],
                multi_asset=multi_asset,
            ),
            datum_hash=utxo["output"].get("datum_hash"),
            datum=utxo["output"].get("datum"),
            script=utxo["output"].get("script"),
        )

        return UTxO(
            input=transaction_input,
            output=transaction_output,
        )

    @staticmethod
    def from_address(address: str) -> AddressInfo:
        """
        Set the address from a string
        :param address: The address
        :return:
        """
        return AddressInfo(address=Address.from_primitive(address))

    @staticmethod
    def utxo_to_dict(utxo: UTxO):
        """
        Convert a UTXO to a dictionary
        :param utxo: The UTXO
        :return:
        """
        multi_asset = utxo.output.amount.multi_asset
        output_multi_asset: Dict[str, Dict[Any, Any]] = {}
        for policy_id in multi_asset:
            output_multi_asset[str(policy_id)] = {}
            for asset_name in multi_asset[policy_id]:
                amount = multi_asset[policy_id][asset_name]
                output_multi_asset[str(policy_id)][asset_name.payload.decode("utf-8")] = amount

        return {
            "input": {
                "transaction_id": str(utxo.input.transaction_id),
                "index": utxo.input.index,
            },
            "output": {
                "address": str(utxo.output.address),
                "amount": {
                    "coin": utxo.output.amount.coin,
                    "multi_asset": output_multi_asset,
                },
                "datum_hash": (str(utxo.output.datum_hash) if utxo.output.datum_hash else None),
                "datum": str(utxo.output.datum) if utxo.output.datum else None,
                "script": str(utxo.output.script) if utxo.output.script else None,
            },
        }
