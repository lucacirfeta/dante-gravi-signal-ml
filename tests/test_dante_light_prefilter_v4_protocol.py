import json
from pathlib import Path
import hashlib
import subprocess

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v4_protocol import PROTOCOL_ID, SEED_PURPOSES, derive_seed, repository_reference
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


def test_repository_reference_uses_canonical_git_blob_across_line_endings(tmp_path):
    subprocess.run(["git","init","-q"],cwd=tmp_path,check=True)
    subprocess.run(["git","config","user.name","Test"],cwd=tmp_path,check=True)
    subprocess.run(["git","config","user.email","test@example.invalid"],cwd=tmp_path,check=True)
    path=tmp_path/"sample.py"; path.write_bytes(b"a=1\nb=2\n")
    subprocess.run(["git","add","sample.py"],cwd=tmp_path,check=True)
    subprocess.run(["git","commit","-q","-m","fixture"],cwd=tmp_path,check=True)
    path.write_bytes(b"a=1\r\nb=2\r\n")
    reference=repository_reference(tmp_path,path)
    assert reference["sha256"]==hashlib.sha256(b"a=1\nb=2\n").hexdigest()
