import json
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v4_protocol import PROTOCOL_ID, SEED_PURPOSES, derive_seed
from src.dante_light.prefilter_v4_freeze import validate_segment_snapshot


def test_seed_derivation_is_order_independent_but_purpose_separated():
    parents=["a"*64,"b"*64]
    assert derive_seed(PROTOCOL_ID,"cohort",parents)==derive_seed(PROTOCOL_ID,"cohort",reversed(parents))
    assert len({derive_seed(PROTOCOL_ID,p,parents) for p in SEED_PURPOSES})==len(SEED_PURPOSES)


def test_segment_snapshot_is_hash_bound():
    body={"schema_version":1,"status":"FROZEN_GWOSC_SEGMENT_IDENTITIES","flags":{"x":{"segments":[[1,2]],"segments_digest":canonical_json_sha256([[1,2]])}}}
    value={**body,"snapshot_digest":canonical_json_sha256(body)}
    assert validate_segment_snapshot(value)==value
    value["flags"]["x"]["segments"]=[[1,3]]
    with pytest.raises(ContractError): validate_segment_snapshot(value)
