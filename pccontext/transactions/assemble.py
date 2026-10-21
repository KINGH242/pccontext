from typing import Any, List, Optional, TypeVar, Union

from pycardano import (
    IndefiniteList,
    NativeScript,
    NonEmptyOrderedSet,
    PlutusV1Script,
    PlutusV2Script,
    PlutusV3Script,
    Redeemers,
    Transaction,
    VerificationKeyWitness,
)

T = TypeVar("T")


def _update_witness_set(
    witness_set_attr: Optional[Union[List[T], NonEmptyOrderedSet[T]]],
    new_witnesses: Union[List[T], NonEmptyOrderedSet[T]],
) -> Union[List[T], NonEmptyOrderedSet[T]]:
    """Helper function to update a witness set with new witnesses."""
    if witness_set_attr is None:
        return new_witnesses

    # Both containers support extend(); copy the new witnesses into a plain list so a
    # NonEmptyOrderedSet is added as well as a list.
    witness_set_attr.extend(list(new_witnesses))
    return witness_set_attr


def assemble_transaction(
    transaction: Transaction,
    vkey_witnesses: Optional[Union[List[VerificationKeyWitness], NonEmptyOrderedSet[VerificationKeyWitness]]] = None,
    native_scripts: Optional[Union[List[NativeScript], NonEmptyOrderedSet[NativeScript]]] = None,
    bootstrap_witness: Optional[List[Any]] = None,
    plutus_v1_script: Optional[Union[List[PlutusV1Script], NonEmptyOrderedSet[PlutusV1Script]]] = None,
    plutus_data: Optional[Union[IndefiniteList, List[Any], NonEmptyOrderedSet[Any]]] = None,
    redeemer: Optional[Redeemers] = None,
    plutus_v2_script: Optional[Union[List[PlutusV2Script], NonEmptyOrderedSet[PlutusV2Script]]] = None,
    plutus_v3_script: Optional[Union[List[PlutusV3Script], NonEmptyOrderedSet[PlutusV3Script]]] = None,
) -> Transaction:
    """
    Assembles a transaction with the provided transaction and witnesses.

    :param transaction: The transaction.
    :param vkey_witnesses: Optional list of verification key witnesses.
    :param native_scripts: Optional list of native scripts.
    :param bootstrap_witness: Optional list of bootstrap witnesses.
    :param plutus_v1_script: Optional list of Plutus V1 scripts.
    :param plutus_data: Optional list of Plutus data.
    :param redeemer: Optional redeemer information.
    :param plutus_v2_script: Optional list of Plutus V2 scripts.
    :param plutus_v3_script: Optional list of Plutus V3 scripts.
    :return: The assembled transaction.
    """
    if vkey_witnesses:
        transaction.transaction_witness_set.vkey_witnesses = _update_witness_set(
            transaction.transaction_witness_set.vkey_witnesses, vkey_witnesses
        )

    if native_scripts:
        transaction.transaction_witness_set.native_scripts = _update_witness_set(
            transaction.transaction_witness_set.native_scripts, native_scripts
        )

    if bootstrap_witness:
        witness_set = transaction.transaction_witness_set
        if witness_set.bootstrap_witness is None:
            witness_set.bootstrap_witness = list(bootstrap_witness)
        else:
            witness_set.bootstrap_witness.extend(bootstrap_witness)

    if plutus_data:
        # Plutus data may also be an IndefiniteList, which the witness helper does not take.
        witness_set = transaction.transaction_witness_set
        if witness_set.plutus_data is None:
            witness_set.plutus_data = plutus_data
        else:
            witness_set.plutus_data.extend(list(plutus_data))

    if redeemer:
        transaction.transaction_witness_set.redeemer = redeemer

    if plutus_v1_script:
        transaction.transaction_witness_set.plutus_v1_script = _update_witness_set(
            transaction.transaction_witness_set.plutus_v1_script, plutus_v1_script
        )

    if plutus_v2_script:
        transaction.transaction_witness_set.plutus_v2_script = _update_witness_set(
            transaction.transaction_witness_set.plutus_v2_script, plutus_v2_script
        )

    if plutus_v3_script:
        transaction.transaction_witness_set.plutus_v3_script = _update_witness_set(
            transaction.transaction_witness_set.plutus_v3_script, plutus_v3_script
        )

    return transaction
