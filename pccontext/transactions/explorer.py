"""
Blockchain explorer implementations
"""

from __future__ import annotations

from abc import ABCMeta
from dataclasses import dataclass
from enum import Enum

from pycardano import Address, PoolOperator, TransactionId

from pccontext import Network, UnsupportedNetworkError


class BlockchainExplorerProtocol(object, metaclass=ABCMeta):
    """
    Abstract base class defining the protocol for blockchain explorer implementations.

    This class provides a standard interface for generating URLs to view various
    blockchain entities (accounts, addresses, blocks, pools, transactions) on
    different blockchain explorers.

    Attributes:
        _network_urls: NetworkURLs object containing the base URLs for different networks
    """

    _network_urls: NetworkURLs

    def view_account(self, address: Address, network: Network) -> str:
        """
        Generate a URL to view an account on the blockchain explorer.
        Account is a set of addresses associated with one stake key
        :param address: The address to view
        :param network: The network to view the account on
        :return: The URL to view the account on the blockchain explorer
        """
        raise NotImplementedError(
            f"view_account not implemented for this explorer: {self.__class__.__name__}"
        )

    def view_address(self, address: Address, network: Network) -> str:
        """
        Generate a URL to view an address on the blockchain explorer.
        :param address: The address to view
        :param network: The network to view the address on
        :return: The URL to view the address on the blockchain explorer
        """
        raise NotImplementedError(
            f"view_address not implemented for this explorer: {self.__class__.__name__}"
        )

    def view_block(self, block_id: str, network: Network) -> str:
        """
        Generate a URL to view a block on the blockchain explorer.
        :param block_id: The block identifier (hash or number depending on explorer)
        :param network: The network to view the block on
        :return: The URL to view the block on the blockchain explorer
        """
        raise NotImplementedError(
            f"view_block not implemented for this explorer: {self.__class__.__name__}"
        )

    def view_pool(self, pool_id: PoolOperator, network: Network) -> str:
        """
        Generate a URL to view a stake pool on the blockchain explorer.
        :param pool_id: The pool operator containing the pool key hash
        :param network: The network to view the pool on
        :return: The URL to view the pool on the blockchain explorer
        """
        raise NotImplementedError(
            f"view_pool not implemented for this explorer: {self.__class__.__name__}"
        )

    def view_transaction(self, transaction_id: TransactionId, network: Network) -> str:
        """
        Generate a URL to view a transaction on the blockchain explorer.
        :param transaction_id: The transaction identifier
        :param network: The network to view the transaction on
        :return: The URL to view the transaction on the blockchain explorer
        """
        raise NotImplementedError(
            f"view_transaction not implemented for this explorer: {self.__class__.__name__}"
        )


@dataclass(frozen=True)
class NetworkURLs:
    """
    Data class holding base URLs for different Cardano networks.
    """

    mainnet: str
    preprod: str | None = None
    preview: str | None = None


class BlockchainExplorer(Enum):
    """
    Enumeration of supported blockchain explorers for the Cardano network.

    Each explorer provides different levels of support for various networks
    (mainnet, preprod, preview) and blockchain entities.

    Attributes:
        ADASTAT: AdaStat blockchain explorer (mainnet only)
        CARDANOSCAN: CardanoScan blockchain explorer (all networks)
        CEXPLORER: Cexplorer blockchain explorer (all networks)
        EUTXO: Eutxo blockchain explorer (mainnet only)
        POOLTOOL: PoolTool blockchain explorer (mainnet only)
    """

    ADASTAT = "adastat"
    CARDANOSCAN = "cardanoscan"
    CEXPLORER = "cexplorer"
    EUTXO = "eutxo"
    POOLTOOL = "pooltool"

    @property
    def description(self) -> str:
        """
        Get a human-readable description of the blockchain explorer.
        :return: A string describing the explorer and its website
        """
        if self is BlockchainExplorer.ADASTAT:
            return "Explore transactions on adastat.net."
        if self is BlockchainExplorer.CARDANOSCAN:
            return "Explore transactions on cardanoscan.io."
        if self is BlockchainExplorer.CEXPLORER:
            return "Explore transactions on cexplorer.io."
        if self is BlockchainExplorer.EUTXO:
            return "Explore transactions on eutxo.org."
        if self is BlockchainExplorer.POOLTOOL:
            return "Explore transactions on pooltool.io."
        raise AssertionError("Unhandled explorer")

    def explorer(self) -> BlockchainExplorerProtocol:
        """
        Get an instance of the blockchain explorer protocol implementation.
        :return: A BlockchainExplorerProtocol instance for the selected explorer
        """
        if self is BlockchainExplorer.ADASTAT:
            return AdaStat()
        if self is BlockchainExplorer.CARDANOSCAN:
            return CardanoScan()
        if self is BlockchainExplorer.CEXPLORER:
            return Cexplorer()
        if self is BlockchainExplorer.EUTXO:
            return Eutxo()
        if self is BlockchainExplorer.POOLTOOL:
            return PoolTool()
        raise AssertionError("Unhandled explorer")


class AdaStat(BlockchainExplorerProtocol):
    """
    AdaStat blockchain explorer implementation (https://adastat.net).

    Provides URL generation for viewing blockchain entities on the AdaStat explorer.
    Only supports mainnet network.
    """

    _network_urls = NetworkURLs(
        mainnet="https://adastat.net",
    )

    def view_account(self, address: Address, network: Network) -> str:
        """
        Generate a URL to view an account on AdaStat.
        :param address: The address containing the stake key to view
        :param network: The network (only mainnet supported)
        :return: URL string for viewing the account on AdaStat
        """
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/accounts/{address.staking_part.payload.hex()}"
        raise UnsupportedNetworkError(network.name)

    def view_address(self, address: Address, network: Network) -> str:
        """
        Generate a URL to view an address on AdaStat.
        :param address: The address to view
        :param network: The network (only mainnet supported)
        :return: URL string for viewing the address on AdaStat
        """
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/addresses/{address}"
        raise UnsupportedNetworkError(network.name)

    def view_block(self, block_id: str, network: Network) -> str:
        """
        Generate a URL to view a block on AdaStat.
        :param block_id: The block hash or identifier
        :param network: The network (only mainnet supported)
        :return: URL string for viewing the block on AdaStat
        """
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/blocks/{block_id}"
        raise UnsupportedNetworkError(network.name)

    def view_pool(self, pool: PoolOperator, network: Network) -> str:
        """
        Generate a URL to view a stake pool on AdaStat.
        :param pool: The pool operator containing the pool key hash
        :param network: The network (only mainnet supported)
        :return: URL string for viewing the pool on AdaStat
        """
        if network is Network.MAINNET:
            return (
                f"{self._network_urls.mainnet}/pools/{pool.pool_key_hash.payload.hex()}"
            )
        raise UnsupportedNetworkError(network.name)

    def view_transaction(self, transaction_id: TransactionId, network: Network) -> str:
        """
        Generate a URL to view a transaction on AdaStat.
        :param transaction_id: The transaction identifier
        :param network: The network (only mainnet supported)
        :return: URL string for viewing the transaction on AdaStat
        """
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/transactions/{transaction_id.payload.hex()}"
        raise UnsupportedNetworkError(network.name)


class CardanoScan(BlockchainExplorerProtocol):
    """
    CardanoScan blockchain explorer implementation (https://cardanoscan.io).

    Provides URL generation for viewing blockchain entities on the CardanoScan explorer.
    Supports mainnet, preprod, and preview networks.
    """

    _network_urls = NetworkURLs(
        mainnet="https://cardanoscan.io",
        preprod="https://preprod.cardanoscan.io",
        preview="https://preview.cardanoscan.io",
    )

    def view_account(self, address: Address, network: Network) -> str:
        """
        Generate a URL to view an account on CardanoScan.
        :param address: The address containing the stake key to view
        :param network: The network (mainnet, preprod, or preview)
        :return: URL string for viewing the account on CardanoScan
        """
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/stakeKey/{address}"
        if network is Network.PREPROD:
            return f"{self._network_urls.preprod}/stakeKey/{address}"
        if network is Network.PREVIEW:
            return f"{self._network_urls.preview}/stakeKey/{address}"
        raise UnsupportedNetworkError(network.name)

    def view_address(self, address: Address, network: Network) -> str:
        """
        Generate a URL to view an address on CardanoScan.
        :param address: The address to view
        :param network: The network (mainnet, preprod, or preview)
        :return: URL string for viewing the address on CardanoScan
        """
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/address/{address}"
        if network is Network.PREPROD:
            return f"{self._network_urls.preprod}/address/{address}"
        if network is Network.PREVIEW:
            return f"{self._network_urls.preview}/address/{address}"
        raise UnsupportedNetworkError(network.name)

    def view_block(self, block_id: str, network: Network) -> str:
        """
        Generate a URL to view a block on CardanoScan.
        :param block_id: The block number (not hash) as a string
        :param network: The network (mainnet, preprod, or preview)
        :return: URL string for viewing the block on CardanoScan
        """
        try:
            block_number = int(block_id)
        except ValueError as e:
            raise ValueError(
                f"Use block number for CardanoScan instead of block id: {block_id}"
            ) from e
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/block/{block_number}"
        if network is Network.PREPROD:
            return f"{self._network_urls.preprod}/block/{block_number}"
        if network is Network.PREVIEW:
            return f"{self._network_urls.preview}/block/{block_number}"
        raise UnsupportedNetworkError(network.name)

    def view_pool(self, pool: PoolOperator, network: Network) -> str:
        """
        Generate a URL to view a stake pool on CardanoScan.
        :param pool: The pool operator containing the pool key hash
        :param network: The network (mainnet, preprod, or preview)
        :return: URL string for viewing the pool on CardanoScan
        """
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/pool/{pool}"
        if network is Network.PREPROD:
            return f"{self._network_urls.preprod}/pool/{pool}"
        if network is Network.PREVIEW:
            return f"{self._network_urls.preview}/pool/{pool}"
        raise UnsupportedNetworkError(network.name)

    def view_transaction(self, transaction_id: TransactionId, network: Network) -> str:
        """
        Generate a URL to view a transaction on CardanoScan.
        :param transaction_id: The transaction identifier
        :param network: The network (mainnet, preprod, or preview)
        :return: URL string for viewing the transaction on CardanoScan
        """
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/transaction/{transaction_id.payload.hex()}"
        if network is Network.PREPROD:
            return f"{self._network_urls.preprod}/transaction/{transaction_id.payload.hex()}"
        if network is Network.PREVIEW:
            return f"{self._network_urls.preview}/transaction/{transaction_id.payload.hex()}"
        raise UnsupportedNetworkError(network.name)


class Cexplorer(BlockchainExplorerProtocol):
    """
    Cexplorer blockchain explorer implementation (https://cexplorer.io).

    Provides URL generation for viewing blockchain entities on the Cexplorer explorer.
    Supports mainnet, preprod, and preview networks.
    """

    _network_urls = NetworkURLs(
        mainnet="https://cexplorer.io",
        preprod="https://preprod.cexplorer.io",
        preview="https://preview.cexplorer.io",
    )

    def view_account(self, address: Address, network: Network) -> str:
        """
        Generate a URL to view an account on Cexplorer.
        :param address: The address containing the stake key to view
        :param network: The network (mainnet, preprod, or preview)
        :return: URL string for viewing the account on Cexplorer
        """
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/stake/{address}"
        if network is Network.PREPROD:
            return f"{self._network_urls.preprod}/stake/{address}"
        if network is Network.PREVIEW:
            return f"{self._network_urls.preview}/stake/{address}"
        raise UnsupportedNetworkError(network.name)

    def view_address(self, address: Address, network: Network) -> str:
        """
        Generate a URL to view an address on Cexplorer.
        :param address: The address to view
        :param network: The network (mainnet, preprod, or preview)
        :return: URL string for viewing the address on Cexplorer
        """
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/address/{address}"
        if network is Network.PREPROD:
            return f"{self._network_urls.preprod}/address/{address}"
        if network is Network.PREVIEW:
            return f"{self._network_urls.preview}/address/{address}"
        raise UnsupportedNetworkError(network.name)

    def view_block(self, block_id: str, network: Network) -> str:
        """
        Generate a URL to view a block on Cexplorer.
        :param block_id: The block hash or identifier
        :param network: The network (mainnet, preprod, or preview)
        :return: URL string for viewing the block on Cexplorer
        """
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/block/{block_id}"
        if network is Network.PREPROD:
            return f"{self._network_urls.preprod}/block/{block_id}"
        if network is Network.PREVIEW:
            return f"{self._network_urls.preview}/block/{block_id}"
        raise UnsupportedNetworkError(network.name)

    def view_pool(self, pool: PoolOperator, network: Network) -> str:
        """
        Generate a URL to view a stake pool on Cexplorer.
        :param pool: The pool operator containing the pool key hash
        :param network: The network (mainnet, preprod, or preview)
        :return: URL string for viewing the pool on Cexplorer
        """
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/pool/{pool}"
        if network is Network.PREPROD:
            return f"{self._network_urls.preprod}/pool/{pool}"
        if network is Network.PREVIEW:
            return f"{self._network_urls.preview}/pool/{pool}"
        raise UnsupportedNetworkError(network.name)

    def view_transaction(self, tx_hash: str, network: Network) -> str:
        """
        Generate a URL to view a transaction on Cexplorer.
        :param tx_hash: The transaction hash
        :param network: The network (mainnet, preprod, or preview)
        :return: URL string for viewing the transaction on Cexplorer
        """
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/tx/{tx_hash}"
        if network is Network.PREPROD:
            return f"{self._network_urls.preprod}/tx/{tx_hash}"
        if network is Network.PREVIEW:
            return f"{self._network_urls.preview}/tx/{tx_hash}"
        raise UnsupportedNetworkError(network.name)


class Eutxo(BlockchainExplorerProtocol):
    """
    Eutxo blockchain explorer implementation (https://eutxo.org).

    Provides URL generation for viewing blockchain entities on the Eutxo explorer.
    Only supports mainnet network and limited entity types (blocks and transactions).
    """

    _network_urls = NetworkURLs(
        mainnet="https://eutxo.org",
    )

    def view_block(self, block_id: str, network: Network) -> str:
        """
        Generate a URL to view a block on Eutxo.
        :param block_id: The block hash or identifier
        :param network: The network (only mainnet supported)
        :return: URL string for viewing the block on Eutxo
        """
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/block/{block_id}"
        raise UnsupportedNetworkError(network.name)

    def view_transaction(self, tx_hash: str, network: Network) -> str:
        """
        Generate a URL to view a transaction on Eutxo.
        :param tx_hash: The transaction hash
        :param network: The network (only mainnet supported)
        :return: URL string for viewing the transaction on Eutxo
        """
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/transaction/{tx_hash}"
        raise UnsupportedNetworkError(network.name)


class PoolTool(BlockchainExplorerProtocol):
    """
    PoolTool blockchain explorer implementation (https://pooltool.io).

    Provides URL generation for viewing blockchain entities on the PoolTool explorer.
    Only supports mainnet network and limited entity types (accounts, blocks, and pools).
    """

    _network_urls = NetworkURLs(
        mainnet="https://pooltool.io",
    )

    def view_account(self, address: Address, network: Network) -> str:
        """
        Generate a URL to view an account on PoolTool.
        :param address: The address to view
        :param network: The network (only mainnet supported)
        :return: URL string for viewing the account on PoolTool
        """
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/address/{address.staking_part.payload.hex()}"
        raise UnsupportedNetworkError(network.name)

    def view_block(self, block_id: str, network: Network) -> str:
        """
        Generate a URL to view a block on PoolTool.
        :param block_id: The block number (not hash) as a string
        :param network: The network (only mainnet supported)
        :return: URL string for viewing the block on PoolTool
        """
        try:
            block_number = int(block_id)
        except ValueError as e:
            raise ValueError(
                f"Use block number for PoolTool instead of block id: {block_id}"
            ) from e
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/realtime/{block_number}"
        raise UnsupportedNetworkError(network.name)

    def view_pool(self, pool: PoolOperator, network: Network) -> str:
        """
        Generate a URL to view a stake pool on PoolTool.
        :param pool: The pool operator containing the pool key hash
        :param network: The network (only mainnet supported)
        :return: URL string for viewing the pool on PoolTool
        """
        if network is Network.MAINNET:
            return f"{self._network_urls.mainnet}/pool/{pool.pool_key_hash.payload.hex()}/epochs"
        raise UnsupportedNetworkError(network.name)
