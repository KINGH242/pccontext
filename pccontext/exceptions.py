"""
Exception classes
"""

__all__ = [
    "CardanoCLIError",
    "CardanoNodeError",
    "BlockfrostError",
    "OgmiosError",
    "CardanoModelError",
    "OfflineTransferFileError",
    "NodeNotSyncedError",
    "NodeNotOnlineError",
    "BinaryExecutableError",
    "TransactionError",
    "UnsupportedNetworkError",
]


class CardanoCLIError(Exception):
    """
    Exception raised for errors in run cardano-cli.

    :param command: input command which caused the error
    :param message: explanation of the error
    """

    def __init__(self, command, message="Failed to run command"):
        self.command = command
        self.message = message
        super().__init__(self.message)


class CardanoNodeError(Exception):
    """
    Exception raised for errors in the Cardano Node.

    :param message: explanation of the error
    """

    def __init__(self, message="Failed cardano node operation"):
        self.message = message
        super().__init__(self.message)


class BlockfrostError(Exception):
    """
    Exception raised for errors with Blockfrost.

    :param message: explanation of the error
    """

    def __init__(self, message="Ogmios failed to run."):
        self.message = message
        super().__init__(self.message)


class OgmiosError(Exception):
    """
    Exception raised for errors with Ogmios.

    :param message: explanation of the error
    """

    def __init__(self, message="Ogmios failed to run."):
        self.message = message
        super().__init__(self.message)


class CardanoModelError(Exception):
    """
    Exception raised for errors in a Cardano model class.

    :param message: explanation of the error
    """

    def __init__(self, message="Error in a Cardano model"):
        self.message = message
        super().__init__(self.message)


class OfflineTransferFileError(Exception):
    """
    Exception raised for errors in offline transfer file.

    :param message: explanation of the error
    """

    def __init__(self, message="Error working offline"):
        self.message = message
        super().__init__(self.message)


class NodeNotSyncedError(Exception):
    """
    Exception raised when the node is not synced

    :param message: explanation of the error
    """

    def __init__(self, message="Node is not fully SYNCED"):
        self.message = message
        super().__init__(self.message)


class NodeNotOnlineError(Exception):
    """
    Exception raised when the node is not online

    :param message: explanation of the error
    """

    def __init__(self, message="Node is not ONLINE"):
        self.message = message
        super().__init__(self.message)


class BinaryExecutableError(Exception):
    """
    Exception raised when a binary executable did not run successfully

    :param message: explanation of the error
    """

    def __init__(self, message="Binary executable did not run successfully"):
        self.message = message
        super().__init__(self.message)


class TransactionError(Exception):
    """
    Exception raised when a transaction did not build successfully

    :param message: explanation of the error
    """

    def __init__(self, message="Transaction did not build successfully"):
        self.message = message
        super().__init__(self.message)


class UnsupportedNetworkError(Exception):
    """
    Exception raised when a network is not supported

    :param message: explanation of the error
    """

    def __init__(self, network: str):
        self.message = f"Unsupported network: {network}"
        super().__init__(self.message)
