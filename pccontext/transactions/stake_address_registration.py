from typing import List, Optional, Union

from pycardano import (
    Address,
    ExtendedSigningKey,
    SigningKey,
    StakeCredential,
    StakeRegistration,
    StakeVerificationKey,
    Transaction,
    TransactionBuilder,
)

from pccontext import ChainContext
from pccontext.exceptions import TransactionError


def stake_address_registration(
    context: ChainContext,
    stake_vkey: StakeVerificationKey,
    send_from_addr: Address,
    signing_keys: Optional[List[Union[SigningKey, ExtendedSigningKey]]] = None,
) -> Transaction:
    """
    Generates an unwitnessed stake address registration transaction.
    :param context: The chain context.
    :param stake_vkey: The stake address vkey file.
    :param send_from_addr: The address to send from.
    :param signing_keys: List of signing keys to be used for signing the transaction.
    :return: An unsigned transaction object.
    """
    stake_credential = StakeCredential(stake_vkey.hash())
    stake_registration_certificate = StakeRegistration(stake_credential)

    stake_address = Address(staking_part=stake_vkey.hash(), network=context.network)

    stake_address_info = context.stake_address_info(str(stake_address))

    if (
        stake_address_info is not None
        and len(stake_address_info)
        and stake_address_info[0].active
        and stake_address_info[0].active_epoch is not None
    ):
        delegation_pool_id = stake_address_info[0].stake_delegation
        delegation_info = (
            f"Account is currently delegated to Pool with ID:  {delegation_pool_id}\n"
            if delegation_pool_id is not None
            else ""
        )
        raise TransactionError(
            f"Stake-Address: {str(stake_address)} is already registered on the chain!\n "
            f"{delegation_info}"
        )

    builder = TransactionBuilder(context)

    builder.add_input_address(send_from_addr)

    builder.certificates = [stake_registration_certificate]

    if signing_keys:
        return builder.build_and_sign(
            signing_keys=signing_keys,
            change_address=send_from_addr,
        )

    transaction_body = builder.build(change_address=send_from_addr)

    return Transaction(transaction_body, builder.build_witness_set())
