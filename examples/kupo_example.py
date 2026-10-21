from pccontext import KupoChainContextExtension, OgmiosChainContext


def main():
    """
    Get the protocol parameters from Ogmios
    """

    ogmios_chain_context = OgmiosChainContext(host="localhost", port=1337)
    chain_context = KupoChainContextExtension(kupo_url="http://localhost:1442", wrapped_backend=ogmios_chain_context)

    print(chain_context.protocol_param)


if __name__ == "__main__":
    main()
