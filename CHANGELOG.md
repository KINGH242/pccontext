## 0.5.5 (2025-12-09)

### Fix

- update to latest pycardano
- sort imports in assemble.py

## 0.5.4 (2025-08-14)

### Fix

- allow multiple types for plutus_data in transaction witness set

## 0.5.3 (2025-08-09)

### Fix

- update plutus data in transaction witness set instead of extending

## 0.5.2 (2025-07-30)

### Fix

- pass initial transaction witness set to be updated rather than overwritten

## 0.5.1 (2025-07-21)

### Fix

- update transaction handling in assemble, sign, and witness functions to use entire transaction

### Refactor

- streamline transaction handling in stake address functions

## 0.5.0 (2025-06-17)

### Feat

- enhance transaction signing with optional signing keys for multiple transaction types
- add witness function for transaction signing with multiple keys
- add methods for network conversion and CLI arguments in Network enum

### Fix

- add transaction-related functions to the module for improved usability
- enhance BlockFrostChainContext with improved network handling and error management

### Refactor

- reorganize import statements for improved readability and consistency
- update network references to use unified Network enum in tests
- simplify CardanoCliNetwork usage and improve network argument handling

## 0.4.1 (2025-05-14)

### Fix

- handle zero rewards case and streamline withdrawal input handling
- cast withdrawable amount to int for reward account balance

## 0.4.0 (2025-05-13)

### Feat

- add functions for stake address registration and delegation, vote delegation, and combined operations

### Refactor

- simplify stake and vote delegation logic by using helper functions

## 0.3.4 (2025-05-09)

### Fix

- enhance stake address validation with active and active_epoch checks

## 0.3.3 (2025-05-09)

### Fix

- add active attribute to StakeAddressInfo and update registration check

## 0.3.2 (2025-05-08)

### Fix

- fix access to rewards_state attributes in StakeAddressInfo

## 0.3.1 (2025-05-05)

### Fix

- handle DRep ID processing for VERIFICATION_KEY_HASH with CIP129

## 0.3.0 (2025-05-04)

### Feat

- add transaction assembly and signing functionality

### Fix

- store transaction ID from command execution

## 0.2.12 (2025-04-21)

### Fix

- remove network args from tx id
- handle protocol parameters better

## 0.2.11 (2025-04-03)

### Fix

- add property_from_dict to handle genesis

## 0.2.10 (2025-04-03)

### Fix

- set default era to Conway

## 0.2.9 (2025-04-03)

### Fix

- create genesis params from config files

## 0.2.8 (2025-03-21)

### Fix

- update to latest pycardano

## 0.2.7 (2025-02-04)

### Fix

- add compatibility with Python 3.13

## 0.2.6 (2025-01-10)

### Fix

- convert time to int timestamp

## 0.2.5 (2025-01-10)

### Fix

- save genesis_param

## 0.2.4 (2024-11-26)

### Fix

- use correct Shelley

## 0.2.3 (2024-11-26)

### Fix

- handle transactions with latest cli

## 0.2.2 (2024-11-07)

### Fix

- return instead of raise
- add sort keys
- use PyCardano base models

## 0.2.1 (2024-11-02)

### Fix

- add calculate epoch and tip to OffflineContext

## 0.2.0 (2024-10-24)

### Feat

- added yaci devkit as a backend

### Fix

- improve reference script handling
- add PlutusV3 support
- improve handle various property names
- use Network and Era enum
- add network enum for network name
- add plutusV3 support and protocol_param from wrapped_backend
- add plutusV3 support
- update backends to output PycardanoProtocolParameters
- update models with latest changes
