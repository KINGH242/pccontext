"""OgmiosChainContext against a live Ogmios v7 server on preview.

Skipped unless ``PCCONTEXT_OGMIOS_URL`` is set, for example::

    PCCONTEXT_OGMIOS_URL=ws://localhost:1337 pytest tests/backend/test_ogmios_live.py

Everything here only reads, except the submission test, which submits an
unsigned transaction for the ledger to reject.
"""

import os
from fractions import Fraction

import pyogmios
import pytest
from pycardano import (
    Address,
    PoolOperator,
    Transaction,
    TransactionBuilder,
    TransactionOutput,
    TransactionWitnessSet,
)
from pycardano.backend.base import GenesisParameters as PyCardanoGenesisParameters
from pycardano.backend.base import ProtocolParameters as PyCardanoProtocolParameters
from pyogmios.errors import MissingSignatoriesError

from pccontext import OgmiosChainContext
from pccontext.enums import Era

URL = os.environ.get("PCCONTEXT_OGMIOS_URL")
#: A preview address with key-locked UTxOs to build the rejected transaction from.
ADDRESS = os.environ.get(
    "PCCONTEXT_OGMIOS_ADDRESS",
    "addr_test1vpy494af9z9th4anvcjnp8pxfsyfmkakqshaw6v784qph9qtutwc9",
)

pytestmark = pytest.mark.skipif(not URL, reason="PCCONTEXT_OGMIOS_URL is not set")


@pytest.fixture(scope="module")
def live():
    with OgmiosChainContext(client=pyogmios.Client(URL)) as context:
        yield context


def test_protocol_and_genesis_parameters(live):
    params = live.protocol_param
    assert type(params) is PyCardanoProtocolParameters
    assert isinstance(params.pool_influence, Fraction)
    assert set(params.min_fee_reference_scripts) == {"range", "base", "multiplier"}
    assert "bytes" in params.maximum_reference_scripts_size
    assert set(params.cost_models) >= {"PlutusV1", "PlutusV2", "PlutusV3"}

    genesis = live.genesis_param
    assert type(genesis) is PyCardanoGenesisParameters
    assert isinstance(genesis.system_start, int)
    assert genesis.slot_length == 1


def test_chain_state(live):
    tip = live.chain_tip
    assert tip.slot > 0 and tip.block > 0
    assert tip.era == Era.CONWAY
    assert live.treasury() > 0


def test_stake_pools_and_governance(live):
    pools = live.stake_pools()
    assert pools
    distribution = live.spo_stake_distribution()
    pool_id = max(distribution, key=lambda entry: entry.stake).pool_id

    info = live.stake_pool_info(pool_id)
    assert info.active_stake and info.active_size

    kes = live.kes_period_info(PoolOperator.from_primitive(pool_id))
    assert kes.next_chain_op_cert_count == kes.on_chain_op_cert_count + 1

    assert live.committee_state().members
    for action in live.gov_actions_all()[:3]:
        assert live.gov_action_info(action.gov_action_id).proposed_in is not None
    assert live.drep_stake_distribution()


def test_one_connection_serves_every_query(live):
    live.epoch
    live.last_block_slot
    assert live.client.generation == 1


def test_an_unsigned_transaction_is_rejected_for_its_signatures_only(live):
    address = Address.from_primitive(ADDRESS)
    utxos = live.utxos(address)
    if not utxos:
        pytest.skip(f"no UTxOs at {ADDRESS}")

    builder = TransactionBuilder(live)
    builder.add_input(max(utxos, key=lambda utxo: utxo.output.amount.coin))
    builder.add_output(TransactionOutput(address, 2_000_000))
    body = builder.build(change_address=address)
    transaction = Transaction(body, TransactionWitnessSet())

    assert live.evaluate_tx_cbor(transaction.to_cbor()) == {}
    # The ledger reports every rule a transaction breaks. Missing signatures
    # alone means the fee and the parameters it was computed from were right.
    with pytest.raises(MissingSignatoriesError):
        live.submit_tx_cbor(transaction.to_cbor())
