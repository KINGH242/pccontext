"""Tests for the extended ChainContext interface and its defaults."""

import pytest

from pccontext import ChainContext
from pccontext.enums import ContextType

# Every query the base declares, with the arguments needed to call it. Kept as
# data so a new method added to the base without a default is caught here.
QUERIES = [
    ("stake_address_info", ("stake1u9test",)),
    ("utxo", (None,)),
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
]

PROPERTIES = ["era", "chain_tip"]


class TestBaseChainContextDefaults:
    @pytest.mark.parametrize("method,args", QUERIES)
    def test_query_raises_not_implemented(self, method, args):
        context = ChainContext()
        with pytest.raises(NotImplementedError) as exc:
            getattr(context, method)(*args)
        assert method in str(exc.value)

    @pytest.mark.parametrize("prop", PROPERTIES)
    def test_property_raises_not_implemented(self, prop):
        context = ChainContext()
        with pytest.raises(NotImplementedError) as exc:
            getattr(context, prop)
        assert prop in str(exc.value)

    def test_error_names_the_context(self):
        """The message identifies which context lacks the method, which is the
        whole point of routing it through `name`."""

        class MyContext(ChainContext):
            @property
            def name(self) -> str:
                return "MyBackend"

        with pytest.raises(NotImplementedError, match="MyBackend"):
            MyContext().treasury()

    def test_name_defaults_to_class_name(self):
        assert ChainContext().name == "ChainContext"

    def test_context_type_defaults_to_online(self):
        assert ChainContext().context_type == ContextType.ONLINE


class TestBackendIdentity:
    """Every shipped backend should identify itself and its type."""

    def test_all_backends_declare_name_and_type(self):
        from pccontext import (
            BlockFrostChainContext,
            CardanoCliChainContext,
            KoiosChainContext,
            KupoChainContextExtension,
            OfflineTransferFileContext,
            OgmiosChainContext,
            YaciDevkitChainContext,
        )

        expected = {
            BlockFrostChainContext: ("Blockfrost", ContextType.ONLINE),
            CardanoCliChainContext: ("CardanoCli", ContextType.ONLINE),
            KoiosChainContext: ("Koios", ContextType.ONLINE),
            KupoChainContextExtension: ("Kupo", ContextType.ONLINE),
            OgmiosChainContext: ("Ogmios", ContextType.ONLINE),
            YaciDevkitChainContext: ("YaciDevkit", ContextType.ONLINE),
            OfflineTransferFileContext: (
                "OfflineTransferFile",
                ContextType.OFFLINE,
            ),
        }

        for cls, (name, context_type) in expected.items():
            assert cls.name.fget(None) == name
            assert cls.context_type.fget(None) == context_type
