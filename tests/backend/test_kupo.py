from unittest.mock import MagicMock, PropertyMock

import pytest
from pycardano import Network

from pccontext import ChainContext, KupoChainContextExtension


def test_kupo_chain_context(ogmios_chain_context):
    chain_context = KupoChainContextExtension(wrapped_backend=ogmios_chain_context)
    assert chain_context.network == Network.TESTNET


class TestKupoDelegatesExtendedQueries:
    """Kupo indexes UTxOs and datums only. Every chain, pool and governance
    query must reach the wrapped backend rather than raise on its own."""

    DELEGATED_METHODS = [
        ("stake_pools", ()),
        ("stake_pool_info", ("pool1test",)),
        ("kes_period_info", ()),
        ("treasury", ()),
        ("drep_info", (None,)),
        ("gov_action_info", (None,)),
        ("gov_action_votes", (None,)),
        ("gov_actions_all", ()),
        ("committee_member_info", ()),
        ("committee_state", ()),
        ("drep_stake_distribution", ()),
        ("spo_stake_distribution", ()),
        ("utxo", (None,)),
    ]

    @pytest.mark.parametrize("method,args", DELEGATED_METHODS)
    def test_method_delegates_to_wrapped_backend(self, method, args):
        wrapped = MagicMock(spec=ChainContext)
        context = KupoChainContextExtension(wrapped_backend=wrapped)

        result = getattr(context, method)(*args)

        called = getattr(wrapped, method)
        called.assert_called_once()
        assert result is called.return_value

    @pytest.mark.parametrize("prop", ["era", "chain_tip"])
    def test_property_delegates_to_wrapped_backend(self, prop):
        wrapped = MagicMock(spec=ChainContext)
        sentinel = object()
        setattr(type(wrapped), prop, PropertyMock(return_value=sentinel))

        context = KupoChainContextExtension(wrapped_backend=wrapped)
        assert getattr(context, prop) is sentinel

    def test_unsupported_query_surfaces_the_wrapped_backends_error(self):
        """Delegation must not mask the wrapped backend's NotImplementedError."""
        context = KupoChainContextExtension(wrapped_backend=ChainContext())
        with pytest.raises(NotImplementedError, match="treasury"):
            context.treasury()
