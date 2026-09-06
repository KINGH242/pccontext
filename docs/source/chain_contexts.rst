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

What every context supports
---------------------------

All seven implement the full interface. The differences below are the ones worth
knowing:

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
