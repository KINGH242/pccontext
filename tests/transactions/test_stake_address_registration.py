from pycardano import Address, StakeSigningKey, StakeVerificationKey

from pccontext.transactions.stake_address_registration import stake_address_registration


def test_stake_address_registration_success(chain_context):
    """
    Test successful stake address registration.
    """
    sk = StakeSigningKey.generate()
    vk = StakeVerificationKey.from_signing_key(sk)
    address = Address.from_primitive(
        "addr1x8nz307k3sr60gu0e47cmajssy4fmld7u493a4xztjrll0aj764lvrxdayh2ux30fl0ktuh27csgmpevdu89jlxppvrswgxsta"
    )
    transaction = stake_address_registration(chain_context, vk, address)
    assert transaction.valid is True
    assert transaction.transaction_body.certificates[0].stake_credential.credential == vk.hash()
