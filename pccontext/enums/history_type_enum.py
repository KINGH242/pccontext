from enum import Enum
from functools import partial

from pccontext.utils.validators import greater_than_version

if greater_than_version((3, 13)):
    from enum import member  # type: ignore[attr-defined]

__all__ = ["HistoryType"]


def attach_file(file_name: str):
    return f"attached file {file_name}"


def add_address(file_name: str):
    return f"added utxo-info for {file_name}"


def add_stake_address(file_name: str):
    return f"added stake address rewards-state for {file_name}"


def extracted_file(file_name: str):
    return f"extracted file {file_name}"


def submit_tx(tx_id: str, transaction_from_name: str, transaction_to_name: str):
    return f"tx submit {tx_id} - utxo from {transaction_from_name} to {transaction_to_name}"


def save_tx(tx_id: str):
    return f"tx save {tx_id}"


def submit_rewards_tx(tx_id: str, transaction_stake_name: str, transaction_to_name: str):
    return f"tx submit {tx_id} - withdrawal from {transaction_stake_name} to {transaction_to_name}"


def submit_stake_tx(
    tx_id: str,
    transaction_type: str,
    transaction_stake_name: str,
    transaction_from_name: str,
):
    return f"tx submit {tx_id} - {transaction_type} for {transaction_stake_name}, payment via {transaction_from_name}"


def submit_pool_tx(tx_id: str, transaction_type: str, pool_meta_ticker: str, transaction_from_name: str):
    return f"tx submit {tx_id} - {transaction_type} for Pool {pool_meta_ticker}, payment via {transaction_from_name}"


def signed_pool_registration_tx(pool_meta_ticker: str, registration_pay_name: str):
    return f"signed pool registration transaction for {pool_meta_ticker}, payment via {registration_pay_name}"


def signed_pool_deregistration_tx(pool_meta_ticker: str, deregistration_pay_name: str):
    return f"signed pool retirement transaction for {pool_meta_ticker}, payment via {deregistration_pay_name}"


def signed_stake_key_registration_tx(stake_addr: str, from_addr: str):
    return f"signed staking key registration transaction for '{stake_addr}', payment via '{from_addr}'"


def signed_delegation_tx(stake_addr: str, from_addr: str):
    return f"signed delegation cert registration transaction for '{stake_addr}', payment via '{from_addr}'"


def signed_stake_key_deregistration_tx(stake_addr: str, from_addr: str):
    return f"signed staking key deregistration transaction for '{stake_addr}', payment via '{from_addr}'"


def signed_utxo_tx(from_addr: str, to_addr: str):
    return f"signed utxo transaction from '{from_addr}' to '{to_addr}'"


def signed_rewards_withdrawal(stake_addr: str, to_addr: str, payment_addr: str):
    return f"signed rewards withdrawal from '{stake_addr}' to '{to_addr}', payment via '{payment_addr}'"


class HistoryType(Enum):
    """
    Enum class for history type in OfflineTransfer
    """

    ADD_UTXO_INFO = member(partial(add_address)) if greater_than_version((3, 13)) else partial(add_address)
    ADD_STAKE_ADDR = member(partial(add_stake_address)) if greater_than_version((3, 13)) else partial(add_stake_address)
    ATTACH = member(partial(attach_file)) if greater_than_version((3, 13)) else partial(attach_file)
    CLEAR_FILES = "attached files cleared"
    CLEAR_HISTORY = "history cleared"
    CLEAR_TRANSACTIONS = "cleared all transactions"
    EXTRACTED_FILE = member(partial(extracted_file)) if greater_than_version((3, 13)) else partial(extracted_file)
    NEW = "new file created"
    SAVE_TRANSACTION = member(partial(save_tx)) if greater_than_version((3, 13)) else partial(save_tx)
    SUBMIT_REWARDS_TRANSACTION = (
        member(partial(submit_rewards_tx)) if greater_than_version((3, 13)) else partial(submit_rewards_tx)
    )
    SUBMIT_STAKE_TRANSACTION = (
        member(partial(submit_stake_tx)) if greater_than_version((3, 13)) else partial(submit_stake_tx)
    )
    SUBMIT_POOL_TRANSACTION = (
        member(partial(submit_pool_tx)) if greater_than_version((3, 13)) else partial(submit_pool_tx)
    )
    SIGNED_POOL_REGISTRATION_TRANSACTION = (
        member(partial(signed_pool_registration_tx))
        if greater_than_version((3, 13))
        else partial(signed_pool_registration_tx)
    )
    SIGNED_POOL_DEREGISTRATION_TRANSACTION = (
        member(partial(signed_pool_deregistration_tx))
        if greater_than_version((3, 13))
        else partial(signed_pool_deregistration_tx)
    )
    SIGNED_STAKE_KEY_REGISTRATION_TRANSACTION = (
        member(partial(signed_stake_key_registration_tx))
        if greater_than_version((3, 13))
        else partial(signed_stake_key_registration_tx)
    )
    SIGNED_DELEGATION_TRANSACTION = (
        member(partial(signed_delegation_tx)) if greater_than_version((3, 13)) else partial(signed_delegation_tx)
    )
    SIGNED_STAKE_KEY_DEREGISTRATION_TRANSACTION = (
        member(partial(signed_stake_key_deregistration_tx))
        if greater_than_version((3, 13))
        else partial(signed_stake_key_deregistration_tx)
    )
    SIGNED_UTXO_TRANSACTION = (
        member(partial(signed_utxo_tx)) if greater_than_version((3, 13)) else partial(signed_utxo_tx)
    )
    SIGNED_REWARDS_WITHDRAWAL = (
        member(partial(signed_rewards_withdrawal))
        if greater_than_version((3, 13))
        else partial(signed_rewards_withdrawal)
    )
