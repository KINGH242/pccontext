from pccontext.transactions.explorer import *


def main():
    network = Network.MAINNET

    stake_address = Address.from_primitive("stake1...")

    payment_address = Address.from_primitive("addr1...")

    block_id = "829fab5ece7f7f979d5f6d06ac0c1772f83e72e55a2ebd1021336939c07cc944"
    block_number = "12971544"

    pool = PoolOperator.from_primitive("pool1...")

    tx_id = TransactionId.from_primitive(
        "a47d84fa99b600ef002e36fba4463acf3e68e863aac0e6ec06f1e360664db13c"
    )

    adastat = BlockchainExplorer.ADASTAT.explorer()
    cardanoscan = BlockchainExplorer.CARDANOSCAN.explorer()
    cexplorer = BlockchainExplorer.CEXPLORER.explorer()
    eutxo = BlockchainExplorer.EUTXO.explorer()
    pooltool = BlockchainExplorer.POOLTOOL.explorer()

    print("ADASTAT URLS")
    print(adastat.view_account(stake_address, network))
    print(adastat.view_address(payment_address, network))
    print(adastat.view_block(block_id, network))
    print(adastat.view_pool(pool, network))
    print(adastat.view_transaction(tx_id, network), end="\n\n")

    print("CARDANOSCAN URLS")
    print(cardanoscan.view_account(stake_address, network))
    print(cardanoscan.view_address(payment_address, network))
    print(cardanoscan.view_block(block_number, network))
    print(cardanoscan.view_pool(pool, network))
    print(cardanoscan.view_transaction(tx_id, network), end="\n\n")

    print("CEXPLORER URLS")
    print(cexplorer.view_account(stake_address, network))
    print(cexplorer.view_address(payment_address, network))
    print(cexplorer.view_block(block_id, network))
    print(cexplorer.view_pool(pool, network))
    print(cexplorer.view_transaction(tx_id, network), end="\n\n")

    print("EUTXO URLS")
    print(eutxo.view_block(block_id, network))
    print(eutxo.view_transaction(tx_id, network), end="\n\n")

    print("POOLTOOL URLS")
    print(pooltool.view_account(stake_address, network))
    print(pooltool.view_block(block_number, network))
    print(pooltool.view_pool(pool, network), end="\n\n")


if __name__ == "__main__":
    main()
