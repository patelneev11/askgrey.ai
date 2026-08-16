from __future__ import annotations

from pydantic import BaseModel

GRANTS_GOV_SEPARATOR = "|"


class AgencyAlias(BaseModel):
    """
    How one human-facing agency name maps onto each provider's own vocabulary.

    grants.gov filters on hierarchical codes (`HHS-NIH11`) and accepts several at once, while
    SBIR.gov only knows top-level department codes (`HHS`). An alias therefore carries a list
    for the former and at most one code for the latter.
    """

    label: str
    grants_gov_codes: list[str]
    sbir_code: str = ""
    note: str = ""


# Keyed by the uppercased alias a researcher would type. Departments resolve to the whole
# department so a search for "HHS" is not silently narrowed to one institute.
AGENCY_ALIASES: dict[str, AgencyAlias] = {
    "NIH": AgencyAlias(label="National Institutes of Health", grants_gov_codes=["HHS-NIH11"]),
    "CDC": AgencyAlias(
        label="Centers for Disease Control and Prevention", grants_gov_codes=["HHS-CDC"]
    ),
    "FDA": AgencyAlias(label="Food and Drug Administration", grants_gov_codes=["HHS-FDA"]),
    "BARDA": AgencyAlias(
        label="Biomedical Advanced Research and Development Authority",
        grants_gov_codes=["HHS-ASPR", "HHS-OS-ASPR"],
        note=(
            "grants.gov has no BARDA-specific code; BARDA posts under its parent office ASPR, "
            "so results include non-BARDA ASPR opportunities."
        ),
    ),
    "ASPR": AgencyAlias(
        label="Administration for Strategic Preparedness and Response",
        grants_gov_codes=["HHS-ASPR", "HHS-OS-ASPR"],
    ),
    "ARPA-H": AgencyAlias(
        label="Advanced Research Projects Agency for Health", grants_gov_codes=["HHS-ARPAH"]
    ),
    "HHS": AgencyAlias(
        label="Department of Health and Human Services",
        grants_gov_codes=["HHS"],
        sbir_code="HHS",
    ),
    "DOD": AgencyAlias(
        label="Department of Defense",
        grants_gov_codes=["DOD"],
        sbir_code="DOW",
        note="SBIR.gov renamed the department code to DOW (Department of War).",
    ),
    "DARPA": AgencyAlias(
        label="Defense Advanced Research Projects Agency",
        grants_gov_codes=[
            "DOD-DARPA-BTO",
            "DOD-DARPA-DSO",
            "DOD-DARPA-I2O",
            "DOD-DARPA-IPTO",
            "DOD-DARPA-TTO",
        ],
    ),
    "DTRA": AgencyAlias(label="Defense Threat Reduction Agency", grants_gov_codes=["DOD-DTRA"]),
    "DHA": AgencyAlias(label="Defense Health Agency", grants_gov_codes=["DOD-AMRAA"]),
    "NASA": AgencyAlias(
        label="National Aeronautics and Space Administration",
        grants_gov_codes=["NASA"],
        sbir_code="NASA",
    ),
    "NSF": AgencyAlias(
        label="National Science Foundation", grants_gov_codes=["NSF"], sbir_code="NSF"
    ),
    "DOE": AgencyAlias(label="Department of Energy", grants_gov_codes=["DOE"], sbir_code="DOE"),
    "ARPA-E": AgencyAlias(
        label="Advanced Research Projects Agency Energy", grants_gov_codes=["DOE-ARPAE"]
    ),
    "USDA": AgencyAlias(
        label="Department of Agriculture", grants_gov_codes=["USDA"], sbir_code="USDA"
    ),
    "EPA": AgencyAlias(
        label="Environmental Protection Agency", grants_gov_codes=["EPA"], sbir_code="EPA"
    ),
    "DHS": AgencyAlias(
        label="Department of Homeland Security", grants_gov_codes=["DHS"], sbir_code="DHS"
    ),
    "DOC": AgencyAlias(label="Department of Commerce", grants_gov_codes=["DOC"], sbir_code="DOC"),
    "DOT": AgencyAlias(
        label="Department of Transportation", grants_gov_codes=["DOT"], sbir_code="DOT"
    ),
    "ED": AgencyAlias(label="Department of Education", grants_gov_codes=["ED"], sbir_code="ED"),
}

# Spellings that should resolve to an existing alias rather than being passed through raw.
AGENCY_SYNONYMS: dict[str, str] = {
    "NATIONAL INSTITUTES OF HEALTH": "NIH",
    "DEPARTMENT OF DEFENSE": "DOD",
    "DEPT OF DEFENSE": "DOD",
    "DOW": "DOD",
    "DEPARTMENT OF WAR": "DOD",
    "HEALTH AND HUMAN SERVICES": "HHS",
    "DEPARTMENT OF HEALTH AND HUMAN SERVICES": "HHS",
    "ARPAH": "ARPA-H",
    "ARPAE": "ARPA-E",
    "DEPARTMENT OF ENERGY": "DOE",
    "NATIONAL SCIENCE FOUNDATION": "NSF",
}


def resolve_agency(agency: str) -> AgencyAlias:
    """
    Map a typed agency name onto provider codes.

    An unrecognized value is passed through as a literal code for both providers rather than
    rejected: grants.gov keeps adding sub-agency codes, and a caller who already knows one
    should not have to wait for this table to catch up.
    """
    key = " ".join(agency.split()).upper()
    key = AGENCY_SYNONYMS.get(key, key)
    alias = AGENCY_ALIASES.get(key)
    if alias is not None:
        return alias
    return AgencyAlias(label=agency.strip(), grants_gov_codes=[key], sbir_code=key)
