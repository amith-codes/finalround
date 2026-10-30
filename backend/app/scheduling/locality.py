"""Shared, dependency-free normalization for customer and electrician locality labels."""
import re


_DISTRICT_SUFFIX = re.compile(r"\s+district$", re.IGNORECASE)
_LOCALITY_ALIASES = {
    "mysore": "mysuru",
    "bangalore": "bengaluru",
}


def locality_key(value: str | None) -> str:
    """Return the locality component of a locality/district/state label.

    Customer address pickers often serialize a location as ``Locality, District,
    State`` while electrician profiles store only ``Locality``. Compare the
    first component so that adding district/state context does not prevent a
    same-locality match.
    """
    if not value:
        return ""
    locality = " ".join(str(value).split(",", 1)[0].split()).casefold()
    locality = _DISTRICT_SUFFIX.sub("", locality).strip()
    return _LOCALITY_ALIASES.get(locality, locality)


def same_locality(left: str | None, right: str | None) -> bool:
    left_key = locality_key(left)
    return bool(left_key) and left_key == locality_key(right)
