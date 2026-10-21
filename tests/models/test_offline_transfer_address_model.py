from pccontext.models import AddressInfo, StakeAddressInfo


def test_offline_transfer_address_from_json(fake_offline_transfer_address):
    # Act
    offline_transfer_address = AddressInfo.from_json(fake_offline_transfer_address)

    # Assert
    assert offline_transfer_address.name == fake_offline_transfer_address["name"]
    assert str(offline_transfer_address.address) == fake_offline_transfer_address["address"]
    assert offline_transfer_address.base16 == fake_offline_transfer_address["base16"]
    assert offline_transfer_address.encoding == fake_offline_transfer_address["encoding"]
    assert offline_transfer_address.type.value == fake_offline_transfer_address["type"]
    assert offline_transfer_address.total_amount == fake_offline_transfer_address["total_amount"]
    assert offline_transfer_address.used == fake_offline_transfer_address["used"]
    assert offline_transfer_address.stake_address_info == [
        StakeAddressInfo.from_dict(reward) for reward in fake_offline_transfer_address["stake_address_info"]
    ]
