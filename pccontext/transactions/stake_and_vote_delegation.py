from typing import List, Optional, Union

from pycardano import (
    Address,
    DRepKind,
    ExtendedSigningKey,
    PoolOperator,
    SigningKey,
    StakeAndVoteDelegation,
    StakeCredential,
    StakeVerificationKey,
    Transaction,
    TransactionBuilder,
)

from pccontext import ChainContext
from pccontext.exceptions import TransactionError
from pccontext.utils.transaction_utils import get_drep


def stake_and_vote_delegation(
    context: ChainContext,
    stake_vkey: StakeVerificationKey,
    pool_id: str,
    send_from_addr: Address,
    drep_kind: DRepKind,
    drep_id: Optional[str] = None,
    signing_keys: Optional[List[Union[SigningKey, ExtendedSigningKey]]] = None,
) -> Transaction:
    """
    Generates an unwitnessed stake and vote delegation transaction.
    :param context: The chain context.
    :param stake_vkey: The stake address vkey file.
    :param pool_id: The pool ID (hex or bech32) to delegate to.
    :param send_from_addr: The address to send from.
    :param drep_kind: The DRep kind.
    :param drep_id: The Delegate Representative ID (hex or bech32).
    :param signing_keys: List of signing keys to be used for signing the transaction.
    :return: An unsigned transaction object.
    """
    pool = PoolOperator.from_primitive(pool_id)

    stake_credential = StakeCredential(stake_vkey.hash())

    drep = get_drep(drep_kind, drep_id)

    stake_and_vote_delegation_certificate = StakeAndVoteDelegation(
        stake_credential=stake_credential,
        pool_keyhash=pool.pool_key_hash,
        drep=drep,
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

    builder.certificates = [stake_and_vote_delegation_certificate]

    if signing_keys:
        return builder.build_and_sign(
            signing_keys=signing_keys,
            change_address=send_from_addr,
        )

    transaction_body = builder.build(change_address=send_from_addr)

    return Transaction(transaction_body, builder.build_witness_set())
