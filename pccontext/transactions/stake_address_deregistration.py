from typing import List, Optional, Union

from pycardano import (
    Address,
    ExtendedSigningKey,
    SigningKey,
    StakeCredential,
    StakeDeregistration,
    StakeVerificationKey,
    Transaction,
    TransactionBuilder,
)

from pccontext import ChainContext
from pccontext.exceptions import TransactionError


def stake_address_deregistration(
    context: ChainContext,
    stake_vkey: StakeVerificationKey,
    send_from_addr: Address,
    signing_keys: Optional[List[Union[SigningKey, ExtendedSigningKey]]] = None,
) -> Transaction:
    """
    Generates an unwitnessed stake address deregistration transaction.
    :param context: The chain context.
    :param stake_vkey: The stake address vkey file.
    :param send_from_addr: The address to send from.
    :param signing_keys: List of signing keys to be used for signing the transaction.
    :return: An unsigned transaction object.
    """
    stake_credential = StakeCredential(stake_vkey.hash())
    stake_deregistration_certificate = StakeDeregistration(stake_credential)

    stake_address = Address(staking_part=stake_vkey.hash(), network=context.network)

    stake_address_info = context.stake_address_info(str(stake_address))

    if stake_address_info is None or len(stake_address_info) == 0 or not stake_address_info[0].active:
        raise TransactionError(f"Stake-Address: {str(stake_address)} is not registered on the chain!")

    builder = TransactionBuilder(context)

    builder.add_input_address(send_from_addr)

    builder.certificates = [stake_deregistration_certificate]

    if signing_keys:
        return builder.build_and_sign(
            signing_keys=signing_keys,
            change_address=send_from_addr,
        )

    transaction_body = builder.build(change_address=send_from_addr)

    return Transaction(transaction_body, builder.build_witness_set())
