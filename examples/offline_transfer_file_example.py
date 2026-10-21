from pathlib import Path

from pccontext import OfflineTransferFileContext


def main():
    """
    Get the protocol parameters from Offline Transfer File
    """

    chain_context = OfflineTransferFileContext(offline_transfer_file=Path("/path/to/offline-transfer.json"))

    print(chain_context.protocol_param)


if __name__ == "__main__":
    main()
