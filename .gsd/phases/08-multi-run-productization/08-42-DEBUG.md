---
status: resolved
trigger: "procedi"
created: 2026-10-06
updated: 2026-10-06
---

## Symptoms

prepare_v2 exitedOS1 during inventory; no copied bytes. checked() rejected a
source directory because C:data/reference is a legitimate existing junction.

## Evidence

Seven trees checked individually: six direct, reference resolves to the E:
reference_artifacts/v1/data/reference tree. Admission/mirror schemas coherent.
No hash mismatch, network fetch, numeric mismatch or scientific stage started.

## Resolution

v3names canonical physical source and retains original logical C: destination.
Only virtual-name validation is lexical; physical source rejects symlink trees
and leaf copy still O_NOFOLLOW/regular-file checked. Historical junction/files
untouched.79testsPASS/1SKIP/11warnings/5.87s/OS0; seven actual source routesPASS.
New namespace required; failed v2 preserved. No scientific method change.
