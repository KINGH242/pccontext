import contextlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Type, TypeVar, Union

from pycardano import Address, TransactionId, UTxO

from pccontext.enums import Era, Network
from pccontext.utils import DATE_FORMAT_2

T = TypeVar("T", bound="BaseModel")


@dataclass(frozen=True)
class BaseModel:
    """
    Base model to be inherited
    """

    def __hash__(self):  # make hashable BaseModel subclass
        return hash((type(self),) + tuple(self.__dict__.values()))

    @classmethod
    def from_json(cls: Type[T], data: Union[Dict, List[Dict]]) -> T:
        """
        Create a model from a json object
        :param data: The json object
        :return: The model
        """
        if isinstance(data, list):
            return cls.from_dict(data[0])
        return cls.from_dict(data)

    @classmethod
    def property_from_dict(cls: Type[T], value, key, field_name, init_args: Dict):
        init_args[field_name] = value

    @classmethod
    def clean_unwanted_fields(cls: Type[T], init_args: Dict):
        return None

    @classmethod
    def from_dict(cls: Type[T], data: Dict) -> T:
        """
        Create a model from a dictionary
        :param data: The dictionary
        :return: The model
        """
        field_names = {}
        for f in cls.__dataclass_fields__.values():
            if "aliases" in f.metadata:
                for alias in f.metadata["aliases"]:
                    field_names[alias] = f.name
            else:
                field_names[f.name] = f.name
        init_args: Dict[Any, Union[Union[int, float, str, dict], Any]] = {}
        for k, v in data.items():
            field_name = field_names.get(k, k)
            with contextlib.suppress(KeyError):
                if isinstance(v, str):
                    field_type = cls.__dataclass_fields__[field_name].type
                    if field_type == "Optional[Dict[str, Any]]":
                        v = json.loads(v)
                    elif field_type == "Optional[float]":
                        # check if the value is a fraction
                        v = float(v) if "/" not in v else float(Fraction(v))
                    elif field_type == "Optional[int]":
                        v = int(v)
                    elif field_type == "Optional[Era]":
                        v = Era(v.lower())
                    elif field_type == "Optional[Network]":
                        v = Network(v.lower())
                elif isinstance(v, dict):
                    init_args[field_name] = cls.property_from_dict(
                        v, k, field_name, init_args
                    )
                    continue
                elif isinstance(v, list):
                    init_args[field_name] = [
                        (
                            cls.property_from_dict(item, k, field_name, init_args)
                            if isinstance(item, dict)
                            else item
                        )
                        for item in v
                    ]
                    continue

            cls.clean_unwanted_fields(init_args)

            init_args[field_name] = v

        # Backends return more than any one model needs — Koios' chain tip
        # carries epoch_slot and block_time, for instance. Drop what this model
        # has no field for rather than raising: these payloads are shaped by the
        # service, not by us, and a new key appearing upstream should not break
        # parsing. Aliases are resolved above, so anything left here is genuinely
        # unmapped.
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in init_args.items() if k in known})

    def to_dict(self) -> Dict:
        """
        Convert the model to a dictionary
        :return: The dictionary
        """
        result: Dict[str, Any] = {}
        for field in self.__dataclass_fields__.values():
            value = getattr(self, field.name)

            try:
                field_name = (
                    field.metadata["aliases"][1]
                    if field.metadata.get("aliases", None) is not None
                    else field.name
                )
            except IndexError:
                field_name = field.metadata["aliases"][0]

            if value is not None:
                if isinstance(value, list):
                    new_list = []
                    for item in value:
                        if hasattr(item, "to_dict"):
                            new_list.append(item.to_dict())
                        elif isinstance(item, UTxO):
                            new_list.append(self._utxo_to_dict(item))
                        else:
                            new_list.append(item)
                    result[field_name] = new_list
                elif isinstance(value, bytes):
                    result[field_name] = value.decode("utf-8")
                elif isinstance(value, Fraction):
                    result[field_name] = str(value)
                elif isinstance(value, (Address, TransactionId)):
                    result[field_name] = str(value)
                elif isinstance(value, UTxO):
                    result[field_name] = value.to_shallow_primitive()
                elif isinstance(value, Enum):
                    # Every enum serialises by value. Listing them
                    # individually meant TransactionType and HistoryType
                    # fell through to json.dumps and raised.
                    result[field_name] = value.value
                elif isinstance(value, Path):
                    result[field_name] = value.as_posix()
                elif isinstance(value, datetime):
                    result[field_name] = value.strftime(DATE_FORMAT_2)
                elif hasattr(value, "to_dict"):
                    result[field_name] = value.to_dict()
                else:
                    result[field_name] = value
        return result

    def to_json(self) -> str:
        """
        Convert the model to a json string
        :return: The json string
        """
        return json.dumps(self.to_dict(), sort_keys=True)

    def _utxo_to_dict(self, utxo: UTxO) -> Dict:
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
                output_multi_asset[str(policy_id)][
                    asset_name.payload.decode("utf-8")
                ] = amount

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
                "datum_hash": (
                    str(utxo.output.datum_hash) if utxo.output.datum_hash else None
                ),
                "datum": str(utxo.output.datum) if utxo.output.datum else None,
                "script": str(utxo.output.script) if utxo.output.script else None,
            },
        }
