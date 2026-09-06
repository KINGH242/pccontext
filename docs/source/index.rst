pccontext
=========

**Chain contexts for** `PyCardano <https://github.com/Python-Cardano/pycardano>`_.

``pccontext`` supplies a family of :class:`~pccontext.backend.base.ChainContext`
implementations that plug into PyCardano's transaction builder, along with a set
of higher-level helpers for building the staking and governance transactions that
PyCardano leaves to the caller.

It exists for three reasons:

* **More backends.** Koios, Yaci DevKit and an offline transfer file have no
  equivalent in PyCardano.
* **Richer chain data.** ``pccontext`` models the full Conway-era protocol
  parameter set and the complete genesis files, not just the subset the
  transaction builder needs.
* **Stake and governance state.** Every context here answers
  :meth:`~pccontext.backend.base.ChainContext.stake_address_info`, which reports
  registration, rewards, pool delegation and DRep vote delegation for a stake
  address. PyCardano has no equivalent method.

If you are already using a PyCardano chain context and want to know what changes,
start with :doc:`differences`.

.. code-block:: python

   from pccontext import KoiosChainContext

   context = KoiosChainContext()

   print(context.epoch)
   print(context.protocol_param.min_fee_coefficient)
   print(context.stake_address_info("stake1u9...")[0].reward_account_balance)

.. toctree::
   :maxdepth: 2
   :caption: Guide

   installation
   differences
   chain_contexts
   transactions

.. toctree::
   :maxdepth: 2
   :caption: Reference

   api/index

Indices
-------

* :ref:`genindex`
* :ref:`modindex`
