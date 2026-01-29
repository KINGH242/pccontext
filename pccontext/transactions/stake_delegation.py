from typing import List, Optional, Union

from pycardano import (
    Address,
    ExtendedSigningKey,
    PoolOperator,
    SigningKey,
    StakeCredential,
    StakeDelegation,
    StakeVerificationKey,
    Transaction,
    TransactionBuilder,
)

from pccontext import ChainContext
from pccontext.exceptions import TransactionError


def stake_delegation(
    context: ChainContext,
    stake_vkey: StakeVerificationKey,
    pool_id: str,
    send_from_addr: Address,
    signing_keys: Optional[List[Union[SigningKey, ExtendedSigningKey]]] = None,
) -> Transaction:
    """
    Generates an unwitnessed stake delegation transaction.
    :param context: The chain context.
    :param stake_vkey: The stake address vkey file.
    :param pool_id: The pool ID (hex or bech32) to delegate to.
    :param send_from_addr: The address to send from.
    :param signing_keys: List of signing keys to be used for signing the transaction.
    :return: An unsigned transaction object.
    """
    pool = PoolOperator.from_primitive(pool_id)

    stake_credential = StakeCredential(stake_vkey.hash())
    stake_delegation_certificate = StakeDelegation(
        stake_credential=stake_credential,
        pool_keyhash=pool.pool_key_hash,
    )

    stake_address = Address(staking_part=stake_vkey.hash(), network=context.network)

    stake_address_info = context.stake_address_info(str(stake_address))

    if (
        stake_address_info is None
        or len(stake_address_info) == 0
        or (
            not stake_address_info[0].active
            and stake_address_info[0].active_epoch is None
        )
    ):
        raise TransactionError("Staking Address may not be on chain.")

    builder = TransactionBuilder(context)

    builder.add_input_address(send_from_addr)

    builder.certificates = [stake_delegation_certificate]

    if signing_keys:
        return builder.build_and_sign(
            signing_keys=signing_keys,
            change_address=send_from_addr,
        )

    transaction_body = builder.build(change_address=send_from_addr)

    return Transaction(transaction_body, builder.build_witness_set())
