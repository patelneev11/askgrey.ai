from __future__ import annotations

import re
from typing import Any

from .models import PUBCHEM_COMPOUND_URL, CompoundRecord

# Characters that only ever appear in structure notation, never in a chemical name.
SMILES_ONLY_CHARACTERS = frozenset("=#$@[]()/\\%")
SMILES_ORGANIC_ATOMS = re.compile(r"Br|Cl|[BCNOPSFIbcnops]")
NAME_WORD = re.compile(r"[A-Za-z]{4,}")


def looks_like_smiles(value: str) -> bool:
    """
    Heuristic for routing an identifier to the structure endpoint before the name endpoint.

    A wrong guess is not fatal — the service falls back to the other endpoint — but guessing
    well halves the request count for the common cases. Names are mostly long alphabetic words
    with spaces or hyphens; SMILES are short, punctuation-heavy and have no spaces.
    """
    candidate = value.strip()
    if not candidate or " " in candidate:
        return False
    if not SMILES_ORGANIC_ATOMS.search(candidate):
        return False
    if set(candidate) & SMILES_ONLY_CHARACTERS:
        return True
    if any(character.isdigit() for character in candidate):
        # Ring-closure digits, as in `c1ccccc1`; a bare name carrying a locant has a hyphen
        # or comma and is caught by the punctuation check above.
        return True
    # No structural punctuation left: only call it a structure if it is not a plain word,
    # so `CCC` reads as a structure while `ethanol` and `caffeine` read as names.
    return not NAME_WORD.search(candidate)


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _as_str(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def parse_property_row(row: dict[str, Any], synonyms: list[str] | None = None) -> CompoundRecord:
    """Normalize one PUG-REST property row, tolerating both the pre- and post-2025 SMILES keys."""
    cid_value = row.get("CID")
    cid = int(cid_value) if isinstance(cid_value, int | float) else 0
    return CompoundRecord(
        cid=cid,
        title=_as_str(row, "Title"),
        iupac_name=_as_str(row, "IUPACName"),
        molecular_formula=_as_str(row, "MolecularFormula"),
        molecular_weight=_as_float(row.get("MolecularWeight")),
        canonical_smiles=_as_str(row, "ConnectivitySMILES", "CanonicalSMILES"),
        isomeric_smiles=_as_str(row, "SMILES", "IsomericSMILES"),
        xlogp=_as_float(row.get("XLogP")),
        synonyms=list(synonyms or []),
        pubchem_url=f"{PUBCHEM_COMPOUND_URL}/{cid}" if cid else "",
    )
