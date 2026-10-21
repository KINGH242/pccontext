import os

from pycardano import (
    Address,
    PaymentSigningKey,
    PaymentVerificationKey,
    StakeSigningKey,
    StakeVerificationKey,
)

from pccontext import BlockFrostChainContext, Network
from pccontext.transactions.stake_address_registration import stake_address_registration


def main():
    """
    Example of registering a stake address on the Cardano testnet using BlockFrost.
    """
    network = Network.PREPROD
    blockfrost_api_key = os.getenv("BLOCKFROST_API_KEY_PREPROD")
    chain_context = BlockFrostChainContext(project_id=blockfrost_api_key, network=network)

    payment_signing_key = PaymentSigningKey.generate()
    payment_verification_key = PaymentVerificationKey.from_signing_key(payment_signing_key)

    stake_signing_key = StakeSigningKey.generate()
    stake_verification_key = StakeVerificationKey.from_signing_key(stake_signing_key)

    address = Address(
        payment_part=payment_verification_key.hash(),
        staking_part=stake_verification_key.hash(),
        network=network.get_network(),
    )

    signed_tx = stake_address_registration(
        context=chain_context,
        stake_vkey=stake_verification_key,
        send_from_addr=address,
        signing_keys=[payment_signing_key, stake_signing_key],
    )

    print(f"Signed Transaction: {signed_tx}")

    chain_context.submit_tx(signed_tx)

    print(f"Transaction ID: {signed_tx.id}")


if __name__ == "__main__":
    main()
