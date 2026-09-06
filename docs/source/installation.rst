Installation
============

``pccontext`` requires Python 3.10 or newer.

.. code-block:: bash

   pip install pccontext

Or with Poetry:

.. code-block:: bash

   poetry add pccontext

PyCardano is installed as a dependency, so you do not need to require it
separately unless you import from it directly.

Backend requirements
--------------------

The library itself has no optional extras — every context is importable from a
default install — but most contexts talk to something that you have to supply.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Context
     - What you need
   * - :class:`~pccontext.backend.blockfrost.BlockFrostChainContext`
     - A Blockfrost project ID from https://blockfrost.io.
   * - :class:`~pccontext.backend.koios.KoiosChainContext`
     - Nothing. An API key raises the rate limit but is optional.
   * - :class:`~pccontext.backend.ogmios.OgmiosChainContext`
     - A running Ogmios server (v6) in front of a Cardano node.
   * - :class:`~pccontext.backend.kupo.KupoChainContextExtension`
     - A running Kupo instance, plus another context to wrap.
   * - :class:`~pccontext.backend.cardano_cli.CardanoCliChainContext`
     - A local ``cardano-cli`` binary and node socket, or a Docker container
       running them.
   * - :class:`~pccontext.backend.yaci_devkit.YaciDevkitChainContext`
     - A running `Yaci DevKit <https://devkit.yaci.xyz/>`_ instance.
   * - :class:`~pccontext.backend.offline_transfer_file.OfflineTransferFileContext`
     - A JSON transfer file produced on an online machine. No network access.

Verifying the install
---------------------

.. code-block:: python

   import pccontext

   print(pccontext.__version__)
