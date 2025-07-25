import json
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest
from pycardano import (
    Address,
    DRepKind,
    PoolKeyHash,
    ScriptHash,
    StakeSigningKey,
    StakeVerificationKey,
    VerificationKeyHash,
)

from pccontext import CardanoCliChainContext, Network
from pccontext.transactions.stake_and_vote_delegation import stake_and_vote_delegation


@pytest.fixture
def delegation_chain_context(
    config_file,
    query_tip_result,
    query_protocol_parameters_result,
    query_utxo_result,
):
    """
    Create a CardanoCliChainContext with a mock run_command method
    """

    def override_run_command(cmd: List[str]):
        """
        Override the run_command method of CardanoCliChainContext to return a mock result
        """
        if "tip" in cmd:
            return json.dumps(query_tip_result)
        if "protocol-parameters" in cmd:
            return json.dumps(query_protocol_parameters_result)
        if "stake-address-info" in cmd:
            return json.dumps(
                [
                    {
                        "delegationDeposit": 1000000000000,
                        "stakeDelegation": "pool1q8m9x2zsux7va6w892g38tvchnzahvcd9tykqf3ygnmwta8k2v59pcduem5uw253zwke30x9mwes62kfvqnzg38kuh6q966kg7",
                        "rewardAccountBalance": 1000000,
                        "voteDelegation": "always-abstain",
                    }
                ]
            )
        if "utxo" in cmd:
            return json.dumps(query_utxo_result)
        if "txid" in cmd:
            return "270be16fa17cdb3ef683bf2c28259c978d4b7088792074f177c8efda247e23f7"
        if "version" in cmd:
            return "cardano-cli 8.1.2 - linux-x86_64 - ghc-8.10\ngit rev d2d90b48c5577b4412d5c9c9968b55f8ab4b9767"
        else:
            return None

    with patch(
        "pccontext.backend.cardano_cli.CardanoCliChainContext._run_command",
        side_effect=override_run_command,
    ):
        context = CardanoCliChainContext(
            binary=Path("cardano-cli"),
            socket=Path("node.socket"),
            config_file=config_file,
            network=Network.PREPROD,
        )
        context._run_command = override_run_command
    return context


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
def test_stake_and_vote_delegation(delegation_chain_context, drep_kind, drep_id):
    """
    Test successful stake address registration.
    """
    sk = StakeSigningKey.generate()
    vk = StakeVerificationKey.from_signing_key(sk)
    address = Address.from_primitive(
        "addr1x8nz307k3sr60gu0e47cmajssy4fmld7u493a4xztjrll0aj764lvrxdayh2ux30fl0ktuh27csgmpevdu89jlxppvrswgxsta"
    )
    pool_id = "dd0b5f0c8db566f23b3ac2ffd63c4b5ea2afe1d2ca7c9810b1827e2f"
    transaction = stake_and_vote_delegation(
        delegation_chain_context, vk, pool_id, address, drep_kind, drep_id
    )
    assert transaction.valid is True
    assert len(transaction.transaction_body.certificates) == 1
    certificate = transaction.transaction_body.certificates[0]
    assert certificate.stake_credential.credential == vk.hash()
    assert certificate.pool_keyhash == PoolKeyHash(bytes.fromhex(pool_id))

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
