from typing import List, Optional, Union

from pycardano import (
    Address,
    ExtendedSigningKey,
    SigningKey,
    StakeVerificationKey,
    Transaction,
    TransactionBuilder,
    Withdrawals,
)

from pccontext import ChainContext
from pccontext.exceptions import TransactionError


def withdraw_rewards(
    context: ChainContext,
    stake_vkey: StakeVerificationKey,
    send_from_addr: Address,
    signing_keys: Optional[List[Union[SigningKey, ExtendedSigningKey]]] = None,
) -> Transaction:
    """
    Withdraw rewards from a stake address.
    :param context: The chain context.
    :param stake_vkey: The stake address vkey file.
    :param send_from_addr: The address to send from.
    :param signing_keys: List of signing keys to be used for signing the transaction.
    :return: An unsigned transaction object.
    """
    stake_address = Address(staking_part=stake_vkey.hash(), network=context.network)

    stake_address_info = context.stake_address_info(str(stake_address))

    if stake_address_info is None or len(stake_address_info) == 0 or not stake_address_info[0].active:
        raise TransactionError("No rewards found on the stake address, Staking Address may not be on chain.")

    rewards_sum = sum(
        reward.reward_account_balance for reward in stake_address_info if reward.reward_account_balance != 0
    )

    if rewards_sum == 0:
        raise TransactionError("Rewards sum is 0, no rewards to withdraw.")

    withdrawal = Withdrawals({bytes(stake_address): rewards_sum})

    builder = TransactionBuilder(context)

    utxos = context.utxos(send_from_addr)
    for utxo in utxos:
        builder.add_input(utxo)

    builder.withdrawals = withdrawal

    if signing_keys:
        return builder.build_and_sign(
            signing_keys=signing_keys,
            change_address=send_from_addr,
            merge_change=True,
        )

    transaction_body = builder.build(change_address=send_from_addr, merge_change=True)

    return Transaction(transaction_body, builder.build_witness_set())
