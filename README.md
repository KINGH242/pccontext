## PyCardano Chain Contexts

This library contains the various Chain Contexts to use with the PyCardano library as well as a few 
helper functions for working with and building certain types of transactions.

### Documentation

Full documentation lives in `docs/`. To build it locally:

```bash
poetry install --with docs
make docs
```

It covers how each chain context is configured, the staking and governance
transaction helpers, a full API reference, and — if you are coming from
PyCardano's built-in chain contexts — a page on what differs between them.

### Chain Context Usage

The library supports multiple blockchain data providers and local node interfaces. Choose the appropriate chain context based on your setup and requirements.

<details>
<summary><strong>Blockfrost</strong></summary>

```python
from pccontext import BlockFrostChainContext, Network

chain_context = BlockFrostChainContext(
    project_id="your_project_id",
    network=Network.MAINNET,
)
```

</details>

<details>
<summary><strong>Cardano-CLI</strong></summary>

```python
from pccontext import CardanoCliChainContext, Network
from pathlib import Path

chain_context = CardanoCliChainContext(
    binary=Path("cardano-cli"),
    socket=Path("node.socket"),
    config_file=Path("config.json"),
    network=Network.MAINNET,
)
```

</details>

<details>
<summary><strong>Koios</strong></summary>

```python
from pccontext import KoiosChainContext

chain_context = KoiosChainContext(api_key="api_key")
```

</details>

<details>
<summary><strong>Ogmios</strong></summary>

```python
from pccontext import OgmiosChainContext

chain_context = OgmiosChainContext(host="localhost", port=1337)
```

</details>

<details>
<summary><strong>Kupo</strong></summary>

```python
from pccontext import OgmiosChainContext, KupoChainContextExtension

ogmios_chain_context = OgmiosChainContext(host="localhost", port=1337)
chain_context = KupoChainContextExtension(wrapped_backend=ogmios_chain_context)
```

</details>

<details>
<summary><strong>Offline Transfer File</strong></summary>

```python
from pathlib import Path
from pccontext import OfflineTransferFileContext

chain_context = OfflineTransferFileContext(offline_transfer_file=Path("offline-transfer.json"))
```

</details>

<details>
<summary><strong>Yaci Devkit</strong></summary>

```python
from pccontext import YaciDevkitChainContext

chain_context = YaciDevkitChainContext(api_url="http://localhost:8080")
```

</details>

### Transactions Usage

The library provides various transaction helper functions for common Cardano operations. All transaction functions can optionally sign the transaction if signing keys are provided.

#### Common Setup for Transaction Examples

```python
from pycardano import (
    Address,
    DRepKind,
    StakeSigningKey,
    StakeVerificationKey,
    PaymentSigningKey,
    PaymentVerificationKey,
)

from pccontext import BlockFrostChainContext, Network
import os

# Setup chain context
network = Network.PREPROD
blockfrost_api_key = os.getenv("BLOCKFROST_API_KEY_PREPROD")
chain_context = BlockFrostChainContext(
    project_id=blockfrost_api_key, network=network
)

# Generate keys
payment_signing_key = PaymentSigningKey.generate()
payment_verification_key = PaymentVerificationKey.from_signing_key(
    payment_signing_key
)

stake_signing_key = StakeSigningKey.generate()
stake_verification_key = StakeVerificationKey.from_signing_key(stake_signing_key)

address = Address(
    payment_part=payment_verification_key.hash(),
    staking_part=stake_verification_key.hash(),
    network=network.get_network(),
)
```

<details>
<summary><strong>Transaction Assembly and Signing Utilities</strong></summary>

#### assemble_transaction

```python
from pccontext.transactions import assemble_transaction
from pycardano import Transaction, VerificationKeyWitness

# Create an unsigned transaction (example using stake registration)
from pccontext.transactions import stake_address_registration

unsigned_transaction = stake_address_registration(
    context=chain_context,
    stake_vkey=stake_verification_key,
    send_from_addr=address,
    signing_keys=None  # Don't sign yet
)

# Create verification key witnesses manually
verification_key_witnesses = [
    VerificationKeyWitness(
        vkey=payment_verification_key,
        signature=payment_signing_key.sign(unsigned_transaction.transaction_body.hash())
    ),
    VerificationKeyWitness(
        vkey=stake_verification_key,
        signature=stake_signing_key.sign(unsigned_transaction.transaction_body.hash())
    )
]

# Assemble a transaction with witnesses
assembled_tx = assemble_transaction(
    transaction=unsigned_transaction,
    vkey_witnesses=verification_key_witnesses
)
```

#### sign_transaction

```python
from pccontext.transactions import sign_transaction, stake_address_registration

# Create an unsigned transaction
unsigned_transaction = stake_address_registration(
    context=chain_context,
    stake_vkey=stake_verification_key,
    send_from_addr=address,
    signing_keys=None  # Don't sign yet
)

# Sign a transaction with provided keys
signed_tx = sign_transaction(
    transaction=unsigned_transaction,
    keys=[payment_signing_key, stake_signing_key],
)
```

#### witness

```python
from pccontext.transactions import witness, stake_address_registration

# Create an unsigned transaction
transaction = stake_address_registration(
    context=chain_context,
    stake_vkey=stake_verification_key,
    send_from_addr=address,
    signing_keys=None  # Don't sign yet
)

# Generate verification key witnesses for a transaction
witnesses = witness(
    transaction=transaction,
    keys=[payment_signing_key, stake_signing_key],
)
```

</details>

<details>
<summary><strong>Stake Address Registration</strong></summary>

```python
from pccontext.transactions import stake_address_registration

# Register a stake address
signed_stake_address_registration_tx = stake_address_registration(
    context=chain_context,
    stake_vkey=stake_verification_key,
    send_from_addr=address,
    signing_keys=[payment_signing_key, stake_signing_key],
)

print(f"Transaction ID: {signed_stake_address_registration_tx.id}")
chain_context.submit_tx(signed_stake_address_registration_tx)
```

</details>

<details>
<summary><strong>Stake Address Deregistration</strong></summary>

```python
from pccontext.transactions import stake_address_deregistration

# Deregister a stake address
signed_stake_address_deregistration_tx = stake_address_deregistration(
    context=chain_context,
    stake_vkey=stake_verification_key,
    send_from_addr=address,
    signing_keys=[payment_signing_key, stake_signing_key],
)

print(f"Transaction ID: {signed_stake_address_deregistration_tx.id}")
chain_context.submit_tx(signed_stake_address_deregistration_tx)
```

</details>

<details>
<summary><strong>Stake Delegation</strong></summary>

```python
from pccontext.transactions import stake_delegation

# Delegate stake to a pool (requires already registered stake address)
pool_id = "abcd1234567890abcdef1234567890abcdef123456789012345678901234"

signed_stake_delegation_tx = stake_delegation(
    context=chain_context,
    stake_vkey=stake_verification_key,
    pool_id=pool_id,
    send_from_addr=address,
    signing_keys=[payment_signing_key, stake_signing_key],
)

print(f"Transaction ID: {signed_stake_delegation_tx.id}")
chain_context.submit_tx(signed_stake_delegation_tx)
```

</details>

<details>
<summary><strong>Stake Address Registration and Delegation</strong></summary>

```python
from pccontext.transactions import stake_address_registration_and_delegation

# Register stake address and delegate in one transaction
pool_id = "abcd1234567890abcdef1234567890abcdef123456789012345678901234"

signed_registration_and_delegation_tx = stake_address_registration_and_delegation(
    context=chain_context,
    stake_vkey=stake_verification_key,
    pool_id=pool_id,
    send_from_addr=address,
    signing_keys=[payment_signing_key, stake_signing_key],
)

print(f"Transaction ID: {signed_registration_and_delegation_tx.id}")
chain_context.submit_tx(signed_registration_and_delegation_tx)
```

</details>

<details>
<summary><strong>Vote Delegation</strong></summary>

```python
from pccontext.transactions import vote_delegation
from pycardano import DRepKind

# Delegate voting power to a DRep
drep_id = "drep1abcd1234567890abcdef1234567890abcdef123456789012345678"

signed_vote_delegation_tx = vote_delegation(
    context=chain_context,
    stake_vkey=stake_verification_key,
    send_from_addr=address,
    drep_kind=DRepKind.KEY_HASH,
    drep_id=drep_id,
    signing_keys=[payment_signing_key, stake_signing_key],
)

print(f"Transaction ID: {signed_vote_delegation_tx.id}")
chain_context.submit_tx(signed_vote_delegation_tx)

# Delegate to "Always Abstain"
signed_vote_abstain_tx = vote_delegation(
    context=chain_context,
    stake_vkey=stake_verification_key,
    send_from_addr=address,
    drep_kind=DRepKind.ALWAYS_ABSTAIN,
    drep_id=None,
    signing_keys=[payment_signing_key, stake_signing_key],
)

# Delegate to "Always No Confidence"
signed_vote_no_confidence_tx = vote_delegation(
    context=chain_context,
    stake_vkey=stake_verification_key,
    send_from_addr=address,
    drep_kind=DRepKind.ALWAYS_NO_CONFIDENCE,
    drep_id=None,
    signing_keys=[payment_signing_key, stake_signing_key],
)
```

</details>

<details>
<summary><strong>Stake Address Registration and Vote Delegation</strong></summary>

```python
from pccontext.transactions import stake_address_registration_and_vote_delegation
from pycardano import DRepKind

# Register stake address and delegate voting power in one transaction
drep_id = "drep1abcd1234567890abcdef1234567890abcdef123456789012345678"

signed_registration_and_vote_delegation_tx = stake_address_registration_and_vote_delegation(
    context=chain_context,
    stake_vkey=stake_verification_key,
    send_from_addr=address,
    drep_kind=DRepKind.KEY_HASH,
    drep_id=drep_id,
    signing_keys=[payment_signing_key, stake_signing_key],
)

print(f"Transaction ID: {signed_registration_and_vote_delegation_tx.id}")
chain_context.submit_tx(signed_registration_and_vote_delegation_tx)
```

</details>

<details>
<summary><strong>Stake and Vote Delegation</strong></summary>

```python
from pccontext.transactions import stake_and_vote_delegation
from pycardano import DRepKind

# Delegate both stake and voting power (requires already registered stake address)
pool_id = "abcd1234567890abcdef1234567890abcdef123456789012345678901234"
drep_id = "drep1abcd1234567890abcdef1234567890abcdef123456789012345678"

signed_stake_and_vote_delegation_tx = stake_and_vote_delegation(
    context=chain_context,
    stake_vkey=stake_verification_key,
    pool_id=pool_id,
    send_from_addr=address,
    drep_kind=DRepKind.KEY_HASH,
    drep_id=drep_id,
    signing_keys=[payment_signing_key, stake_signing_key],
)

print(f"Transaction ID: {signed_stake_and_vote_delegation_tx.id}")
chain_context.submit_tx(signed_stake_and_vote_delegation_tx)
```

</details>

<details>
<summary><strong>Stake Address Registration, Delegation and Vote Delegation</strong></summary>

```python
from pccontext.transactions import stake_address_registration_delegation_and_vote_delegation
from pycardano import DRepKind

# Register stake address, delegate to pool, and delegate voting power in one transaction
pool_id = "abcd1234567890abcdef1234567890abcdef123456789012345678901234"
drep_id = "drep1abcd1234567890abcdef1234567890abcdef123456789012345678"

signed_full_registration_tx = stake_address_registration_delegation_and_vote_delegation(
    context=chain_context,
    stake_vkey=stake_verification_key,
    pool_id=pool_id,
    send_from_addr=address,
    drep_kind=DRepKind.KEY_HASH,
    drep_id=drep_id,
    signing_keys=[payment_signing_key, stake_signing_key],
)

print(f"Transaction ID: {signed_full_registration_tx.id}")
chain_context.submit_tx(signed_full_registration_tx)
```

</details>

<details>
<summary><strong>Withdraw Rewards</strong></summary>

```python
from pccontext.transactions import withdraw_rewards

# Withdraw rewards from a stake address
signed_withdraw_rewards_tx = withdraw_rewards(
    context=chain_context,
    stake_vkey=stake_verification_key,
    send_from_addr=address,
    signing_keys=[payment_signing_key, stake_signing_key],
)

print(f"Transaction ID: {signed_withdraw_rewards_tx.id}")
chain_context.submit_tx(signed_withdraw_rewards_tx)
```

</details>

#### Notes

- All transaction functions return a `Transaction` object 
- When `signing_keys` are provided, the transaction is automatically signed
- When `signing_keys` are not provided, you get an unsigned transaction that needs to be signed separately
- Pool IDs should be provided as hex strings without the "pool" prefix
- DRep IDs should be provided as hex strings or you can use the special DRep kinds (ALWAYS_ABSTAIN, ALWAYS_NO_CONFIDENCE)
