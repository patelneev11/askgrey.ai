"""
Server-side SMILES validation, shared by every screening service.

RDKit is a C++ library reached through a Python wrapper: handing it unbounded caller input is
how a request turns into a long parse or an unhelpful crash, so every structure passes through
here first. Validation is deliberately in two stages — a cheap syntactic gate (length, charset)
before RDKit is asked to parse at all, then RDKit's own sanitization, which is the only real
authority on whether a string denotes a chemically valid molecule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rdkit import Chem, RDLogger
from rdkit.Chem import rdMolDescriptors

from .errors import InvalidStructureError

MAX_SMILES_LENGTH = 600
# A screening candidate is a small molecule. Anything past this is a polymer or a paste
# accident, and the descriptor set below would be meaningless for it either way.
MAX_HEAVY_ATOMS = 200

# Every character SMILES/SMARTS notation can legitimately contain. Whitespace is excluded on
# purpose: it never appears inside a single structure, and rejecting it here is what keeps a
# pasted name, a newline-separated list, or a query fragment from reaching an external API.
ALLOWED_CHARACTERS = re.compile(r"^[A-Za-z0-9@+\-\[\]\(\)=#$:/\\%.*~,{}]+$")

# RDKit logs parse failures to stderr by default. The exception carries the same information,
# and the log line would otherwise appear in production logs as an unattributed error.
RDLogger.DisableLog("rdApp.*")


@dataclass(frozen=True)
class ParsedStructure:
    """A validated structure: the caller's string, plus RDKit's canonical view of it."""

    input_smiles: str
    canonical_smiles: str
    molecular_formula: str
    inchikey: str
    heavy_atom_count: int
    mol: Chem.Mol

    @property
    def scaffold_hint(self) -> str:
        """Formula-and-canonical-SMILES label for logs and UI headers."""
        return f"{self.molecular_formula} ({self.canonical_smiles})"


def normalize_smiles(value: object) -> str:
    """
    Syntactic gate: return the trimmed string, or raise before RDKit ever sees it.

    Raises `InvalidStructureError` for a non-string, an empty string, one over
    `MAX_SMILES_LENGTH`, or one containing a character SMILES notation cannot contain.
    """
    if not isinstance(value, str):
        raise InvalidStructureError("structure must be a string of SMILES notation")
    candidate = value.strip()
    if not candidate:
        raise InvalidStructureError("structure must not be empty")
    if len(candidate) > MAX_SMILES_LENGTH:
        raise InvalidStructureError(
            f"structure must be at most {MAX_SMILES_LENGTH} characters "
            f"(received {len(candidate)})"
        )
    if not ALLOWED_CHARACTERS.match(candidate):
        raise InvalidStructureError(
            "structure contains characters that are not valid in SMILES notation; "
            "paste a single structure with no spaces or line breaks"
        )
    return candidate


def parse_structure(value: object) -> ParsedStructure:
    """
    Validate `value` and return it parsed, canonicalized and described.

    Sanitization is left on: an aromatic ring RDKit cannot kekulize, or a nitrogen with an
    impossible valence, is invalid input rather than something to compute descriptors for.
    """
    candidate = normalize_smiles(value)
    try:
        mol = Chem.MolFromSmiles(candidate)
    except Exception as exc:  # noqa: BLE001 — the wrapper raises bare RuntimeError/ValueError
        raise InvalidStructureError(f"{candidate!r} could not be parsed as SMILES") from exc
    if mol is None:
        raise InvalidStructureError(
            f"{candidate!r} is not a valid SMILES string (RDKit could not sanitize it)"
        )
    heavy_atoms = mol.GetNumHeavyAtoms()
    if heavy_atoms == 0:
        raise InvalidStructureError("structure contains no heavy atoms")
    if heavy_atoms > MAX_HEAVY_ATOMS:
        raise InvalidStructureError(
            f"structure has {heavy_atoms} heavy atoms; this service is limited to "
            f"{MAX_HEAVY_ATOMS}-atom small molecules"
        )

    return ParsedStructure(
        input_smiles=candidate,
        canonical_smiles=Chem.MolToSmiles(mol),
        molecular_formula=rdMolDescriptors.CalcMolFormula(mol),
        inchikey=_inchikey(mol),
        heavy_atom_count=heavy_atoms,
        mol=mol,
    )


def _inchikey(mol: Chem.Mol) -> str:
    """InChIKey if the InChI toolkit is present, empty string otherwise.

    It is a build-time option in RDKit, so treat it as a bonus identifier rather than
    failing a descriptor request over it.
    """
    try:
        return Chem.MolToInchiKey(mol) or ""
    except Exception:  # noqa: BLE001 — a missing InChI backend must not fail the request
        return ""
