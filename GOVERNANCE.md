# Governance

DANTE is currently a single-maintainer research-software project. Luca Cirfeta
is the project maintainer and release steward.

## Decision process

Routine bug fixes, tests, documentation, and compatibility improvements are
decided through public issues and pull requests. Decisions are based on
correctness, reproducibility, maintenance cost, and compatibility with the
documented scientific contract.

Changes that alter what is measured or how it is validated require a written
proposal before implementation. This includes preprocessing, scoring,
reference populations, thresholds, statistical tests, detector joining,
vetoes, and promotion of experimental components. Such changes must define
their validation evidence and a new run or release identity; existing evidence
is not silently reinterpreted.

## Roles

- **Maintainer:** reviews changes, manages releases, and protects scientific
  and provenance boundaries.
- **Contributors:** propose and implement scoped changes and provide test and
  validation evidence.
- **Reviewers and users:** may report defects, reproduce workflows, and comment
  on proposals without becoming maintainers.

Maintainer status may be offered after sustained, technically sound public
contributions. Changes to project governance will be proposed and reviewed in
the repository before taking effect.

## Releases

Published tags are immutable. Each release must identify its source commit,
versioned configuration, relevant environment, tests, and bounded scientific
claims. A documentation or orchestration release cannot relabel an older
scientific artifact or DOI.

## Project scope

DANTE is research software, not an operational gravitational-wave alert
service. The maintainer provides no uptime, response-time, or discovery
guarantee. Experimental components remain explicitly labelled until their
scientific and operational gates are passed.
