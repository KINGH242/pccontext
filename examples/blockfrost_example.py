import os

from blockfrost import ApiUrls

from pccontext import BlockFrostChainContext


def main():
    """
    Get the protocol parameters from Blockfrost API
    """

    blockfrost_api_key = os.getenv("BLOCKFROST_API_KEY")
    chain_context = BlockFrostChainContext(project_id=blockfrost_api_key, base_url=ApiUrls.mainnet.value)

    print(chain_context.protocol_param)


if __name__ == "__main__":
    main()
