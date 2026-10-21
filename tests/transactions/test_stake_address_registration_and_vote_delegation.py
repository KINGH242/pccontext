import pytest
from pycardano import (
    Address,
    DRepKind,
    ScriptHash,
    StakeSigningKey,
    StakeVerificationKey,
    VerificationKeyHash,
)

from pccontext.transactions.stake_address_registration_and_vote_delegation import (
    stake_address_registration_and_vote_delegation,
)


@pytest.mark.parametrize(
    "drep_kind,drep_id",
    [
        (DRepKind.ALWAYS_ABSTAIN, None),
        (DRepKind.ALWAYS_NO_CONFIDENCE, None),
        (DRepKind.SCRIPT_HASH, "af" * 28),
        (
            DRepKind.VERIFICATION_KEY_HASH,
            "ab" * 28,
        ),
        (
            DRepKind.VERIFICATION_KEY_HASH,
            "ab" * 29,
        ),
    ],
)
def test_stake_address_registration_and_vote_delegation_success(chain_context, drep_kind, drep_id):
    """
    Test successful stake address registration and vote delegation.
    """
    sk = StakeSigningKey.generate()
    vk = StakeVerificationKey.from_signing_key(sk)
    address = Address.from_primitive(
        "addr1x8nz307k3sr60gu0e47cmajssy4fmld7u493a4xztjrll0aj764lvrxdayh2ux30fl0ktuh27csgmpevdu89jlxppvrswgxsta"
    )
    transaction = stake_address_registration_and_vote_delegation(chain_context, vk, address, drep_kind, drep_id)
    assert transaction.valid is True
    assert transaction.transaction_body is not None
    assert transaction.transaction_body.hash() is not None

    certificate = transaction.transaction_body.certificates[0]
    assert certificate.stake_credential.credential == vk.hash()

    if drep_kind == DRepKind.SCRIPT_HASH:
        assert certificate.drep.kind == DRepKind.SCRIPT_HASH
        assert certificate.drep.credential == ScriptHash(bytes.fromhex(drep_id))
    elif drep_kind == DRepKind.VERIFICATION_KEY_HASH:
        assert certificate.drep.kind == DRepKind.VERIFICATION_KEY_HASH
        drep_bytes = bytes.fromhex(drep_id)
        if len(drep_bytes) == 29:
            assert certificate.drep.credential == VerificationKeyHash(drep_bytes[1:])
        else:
            assert certificate.drep.credential == VerificationKeyHash(drep_bytes)
    else:
        assert certificate.drep.kind == drep_kind
