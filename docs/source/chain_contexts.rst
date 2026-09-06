Chain contexts
==============

Every context in this library implements the same interface, so the choice
between them is about where your chain data comes from, not about what you can do
with it once you have one.

.. contents::
   :local:
   :depth: 1

Choosing a context
------------------

.. list-table::
   :header-rows: 1
   :widths: 26 40 34

   * - Context
     - Use it when
     - Runs against
   * - :ref:`Blockfrost <ctx-blockfrost>`
     - You want a hosted API and are happy to register for a key.
     - Hosted service
   * - :ref:`Koios <ctx-koios>`
     - You want a hosted API with no signup.
     - Hosted service
   * - :ref:`Ogmios <ctx-ogmios>`
     - You run your own node and want a live WebSocket connection.
     - Your own node
   * - :ref:`Kupo <ctx-kupo>`
     - Ogmios UTxO queries are too slow; you need an index.
     - Your own node
   * - :ref:`cardano-cli <ctx-cardano-cli>`
     - You have a node socket and prefer shelling out to the CLI.
     - Your own node
   * - :ref:`Yaci DevKit <ctx-yaci-devkit>`
     - You are testing against a local devnet.
     - Local devnet
   * - :ref:`Offline transfer file <ctx-offline-transfer-file>`
     - The signing machine has no network at all.
     - A JSON file

A note on the ``network`` argument
----------------------------------

The contexts do not agree on how the network is specified, because each follows
the convention of the service behind it. This trips people up, so it is worth
stating plainly:

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Context
     - ``network`` argument
   * - ``BlockFrostChainContext``, ``CardanoCliChainContext``
     - :class:`pccontext.Network` — ``MAINNET``, ``PREPROD``, ``PREVIEW``,
       ``SANCHONET``, ``GUILDNET``, ``CUSTOM``
   * - ``OgmiosChainContext``
     - :class:`pycardano.Network` — ``MAINNET`` or ``TESTNET`` only
   * - ``KoiosChainContext``
     - a plain string, ``"mainnet"`` by default
   * - ``KupoChainContextExtension``, ``YaciDevkitChainContext``, ``OfflineTransferFileContext``
     - none — taken from the wrapped context, the devnet, or the file

The read-only ``.network`` property always returns a
:class:`pycardano.Network`, whichever context you are on, because that is what
PyCardano's transaction builder expects.

.. _ctx-blockfrost:

Blockfrost
----------

A wrapper around the `Blockfrost <https://blockfrost.io/>`_ API. Needs a project
ID, which is free for the standard tier.

.. code-block:: python

   from pccontext import BlockFrostChainContext, Network

   context = BlockFrostChainContext(
       project_id="your_project_id",
       network=Network.MAINNET,
   )

The project ID is scoped to one network by Blockfrost, so it must match the
``network`` you pass. Pass ``base_url`` to point at a self-hosted deployment;
otherwise the URL is derived from ``network``.

.. _ctx-koios:

Koios
-----

A wrapper around `Koios <https://api.koios.rest/>`_, a community-run public API.
The distinguishing feature is that it needs no credentials at all:

.. code-block:: python

   from pccontext import KoiosChainContext

   context = KoiosChainContext()

An API key raises your rate limit but is optional:

.. code-block:: python

   context = KoiosChainContext(
       api_key="your_api_key",
       network="mainnet",
       endpoint="https://api.koios.rest/api/v1/",
   )

For a testnet, point ``endpoint`` at that network's Koios deployment and set
``network`` to a value other than ``"mainnet"`` — any other string is treated as
a testnet when the ``.network`` property is derived.

Koios has no PyCardano equivalent.

.. _ctx-ogmios:

Ogmios
------

Talks to an `Ogmios <https://ogmios.dev/>`_ server (**v6**) in front of your own
Cardano node.

.. code-block:: python

   from pccontext import OgmiosChainContext

   context = OgmiosChainContext(host="localhost", port=1337)

For a secure connection and explicit network:

.. code-block:: python

   from pycardano import Network

   context = OgmiosChainContext(
       host="ogmios.example.com",
       port=443,
       secure=True,
       network=Network.MAINNET,
   )

.. note::

   This context is v6-only. For Ogmios v5, use PyCardano's
   ``OgmiosV5ChainContext``.

Results are cached to avoid hammering the node. ``refetch_chain_tip_interval``
controls how often the chain tip is re-read (it defaults to roughly half the
expected block time derived from genesis), while ``utxo_cache_size`` and
``datum_cache_size`` bound the UTxO and datum caches.

.. _ctx-kupo:

Kupo
----

`Kupo <https://cardanosolutions.github.io/kupo/>`_ is a fast chain indexer. It
does not provide protocol parameters or submit transactions, so this context is
an *extension*: it wraps another context and takes over only the UTxO and datum
queries.

.. code-block:: python

   from pccontext import OgmiosChainContext, KupoChainContextExtension

   context = KupoChainContextExtension(
       wrapped_backend=OgmiosChainContext(host="localhost", port=1337),
       kupo_url="http://localhost:1442",
   )

Any context can be wrapped, not just Ogmios. Everything the extension does not
handle is delegated to the wrapped context, including
``stake_address_info``.

If ``kupo_url`` is omitted, queries fall through to the wrapped backend, which
makes it safe to construct the extension unconditionally and enable Kupo by
configuration.

.. _ctx-cardano-cli:

cardano-cli
-----------

Shells out to a local ``cardano-cli`` against a node socket. This is the context
with the most direct view of the node — it is the one that reports the full
genesis and the complete protocol parameter set without an intermediary.

.. code-block:: python

   from pathlib import Path
   from pccontext import CardanoCliChainContext, Network

   context = CardanoCliChainContext(
       binary=Path("/usr/local/bin/cardano-cli"),
       socket=Path("/run/cardano/node.socket"),
       config_file=Path("/etc/cardano/config.json"),
       network=Network.MAINNET,
   )

If the node runs in Docker, pass a
:class:`~pccontext.backend.cardano_cli.DockerConfig` instead of a local socket
and the commands are executed inside the container:

.. code-block:: python

   from pccontext import CardanoCliChainContext, DockerConfig, Network

   context = CardanoCliChainContext(
       binary=Path("cardano-cli"),
       socket=Path("/ipc/node.socket"),
       config_file=Path("/config/config.json"),
       network=Network.MAINNET,
       docker_config=DockerConfig(container_name="cardano-node"),
   )

Use ``Network.CUSTOM`` together with ``network_magic_number`` for a private
network.

This context evaluates Plutus script execution costs through the CLI, so
``evaluate_tx`` works without a separate evaluation service.

.. _ctx-yaci-devkit:

Yaci DevKit
-----------

`Yaci DevKit <https://devkit.yaci.xyz/>`_ runs a disposable local Cardano devnet,
which makes it the quickest way to exercise real transactions in tests.

.. code-block:: python

   from pccontext import YaciDevkitChainContext

   context = YaciDevkitChainContext(api_url="http://localhost:8080")

The devnet reports its own network parameters, so there is no ``network``
argument. Yaci DevKit has no PyCardano equivalent.

.. _ctx-offline-transfer-file:

Offline transfer file
---------------------

For air-gapped signing. Instead of reaching the network, this context reads chain
data from a JSON file produced on an online machine, and "submitting" a
transaction appends it to that file for you to carry back.

.. code-block:: python

   from pathlib import Path
   from pccontext import OfflineTransferFileContext

   context = OfflineTransferFileContext(
       offline_transfer_file=Path("offline-transfer.json"),
   )

``submit_tx_cbor`` does not talk to a node. It records the signed transaction in
the file, along with a history entry, and writes the file back to disk. Move the
file to an online machine to submit for real.

Protocol parameters, genesis parameters and UTxOs are served from whatever the
file contains, so it is only as fresh as the last time it was updated online. The
transaction builder cannot know this, so a stale file yields a transaction that
is rejected at submission — refresh the file before signing anything
fee-sensitive.

This context has no PyCardano equivalent.

Extended queries
----------------

Beyond PyCardano's interface, every context here also answers stake, pool and
governance queries. Each has a default implementation on
:class:`~pccontext.backend.base.ChainContext` that raises
:class:`NotImplementedError` naming the context, so a backend implements only
what the service behind it can answer:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Query
     - Returns
   * - ``era``
     - The era the chain is in, as an :class:`~pccontext.enums.Era`.
   * - ``chain_tip``
     - :class:`~pccontext.models.chain_tip_model.ChainTip` — slot, block hash
       and height of the latest block.
   * - ``utxo(tx_input)``
     - A single UTxO and whether it has been spent, or ``None``.
   * - ``stake_address_info(addr)``
     - Registration, rewards, pool and DRep delegation for a stake address.
   * - ``stake_pools()``
     - Every registered pool.
   * - ``stake_pool_info(pool_id, strict)``
     - :class:`~pccontext.models.stake_pool_info_model.StakePoolInfo` — the
       pool's registered parameters and stake figures.
   * - ``kes_period_info(pool, op_cert)``
     - :class:`~pccontext.models.kes_period_info_model.KESPeriodInfo` — the
       counters needed to decide whether to rotate an operational certificate.
   * - ``treasury()``
     - The treasury balance in lovelace.
   * - ``drep_info(drep)``
     - A DRep's registration and voting power.
   * - ``gov_action_info(id)``
     - A governance action's lifecycle information.
   * - ``gov_action_votes(id)``
     - The action plus every vote against it, split by voter class.
   * - ``gov_actions_all()``
     - The same, for every active proposal.
   * - ``committee_member_info(cold=, hot=)``
     - A committee member's authorization and term.
   * - ``committee_state()``
     - Every member plus the active quorum threshold.
   * - ``drep_stake_distribution()``
     - Stake behind each DRep this epoch.
   * - ``spo_stake_distribution()``
     - Stake behind each pool this epoch.

Which backend answers what
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 26 11 9 11 9 8 8 9

   * - Query
     - cardano-cli
     - Koios
     - Blockfrost
     - Ogmios
     - Kupo
     - Yaci
     - Offline
   * - ``era``
     - yes
     - yes
     - yes
     - yes
     - via wrapped
     - \-
     - yes
   * - ``chain_tip``
     - yes
     - yes
     - yes
     - yes
     - via wrapped
     - \-
     - \-
   * - ``utxo``
     - yes
     - yes
     - yes
     - yes
     - via wrapped
     - \-
     - \-
   * - ``stake_pools``
     - yes
     - yes
     - yes
     - yes
     - via wrapped
     - \-
     - \-
   * - ``stake_pool_info``
     - yes
     - yes
     - yes
     - yes
     - via wrapped
     - \-
     - \-
   * - ``kes_period_info``
     - yes
     - yes
     - yes
     - \-
     - via wrapped
     - \-
     - \-
   * - ``treasury``
     - yes
     - yes
     - yes
     - yes
     - via wrapped
     - \-
     - \-
   * - ``drep_info``
     - yes
     - \-
     - yes
     - \-
     - via wrapped
     - \-
     - \-
   * - ``gov_action_info``
     - yes
     - \-
     - yes
     - \-
     - via wrapped
     - \-
     - \-
   * - ``gov_action_votes``
     - yes
     - \-
     - yes
     - \-
     - via wrapped
     - \-
     - \-
   * - ``gov_actions_all``
     - yes
     - \-
     - yes
     - \-
     - via wrapped
     - \-
     - \-
   * - ``committee_member_info``
     - yes
     - \-
     - \-
     - yes
     - via wrapped
     - \-
     - \-
   * - ``committee_state``
     - yes
     - \-
     - \-
     - yes
     - via wrapped
     - \-
     - \-
   * - ``drep_stake_distribution``
     - yes
     - \-
     - yes
     - \-
     - via wrapped
     - \-
     - \-
   * - ``spo_stake_distribution``
     - yes
     - \-
     - yes
     - yes
     - via wrapped
     - \-
     - \-

``cardano-cli`` answers all fifteen because it talks straight to a node socket.

Blockfrost covers most of Conway governance since ``blockfrost-python`` 0.7.0,
which added the DRep and proposal endpoints. One gap remains: 0.7.0 wraps no
committee endpoint even though the Blockfrost API has
``/governance/committee``.

Koios and Ogmios stop earlier, and in both cases the limit is the client
library rather than the service. ``koios-python`` 2.0.0 wraps none of Koios'
governance endpoints — ``/drep_info``, ``/committee_info``, ``/proposal_list``
and ``/proposal_votes`` all exist and answer — and the installed ``ogmios``
client has no binding for ``governanceProposals``,
``delegateRepresentatives`` or ``operationalCertificates``.

Kupo delegates everything to the context it wraps, so its row is whatever that
backend supports.

Because unsupported queries raise rather than return ``None``, code that must
work across backends should either catch :class:`NotImplementedError` or pick a
backend it knows can answer:

.. code-block:: python

   try:
       state = context.committee_state()
   except NotImplementedError:
       state = None  # this backend cannot answer; fall back

Identifying a context
---------------------

Two properties describe a context itself rather than the chain:

.. code-block:: python

   context.name           # "Koios", "CardanoCli", ...
   context.context_type   # ContextType.ONLINE or ContextType.OFFLINE

``context_type`` is what distinguishes a context that reaches the network from
one answering out of a captured file, which matters when the freshness of an
answer affects whether a transaction will be accepted.

What every context supports
---------------------------

All seven implement the full PyCardano interface. The differences below are the
ones worth knowing:

.. list-table::
   :header-rows: 1
   :widths: 26 18 18 38

   * - Context
     - ``evaluate_tx``
     - ``submit_tx``
     - Notes
   * - Blockfrost
     - yes
     - yes
     -
   * - Koios
     - yes
     - yes
     -
   * - Ogmios
     - yes
     - yes
     -
   * - Kupo
     - delegated
     - delegated
     - Overrides UTxO and datum queries only.
   * - cardano-cli
     - yes
     - yes
     - Evaluation runs through the CLI.
   * - Yaci DevKit
     - yes
     - yes
     - ``genesis_param`` and ``last_block_slot`` come from the base class.
   * - Offline transfer file
     - no
     - writes to file
     - Submission appends to the JSON file instead of the network.

Using a context with PyCardano
------------------------------

A ``pccontext`` context is a PyCardano chain context, so it goes straight into
the transaction builder:

.. code-block:: python

   from pycardano import Address, TransactionBuilder, TransactionOutput
   from pccontext import KoiosChainContext

   context = KoiosChainContext()

   builder = TransactionBuilder(context)
   builder.add_input_address(Address.from_primitive("addr1..."))
   builder.add_output(
       TransactionOutput(Address.from_primitive("addr1..."), 2_000_000)
   )

   signed = builder.build_and_sign([signing_key], change_address=my_address)
   context.submit_tx(signed)
