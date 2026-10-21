"""
Cardano Network Enum
"""

from enum import Enum
from typing import List, Optional

from pycardano import Network as PyCardanoNetwork


class Network(Enum):
    """
    Enum class for Cardano Network
    """

    MAINNET = "mainnet"
    PREPROD = "preprod"
    PREVIEW = "preview"
    SANCHONET = "sanchonet"
    GUILDNET = "guildnet"
    CUSTOM = "custom"

    def get_network(self) -> PyCardanoNetwork:
        """
        Returns the corresponding PyCardano Network enum.
        """
        if self == Network.MAINNET:
            return PyCardanoNetwork.MAINNET
        else:
            return PyCardanoNetwork.TESTNET

    def get_cli_network_args(self, network_magic_number: Optional[int] = None) -> List[str]:
        """
        Returns the CLI network argument for the Cardano network.
        """
        if self == Network.MAINNET:
            return ["--mainnet"]
        elif self == Network.PREPROD:
            return ["--testnet-magic", str(1)]
        elif self == Network.PREVIEW:
            return ["--testnet-magic", str(2)]
        elif self == Network.SANCHONET:
            return ["--testnet-magic", str(4)]
        elif self == Network.GUILDNET:
            return ["--testnet-magic", str(141)]
        else:
            return ["--testnet-magic", str(network_magic_number)]
