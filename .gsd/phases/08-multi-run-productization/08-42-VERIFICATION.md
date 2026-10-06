# 08.42 native preparation verification

This is preparation-only, not calibration/numerical equivalence or speedup.

- Final targeted WSL suite:75passed,1root-onlyskipped,11upstreamwarnings,
  5.94seconds, observedOS0. Includes unchanged59calibration unit regressions.
- Actual root private read-only mount fixture:1passed,15deselected,1.11seconds,
  observedOS0. Native bytes visible only inside private namespace; writes denied;
  outside original and native source bytes unchanged after child exits.
- Ruff format3files unchanged and lintAll checks passed, actualOS0.
- Frozen scientific raw audit21SHA PASS;10protocol artifact byteSHA PASS.
  No scientific source/config normalization, algorithm, population or tolerance
  change. New filesystem config is operational preparation-only.
- Earlier first preparation suite73PASS/1FAIL exposed top-level exclusion bug,
  corrected before any real preparation. No failed scientific run reinterpreted.
- Detached systemd fixtureUID1000 PID598 journal completion marker and successful
  deactivation; no recurring automation. Mount and launcher tools verified
  locally, no install/global filesystem reconfiguration required.
- FreeC:442974982144bytes; ext4 guest907780648960bytes. Config copied-byte budget
  120GiB checked before copying, alongside2xguest reserve. Old expanded unused
  frame archive excluded from transfer, not from the calibration population.
- Byte preparation pending single real launch; no snapshotPASS or scientific
  stage observed yet. Failure preserves namespace/logs, no automatic resume.
  Full-tree guard scheduling remains unchanged pending author choice.

Historical benchmark: mirror completed actualOS0/all79787files/7889662239bytes;
measurement human-interrupted actualsignalexit-2/supervisorOS1, no speedup result.
Both historical benchmark attempts and interrupted08.40calibration preserved.
