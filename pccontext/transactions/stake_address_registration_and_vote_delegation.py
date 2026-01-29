from typing import List, Optional, Union

from pycardano import (
    Address,
    DRepKind,
    ExtendedSigningKey,
    SigningKey,
    StakeCredential,
    StakeRegistrationAndVoteDelegation,
    StakeVerificationKey,
    Transaction,
    TransactionBuilder,
)

from pccontext import ChainContext
from pccontext.exceptions import TransactionError
from pccontext.utils.transaction_utils import get_drep


def stake_address_registration_and_vote_delegation(
    context: ChainContext,
    stake_vkey: StakeVerificationKey,
    send_from_addr: Address,
    drep_kind: DRepKind,
    drep_id: Optional[str] = None,
    signing_keys: Optional[List[Union[SigningKey, ExtendedSigningKey]]] = None,
) -> Transaction:
    """
    Generates an unwitnessed stake address registration and vote delegation transaction.
    :param context: The chain context.
    :param stake_vkey: The stake address vkey file.
    :param send_from_addr: The address to send from.
    :param drep_kind: The DRep kind.
    :param drep_id: The Delegate Representative ID (hex or bech32).
    :param signing_keys: List of signing keys to be used for signing the transaction.
    :return: An unsigned transaction object.
    """
    stake_credential = StakeCredential(stake_vkey.hash())

    drep = get_drep(drep_kind, drep_id)

    stake_registration_and_vote_delegation_certificate = (
        StakeRegistrationAndVoteDelegation(
            stake_credential=stake_credential,
            drep=drep,
            coin=context.protocol_param.key_deposit,
        )
    )

    stake_address = Address(staking_part=stake_vkey.hash(), network=context.network)

    stake_address_info = context.stake_address_info(str(stake_address))

    if (
        stake_address_info is not None
        and len(stake_address_info)
        and stake_address_info[0].active
        and stake_address_info[0].active_epoch is not None
    ):
        delegation_pool_id = stake_address_info[0].stake_delegation
        raise TransactionError(
            f"Stake-Address: {str(stake_address)} is already registered on the chain!\n "
            f"{f"Account is currently delegated to Pool with ID: "
               f" {delegation_pool_id}\n" if delegation_pool_id is not None else ''}"
        )

    builder = TransactionBuilder(context)

    builder.add_input_address(send_from_addr)

    builder.certificates = [stake_registration_and_vote_delegation_certificate]

    if signing_keys:
        return builder.build_and_sign(
            signing_keys=signing_keys,
            change_address=send_from_addr,
        )

    transaction_body = builder.build(change_address=send_from_addr)

    return Transaction(transaction_body, builder.build_witness_set())
