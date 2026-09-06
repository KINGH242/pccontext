from freezegun import freeze_time
from pycardano import Network, Transaction, TransactionBody, TransactionWitnessSet

from pccontext import GenesisParameters, OfflineTransferFileContext, ProtocolParameters
from pccontext.enums import Era


def test_offline_chain_context(offline_transfer_file):
    chain_context = OfflineTransferFileContext(
        offline_transfer_file=offline_transfer_file
    )
    assert isinstance(chain_context.network, Network)


def test_protocol_param(offline_transfer_file, cli_protocol_parameters_json):
    chain_context = OfflineTransferFileContext(
        offline_transfer_file=offline_transfer_file
    )
    expected_protocol_params = ProtocolParameters.from_json(
        cli_protocol_parameters_json
    )
    assert chain_context.protocol_param == expected_protocol_params.to_pycardano()


def test_genesis(offline_transfer_file, fake_genesis_parameters_json):
    chain_context = OfflineTransferFileContext(
        offline_transfer_file=offline_transfer_file
    )
    expected_genesis = GenesisParameters.from_json(fake_genesis_parameters_json)
    assert chain_context.genesis_param == expected_genesis.to_pycardano()


@freeze_time("2024-11-2")
def test_epoch(offline_transfer_file):
    chain_context = OfflineTransferFileContext(
        offline_transfer_file=offline_transfer_file
    )
    assert chain_context.epoch == 519


def test_era_is_an_era_enum(offline_transfer_file):
    chain_context = OfflineTransferFileContext(
        offline_transfer_file=offline_transfer_file
    )
    assert chain_context.era is None or isinstance(chain_context.era, Era)


def test_submit_tx_envelope_uses_era_name(offline_transfer_file, monkeypatch):
    """The envelope type must embed the era's name, not the Era enum's repr.

    `f"{Era.CONWAY}"` yields "Era.CONWAY", which produced the malformed type
    "Witnessed Tx Era.CONWAYEra".
    """
    written = {}

    chain_context = OfflineTransferFileContext(
        offline_transfer_file=offline_transfer_file
    )
    monkeypatch.setattr(
        type(chain_context),
        "era",
        property(lambda self: Era.CONWAY),
    )
    monkeypatch.setattr(
        "pccontext.backend.offline_transfer_file.dump_file",
        lambda path, contents: written.update(path=path, contents=contents),
    )

    tx = Transaction(
        TransactionBody(inputs=[], outputs=[], fee=0), TransactionWitnessSet()
    )
    chain_context.submit_tx_cbor(tx.to_cbor_hex())

    assert "Era." not in written["contents"]
    assert "Witnessed Tx ConwayEra" in written["contents"]
