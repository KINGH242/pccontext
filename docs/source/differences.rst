Differences from PyCardano's chain contexts
===========================================

PyCardano ships its own chain contexts in :mod:`pycardano.backend`. ``pccontext``
does not replace them so much as widen them: it adds backends PyCardano does not
have, extends the interface with stake and governance state, and returns much
more complete protocol and genesis data.

This page is the map between the two.

At a glance
-----------

.. list-table::
   :header-rows: 1
   :widths: 34 33 33

   * -
     - PyCardano
     - pccontext
   * - Blockfrost
     - ``BlockFrostChainContext``
     - ``BlockFrostChainContext``
   * - Ogmios (v6)
     - ``OgmiosV6ChainContext``
     - ``OgmiosChainContext``
   * - Ogmios (v5)
     - ``OgmiosV5ChainContext``
     - *not provided*
   * - Kupo
     - ``KupoChainContextExtension``, ``KupoOgmiosV6ChainContext``
     - ``KupoChainContextExtension``
   * - ``cardano-cli``
     - ``CardanoCliChainContext``
     - ``CardanoCliChainContext``
   * - Koios
     - *not provided*
     - ``KoiosChainContext``
   * - Yaci DevKit
     - *not provided*
     - ``YaciDevkitChainContext``
   * - Offline transfer file
     - *not provided*
     - ``OfflineTransferFileContext``

.. warning::

   Four names are shared between the two packages —
   ``BlockFrostChainContext``, ``CardanoCliChainContext``,
   ``OgmiosChainContext`` and ``KupoChainContextExtension``. They are *different
   classes* with different constructor signatures. If you import from both
   packages in one module, alias one of them:

   .. code-block:: python

      from pccontext import BlockFrostChainContext
      from pycardano.backend import BlockFrostChainContext as PyCardanoBlockFrost

   Note also that ``OgmiosChainContext`` means different things in each package:
   in PyCardano it is an alias for the v6 context, and in ``pccontext`` it is the
   only Ogmios context there is.

The interface is one method wider
---------------------------------

:class:`pccontext.backend.base.ChainContext` subclasses
:class:`pycardano.backend.base.ChainContext` and adds a single method:

.. code-block:: python

   def stake_address_info(self, stake_address: str) -> List[StakeAddressInfo]:
       ...

Every context in this library implements it. It returns registration status,
rewards balance, deposit, pool delegation and DRep vote delegation for a stake
address:

.. code-block:: python

   info = context.stake_address_info("stake1u9...")[0]

   info.active                   # registered on-chain?
   info.active_epoch             # epoch the registration became active
   info.reward_account_balance   # withdrawable rewards, in lovelace
   info.delegation_deposit       # the deposit held for the registration
   info.stake_delegation         # pool ID, or None
   info.vote_delegation          # DRep, or None
   info.delegate_representative  # the full DRep record, where available

This is what the staking and governance helpers in :doc:`transactions` use to
refuse invalid transactions before they are built — registering an
already-registered address, delegating from an unregistered one, and so on.

Everything else on the interface — ``utxos``, ``submit_tx``, ``submit_tx_cbor``,
``evaluate_tx``, ``evaluate_tx_cbor``, ``epoch``, ``last_block_slot``,
``network``, ``protocol_param``, ``genesis_param`` — keeps PyCardano's semantics,
so these contexts drop into
:class:`~pycardano.txbuilder.TransactionBuilder` unchanged.

Protocol parameters are much more complete
------------------------------------------

PyCardano's :class:`~pycardano.backend.base.ProtocolParameters` carries the
roughly thirty fields the transaction builder needs to compute a fee. The
``pccontext`` model carries the full parameter set as the node reports it —
around seventy fields, including the Conway-era governance parameters that have
no PyCardano equivalent:

* **DRep voting thresholds** — ``d_rep_voting_thresholds``, and the individual
  ``dvt_*`` fields (``dvt_motion_no_confidence``, ``dvt_committee_normal``,
  ``dvt_hard_fork_initiation``, ``dvt_treasury_withdrawal``,
  ``dvt_update_to_constitution``, and the four ``dvt_p_p_*`` protocol-parameter
  groups).
* **Pool voting thresholds** — ``pool_voting_thresholds`` and the ``pvt_*``
  fields, including ``pvt_pp_security_group``.
* **Governance actions** — ``gov_action_deposit``, ``gov_action_lifetime``,
  ``d_rep_deposit``, ``d_rep_activity``.
* **Constitutional committee** — ``committee_min_size``,
  ``committee_max_term_length``.
* **Context** — ``epoch``, ``block_hash`` and ``nonce``, so you can tell which
  epoch a parameter set was read from.

It also exposes ``cardano-cli`` spellings alongside the PyCardano ones —
``tx_fee_fixed`` and ``tx_fee_per_byte`` next to ``min_fee_constant`` and
``min_fee_coefficient``, ``utxo_cost_per_byte`` next to ``coins_per_utxo_byte``,
``max_tx_execution_units`` next to ``max_tx_ex_mem``/``max_tx_ex_steps`` — which
makes it far easier to compare a context's view against raw
``cardano-cli query protocol-parameters`` output.

When you need PyCardano's narrower dataclass, convert:

.. code-block:: python

   pycardano_params = context.protocol_param.to_pycardano()

Genesis parameters carry the whole genesis
------------------------------------------

PyCardano's :class:`~pycardano.backend.base.GenesisParameters` holds ten fields
drawn from the Shelley genesis file. The ``pccontext`` model keeps those and adds
the rest of the genesis, per era:

* ``byron_genesis``, ``shelley_genesis``, ``alonzo_genesis``, ``conway_genesis``
* ``era`` — which era the parameters describe
* ``initial_funds``, ``gen_delegs``, ``staking``, ``protocol_params``
* ``network_id`` alongside ``network_magic``

As with protocol parameters, ``to_pycardano()`` narrows it back down when a
PyCardano API wants the original type.

Staking and governance transaction helpers
------------------------------------------

PyCardano gives you :class:`~pycardano.txbuilder.TransactionBuilder` and the
certificate types; assembling a correct stake registration or vote delegation is
left to you. ``pccontext`` adds ready-made builders for the common certificate
flows, each of which validates against on-chain state first:

``stake_address_registration``, ``stake_address_deregistration``,
``stake_delegation``, ``vote_delegation``, ``stake_and_vote_delegation``,
``stake_address_registration_and_delegation``,
``stake_address_registration_and_vote_delegation``,
``stake_address_registration_delegation_and_vote_delegation``,
``withdraw_rewards``.

Plus transaction-plumbing helpers that work on any context: ``sign_transaction``,
``assemble_transaction``, ``witness``. See :doc:`transactions`.

What PyCardano has that this library does not
---------------------------------------------

* **Ogmios v5.** ``pccontext``'s Ogmios context targets v6 only. Stay on
  PyCardano's ``OgmiosV5ChainContext`` if you run an older Ogmios.
* **A pre-composed Kupo + Ogmios context.** PyCardano offers
  ``KupoOgmiosV6ChainContext`` as a single class. Here you compose it yourself,
  which takes one extra line:

  .. code-block:: python

     from pccontext import OgmiosChainContext, KupoChainContextExtension

     context = KupoChainContextExtension(
         wrapped_backend=OgmiosChainContext(host="localhost", port=1337),
         kupo_url="http://localhost:1442",
     )

Choosing between them
---------------------

Stay with PyCardano's contexts when you only need to build and submit
transactions, you are on Ogmios v5, and Blockfrost, Ogmios, Kupo or
``cardano-cli`` already covers your backend.

Reach for ``pccontext`` when you need any of: Koios, Yaci DevKit, or an offline
signing workflow; stake or DRep delegation state; the Conway governance
parameters; the full genesis files; or the staking and governance transaction
builders.

They interoperate — a ``pccontext`` context *is* a PyCardano chain context, so
you can adopt it without changing how you build transactions.
