from dataclasses import dataclass

from pycardano import (
    Address,
    AuxiliaryData,
    ExecutionUnits,
    IndefiniteList,
    InvalidBefore,
    InvalidHereAfter,
    Metadata,
    NonEmptyOrderedSet,
    PaymentSigningKey,
    PaymentVerificationKey,
    PlutusData,
    PlutusV1Script,
    PlutusV2Script,
    PlutusV3Script,
    Redeemer,
    RedeemerTag,
    ScriptAll,
    ScriptPubkey,
    StakeSigningKey,
    StakeVerificationKey,
    VerificationKey,
    VerificationKeyWitness,
)

from pccontext.transactions.assemble import assemble_transaction
from pccontext.transactions.stake_address_registration import stake_address_registration


@dataclass
class MyTest(PlutusData):
    CONSTR_ID = 130

    a: int
    b: bytes
    c: IndefiniteList
    d: dict


@dataclass
class MyRedeemer(Redeemer):
    data: MyTest


def test_assemble_transaction(
    chain_context,
):
    """
    Test the assembly of a transaction with various components.
    """
    payment_skey = PaymentSigningKey.generate()
    payment_vkey = PaymentVerificationKey.from_signing_key(payment_skey)
    stake_skey = StakeSigningKey.generate()
    stake_vkey = StakeVerificationKey.from_signing_key(stake_skey)

    other_payment_skey = PaymentSigningKey.generate()
    other_payment_vkey = PaymentVerificationKey.from_signing_key(other_payment_skey)

    address = Address(
        payment_vkey.hash(),
        stake_vkey.hash(),
    )
    transaction = stake_address_registration(chain_context, stake_vkey, address)

    auxiliary_data = AuxiliaryData(
        data=Metadata(
            {
                674: {"MySwap": "Market Order"},
            }
        )
    )
    transaction.auxiliary_data = auxiliary_data

    vk1 = VerificationKey.from_cbor("58206443a101bdb948366fc87369336224595d36d8b0eee5602cba8b81a024e58473")
    vk2 = VerificationKey.from_cbor("58206443a101bdb948366fc87369336224595d36d8b0eee5602cba8b81a024e58475")
    spk1 = ScriptPubkey(key_hash=vk1.hash())
    spk2 = ScriptPubkey(key_hash=vk2.hash())
    before = InvalidHereAfter(123456789)
    after = InvalidBefore(123456780)
    script = ScriptAll([before, after, spk1, spk2])
    native_scripts = [script]
    transaction.transaction_witness_set.native_scripts = native_scripts

    data = MyTest(123, b"1234", IndefiniteList([4, 5, 6]), {1: b"1", 2: b"2"})

    plutus_data = [data]
    transaction.transaction_witness_set.plutus_data = plutus_data

    redeemer = MyRedeemer(data, ExecutionUnits(1000000, 1000000))
    redeemer.tag = RedeemerTag.SPEND
    redeemers = [redeemer]
    transaction.transaction_witness_set.redeemer = redeemers

    plutus_v1_script = NonEmptyOrderedSet([PlutusV1Script(b"magic script v1")])
    plutus_v2_script = NonEmptyOrderedSet([PlutusV2Script(b"magic script v2")])
    plutus_v3_script = NonEmptyOrderedSet([PlutusV3Script(b"magic script v3")])
    transaction.transaction_witness_set.plutus_v1_script = plutus_v1_script
    transaction.transaction_witness_set.plutus_v2_script = plutus_v2_script
    transaction.transaction_witness_set.plutus_v3_script = plutus_v3_script

    initial_vkey_witnesses = NonEmptyOrderedSet(
        [
            VerificationKeyWitness(
                other_payment_vkey,
                other_payment_skey.sign(transaction.transaction_body.hash()),
            )
        ]
    )
    transaction.transaction_witness_set.vkey_witnesses = initial_vkey_witnesses

    vkey_witnesses = [
        VerificationKeyWitness(payment_vkey, payment_skey.sign(transaction.transaction_body.hash())),
        VerificationKeyWitness(stake_vkey, stake_skey.sign(transaction.transaction_body.hash())),
    ]

    assembled_tx = assemble_transaction(
        transaction=transaction,
        vkey_witnesses=vkey_witnesses,
    )

    assert assembled_tx is not None
    assert assembled_tx.transaction_body == transaction.transaction_body
    assert assembled_tx.valid is True
    assert assembled_tx.auxiliary_data == auxiliary_data
    assert assembled_tx.transaction_witness_set.native_scripts == native_scripts
    assert assembled_tx.transaction_witness_set.plutus_data == plutus_data
    assert assembled_tx.transaction_witness_set.redeemer == redeemers
    assert assembled_tx.transaction_witness_set.plutus_v1_script == plutus_v1_script
    assert assembled_tx.transaction_witness_set.plutus_v2_script == plutus_v2_script
    assert assembled_tx.transaction_witness_set.plutus_v3_script == plutus_v3_script
    assert len(assembled_tx.transaction_witness_set.vkey_witnesses) == 3
