from typing import Optional

from pycardano import DRep, DRepKind, ScriptHash, VerificationKeyHash


def get_drep(
    drep_kind: Optional[DRepKind] = None,
    drep_id: Optional[str] = None,
) -> DRep:
    """
    Returns a DRep object based on the provided DRep kind and ID.
    :param drep_kind: The DRep kind.
    :param drep_id: The Delegate Representative ID (hex).
    :return: A DRep object.
    """
    if drep_id is not None and drep_id.startswith("drep"):
        return DRep.decode(drep_id)
    if drep_kind in [DRepKind.ALWAYS_ABSTAIN, DRepKind.ALWAYS_NO_CONFIDENCE]:
        drep = DRep(drep_kind)
    elif drep_kind == DRepKind.SCRIPT_HASH and drep_id is not None:
        drep = DRep(drep_kind, ScriptHash(bytes.fromhex(drep_id)))
    elif drep_kind == DRepKind.VERIFICATION_KEY_HASH and drep_id is not None:
        drep_bytes = bytes.fromhex(drep_id)
        if len(drep_bytes) == 29:
            drep_bytes = drep_bytes[1:]
        drep = DRep(drep_kind, VerificationKeyHash(drep_bytes))
    else:
        raise ValueError(
            "DRep ID must be provided for DRepKind SCRIPT_HASH or VERIFICATION_KEY_HASH."
        )
    return drep
