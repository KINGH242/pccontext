"""
Tests for blockchain explorer implementations
"""

import pytest
from pycardano import Address, PoolKeyHash, PoolOperator, TransactionId

from pccontext import Network, UnsupportedNetworkError
from pccontext.transactions.explorer import (
    AdaStat,
    BlockchainExplorer,
    CardanoScan,
    Cexplorer,
    Eutxo,
    NetworkURLs,
    PoolTool,
)


class TestNetworkURLs:
    """Test NetworkURLs dataclass"""

    def test_network_urls_mainnet_only(self):
        """Test NetworkURLs with mainnet only"""
        urls = NetworkURLs(mainnet="https://example.com")
        assert urls.mainnet == "https://example.com"
        assert urls.preprod is None
        assert urls.preview is None

    def test_network_urls_all_networks(self):
        """Test NetworkURLs with all networks"""
        urls = NetworkURLs(
            mainnet="https://mainnet.example.com",
            preprod="https://preprod.example.com",
            preview="https://preview.example.com",
        )
        assert urls.mainnet == "https://mainnet.example.com"
        assert urls.preprod == "https://preprod.example.com"
        assert urls.preview == "https://preview.example.com"

    def test_network_urls_frozen(self):
        """Test that NetworkURLs is immutable"""
        urls = NetworkURLs(mainnet="https://example.com")
        with pytest.raises(Exception):  # dataclass frozen raises FrozenInstanceError
            urls.mainnet = "https://new.example.com"


class TestBlockchainExplorerEnum:
    """Test BlockchainExplorer enum"""

    def test_explorer_values(self):
        """Test that all explorer values are correct"""
        assert BlockchainExplorer.ADASTAT.value == "adastat"
        assert BlockchainExplorer.CARDANOSCAN.value == "cardanoscan"
        assert BlockchainExplorer.CEXPLORER.value == "cexplorer"
        assert BlockchainExplorer.EUTXO.value == "eutxo"
        assert BlockchainExplorer.POOLTOOL.value == "pooltool"

    def test_description_adastat(self):
        """Test AdaStat description"""
        assert (
            BlockchainExplorer.ADASTAT.description
            == "Explore transactions on adastat.net."
        )

    def test_description_cardanoscan(self):
        """Test CardanoScan description"""
        assert (
            BlockchainExplorer.CARDANOSCAN.description
            == "Explore transactions on cardanoscan.io."
        )

    def test_description_cexplorer(self):
        """Test Cexplorer description"""
        assert (
            BlockchainExplorer.CEXPLORER.description
            == "Explore transactions on cexplorer.io."
        )

    def test_description_eutxo(self):
        """Test Eutxo description"""
        assert (
            BlockchainExplorer.EUTXO.description == "Explore transactions on eutxo.org."
        )

    def test_description_pooltool(self):
        """Test PoolTool description"""
        assert (
            BlockchainExplorer.POOLTOOL.description
            == "Explore transactions on pooltool.io."
        )

    def test_explorer_factory_adastat(self):
        """Test that explorer() returns AdaStat instance"""
        explorer = BlockchainExplorer.ADASTAT.explorer()
        assert isinstance(explorer, AdaStat)

    def test_explorer_factory_cardanoscan(self):
        """Test that explorer() returns CardanoScan instance"""
        explorer = BlockchainExplorer.CARDANOSCAN.explorer()
        assert isinstance(explorer, CardanoScan)

    def test_explorer_factory_cexplorer(self):
        """Test that explorer() returns Cexplorer instance"""
        explorer = BlockchainExplorer.CEXPLORER.explorer()
        assert isinstance(explorer, Cexplorer)

    def test_explorer_factory_eutxo(self):
        """Test that explorer() returns Eutxo instance"""
        explorer = BlockchainExplorer.EUTXO.explorer()
        assert isinstance(explorer, Eutxo)

    def test_explorer_factory_pooltool(self):
        """Test that explorer() returns PoolTool instance"""
        explorer = BlockchainExplorer.POOLTOOL.explorer()
        assert isinstance(explorer, PoolTool)


class TestAdaStat:
    """Test AdaStat blockchain explorer"""

    @pytest.fixture
    def explorer(self):
        """Create AdaStat explorer instance"""
        return AdaStat()

    @pytest.fixture
    def address(self):
        """Create a test address"""
        return Address.from_primitive(
            "addr1qx2fxv2umyhttkxyxp8x0dlpdt3k6cwng5pxj3jhsydzer3n0d3vllmyqwsx5wktcd8cc3sq835lu7drv2xwl2wywfgse35a3x"
        )

    @pytest.fixture
    def pool_operator(self):
        """Create a test pool operator"""
        pool_key_hash = PoolKeyHash.from_primitive(
            "00000036d515e12e18cd3c88c74f09a67984c2c279a5296aa96efe89"
        )
        return PoolOperator(pool_key_hash=pool_key_hash)

    @pytest.fixture
    def transaction_id(self):
        """Create a test transaction ID"""
        return TransactionId.from_primitive(
            "1e043f100dce12d107f679685acd2fc0610e10f72a92d412794c9773d11d8477"
        )

    def test_network_urls(self, explorer):
        """Test that AdaStat has correct network URLs"""
        assert explorer._network_urls.mainnet == "https://adastat.net"
        assert explorer._network_urls.preprod is None
        assert explorer._network_urls.preview is None

    def test_view_account_mainnet(self, explorer, address):
        """Test view_account for mainnet"""
        url = explorer.view_account(address, Network.MAINNET)
        expected_stake_hash = address.staking_part.payload.hex()
        assert url == f"https://adastat.net/accounts/{expected_stake_hash}"

    def test_view_account_preprod_raises_error(self, explorer, address):
        """Test view_account raises error for preprod"""
        with pytest.raises(UnsupportedNetworkError):
            explorer.view_account(address, Network.PREPROD)

    def test_view_account_preview_raises_error(self, explorer, address):
        """Test view_account raises error for preview"""
        with pytest.raises(UnsupportedNetworkError):
            explorer.view_account(address, Network.PREVIEW)

    def test_view_address_mainnet(self, explorer, address):
        """Test view_address for mainnet"""
        url = explorer.view_address(address, Network.MAINNET)
        assert url == f"https://adastat.net/addresses/{address}"

    def test_view_address_preprod_raises_error(self, explorer, address):
        """Test view_address raises error for preprod"""
        with pytest.raises(UnsupportedNetworkError):
            explorer.view_address(address, Network.PREPROD)

    def test_view_block_mainnet(self, explorer):
        """Test view_block for mainnet"""
        block_id = "abc123"
        url = explorer.view_block(block_id, Network.MAINNET)
        assert url == "https://adastat.net/blocks/abc123"

    def test_view_block_preprod_raises_error(self, explorer):
        """Test view_block raises error for preprod"""
        with pytest.raises(UnsupportedNetworkError):
            explorer.view_block("abc123", Network.PREPROD)

    def test_view_pool_mainnet(self, explorer, pool_operator):
        """Test view_pool for mainnet"""
        url = explorer.view_pool(pool_operator, Network.MAINNET)
        expected_pool_hash = pool_operator.pool_key_hash.payload.hex()
        assert url == f"https://adastat.net/pools/{expected_pool_hash}"

    def test_view_pool_preprod_raises_error(self, explorer, pool_operator):
        """Test view_pool raises error for preprod"""
        with pytest.raises(UnsupportedNetworkError):
            explorer.view_pool(pool_operator, Network.PREPROD)

    def test_view_transaction_mainnet(self, explorer, transaction_id):
        """Test view_transaction for mainnet"""
        url = explorer.view_transaction(transaction_id, Network.MAINNET)
        expected_tx_hash = transaction_id.payload.hex()
        assert url == f"https://adastat.net/transactions/{expected_tx_hash}"

    def test_view_transaction_preprod_raises_error(self, explorer, transaction_id):
        """Test view_transaction raises error for preprod"""
        with pytest.raises(UnsupportedNetworkError):
            explorer.view_transaction(transaction_id, Network.PREPROD)


class TestCardanoScan:
    """Test CardanoScan blockchain explorer"""

    @pytest.fixture
    def explorer(self):
        """Create CardanoScan explorer instance"""
        return CardanoScan()

    @pytest.fixture
    def address(self):
        """Create a test address"""
        return Address.from_primitive(
            "addr1qx2fxv2umyhttkxyxp8x0dlpdt3k6cwng5pxj3jhsydzer3n0d3vllmyqwsx5wktcd8cc3sq835lu7drv2xwl2wywfgse35a3x"
        )

    @pytest.fixture
    def pool_operator(self):
        """Create a test pool operator"""
        pool_key_hash = PoolKeyHash.from_primitive(
            "00000036d515e12e18cd3c88c74f09a67984c2c279a5296aa96efe89"
        )
        return PoolOperator(pool_key_hash=pool_key_hash)

    @pytest.fixture
    def transaction_id(self):
        """Create a test transaction ID"""
        return TransactionId.from_primitive(
            "1e043f100dce12d107f679685acd2fc0610e10f72a92d412794c9773d11d8477"
        )

    def test_network_urls(self, explorer):
        """Test that CardanoScan has correct network URLs"""
        assert explorer._network_urls.mainnet == "https://cardanoscan.io"
        assert explorer._network_urls.preprod == "https://preprod.cardanoscan.io"
        assert explorer._network_urls.preview == "https://preview.cardanoscan.io"

    def test_view_account_mainnet(self, explorer, address):
        """Test view_account for mainnet"""
        url = explorer.view_account(address, Network.MAINNET)
        assert url == f"https://cardanoscan.io/stakeKey/{address}"

    def test_view_account_preprod(self, explorer, address):
        """Test view_account for preprod"""
        url = explorer.view_account(address, Network.PREPROD)
        assert url == f"https://preprod.cardanoscan.io/stakeKey/{address}"

    def test_view_account_preview(self, explorer, address):
        """Test view_account for preview"""
        url = explorer.view_account(address, Network.PREVIEW)
        assert url == f"https://preview.cardanoscan.io/stakeKey/{address}"

    def test_view_address_mainnet(self, explorer, address):
        """Test view_address for mainnet"""
        url = explorer.view_address(address, Network.MAINNET)
        assert url == f"https://cardanoscan.io/address/{address}"

    def test_view_address_preprod(self, explorer, address):
        """Test view_address for preprod"""
        url = explorer.view_address(address, Network.PREPROD)
        assert url == f"https://preprod.cardanoscan.io/address/{address}"

    def test_view_address_preview(self, explorer, address):
        """Test view_address for preview"""
        url = explorer.view_address(address, Network.PREVIEW)
        assert url == f"https://preview.cardanoscan.io/address/{address}"

    def test_view_block_mainnet(self, explorer):
        """Test view_block for mainnet with block number"""
        url = explorer.view_block("12345", Network.MAINNET)
        assert url == "https://cardanoscan.io/block/12345"

    def test_view_block_preprod(self, explorer):
        """Test view_block for preprod with block number"""
        url = explorer.view_block("12345", Network.PREPROD)
        assert url == "https://preprod.cardanoscan.io/block/12345"

    def test_view_block_preview(self, explorer):
        """Test view_block for preview with block number"""
        url = explorer.view_block("12345", Network.PREVIEW)
        assert url == "https://preview.cardanoscan.io/block/12345"

    def test_view_block_invalid_id_raises_error(self, explorer):
        """Test view_block raises ValueError for non-numeric block ID"""
        with pytest.raises(ValueError, match="Use block number for CardanoScan"):
            explorer.view_block("abc123", Network.MAINNET)

    def test_view_pool_mainnet(self, explorer, pool_operator):
        """Test view_pool for mainnet"""
        url = explorer.view_pool(pool_operator, Network.MAINNET)
        assert url == f"https://cardanoscan.io/pool/{pool_operator}"

    def test_view_pool_preprod(self, explorer, pool_operator):
        """Test view_pool for preprod"""
        url = explorer.view_pool(pool_operator, Network.PREPROD)
        assert url == f"https://preprod.cardanoscan.io/pool/{pool_operator}"

    def test_view_pool_preview(self, explorer, pool_operator):
        """Test view_pool for preview"""
        url = explorer.view_pool(pool_operator, Network.PREVIEW)
        assert url == f"https://preview.cardanoscan.io/pool/{pool_operator}"

    def test_view_transaction_mainnet(self, explorer, transaction_id):
        """Test view_transaction for mainnet"""
        url = explorer.view_transaction(transaction_id, Network.MAINNET)
        expected_tx_hash = transaction_id.payload.hex()
        assert url == f"https://cardanoscan.io/transaction/{expected_tx_hash}"

    def test_view_transaction_preprod(self, explorer, transaction_id):
        """Test view_transaction for preprod"""
        url = explorer.view_transaction(transaction_id, Network.PREPROD)
        expected_tx_hash = transaction_id.payload.hex()
        assert url == f"https://preprod.cardanoscan.io/transaction/{expected_tx_hash}"

    def test_view_transaction_preview(self, explorer, transaction_id):
        """Test view_transaction for preview"""
        url = explorer.view_transaction(transaction_id, Network.PREVIEW)
        expected_tx_hash = transaction_id.payload.hex()
        assert url == f"https://preview.cardanoscan.io/transaction/{expected_tx_hash}"


class TestCexplorer:
    """Test Cexplorer blockchain explorer"""

    @pytest.fixture
    def explorer(self):
        """Create Cexplorer explorer instance"""
        return Cexplorer()

    @pytest.fixture
    def address(self):
        """Create a test address"""
        return Address.from_primitive(
            "addr1qx2fxv2umyhttkxyxp8x0dlpdt3k6cwng5pxj3jhsydzer3n0d3vllmyqwsx5wktcd8cc3sq835lu7drv2xwl2wywfgse35a3x"
        )

    @pytest.fixture
    def pool_operator(self):
        """Create a test pool operator"""
        pool_key_hash = PoolKeyHash.from_primitive(
            "00000036d515e12e18cd3c88c74f09a67984c2c279a5296aa96efe89"
        )
        return PoolOperator(pool_key_hash=pool_key_hash)

    def test_network_urls(self, explorer):
        """Test that Cexplorer has correct network URLs"""
        assert explorer._network_urls.mainnet == "https://cexplorer.io"
        assert explorer._network_urls.preprod == "https://preprod.cexplorer.io"
        assert explorer._network_urls.preview == "https://preview.cexplorer.io"

    def test_view_account_mainnet(self, explorer, address):
        """Test view_account for mainnet"""
        url = explorer.view_account(address, Network.MAINNET)
        assert url == f"https://cexplorer.io/stake/{address}"

    def test_view_account_preprod(self, explorer, address):
        """Test view_account for preprod"""
        url = explorer.view_account(address, Network.PREPROD)
        assert url == f"https://preprod.cexplorer.io/stake/{address}"

    def test_view_account_preview(self, explorer, address):
        """Test view_account for preview"""
        url = explorer.view_account(address, Network.PREVIEW)
        assert url == f"https://preview.cexplorer.io/stake/{address}"

    def test_view_address_mainnet(self, explorer, address):
        """Test view_address for mainnet"""
        url = explorer.view_address(address, Network.MAINNET)
        assert url == f"https://cexplorer.io/address/{address}"

    def test_view_address_preprod(self, explorer, address):
        """Test view_address for preprod"""
        url = explorer.view_address(address, Network.PREPROD)
        assert url == f"https://preprod.cexplorer.io/address/{address}"

    def test_view_address_preview(self, explorer, address):
        """Test view_address for preview"""
        url = explorer.view_address(address, Network.PREVIEW)
        assert url == f"https://preview.cexplorer.io/address/{address}"

    def test_view_block_mainnet(self, explorer):
        """Test view_block for mainnet"""
        block_id = "abc123"
        url = explorer.view_block(block_id, Network.MAINNET)
        assert url == "https://cexplorer.io/block/abc123"

    def test_view_block_preprod(self, explorer):
        """Test view_block for preprod"""
        block_id = "abc123"
        url = explorer.view_block(block_id, Network.PREPROD)
        assert url == "https://preprod.cexplorer.io/block/abc123"

    def test_view_block_preview(self, explorer):
        """Test view_block for preview"""
        block_id = "abc123"
        url = explorer.view_block(block_id, Network.PREVIEW)
        assert url == "https://preview.cexplorer.io/block/abc123"

    def test_view_pool_mainnet(self, explorer, pool_operator):
        """Test view_pool for mainnet"""
        url = explorer.view_pool(pool_operator, Network.MAINNET)
        assert url == f"https://cexplorer.io/pool/{pool_operator}"

    def test_view_pool_preprod(self, explorer, pool_operator):
        """Test view_pool for preprod"""
        url = explorer.view_pool(pool_operator, Network.PREPROD)
        assert url == f"https://preprod.cexplorer.io/pool/{pool_operator}"

    def test_view_pool_preview(self, explorer, pool_operator):
        """Test view_pool for preview"""
        url = explorer.view_pool(pool_operator, Network.PREVIEW)
        assert url == f"https://preview.cexplorer.io/pool/{pool_operator}"

    def test_view_transaction_mainnet(self, explorer):
        """Test view_transaction for mainnet"""
        tx_hash = "1e043f100dce12d107f679685acd2fc0610e10f72a92d412794c9773d11d8477"
        url = explorer.view_transaction(tx_hash, Network.MAINNET)
        assert url == f"https://cexplorer.io/tx/{tx_hash}"

    def test_view_transaction_preprod(self, explorer):
        """Test view_transaction for preprod"""
        tx_hash = "1e043f100dce12d107f679685acd2fc0610e10f72a92d412794c9773d11d8477"
        url = explorer.view_transaction(tx_hash, Network.PREPROD)
        assert url == f"https://preprod.cexplorer.io/tx/{tx_hash}"

    def test_view_transaction_preview(self, explorer):
        """Test view_transaction for preview"""
        tx_hash = "1e043f100dce12d107f679685acd2fc0610e10f72a92d412794c9773d11d8477"
        url = explorer.view_transaction(tx_hash, Network.PREVIEW)
        assert url == f"https://preview.cexplorer.io/tx/{tx_hash}"


class TestEutxo:
    """Test Eutxo blockchain explorer"""

    @pytest.fixture
    def explorer(self):
        """Create Eutxo explorer instance"""
        return Eutxo()

    @pytest.fixture
    def address(self):
        """Create a test address"""
        return Address.from_primitive(
            "addr1qx2fxv2umyhttkxyxp8x0dlpdt3k6cwng5pxj3jhsydzer3n0d3vllmyqwsx5wktcd8cc3sq835lu7drv2xwl2wywfgse35a3x"
        )

    @pytest.fixture
    def pool_operator(self):
        """Create a test pool operator"""
        pool_key_hash = PoolKeyHash.from_primitive(
            "00000036d515e12e18cd3c88c74f09a67984c2c279a5296aa96efe89"
        )
        return PoolOperator(pool_key_hash=pool_key_hash)

    def test_network_urls(self, explorer):
        """Test that Eutxo has correct network URLs"""
        assert explorer._network_urls.mainnet == "https://eutxo.org"
        assert explorer._network_urls.preprod is None
        assert explorer._network_urls.preview is None

    def test_view_account_not_implemented(self, explorer, address):
        """Test that view_account raises NotImplementedError"""
        with pytest.raises(NotImplementedError, match="view_account not implemented"):
            explorer.view_account(address, Network.MAINNET)

    def test_view_address_not_implemented(self, explorer, address):
        """Test that view_address raises NotImplementedError"""
        with pytest.raises(NotImplementedError, match="view_address not implemented"):
            explorer.view_address(address, Network.MAINNET)

    def test_view_block_mainnet(self, explorer):
        """Test view_block for mainnet"""
        block_id = "abc123"
        url = explorer.view_block(block_id, Network.MAINNET)
        assert url == "https://eutxo.org/block/abc123"

    def test_view_block_preprod_raises_error(self, explorer):
        """Test view_block raises error for preprod"""
        with pytest.raises(UnsupportedNetworkError):
            explorer.view_block("abc123", Network.PREPROD)

    def test_view_pool_not_implemented(self, explorer, pool_operator):
        """Test that view_pool raises NotImplementedError"""
        with pytest.raises(NotImplementedError, match="view_pool not implemented"):
            explorer.view_pool(pool_operator, Network.MAINNET)

    def test_view_transaction_mainnet(self, explorer):
        """Test view_transaction for mainnet"""
        tx_hash = "1e043f100dce12d107f679685acd2fc0610e10f72a92d412794c9773d11d8477"
        url = explorer.view_transaction(tx_hash, Network.MAINNET)
        assert url == f"https://eutxo.org/transaction/{tx_hash}"

    def test_view_transaction_preprod_raises_error(self, explorer):
        """Test view_transaction raises error for preprod"""
        with pytest.raises(UnsupportedNetworkError):
            explorer.view_transaction("abc123", Network.PREPROD)


class TestPoolTool:
    """Test PoolTool blockchain explorer"""

    @pytest.fixture
    def explorer(self):
        """Create PoolTool explorer instance"""
        return PoolTool()

    @pytest.fixture
    def address(self):
        """Create a test address"""
        return Address.from_primitive(
            "addr1qx2fxv2umyhttkxyxp8x0dlpdt3k6cwng5pxj3jhsydzer3n0d3vllmyqwsx5wktcd8cc3sq835lu7drv2xwl2wywfgse35a3x"
        )

    @pytest.fixture
    def pool_operator(self):
        """Create a test pool operator"""
        pool_key_hash = PoolKeyHash.from_primitive(
            "00000036d515e12e18cd3c88c74f09a67984c2c279a5296aa96efe89"
        )
        return PoolOperator(pool_key_hash=pool_key_hash)

    @pytest.fixture
    def transaction_id(self):
        """Create a test transaction ID"""
        return TransactionId.from_primitive(
            "1e043f100dce12d107f679685acd2fc0610e10f72a92d412794c9773d11d8477"
        )

    def test_network_urls(self, explorer):
        """Test that PoolTool has correct network URLs"""
        assert explorer._network_urls.mainnet == "https://pooltool.io"
        assert explorer._network_urls.preprod is None
        assert explorer._network_urls.preview is None

    def test_view_account_mainnet(self, explorer, address):
        """Test view_account for mainnet"""
        url = explorer.view_account(address, Network.MAINNET)
        # Note: PoolTool uses address.p attribute
        assert (
            url == f"https://pooltool.io/address/{address.staking_part.payload.hex()}"
        )

    def test_view_account_preprod_raises_error(self, explorer, address):
        """Test view_account raises error for preprod"""
        with pytest.raises(UnsupportedNetworkError):
            explorer.view_account(address, Network.PREPROD)

    def test_view_address_not_implemented(self, explorer, address):
        """Test that view_address raises NotImplementedError"""
        with pytest.raises(NotImplementedError, match="view_address not implemented"):
            explorer.view_address(address, Network.MAINNET)

    def test_view_block_mainnet(self, explorer):
        """Test view_block for mainnet with block number"""
        url = explorer.view_block("12345", Network.MAINNET)
        assert url == "https://pooltool.io/realtime/12345"

    def test_view_block_invalid_id_raises_error(self, explorer):
        """Test view_block raises ValueError for non-numeric block ID"""
        with pytest.raises(ValueError, match="Use block number for PoolTool"):
            explorer.view_block("abc123", Network.MAINNET)

    def test_view_block_preprod_raises_error(self, explorer):
        """Test view_block raises error for preprod"""
        with pytest.raises(UnsupportedNetworkError):
            explorer.view_block("12345", Network.PREPROD)

    def test_view_pool_mainnet(self, explorer, pool_operator):
        """Test view_pool for mainnet"""
        url = explorer.view_pool(pool_operator, Network.MAINNET)
        expected_pool_hash = pool_operator.pool_key_hash.payload.hex()
        assert url == f"https://pooltool.io/pool/{expected_pool_hash}/epochs"

    def test_view_pool_preprod_raises_error(self, explorer, pool_operator):
        """Test view_pool raises error for preprod"""
        with pytest.raises(UnsupportedNetworkError):
            explorer.view_pool(pool_operator, Network.PREPROD)

    def test_view_transaction_not_implemented(self, explorer, transaction_id):
        """Test that view_transaction raises NotImplementedError"""
        with pytest.raises(
            NotImplementedError, match="view_transaction not implemented"
        ):
            explorer.view_transaction(transaction_id, Network.MAINNET)
