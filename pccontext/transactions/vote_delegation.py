from typing import List, Optional, Union

from pycardano import (
    Address,
    DRepKind,
    ExtendedSigningKey,
    SigningKey,
    StakeCredential,
    StakeVerificationKey,
    Transaction,
    TransactionBuilder,
    VoteDelegation,
)

from pccontext import ChainContext
from pccontext.utils.transaction_utils import get_drep


def vote_delegation(
    context: ChainContext,
    stake_vkey: StakeVerificationKey,
    send_from_addr: Address,
    drep_kind: DRepKind,
    drep_id: Optional[str] = None,
    signing_keys: Optional[List[Union[SigningKey, ExtendedSigningKey]]] = None,
) -> Transaction:
    """
    Generates an unwitnessed vote delegation transaction.
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

    vote_delegation_certificate = VoteDelegation(stake_credential, drep)

    builder = TransactionBuilder(context)

    builder.add_input_address(send_from_addr)

    builder.certificates = [vote_delegation_certificate]

    if signing_keys:
        return builder.build_and_sign(
            signing_keys=signing_keys,
            change_address=send_from_addr,
        )

    transaction_body = builder.build(change_address=send_from_addr)

    return Transaction(transaction_body, builder.build_witness_set())
