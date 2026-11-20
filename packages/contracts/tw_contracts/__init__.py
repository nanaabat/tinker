"""tinker + wink shared contracts: strict JSON Schema validation, versioning and migrations."""
from .core import (SCHEMA_VERSION, KINDS, ContractError, VersionMismatch, load_schema, migrate,
                   validate, canonical_json, content_hash, MAX_DOCUMENT_BYTES, parse_json)

__all__ = ["SCHEMA_VERSION", "KINDS", "ContractError", "VersionMismatch", "load_schema", "migrate",
           "validate", "canonical_json", "content_hash", "MAX_DOCUMENT_BYTES", "parse_json"]
__version__ = "0.1.0"
