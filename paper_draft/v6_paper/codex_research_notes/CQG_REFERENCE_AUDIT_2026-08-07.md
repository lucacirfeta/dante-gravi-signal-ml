# CQG reference audit (2026-08-07)

## Scope and result

The CQG manuscript cites 38 unique BibTeX keys.  All 38 exist in
`cqg_v6/references.bib`; there are no missing cite keys.  Fourteen retained
bibliography entries are currently uncited and do not enter the rendered
reference list.  The cited set contains 28 DOI-bearing records: 25 journal or
conference DOI records matched Crossref metadata, two Zenodo records matched
DataCite metadata, and the GWOSC auxiliary-data DOI matched the official GWOSC
release page.  Eleven arXiv identifiers in the cited set resolved to the
expected titles through the arXiv API.

## DOI registry checks

Each URL below was checked on 2026-08-07.  `OK` means that the DOI resolved and
the registered title matched the cited work; capitalization-only differences
were ignored.

| BibTeX key | DOI registry URL | result |
|---|---|---|
| `LIGOScientific:2014pky` | https://doi.org/10.1088/0264-9381/32/7/074001 | OK |
| `Acernese_2014` | https://doi.org/10.1088/0264-9381/32/2/024001 | OK |
| `KAGRA:2020tym` | https://doi.org/10.1093/ptep/ptaa125 | OK |
| `nuttall2018` | https://doi.org/10.1098/rsta.2017.0286 | OK |
| `davis2021` | https://doi.org/10.1088/1361-6382/abfd85 | OK |
| `powell2015` | https://doi.org/10.1088/0264-9381/32/21/215012 | OK |
| `pankow2018` | https://doi.org/10.1103/PhysRevD.98.084016 | OK |
| `zevin2017` | https://doi.org/10.1088/1361-6382/aa5cea | OK |
| `glanzer2023` | https://doi.org/10.1088/1361-6382/acb633 | OK |
| `gwosc2023` | https://doi.org/10.3847/1538-4365/acdc9f | OK |
| `gwosc_aux_o4` | https://doi.org/10.7935/kt51-6n86 | OK; official GWOSC record |
| `dante_zenodo` | https://doi.org/10.5281/zenodo.21676289 | OK; DataCite |
| `gspy_zenodo` | https://doi.org/10.5281/zenodo.5649212 | OK; DataCite |
| `welch1967` | https://doi.org/10.1109/TAU.1967.1161901 | OK |
| `wilson1927` | https://doi.org/10.1080/01621459.1927.10502953 | OK |
| `kunsch1989` | https://doi.org/10.1214/aos/1176347265 | OK |
| `sculley2010` | https://doi.org/10.1145/1772690.1772862 | OK |
| `chatterji2004` | https://doi.org/10.1088/0264-9381/21/20/024 | OK |
| `essick2020` | https://doi.org/10.1088/2632-2153/abab5f | OK |
| `cuoco2021` | https://doi.org/10.1088/2632-2153/abb93a | OK |
| `razzano2018` | https://doi.org/10.1088/1361-6382/aab793 | OK |
| `coughlin2019` | https://doi.org/10.1103/PhysRevD.99.082002 | OK |
| `george2018` | https://doi.org/10.1103/PhysRevD.97.101501 | OK |
| `biswas2013` | https://doi.org/10.1103/PhysRevD.88.062003 | OK |
| `mukund2017` | https://doi.org/10.1103/PhysRevD.95.104059 | OK |
| `bahaadini2018` | https://doi.org/10.1016/j.ins.2018.02.068 | OK |
| `vajente2020` | https://doi.org/10.1103/PhysRevD.101.042003 | OK |
| `ormiston2020` | https://doi.org/10.1103/PhysRevResearch.2.033066 | OK |

## arXiv checks

The following cited identifiers resolve to the expected titles through
`https://export.arxiv.org/api/query?id_list=...`: `2607.18136`, `2304.07193`,
`2309.16588`, `2309.11537`, `2507.12374`, `2508.18079`, `2401.12913`,
`2409.02831`, `2208.03623`, `2310.03453`, and `gr-qc/0412119`.

## Corrections made during the audit

- `chatterji2004` now names S. Chatterji, L. Blackburn, G. Martin and
  E. Katsavounidis, gives *Classical and Quantum Gravity* 21 S1809--S1818,
  DOI `10.1088/0264-9381/21/20/024`, and arXiv `gr-qc/0412119`.
- The unverified `jadhav2024` entry was removed from the cited chain and
  replaced by George, Shen and Huerta (2018), DOI
  `10.1103/PhysRevD.97.101501`, arXiv `1711.07468`.
- `dante_v1` now points to arXiv `2607.18136` and its registered current title.
  The manuscript explicitly describes the CQG article as a self-contained,
  substantially extended journal treatment, rather than concealing the
  evolving preprint.

## Reproducible closure commands

The cite-key closure is checked by extracting every comma-separated key from
`\\cite{...}` in `main.tex` and comparing it with every BibTeX entry key.
BibTeX compilation is the second fail-closed check: an undefined citation or
missing database entry prevents the submission gate from passing.  Registry
metadata were obtained from Crossref (`api.crossref.org/works/<doi>`), DataCite
(`api.datacite.org/dois/<doi>`), the arXiv export API, and the official GWOSC
auxiliary-data release record.
