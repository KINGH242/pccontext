Staking and governance transactions
===================================

PyCardano gives you :class:`~pycardano.txbuilder.TransactionBuilder` and the
certificate types, and leaves assembling a correct stake registration or vote
delegation to you. ``pccontext`` provides builders for the common certificate
flows.

Each one takes a chain context, checks the stake address's on-chain state through
:meth:`~pccontext.backend.base.ChainContext.stake_address_info`, and raises
:class:`~pccontext.exceptions.TransactionError` rather than building something
the node will reject — registering an already-registered address, delegating from
an unregistered one, withdrawing zero rewards.

.. contents::
   :local:
   :depth: 1

Common setup
------------

Every example below assumes this:

.. code-block:: python

   from pathlib import Path

   from pycardano import Address, PaymentSigningKey, PaymentVerificationKey
   from pycardano import StakeSigningKey, StakeVerificationKey
   from pccontext import KoiosChainContext, Network

   context = KoiosChainContext()

   payment_signing_key = PaymentSigningKey.load("payment.skey")
   payment_verification_key = PaymentVerificationKey.from_signing_key(
       payment_signing_key
   )
   stake_signing_key = StakeSigningKey.load("stake.skey")
   stake_verification_key = StakeVerificationKey.from_signing_key(
       stake_signing_key
   )

   send_from_addr = Address(
       payment_part=payment_verification_key.hash(),
       staking_part=stake_verification_key.hash(),
       network=Network.MAINNET.get_network(),
   )

   signing_keys = [payment_signing_key, stake_signing_key]

Signing
-------

Pass ``signing_keys`` and the returned transaction is already signed. Omit them
and you get an unsigned transaction to sign later — which is what you want for an
air-gapped flow, where the transaction is built online and signed on a machine
that holds the keys.

.. code-block:: python

   # Signed in one step
   tx = stake_address_registration(
       context, stake_verification_key, send_from_addr, signing_keys
   )

   # Or unsigned, to sign elsewhere
   unsigned = stake_address_registration(
       context, stake_verification_key, send_from_addr
   )

Stake registration and deregistration
-------------------------------------

Registering a stake address pays the key deposit and makes the address eligible
to delegate:

.. code-block:: python

   from pccontext.transactions import stake_address_registration

   tx = stake_address_registration(
       context=context,
       stake_vkey=stake_verification_key,
       send_from_addr=send_from_addr,
       signing_keys=signing_keys,
   )
   context.submit_tx(tx)

Deregistering returns the deposit. Withdraw any outstanding rewards first — the
deregistration certificate does not do it for you:

.. code-block:: python

   from pccontext.transactions import stake_address_deregistration

   tx = stake_address_deregistration(
       context=context,
       stake_vkey=stake_verification_key,
       send_from_addr=send_from_addr,
       signing_keys=signing_keys,
   )

Stake delegation
----------------

Delegates stake to a pool. The address must already be registered:

.. code-block:: python

   from pccontext.transactions import stake_delegation

   tx = stake_delegation(
       context=context,
       stake_vkey=stake_verification_key,
       pool_id="pool1...",
       send_from_addr=send_from_addr,
       signing_keys=signing_keys,
   )

To register and delegate in a single transaction — one fee, one deposit, and no
window where the address is registered but undelegated:

.. code-block:: python

   from pccontext.transactions import stake_address_registration_and_delegation

   tx = stake_address_registration_and_delegation(
       context=context,
       stake_vkey=stake_verification_key,
       pool_id="pool1...",
       send_from_addr=send_from_addr,
       signing_keys=signing_keys,
   )

Vote delegation
---------------

Conway-era governance: delegate voting power to a DRep. ``drep_kind`` selects
what you are delegating to, and ``drep_id`` is required only for
:attr:`~pycardano.certificate.DRepKind.VERIFICATION_KEY_HASH` and
:attr:`~pycardano.certificate.DRepKind.SCRIPT_HASH`.

.. code-block:: python

   from pycardano import DRepKind
   from pccontext.transactions import vote_delegation

   # Delegate to a specific DRep
   tx = vote_delegation(
       context=context,
       stake_vkey=stake_verification_key,
       send_from_addr=send_from_addr,
       drep_kind=DRepKind.VERIFICATION_KEY_HASH,
       drep_id="drep1...",
       signing_keys=signing_keys,
   )

   # Or one of the predefined options, which take no drep_id
   tx = vote_delegation(
       context=context,
       stake_vkey=stake_verification_key,
       send_from_addr=send_from_addr,
       drep_kind=DRepKind.ALWAYS_ABSTAIN,
       signing_keys=signing_keys,
   )

``DRepKind.ALWAYS_NO_CONFIDENCE`` is the other predefined option.

Combined certificates
---------------------

Three helpers combine certificates into one transaction:

.. list-table::
   :header-rows: 1
   :widths: 46 54

   * - Helper
     - Certificates
   * - ``stake_address_registration_and_delegation``
     - register + delegate to pool
   * - ``stake_address_registration_and_vote_delegation``
     - register + delegate vote to DRep
   * - ``stake_address_registration_delegation_and_vote_delegation``
     - register + delegate to pool + delegate vote
   * - ``stake_and_vote_delegation``
     - delegate to pool + delegate vote (already registered)

The three-certificate form is the usual choice for onboarding a new stake
address in the Conway era:

.. code-block:: python

   from pycardano import DRepKind
   from pccontext.transactions import (
       stake_address_registration_delegation_and_vote_delegation,
   )

   tx = stake_address_registration_delegation_and_vote_delegation(
       context=context,
       stake_vkey=stake_verification_key,
       pool_id="pool1...",
       send_from_addr=send_from_addr,
       drep_kind=DRepKind.ALWAYS_ABSTAIN,
       signing_keys=signing_keys,
   )

Withdrawing rewards
-------------------

Withdraws the full rewards balance — a partial withdrawal is not a thing the
ledger supports. Raises if the balance is zero:

.. code-block:: python

   from pccontext.transactions import withdraw_rewards

   tx = withdraw_rewards(
       context=context,
       stake_vkey=stake_verification_key,
       send_from_addr=send_from_addr,
       signing_keys=signing_keys,
   )

To check the balance first:

.. code-block:: python

   info = context.stake_address_info(str(send_from_addr))[0]
   if info.reward_account_balance > 0:
       tx = withdraw_rewards(...)

Signing, witnessing and assembly
--------------------------------

Three helpers handle the plumbing of multi-party and offline signing. They work
on any transaction, not just the ones built above.

``sign_transaction`` attaches witnesses for the given keys and returns the signed
transaction:

.. code-block:: python

   from pccontext.transactions import sign_transaction

   signed = sign_transaction(unsigned_tx, [payment_signing_key, stake_signing_key])

``witness`` produces the verification key witnesses without attaching them, which
is what each party runs when a transaction needs signatures from several holders:

.. code-block:: python

   from pccontext.transactions import witness

   witnesses = witness(unsigned_tx, [payment_signing_key])

``assemble_transaction`` combines witnesses collected separately into a final
transaction. It also accepts native scripts, Plutus scripts (v1, v2 and v3),
datums and redeemers:

.. code-block:: python

   from pccontext.transactions import assemble_transaction

   final = assemble_transaction(
       transaction=unsigned_tx,
       vkey_witnesses=witnesses_from_alice + witnesses_from_bob,
   )

   context.submit_tx(final)

Air-gapped signing
------------------

Combining the pieces: build online, sign offline, submit online.

.. code-block:: python

   # --- online machine -------------------------------------------------
   from pccontext import KoiosChainContext
   from pccontext.transactions import stake_address_registration

   context = KoiosChainContext()
   unsigned = stake_address_registration(
       context, stake_verification_key, send_from_addr  # no signing_keys
   )
   unsigned_cbor = unsigned.to_cbor_hex()

   # --- air-gapped machine ---------------------------------------------
   from pathlib import Path
   from pycardano import Transaction
   from pccontext import OfflineTransferFileContext
   from pccontext.transactions import sign_transaction

   offline = OfflineTransferFileContext(Path("offline-transfer.json"))
   signed = sign_transaction(
       Transaction.from_cbor(unsigned_cbor), [payment_signing_key, stake_signing_key]
   )
   offline.submit_tx(signed)   # appends to offline-transfer.json

   # --- online machine again -------------------------------------------
   context.submit_tx(signed)

See :ref:`chain_contexts:Offline transfer file` for what the file holds and how
stale data affects the transactions you build from it.
