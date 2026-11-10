# Task4 consumer and initialization evidence

Main path remains the existing 20-task feature-development plan. Task4 is not completed yet. Raw logs stay ignored; versioned completion evidence will contain safe argv, identities, hashes and exit codes.

## Physical state regression

The original SessionDB quarantine predicate reads one physical structural-damage flag before checkpoint/close. An initial extraction kept that flag in SessionDB and mirrored a reason into the resource. The full Linux Native batch on source62dbb6098df2967b4d8bbe64f96cbee63e2e2c565c534bf953bd5158aafbfc88 completed with1886passed/1failed/16skipped, exit1; test_retry_skips_quarantined_handle was red. Windows completed1756passed/147skipped, exit0, which cannot cover this Linux case. The final layout has a single flag/cause in SQLiteConnections, with all real private consumers migrated. SessionDB still owns FTS provenance and profile health. No compatibility property, additional lock, or SessionDB object is passed to infra. Metadata fallback retains the existing IOERR budget and forwards final database errors to the application health publisher.

## Existing external failures reproduced on exact0d

With the new development interpreter and isolated D temporary state, the exact0d archive reproduced5failures in4files: caller-owned compaction connections outlive TemporaryDirectory on Windows; the media fixture exceeds native path length; a profile path is used as an unescaped regex; a file symlink requires unavailable Windows privilege; synchronous application Thread doubles also replace subprocess pipe-reader threads. A separate exact0d RPC probe reproduced the SSH absolute-path rejection. These are not silently classified from symptoms: logs and source identities are retained.

The compaction tests now use SessionDB contexts, preserving every persistence assertion. The media scan uses a short owned fixture root and retains canonical API filenames, digests, holder checks, one-scan assertion and collected-file/receipt assertions; production authorization, pin generation and collection code are unchanged. The profile regex is escaped. The original dangling file-symlink test and assertions remain, with POSIX metadata; Windows symlink capability remains unverified and the original eight Profile defects stay independent. A directory junction was tried as a fixture and correctly rejected as a different marker type; that attempt was reverted, with no production profile-policy change.

## Thread fixture hypothesis and correction

The first attempted server-only threading namespace did not preserve the existing synchronous behavior in all facade/sibling consumers. Adding missing namespace attributes did not fix that and was not stacked further. The final narrow seam retains the original application Thread factory while giving subprocess its actual native Thread/Lock dependency. The exact standard-library dependency was inspected, not inferred from argv. Both prompt-completion and approval-key behavior probes now pass; the full TUI file still must run.

## SSH target-path root cause

Expected: a bound SSH profile may name a POSIX absolute directory without requiring that directory on the control host. Actual: exact0d Windows RPC returned4017. The first divergence is session_workdir._is_remote_cwd_shape using control-host os.path.isabs; native ntpath rejects a single-slash POSIX root. git log -p -S _is_remote_cwd_shape shows a0fe806c46e729894c60e5dd25154400d179b231 intentionally unifies remote absolute/tilde rules. The minimal change accepts a POSIX root in addition to the existing host-absolute/tilde cases. No filesystem, SSH service or DB algorithm changed.

The seven-case regression is called at the bound server facade (the module bodies are intentionally rebound, so an early direct-module NameError run is invalid as a regression proof). At the correct production seam it was5pass/2fail on Windows before the fix and7pass after. Five actual RPC behavior probes passed after, including remote-profile workspaces and prompt/approval behavior. Linux critical physical-state/initialization/path group passed54tests. All mandatory full batches and latest static gates remain required before Task4 completion.

## Environment

C temporary state had0.70GiB free and the original repair headroom blocked tests. The isolated D temporary root had1159.70GiB; thresholds were unchanged. ACP was absent from the original optional-extra set, so project PM built a fresh env-task4-full with existing declared postgresql,messaging,matrix,acp extras. No old environment was mutated. Source-local Linux export/new PM environment will be development evidence only, not Task17 final acceptance.

## Late header import found by the full Linux batch

The source-local Linux224-file batch completed1871passed/17failed/16skipped, exit1. Three files exercising retired WAL capture and invalid-header quarantine reached db_session_schema._parse_sqlite_header, whose function-local import still named the former mixed errors module. A standalone AST import-binding inventory found exactly this unresolved symbol among all moved-module consumers. The import now names the physical header owner in infra; no old-path export is restored. The preceding Windows224-file batch completed1757passed/147skipped, exit0, but does not replace this Linux evidence. A new source export and environment are required for the final Task4 batches.

The full Windows external batch also reproduced the same stdlib Thread-double collision in test_composite_carrier_rewind (16pass/1fail in an isolated rerun). All remaining actual server.threading.Thread test patches now use the existing subprocess-safe helper, preserving their original synchronous factories and assertions. Timer and unrelated thread patches are unchanged. The mandatory external file list expands to every changed test consumer.

## Test temporary-root shape

The remaining two full-TUI failures were fixture placement, not lost session data: the first D temporary root was inside the package checkout. find_project_root correctly found its ancestor .git, and resume correctly refused an install-tree cwd. On exact0d, with the temporary root inside that exact source installation, both original tests failed (0pass/2fail, exit1). An independently owned random D temporary root outside either checkout keeps the original disk headroom and workspace contracts: the same two unchanged tests then passed2/2, exit0. No production workspace policy or assertion was weakened. Both hosts still require their latest complete batches. The original eight Windows Profile failures remain independent.
