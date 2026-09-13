# Clawpatch Remediation Plan

**Status:** Approved — repository owner/requesting user, 2026-09-11.

**Baseline:** Clawpatch mapped 63 semantic features and reported 149 open findings (32 high, 111 medium, 6 low). This plan assigns every finding to exactly one of 37 bounded batches. The authoritative evidence remains in `.clawpatch/reports/20260911T105524-37b7cd.md`.

## Objective

Resolve every recorded finding without weakening strict all-cases assessment, scoring provenance, failure visibility, filesystem confinement, process cleanup, or secret handling.

## Non-negotiable invariants

- Preserve canonical scoring and immutable provenance; unavailable or malformed evidence must never become a clean result.
- Preserve strict all-cases semantics; isolated passes and missing evidence must never imply solved status.
- Keep `continue_after_test_failure` independent from assessment policy.
- Confine every read, write, extraction, deletion, and materialization operation to its declared root.
- Preserve argv boundaries; shell text must be produced only from a fully quoted argv representation.
- Terminate and reap complete process/container trees on timeout, cancellation, and cleanup.
- Never log secrets. Tests use synthetic sentinels and assert redaction or absence.
- For findings that replace persisted artifacts, retain the original until the replacement validates and publishes successfully.
- Keep only regression tests that assert observable contracts or plausible recurrence; replace or delete weak tests rather than pinning implementation details.

## Execution rules

1. Execute batches in dependency order. Batches with disjoint production/documentation and test mutation boundaries may run concurrently.
2. Start each batch by reproducing its assigned IDs. Store status and evidence through Clawpatch triage/revalidation so the registry remains the single finding record.
3. Inspect references and blast radius before changing an exported or shared contract. Implement the smallest shared root-cause fix, migrate every caller, and remove obsolete paths without compatibility shims.
4. Run the registry `Verify` check for every included ID. Add a smoke check only when that check does not exercise the changed observable path.
5. Mutate files only inside the batch boundaries. Revalidate each included ID independently with `clawpatch revalidate --finding <id>`. Commit only if separately authorized.
6. After every registry ID is revalidated, run the repository-required suite once. Completion requires every ID to be `fixed` or to have an explicitly approved, evidenced `false-positive` or `wont-fix` disposition.

## Batch ledger

Each registry row names one batch. Production/documentation and test boundaries contain literal paths or globs and do not overlap across batches. A `(new)` path is created only when no existing owner file fits. A prerequisite finishes before its dependent mutates files.

| Batch | Findings | Production/documentation mutation boundary | Test mutation boundary | Prerequisites |
|---|---:|---|---|---|
| `C01` — Problem-runner orchestration | 4 | `src/slop_code/entrypoints/problem_runner/{driver,worker}.py` | `tests/entrypoints/problem_runner/{test_driver,test_one_shot}.py` | None |
| `C02` — Entrypoint output utilities | 4 | `src/slop_code/entrypoints/utils.py; src/slop_code/entrypoints/commands/run_agent.py` | `tests/entrypoints/test_utils_summary.py; tests/entrypoints/commands/test_run_agent.py` | None |
| `C03` — Problem catalog lifecycle | 2 | `src/slop_code/problem_catalog.py` | `tests/problem_catalog_test.py` | None |
| `C04` — Protocol loading | 1 | `src/slop_code/protocol_loader.py` | `tests/protocol_loader_test.py` | None |
| `C05` — Logging contracts | 2 | `src/slop_code/logging.py` | `tests/logging_test.py` | None |
| `C06` — Prompt rendering | 3 | `src/slop_code/common/render.py` | `tests/common/render_test.py` | None |
| `C08` — Experiment allocation | 2 | `src/slop_code/utils.py` | `tests/utils_test.py (new)` | None |
| `E01` — Local process lifecycle | 4 | `src/slop_code/execution/{local_exec,local_streaming}.py` | `tests/execution/{local_exec,local_streaming}_test.py` | None |
| `E02` — Docker process lifecycle | 5 | `src/slop_code/execution/docker_runtime/{exec,streaming}.py` | `tests/execution/docker_runtime/{exec,streaming}_test.py` | None |
| `E03` — Structured and raw file operations | 5 | `src/slop_code/execution/file_ops/**` | `tests/execution/file_ops_test.py` | None |
| `E04` — Workspace, snapshot, and assets | 6 | `src/slop_code/execution/{workspace,snapshot,assets}.py` | `tests/execution/{workspace,snapshot_diff}_test.py` | None |
| `E05` — Stream and session cleanup | 3 | `src/slop_code/execution/{stream_processor,session}.py` | `tests/execution/{stream_processor,session}_test.py` | E01, E02 |
| `A01` — Shared agent runner lifecycle | 6 | `src/slop_code/agent_runner/{agent,runner,resume,trajectory_parsing}.py; src/slop_code/agent_runner/agents/cli_utils.py` | `tests/agent_runner/test_runner_unit.py; tests/agent_runner/test_runner_integration.py; tests/agent_runner/{resume,resume_integration}_test.py; tests/agent_runner/test_registry.py; tests/agent_runner/parsers/test_new_parsers.py; tests/agent_runner/agents/cli_utils_test.py (new)` | E05 |
| `A02` — Cursor adapter | 2 | `src/slop_code/agent_runner/agents/cursor_cli/**` | `tests/agent_runner/agents/cursor_cli_agent_test.py` | A01 |
| `A03` — Kimi adapter | 2 | `src/slop_code/agent_runner/agents/kimi_cli/**` | `tests/agent_runner/agents/kimi_cli_agent_test.py` | A01 |
| `A04` — Gemini adapter | 3 | `src/slop_code/agent_runner/agents/gemini/**` | `tests/agent_runner/agents/gemini_agent_test.py` | A01 |
| `A05` — OpenHands adapter | 3 | `src/slop_code/agent_runner/agents/openhands/**` | `tests/agent_runner/agents/openhands_agent_test.py` | A01 |
| `A06` — Claude Code adapter | 2 | `src/slop_code/agent_runner/agents/claude_code/**` | `tests/agent_runner/agents/{claude_code_agent,claude_code_stream_parser}_test.py` | A01 |
| `A07` — MiniSWE adapter | 2 | `src/slop_code/agent_runner/agents/{miniswe.py,miniswe/**}` | `tests/agent_runner/agents/miniswe_parser_test.py; tests/agent_runner/agents/miniswe_agent_test.py (new)` | A01 |
| `A08` — Codex adapter | 5 | `src/slop_code/agent_runner/agents/codex/**` | `tests/agent_runner/agents/codex_agent_test.py; tests/agent_runner/parsers/test_fixtures.py` | A01 |
| `A09` — OpenCode adapter | 1 | `src/slop_code/agent_runner/agents/opencode/**` | `tests/agent_runner/agents/opencode_test.py` | A01 |
| `A10` — Pi adapter | 2 | `src/slop_code/agent_runner/agents/pi/**` | `tests/agent_runner/agents/pi_agent_test.py` | A01 |
| `V01` — Evaluation collection and execution | 5 | `src/slop_code/evaluation/**` | `tests/evaluation/**` | E04, E05 |
| `V02` — Canonical and production scoring | 11 | `src/slop_code/metrics/scoring/**` | `tests/metrics/scoring_*.py` | V01 |
| `V04` — Evaluation reporting lifecycle | 3 | `src/slop_code/entrypoints/evaluation/**` | `tests/entrypoints/test_evaluation_driver.py; tests/entrypoints/commands/test_backfill_reports.py` | V01, V02 |
| `M01` — Python language metrics | 6 | `src/slop_code/metrics/languages/python/**` | `tests/metrics/language/**` | None |
| `M02` — Checkpoint, summary, registry, and metric driver | 10 | `src/slop_code/metrics/{checkpoint,summary}/**; src/slop_code/metrics/{driver,grade,quality_io}.py` | `tests/metrics/{driver,models,summary,checkpoint_results}_test.py` | V01, M01 |
| `M03` — Rubric grading and carry-forward | 6 | `src/slop_code/metrics/rubric/**` | `tests/metrics/rubric/**` | V02 |
| `D01` — Dashboard data and strict classification | 5 | `src/slop_code/dashboard/{app,data}.py` | `tests/dashboard/data_test.py` | V02, M02 |
| `D02` — Dashboard graphs | 5 | `src/slop_code/dashboard/graphs/**` | `tests/dashboard/graphs/**` | D01 |
| `D03` — Dashboard pages | 5 | `src/slop_code/dashboard/pages/**` | `tests/dashboard/pages_test.py (new)` | D01, D02 |
| `D04` — Standalone visualization | 3 | `src/slop_code/visualization/**` | `tests/visualization/annotations_test.py; tests/visualization/data_transforms_test.py (new); tests/visualization/chart_builders_test.py (new); tests/visualization/diff_viewer_test.py (new)` | None |
| `Q01` — Configuration and shared LLM loading | 5 | `src/slop_code/entrypoints/config/**; src/slop_code/common/llms.py` | `tests/entrypoints/config/**; tests/agent_runner/llms_test.py` | None |
| `Q02` — Evaluation commands | 3 | `src/slop_code/entrypoints/commands/{eval_problem_dir,eval_run_dir}.py; docs/commands/eval.md` | `tests/entrypoints/commands/{test_eval_run_dir,test_eval_run_dir_writes_config,test_eval_checkpoint_cli}.py` | V01, V04 |
| `Q03` — Artifact and catalog commands | 5 | `src/slop_code/entrypoints/commands/{backfill_categories,compress_artifacts,consolidate_runs,infer_problem,migrate_evaluation_format}.py` | `tests/entrypoints/commands/test_consolidate_runs.py; tests/entrypoints/commands/test_migrate_evaluation_format.py; tests/entrypoints/commands/test_infer_problem.py (new); tests/entrypoints/commands/test_compress_artifacts.py (new)` | C03, C08 |
| `Q04` — Rendering, static metrics, and variance commands | 4 | `src/slop_code/entrypoints/commands/{render_prompts,static,variance}.py` | `tests/entrypoints/commands/test_variance.py; tests/entrypoints/commands/test_render_prompts.py (new); tests/entrypoints/commands/test_static.py (new)` | C06, M02 |
| `Q05` — Maintenance scripts | 4 | `scripts/{mass_delta_analysis,analyze_trajectory,migrate_specs_solutions}.py` | `tests/metrics/test_mass_delta.py; tests/scripts/analyze_trajectory_test.py (new); tests/scripts/migrate_specs_solutions_test.py (new)` | None |

## Finding implementation registry

The registry is exhaustive. “Change” is the selected implementation contract; “Scope” is the minimum surface; “Verify” is the consumer-visible acceptance check.

### WS1 — Core safety, catalog, rendering, and shared contracts (12 findings)

- [ ] `fnd_sig-feat-library-a1c6cc683e-5451_70b45a0485` — **Promotion rollback can delete the existing catalog and manifest** (high; data-loss; current triage: confirmed-bug; status: open)
  - **Batch:** `C03`
  - **Change:** Track completed promotion operations explicitly and undo only those operations. Never delete an original destination whose backup was not successfully created.
  - **Scope:** _promote_install, _rollback_promotion, and catalog failure-preservation tests.
  - **Verify:** Extend installation-preservation coverage with failures at each promotion rename and assert the original catalog and manifest remain byte-for-byte intact.
- [ ] `fnd_sig-feat-library-a1c6cc683e-6960_da51e7d188` — **Protocol loading can return an implementation from a different file** (high; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `C04`
  - **Change:** Use a module/package identity derived from the resolved source location and load that exact file, preserving relative-import support without sharing cached packages across different roots.
  - **Scope:** load_protocol_entrypoint import identity and protocol-loader tests.
  - **Verify:** Extend nested loading coverage to load same-named packages from different roots sequentially, including relative dependencies, and verify each implementation and dependency comes from its requested root.
- [ ] `fnd_sig-feat-library-b487360049-a404_3d2d4e3a67` — **Canary stripping deletes specification content through later HTML comments** (high; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `C06`
  - **Change:** Bound matching to the first closing comment delimiter, preserving all subsequent specification content.
  - **Scope:** Update CANARY_HTML_COMMENT_PATTERN and extend TestStripCanaryString.
  - **Verify:** Expand canary stripping scenarios to include leading single-line and multiline canaries followed by requirements and additional HTML comments; assert the entire suffix is preserved.
- [ ] `fnd_sig-feat-library-5f1fe93632-58f6_5052a217c4` — **Final progress updates are discarded when all futures finish** (medium; concurrency; current triage: confirmed-bug; status: open)
  - **Batch:** `C01`
  - **Change:** After all producers finish, drain remaining progress messages through the same update handler and refresh the display before returning.
  - **Scope:** driver.py progress-consumption loop and tests/entrypoints/problem_runner/test_driver.py.
  - **Verify:** Expand the executor scenario to cover queued updates before and during future completion, asserting that every problem's final state, usage, and evaluation counts are applied.
- [ ] `fnd_sig-feat-library-5f1fe93632-e664_d8d8014e63` — **Problem setup failures escape per-problem error handling** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `C01`
  - **Change:** Include per-problem setup in the worker's exception boundary so setup failures also return a TaskResult with diagnostic information.
  - **Scope:** driver.py worker exception boundary and tests/entrypoints/problem_runner/test_driver.py.
  - **Verify:** Exercise configuration, directory, and logging setup failures alongside a successful sibling and assert that the batch returns one structured result per problem.
- [ ] `fnd_sig-feat-library-5f1fe93632-f7c7_9514b0429b` — **Completed resume skips are returned as failed tasks** (medium; api-contract; current triage: contract-mismatch; status: open)
  - **Batch:** `C01`
  - **Change:** Use a consistent successful completion contract for fully completed resume skips between the worker and driver, without conflating execution completion with strict evaluation success.
  - **Scope:** worker.py completion summary or driver.py outcome classification, plus driver tests.
  - **Verify:** Cover normal completion, completed resume skips, and actual failures through the worker-to-driver boundary, asserting consistent TaskResult outcomes.
- [ ] `fnd_sig-feat-library-a1860c398b-2779_5862527eae` — **Saving the summary also prints it to global stdout** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `C02`
  - **Change:** Give the recording console a private in-memory output stream, then export its recorded text to the summary file.
  - **Scope:** The recording console initialization in _save_experiment_summary and summary output-routing coverage.
  - **Verify:** Test that summary generation writes to the supplied console and artifact while leaving unrelated stdout untouched, with both available and unavailable scoring.
- [ ] `fnd_sig-feat-library-a1860c398b-9426_6377cb3631` — **Generation ID is reread separately from verified scoring evidence** (medium; concurrency; current triage: risk; status: open)
  - **Batch:** `C02`
  - **Change:** In `_verified_score_projection`, read the current generation pointer before and after loading the verified current state. Publish the projection only when both pointer reads match; on mismatch, retry the complete read once, then return scoring unavailable if the pointer changes again. Use the stable pointer value as the projection generation ID.
  - **Scope:** _verified_score_projection and the verified-state return contract if it does not already expose the verified generation ID.
  - **Verify:** Hold the pointer stable and assert one internally consistent projection. Advance it during the first load and assert one full retry returns only the second stable generation. Advance it during both attempts and assert scoring unavailable; never pair one generation’s evidence with another ID.
- [ ] `fnd_sig-feat-library-a1c6cc683e-4b97_5f2cbd27d0` — **Concurrent experiment allocations can share one output directory** (medium; concurrency; current triage: confirmed-bug; status: open)
  - **Batch:** `C08`
  - **Change:** Reserve each candidate output directory with exclusive `mkdir`; on `FileExistsError`, choose and reserve the next candidate.
  - **Scope:** get_next_experiment_dir reservation logic and concurrent allocation tests.
  - **Verify:** Run multiple synchronized allocators against one parent and assert all successful calls return distinct, newly created directories.
- [ ] `fnd_sig-feat-library-a1c6cc683e-723e_aac0f76086` — **Experiment numbering reads numeric suffixes from ancestor directories** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `C08`
  - **Change:** Match an escaped prefix and numeric suffix against each child's name only, using a full match, and reject an already-existing destination.
  - **Scope:** get_next_experiment_dir suffix parsing and directory-allocation tests.
  - **Verify:** Cover numbering under ancestors containing experiment-like names and with varied literal prefixes, asserting every successful allocation creates a previously absent directory.
- [ ] `fnd_sig-feat-library-a1c6cc683e-fb2b_9c958f47d4` — **The stdlib adapter bypasses logger-level and disabled-state filtering** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `C05`
  - **Change:** After determining the effective level, check isEnabledFor before formatting kwargs or creating a record, or use the public logger.log method.
  - **Scope:** StdlibLoggerAdapter._log and adapter logging tests.
  - **Verify:** Extend adapter filtering coverage across logger thresholds, logging.disable, and VERBOSE conversion; assert suppressed calls neither emit records nor serialize structured values.
- [ ] `fnd_sig-feat-library-b487360049-0548_049163a0e5` — **Entrypoint substitutions interpret literal backslashes as regex replacement syntax** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `C06`
  - **Change:** Use literal string replacement or callable regex replacements for both placeholders.
  - **Scope:** Change replace_spec_placeholders and extend the existing prompt substitution test.
  - **Verify:** Parameterize the existing placeholder scenario with paths and commands containing literal backslashes, escape sequences, and group-reference-like text; assert exact preservation.

### WS2 — Execution, filesystems, and process lifecycle (20 findings)

- [ ] `fnd_sig-feat-library-2d56c14338-2daa_af408aab54` — **Blocking text reads can stall streaming and deadlock output draining** (high; concurrency; current triage: confirmed-bug; status: open)
  - **Batch:** `E01`
  - **Change:** Read available bytes from binary pipes using nonblocking reads or bounded raw reads, and decode each stream incrementally.
  - **Scope:** Streaming subprocess pipe configuration, _create_demuxed_stream, and streaming output tests.
  - **Verify:** Extend mixed-output coverage with a synchronized child that emits a short flushed marker followed by stderr exceeding pipe capacity. Assert prompt marker delivery and complete draining under an independent watchdog, including split multibyte characters.
- [ ] `fnd_sig-feat-library-2d56c14338-e1d2_9e3deaa28a` — **Timeout and cleanup kill only the direct child, leaving descendants alive** (high; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `E01`
  - **Change:** Launch commands in an owned process group/session and terminate the group on timeout and cleanup, with bounded output draining and direct-child reaping.
  - **Scope:** Process creation and termination paths in both local runtimes, plus their timeout and cleanup tests.
  - **Verify:** Expand timeout and cleanup scenarios across both runtimes to include a parent with a long-running descendant that inherits output pipes. Assert bounded completion and that both processes terminate, using independent cleanup for failed assertions.
- [ ] `fnd_sig-feat-library-9b348010a5-1782_0b712e286e` — **Materialization can write outside the working directory** (high; security; current triage: confirmed-bug; status: open)
  - **Batch:** `E03`
  - **Change:** Reject absolute and escaping paths and enforce destination containment, including symlink handling, before creating directories or opening files.
  - **Scope:** Destination validation in materialize_input_files.
  - **Verify:** Exercise ordinary nested paths, absolute paths, parent traversal, and symlink escapes; assert rejected destinations leave outside files unchanged.
- [ ] `fnd_sig-feat-library-9b348010a5-4dba_f27d4f2ad2` — **SQLite replacement deletes the original before the new database succeeds** (high; data-loss; current triage: confirmed-bug; status: open)
  - **Batch:** `E03`
  - **Change:** Build and close the replacement in a sibling temporary file, replacing the destination atomically only after successful completion; clean up failed temporary files.
  - **Scope:** SQLiteHandler.write replacement lifecycle.
  - **Verify:** Verify that schema errors and insertion failures preserve an existing destination byte-for-byte, while successful replacements contain the complete requested database.
- [ ] `fnd_sig-feat-library-a779b6f7f0-2438_1f7041d1ab` — **Synchronous stdin writes can deadlock before timeout enforcement** (high; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `E02`
  - **Change:** Pass encoded input to communicate so input delivery and output draining run together under the timeout, and ensure exceptional paths terminate and reap the execution.
  - **Scope:** DockerExecRuntime stdin handling and execute lifecycle.
  - **Verify:** Expand stdin coverage to large input, commands that do not consume input, and simultaneous large output, asserting bounded timeout and cleanup.
- [ ] `fnd_sig-feat-library-a779b6f7f0-9a94_627969111e` — **Docker command logging exposes environment secrets** (high; security; current triage: confirmed-bug; status: open)
  - **Batch:** `E02`
  - **Change:** Log safe command metadata without environment values, or redact values in a separate logging representation.
  - **Scope:** Both Docker command builders and their environment tests.
  - **Verify:** Extend environment propagation scenarios to capture logs and assert that synthetic sensitive values are absent while still reaching the subprocess.
- [ ] `fnd_sig-feat-library-a779b6f7f0-d0aa_855ae9b5a4` — **Timeouts kill Docker clients while container workloads continue** (high; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `E02`
  - **Change:** Track and explicitly terminate the daemon-side execution on timeout and cancellation. For one-shot runs, retain a unique container identity and force removal; for streaming runs, terminate the command process group or stop and recreate the container.
  - **Scope:** Timeout and cancellation lifecycle in both runtimes.
  - **Verify:** Extend timeout and cancellation scenarios to assert that delayed writes never occur and no timed-out workload remains running.
- [ ] `fnd_sig-feat-library-bd130bc9cb-8d7f_6dc402465e` — **File collection can read outside the workspace** (high; security; current triage: confirmed-bug; status: open)
  - **Batch:** `E04`
  - **Change:** Apply a consistent containment and symlink policy to every collection branch. Reject parent traversal and prevent reads through paths resolving outside the workspace.
  - **Scope:** Workspace.get_file_contents path validation and candidate selection.
  - **Verify:** Expand file collection scenarios across literal, glob, and directory requests with external symlink targets and parent traversal; assert no external contents are returned.
- [ ] `fnd_sig-feat-library-bd130bc9cb-c8f6_a7210ad4ec` — **Snapshot restoration drops executable permissions and links** (high; data-loss; current triage: confirmed-bug; status: open)
  - **Batch:** `E04`
  - **Change:** Restore regular files, directories, executable mode bits, symbolic links, and hard links. Permit only relative link targets that resolve within the snapshot root. Validate the complete archive first and reject absolute targets, escaping targets, device nodes, FIFOs, sockets, and other special entries before mutating the destination.
  - **Scope:** Snapshot archive restoration and filesystem metadata handling.
  - **Verify:** Round-trip regular files, executable files, safe relative symbolic links, and hard links through both prepare and reset. Reject absolute/escaping links and special entries before mutation; assert no outside write and no partially published destination.
- [ ] `fnd_sig-feat-library-bd130bc9cb-f780_61df02b942` — **Stream timeout can block indefinitely while joining the pump** (high; concurrency; current triage: confirmed-bug; status: open)
  - **Batch:** `E05`
  - **Change:** Provide a cancellation mechanism that interrupts the underlying stream read, and bound pump shutdown by an explicit cleanup deadline.
  - **Scope:** Stream pump cancellation and process_stream shutdown.
  - **Verify:** Test silent and partially emitting blocked streams, asserting bounded timeout completion and pump termination. Release blocked test iterators in teardown.
- [ ] `fnd_sig-feat-library-2d56c14338-6ee1_9773306e2b` — **Streaming execution drops spawn-time environment variables** (medium; api-contract; current triage: contract-mismatch; status: open)
  - **Batch:** `E01`
  - **Change:** Merge self._env_vars with the per-command env before calling get_full_env, allowing per-command values to override spawn-time values.
  - **Scope:** LocalStreamingRuntime._start_process and streaming environment tests.
  - **Verify:** Extend streaming environment coverage to check preservation of spawn-only and command-only variables and command-level precedence for overlapping keys.
- [ ] `fnd_sig-feat-library-9b348010a5-7f2b_790f45bda7` — **Compressed text reads use binary mode with a text encoding** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `E03`
  - **Change:** Open text reads explicitly in 'rt' mode for all compression settings.
  - **Scope:** TextHandler.read stream mode.
  - **Verify:** Verify text write/read round trips with NONE, GZIP, and BZIP2 compression using Unicode and empty content.
- [ ] `fnd_sig-feat-library-9b348010a5-a82d_de049b31b2` — **SQLite reads discard columns required to recreate empty tables** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `E03`
  - **Change:** Include column metadata in the reader's table payload using the writer's supported columns/rows representation.
  - **Scope:** SQLiteHandler.read table metadata serialization.
  - **Verify:** Round-trip databases with populated tables, empty tables, and mixtures of both; verify table names, columns, and rows survive.
- [ ] `fnd_sig-feat-library-9b348010a5-cb5e_0204388d60` — **Binary fallback retains the text handler for materialization** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `E03`
  - **Change:** Propagate the effective BINARY signature when fallback reading succeeds so subsequent writes preserve the bytes.
  - **Scope:** Binary fallback signature propagation through InputFile construction.
  - **Verify:** Round-trip unknown-extension files containing valid UTF-8 and arbitrary binary bytes through both InputFile constructors and materialization; assert byte preservation for binary fallback.
- [ ] `fnd_sig-feat-library-a779b6f7f0-55cc_02afb5ef72` — **Streaming port mappings reverse the public host-to-container mapping** (medium; api-contract; current triage: contract-mismatch; status: open)
  - **Batch:** `E02`
  - **Change:** Translate the public host-to-container mapping into Docker SDK container-to-host bindings before creating the container.
  - **Scope:** Streaming port conversion and port mapping tests.
  - **Verify:** Extend port scenarios to verify SDK bindings and host connectivity for unequal host and container ports, while retaining host-network behavior.
- [ ] `fnd_sig-feat-library-a779b6f7f0-c21e_4b8fd2fe9d` — **Failed container startup loses the container needed for cleanup** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `E02`
  - **Change:** Retain ownership immediately after creation and explicitly remove the container if startup fails, preserving the original startup error.
  - **Scope:** DockerStreamingRuntime container startup failure handling and lifecycle tests.
  - **Verify:** Expand lifecycle coverage with startup failures after successful creation and assert removal, client closure, and safe repeated cleanup.
- [ ] `fnd_sig-feat-library-bd130bc9cb-41c8_51607d846b` — **Path normalization strips meaningful leading dots** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `E04`
  - **Change:** Remove only explicit current-directory prefixes while preserving hidden path components and glob syntax.
  - **Scope:** Workspace.get_file_contents normalization.
  - **Verify:** Extend literal and glob collection tests with hidden paths, optional './' prefixes, and similarly named non-hidden files.
- [ ] `fnd_sig-feat-library-bd130bc9cb-43e1_d58b9bc000` — **Stream iterator failures are lost and can stall the consumer** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `E05`
  - **Change:** Send pump exceptions through the queue and ensure every pump termination signals the consumer; propagate the failure after cleanup.
  - **Scope:** Pump event protocol and process_stream error handling.
  - **Verify:** Exercise iterator failures both before output and after partial output, verifying prompt error propagation and completed cleanup.
- [ ] `fnd_sig-feat-library-bd130bc9cb-cb39_37ffbcb881` — **One runtime cleanup failure prevents all remaining cleanup** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `E05`
  - **Change:** Attempt cleanup for every runtime and the workspace, then report collected failures while retaining useful context from any original session exception.
  - **Scope:** Session.cleanup and context-manager teardown error handling.
  - **Verify:** Expand cleanup tests with failures at different positions across streaming and execution runtimes, asserting every resource receives a cleanup attempt and errors remain observable.
- [ ] `fnd_sig-feat-library-bd130bc9cb-f0a4_64aef18dd0` — **Nested file assets fail when their destination parents do not exist** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `E04`
  - **Change:** Create the file destination's parent directories before copying, subject to workspace containment checks.
  - **Scope:** Workspace._maybe_materialize_static_assets file-copy branch.
  - **Verify:** Expand asset materialization coverage to nested file destinations with absent and existing parents, including repeated materialization.

### WS3 — Agent adapters, parsing, and usage accounting (26 findings)

- [ ] `fnd_sig-feat-cli-command-f2682fcc7e-_5b52309309` — **Configured arguments are interpolated into shell code without quoting** (high; security; current triage: confirmed-bug; status: open)
  - **Batch:** `A02`
  - **Change:** Build a literal argv list and apply shlex.join to the entire invocation. Keep the fixed PATH export separate from the quoted invocation, or pass PATH through the runtime environment.
  - **Scope:** CursorCliAgent._build_command and _run_invocation command serialization.
  - **Verify:** Test that binary paths, model values, and extra arguments containing whitespace, quotes, dollar signs, and shell metacharacters reach a test executable unchanged and cause no shell side effects.
- [ ] `fnd_sig-feat-library-4a81fc4e56-2172_86c2b36520` — **Nonzero process exits are accepted after any completed step** (high; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `A09`
  - **Change:** Validate the finished result's exit code before returning normally. Explicitly distinguish intentional termination caused by enforced limits from unexpected process failure.
  - **Scope:** OpenCodeAgent.run and focused runtime-stream tests; track intentional limit termination if needed.
  - **Verify:** Exercise successful completion, nonzero exits before and after intermediate steps, structured error events, and intentional limit-triggered termination. Assert that unexpected process failures always raise AgentError regardless of prior progress.
- [ ] `fnd_sig-feat-library-4ddc042c0c-689c_d66fc25d30` — **Retry usage replaces previously incurred cost and tokens** (high; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `A04`
  - **Change:** Accumulate invocation cost and net tokens across retries, while maintaining current_tokens according to its intended per-invocation contract.
  - **Scope:** GeminiAgent._sync_usage and retry accounting tests.
  - **Verify:** Exercise a run followed by multiple retries with distinct usage totals; verify cumulative cost, net tokens, steps, and enforcement when combined consumption crosses a limit.
- [ ] `fnd_sig-feat-library-94a87ca9bc-ce04_8e3722ebc5` — **Resumed session totals are added again as invocation usage** (high; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `A08`
  - **Change:** Track previously accounted cumulative totals per session and add only their deltas, or consistently account using invocation-local usage.
  - **Scope:** CodexAgent cumulative usage accounting and retry coverage.
  - **Verify:** Exercise multiple resumed invocations with cumulative token and cost reports, asserting accumulated usage equals the latest session total and limits are evaluated against actual consumption.
- [ ] `fnd_sig-feat-library-b1599e62e1-77e1_a3e2e5b6c2` — **Runner cleanup is bypassed by setup and cleanup failures** (high; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `A01`
  - **Change:** Protect setup with the run lifecycle cleanup boundary, track acquired resources, and independently attempt agent cleanup, session closure, and result persistence while preserving the primary failure.
  - **Scope:** AgentRunner.run, setup resource tracking, and finish teardown sequencing.
  - **Verify:** Exercise failures at each resource acquisition and teardown stage; verify every acquired resource is released exactly once and the original failure remains identifiable.
- [ ] `fnd_sig-feat-library-b1599e62e1-f8b4_f739ecabef` — **Archive extraction can write outside the temporary directory** (high; security; current triage: confirmed-bug; status: open)
  - **Batch:** `A01`
  - **Change:** Pass filter="data" explicitly to extractall and translate rejected or invalid archives into ParseError.
  - **Scope:** parse_trajectory archive extraction and focused archive safety coverage.
  - **Verify:** Test traversal, absolute paths, and escaping links on the minimum supported Python version; assert extraction fails without creating files outside the temporary directory.
- [ ] `fnd_sig-feat-cli-command-07e2c9afa6-_34fde2045e` — **Wire parsing depends on JSON member order and absorbs trailing diagnostics** (medium; api-contract; current triage: contract-mismatch; status: open)
  - **Batch:** `A03`
  - **Change:** Use shared JSON-aware framing for batch and streaming parsing. Validate jsonrpc after decoding, accept arbitrary member order and legal whitespace, and stop accumulating a message once its JSON object is complete while retaining support for multiline payloads.
  - **Scope:** Replace the framing logic in parser.py and reuse it for streamed event parsing in agent.py.
  - **Verify:** Exercise equivalent wire messages across member order, legal whitespace, multiline control-character payloads, and surrounding diagnostic lines; assert identical events, usage, and final-result detection.
- [ ] `fnd_sig-feat-cli-command-f2682fcc7e-_94fbda7f70` — **Trajectory detection crashes on valid JSON values that are not objects** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `A02`
  - **Change:** Validate decoded event and nested message types before accessing fields. During detection, skip incompatible records; during parsing, report invalid event shapes with line-numbered ParseError exceptions.
  - **Scope:** CursorCliParser.can_parse and parse event-shape validation.
  - **Verify:** Cover scalar, null, and array records, plus invalid nested assistant message shapes. Assert detection remains boolean and parsing either accepts supported shapes or raises a line-numbered ParseError.
- [ ] `fnd_sig-feat-library-1c4859137b-f14e_41ad7f6fc8` — **MiniSWE setup ignores failed setup commands** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `A07`
  - **Change:** Check every setup command's returncode and raise a setup failure immediately on nonzero status, identifying the failed command without exposing sensitive output.
  - **Scope:** Validate execution results in MiniSWEAgent.setup and add setup lifecycle coverage.
  - **Verify:** Exercise successful setup sequences and failures at different positions. Assert that a failure prevents subsequent commands and propagates to the caller.
- [ ] `fnd_sig-feat-library-1c4859137b-fa52_64bd108fcc` — **Missing terminal events are reported as successful execution** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `A01`
  - **Change:** Raise an explicit incomplete-stream error when a stream ends without a terminal result; success must require an explicit successful terminal event.
  - **Scope:** Change the missing-result branch in stream_cli_command and extend streaming lifecycle coverage.
  - **Verify:** End a stream after partial output without a terminal event and assert the explicit incomplete-stream error; assert explicit successful and failed terminal events preserve their outcomes.
- [ ] `fnd_sig-feat-library-4ddc042c0c-0bf5_63f5fb704b` — **CLI argument boundaries are lost when constructing the shell command** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `A04`
  - **Change:** Build an unquoted argument vector and apply shlex.join once at the shell boundary, removing the existing prompt-only quoting; alternatively pass the vector directly if the runtime supports it.
  - **Scope:** GeminiAgent._build_command, command serialization, and argument-boundary tests.
  - **Verify:** Verify argument round-tripping for prompts, binary paths, model values, and extra arguments containing spaces, quotes, dollar signs, and shell metacharacters.
- [ ] `fnd_sig-feat-library-4ddc042c0c-6a73_622566967a` — **Host authentication variables override explicit invocation overrides** (medium; api-contract; current triage: contract-mismatch; status: open)
  - **Batch:** `A04`
  - **Change:** Resolve authentication inputs in this order: explicit per-invocation environment overrides, configured model/provider credentials and base URL, inherited host environment, then provider-library defaults. Apply each lower-precedence source only when the higher-precedence value is absent.
  - **Scope:** Authentication environment merging in GeminiAgent._prepare_runtime_execution and precedence tests.
  - **Verify:** Set distinct synthetic values at all four precedence levels and assert explicit invocation wins, then remove each level in turn and assert fallback to configured provider, host environment, and library default without exposing values in logs.
- [ ] `fnd_sig-feat-library-55341e0286-8fdd_5daa6af408` — **Trajectory metadata reports the first accumulated usage instead of the final totals** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `A05`
  - **Change:** Extract metadata from the last applicable metrics entry, consistently with the agent's usage extraction.
  - **Scope:** OpenHandsParser._parse_trajectory_json metadata extraction.
  - **Verify:** Cover trajectories with increasing cumulative metrics and intervening entries without metrics; assert that parsed totals match the final metrics.
- [ ] `fnd_sig-feat-library-55341e0286-d405_56d39d0cc7` — **Timed-out runs lose usage already recorded in the trajectory** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `A05`
  - **Change:** Account for available trajectory usage before raising the timeout error, while preserving the timeout failure.
  - **Scope:** OpenHandsAgent.run termination and usage-accounting order.
  - **Verify:** Cover successful and timed-out invocations with recorded usage, asserting identical extraction of available totals and continued error propagation for timeouts.
- [ ] `fnd_sig-feat-library-55341e0286-dcbb_47b9134faf` — **JSONL detection accepts action events that parsing silently discards** (medium; api-contract; current triage: contract-mismatch; status: open)
  - **Batch:** `A05`
  - **Change:** Make detection and processing share an explicit event contract, including processing supported action events when is_step is absent.
  - **Scope:** OpenHandsParser JSONL detection and event processing.
  - **Verify:** Exercise supported action events with and without is_step and verify that accepted actionable events produce their corresponding trajectory steps.
- [ ] `fnd_sig-feat-library-56a50662dd-99ad_6114817cb1` — **Configured max_turns is discarded during agent construction** (medium; api-contract; current triage: contract-mismatch; status: open)
  - **Batch:** `A06`
  - **Change:** Carry max_turns through agent construction and apply it to the CLI invocation.
  - **Scope:** ClaudeCodeConfig-to-ClaudeCodeAgent propagation and CLI argument construction.
  - **Verify:** Exercise configuration-to-command propagation for several turn limits and the unset case, asserting that the resulting invocation preserves the configured bound.
- [ ] `fnd_sig-feat-library-56a50662dd-b2db_2490cfc8c6` — **Command sequence conversion loses argument boundaries** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `A06`
  - **Change:** Define sequence inputs as raw argv and use shlex.join when converting them to a shell command, or preserve argv through the runtime API. Check callers for prequoted arguments before changing conversion.
  - **Scope:** ClaudeCodeAgent._run sequence conversion and its callers' quoting contract.
  - **Verify:** Verify that sequence arguments containing spaces, quotes, empty strings, and shell metacharacters reach execution unchanged as individual arguments.
- [ ] `fnd_sig-feat-library-7d011dda6b-05dd_cc8bed441b` — **Malformed step_type values crash format detection** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `A07`
  - **Change:** Check that step_type is a string before testing membership in _step_types.
  - **Scope:** MinisweParser.can_parse discriminator validation and the relevant parser detection tests.
  - **Verify:** Exercise format detection with each JSON value type for step_type, including arrays, objects, null, numbers, and strings. Assert that unsupported types return False without raising and supported strings remain recognized.
- [ ] `fnd_sig-feat-library-94a87ca9bc-6910_5db5eb1991` — **Saving a trace once permanently excludes later appended events** (medium; data-loss; current triage: confirmed-bug; status: open)
  - **Batch:** `A08`
  - **Change:** Track trace changes or read offsets rather than treating saved paths as immutable. Keep usage discovery independent of artifact export bookkeeping.
  - **Scope:** CodexAgent trace discovery, export bookkeeping, and lifecycle coverage.
  - **Verify:** Exercise save, append, and save sequences for an existing trace, verifying updated events are exported and usage remains identical with and without intermediate artifact saves.
- [ ] `fnd_sig-feat-library-94a87ca9bc-dda0_1616fa3236` — **Command unwrapping removes quotes belonging to the command** (medium; data-loss; current triage: confirmed-bug; status: open)
  - **Batch:** `A08`
  - **Change:** Parse the wrapper using shell-aware tokenization and extract the command argument without stripping characters from its contents.
  - **Scope:** CodexParser._unwrap_bash_command and shell-wrapper parsing coverage.
  - **Verify:** Cover wrapped commands containing nested quotes, escaped quotes, multiline text, and trailing quoted arguments, asserting the inner command is preserved exactly.
- [ ] `fnd_sig-feat-library-94a87ca9bc-f8de_907ae763b2` — **Shell command construction does not preserve configured arguments** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `A08`
  - **Change:** Build raw argument values and shell-quote every element once at the execution boundary using shlex.join, or pass an argv list directly if the runtime supports it.
  - **Scope:** CodexAgent command construction and execution-boundary tests.
  - **Verify:** Verify round-trip argument preservation for spaces, embedded quotes, dollar signs, and shell metacharacters across prompts, binary paths, and extra_args.
- [ ] `fnd_sig-feat-library-b1599e62e1-2dde_bfcf334af4` — **Docker template rendering omits the required version** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `A01`
  - **Change:** Include version=self.version in the Docker template context and reject undefined template variables instead of silently rendering them empty.
  - **Scope:** AgentConfigBase.get_docker_file and template-rendering coverage.
  - **Verify:** Extend configuration coverage to verify that validated template inputs reach rendered Docker instructions and that undeclared variables fail clearly.
- [ ] `fnd_sig-feat-library-b1599e62e1-e1d2_cd2f0e9c1f` — **Resume validation regenerates prompts without agent and model context** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `A01`
  - **Change:** Share prompt context construction between execution and resume, and pass the same agent and model metadata through the resume validation API.
  - **Scope:** Resume prompt-generation parameters and shared context construction with get_task_for_checkpoint.
  - **Verify:** Round-trip execution-generated prompts through resume validation for all supported context fields and continuation states; unchanged inputs must remain valid, while changed rendered inputs must invalidate dependent checkpoints.
- [ ] `fnd_sig-feat-library-b487360049-8bbe_aaf48788fa` — **Agent-specific thinking settings bypass the mutually exclusive configuration contract** (medium; api-contract; current triage: contract-mismatch; status: open)
  - **Batch:** `Q01`
  - **Change:** Validate the recognized thinking fields in each agent override using the same type and mutual-exclusion rules as the top-level configuration.
  - **Scope:** Extend ModelDefinition thinking validation and TestModelDefinitionThinking.
  - **Verify:** Expand thinking configuration validation scenarios across top-level and agent-specific settings, checking conflicting pairs and invalid presets while preserving valid override precedence.
- [ ] `fnd_sig-feat-library-c2210a2f89-14e9_9202a9c43f` — **Tool calls are duplicated when execution starts** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `A10`
  - **Change:** Reuse the pending step when tool_execution_start references an already recorded call ID. Create a new step only when no corresponding call exists.
  - **Scope:** PiParser._process_tool_start and the relevant trajectory lifecycle tests.
  - **Verify:** Cover complete tool lifecycles both with and without preceding assistant toolCall blocks, including multiple interleaved call IDs; assert one step per invocation with the correct arguments and final result.
- [ ] `fnd_sig-feat-library-c2210a2f89-73c7_c47ca0fee9` — **Non-object JSON records escape parser error handling** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `A10`
  - **Change:** Validate decoded records as objects before accessing event fields. Have detection reject unsupported records, streaming parsing handle them consistently with invalid input, and trajectory parsing raise ParseError with the line number.
  - **Scope:** The JSON decoding boundaries in PiAgent.parse_line, PiParser.can_parse, and PiParser.parse.
  - **Verify:** Exercise object, array, string, number, boolean, and null records across the parser entry points, asserting their intended rejection behavior and contextual errors.

### WS4 — Evaluation and scoring provenance (14 findings)

- [ ] `fnd_sig-feat-library-14b4e49324-0da9_4e321d7e46` — **Directory enumeration failures silently produce a valid partial inventory** (high; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `V02`
  - **Change:** Convert any root or nested enumeration failure into structured `score_evidence_invalid` output. Never publish a partial inventory as valid and do not leak a raw filesystem exception from score finalization.
  - **Scope:** src/slop_code/metrics/scoring/inventory.py traversal error propagation and focused inventory tests.
  - **Verify:** Inject enumeration failure at the root and in a nested directory; assert structured `score_evidence_invalid`, no valid partial inventory, and no uncaught filesystem exception.
- [ ] `fnd_sig-feat-library-6150408686-8789_4fb4b29fad` — **Collection silently drops parameterized test IDs containing spaces** (high; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `V01`
  - **Change:** Collect structured node IDs or parse collection output without rejecting whitespace inside valid node IDs.
  - **Scope:** Collection output parsing and collection inventory tests.
  - **Verify:** Extend collection scenarios with parameterized IDs containing whitespace and punctuation, and verify exact inventory membership, hashes, and missing-result backfilling.
- [ ] `fnd_sig-feat-library-7850d202f5-d452_74bbabb116` — **Require complete artifact verification before producing score evidence** (high; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `V02`
  - **Change:** Centralize required-artifact completeness and digest validation in the shared verifier, and invoke it for both historical regression endpoints before measurement.
  - **Scope:** Shared artifact validation in live_evidence.py and historical target validation in live_regression.py.
  - **Verify:** Exercise live and historical provenance with complete, omitted, missing, and modified required artifacts. Assert that only complete matching inputs can reach evidence production or evaluator execution.
- [ ] `fnd_sig-feat-library-afaa9cef67-108b_f86b866ee1` — **Clone detection retains cubic-size statement vectors** (high; performance; current triage: risk; status: open)
  - **Batch:** `V02`
  - **Change:** Replace retained AST-dump tuples with a constant-width repeated-sequence index and materialize clone vectors only for repeated candidates. Enforce a 300-second production measurement deadline, configurable only within 1–3600 seconds. On timeout, terminate and reap the worker and return structured unavailable evidence.
  - **Scope:** Clone candidate construction in _verified_payload and measurement process lifecycle in _execute.
  - **Verify:** For 128/256 distinct-statement fixtures, assert constant-width index records and at most 5× record growth while preserving output. Assert production defaults to 300 seconds, accepts only 1–3600 seconds, and rejects public 10 ms configuration. Through a non-public injected test deadline of 10 ms, make a worker sleep and assert structured unavailable evidence plus termination/reaping.
- [ ] `fnd_sig-feat-library-bbf603cd2d-de09_4c0c4271d8` — **Failed reevaluations can leave a stale passing run summary** (high; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `V04`
  - **Change:** Finalize every requested problem, including those with no successful results, using its expected checkpoints. Persist a non-passing status and clear stale pass-rate data when no current evaluation results exist.
  - **Scope:** evaluate finalization and maybe_update_problem_report handling of empty current results.
  - **Verify:** Cover complete, partially failed, entirely failed, and missing-snapshot reevaluations of previously passing problems; assert persisted summaries reflect only the current evaluation and account for every expected checkpoint.
- [ ] `fnd_sig-feat-library-14b4e49324-4ad3_3aa2b4b9b6` — **Malformed production-quality sidecars escape aggregate validation** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `V02`
  - **Change:** Validate the decoded production-quality shape and schema ID before collecting it, and convert malformed artifact failures into canonical_artifact_invalid.
  - **Scope:** src/slop_code/metrics/scoring/finalization.py artifact parsing and focused finalization validation tests.
  - **Verify:** Cover malformed JSON shapes, missing required fields, and invalid schema-ID types across producer fragments; assert an ineligible result rather than an uncaught exception.
- [ ] `fnd_sig-feat-library-6150408686-53ac_5a207b6383` — **Inventory reconciliation changes the documented skipped-test counting contract** (medium; api-contract; current triage: contract-mismatch; status: open)
  - **Batch:** `V01`
  - **Change:** Exclude skipped tests from every numerator and denominator, including category totals and aggregate all-cases totals. A checkpoint is strictly solved only when every executed, non-skipped collected case passes and collection/provenance is complete.
  - **Scope:** Inventory aggregate recomputation and report/collection integration coverage.
  - **Verify:** Collect passed, failed, and skipped cases across categories; assert skipped cases appear in detail but contribute to no numerator or denominator, and strict solved status depends only on complete executed non-skipped cases plus valid provenance.
- [ ] `fnd_sig-feat-library-6150408686-91b9_4b671e2183` — **Collection overwrites configured custom-marker classifications** (medium; api-contract; current triage: contract-mismatch; status: open)
  - **Batch:** `V01`
  - **Change:** Use one classification rule for collection and execution, including custom-marker mappings and the existing precedence rules.
  - **Scope:** Collection marker discovery/classification, shared classification logic, and associated tests.
  - **Verify:** Exercise custom markers mapped to each group through collection and reconciliation, including combinations with built-in markers and prior-checkpoint tests.
- [ ] `fnd_sig-feat-library-7850d202f5-6ed3_e90ed9b748` — **Missing live oracles escape provenance error handling** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `V02`
  - **Change:** Raise canonical_provenance_unavailable as ValueError for zero live oracles and canonical_artifact_invalid for multiple live oracles, matching the callers' existing handling.
  - **Scope:** _committed_artifacts oracle-cardinality handling.
  - **Verify:** Parameterize oracle cardinality across zero, one, and multiple files for both producers; assert structured provenance ineligibility for invalid cardinalities and no measurement execution.
- [ ] `fnd_sig-feat-library-afaa9cef67-91ad_e18749d1a7` — **Each strongly connected component rescans every graph edge** (medium; performance; current triage: risk; status: open)
  - **Batch:** `V02`
  - **Change:** Build component-local adjacency once and traverse each node and edge a bounded number of times instead of rescanning all graph edges for each strongly connected component.
  - **Scope:** Component mass aggregation in produce_production_graph.
  - **Verify:** Instrument edge iteration on deterministic sparse graphs of 128 and 256 nodes; assert no more than `2E + V` edge/node visits and identical strongly connected components. This distinguishes the existing per-component edge rescans without wall-clock thresholds.
- [ ] `fnd_sig-feat-library-afaa9cef67-bdf8_ac14f9dbca` — **Parser launch errors bypass independent graph evidence production** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `V02`
  - **Change:** Translate parser process launch OSError into ProductionQualityError with the measurement_environment_mismatch code, matching the Ruff launch handling.
  - **Scope:** Exception translation around the process executor call in _verified_payload.
  - **Verify:** Cover evaluator launch failures across missing and non-executable paths, asserting an environment-mismatch eligibility reason and continued graph evidence production.
- [ ] `fnd_sig-feat-library-bbf603cd2d-7ed8_9e38cfe373` — **A checkpoint metrics error aborts the entire problem report** (medium; api-contract; current triage: contract-mismatch; status: open)
  - **Batch:** `V04`
  - **Change:** Catch MetricsError per checkpoint, append the checkpoint-specific error, and continue collecting reports. Explicitly preserve the intended prior-checkpoint comparison semantics across failures.
  - **Scope:** The checkpoint loop in create_problem_reports.
  - **Verify:** Exercise a sequence containing successful, missing, and metrics-failing checkpoints; verify all usable reports and checkpoint-specific errors are returned and comparison inputs remain correct.
- [ ] `fnd_sig-feat-library-bbf603cd2d-a176_911fa3d552` — **Valid YAML with an invalid structure crashes run-summary loading** (medium; api-contract; current triage: contract-mismatch; status: open)
  - **Batch:** `V04`
  - **Change:** Validate the root and nested summary structures before accessing them, log invalid metadata, and return None according to the documented contract.
  - **Scope:** Structural validation in get_run_summary.
  - **Verify:** Parameterize missing, syntactically invalid, structurally invalid, and valid run metadata, asserting invalid inputs return None and valid mappings retain their summary fields.
- [ ] `fnd_sig-feat-library-14b4e49324-5148_8fa9b3da96` — **InterpreterEvidence is advertised but missing from package exports** (low; api-contract; current triage: contract-mismatch; status: open)
  - **Batch:** `V02`
  - **Change:** Import InterpreterEvidence from .models alongside the other public evidence models.
  - **Scope:** src/slop_code/metrics/scoring/__init__.py and a package export contract test.
  - **Verify:** Verify that every name in scoring.__all__ resolves to a package attribute.

### WS5 — Metrics and rubric processing (16 findings)

- [ ] `fnd_sig-feat-library-566aaab053-dc34_b159acc174` — **Checker execution failures are reported as clean metrics** (high; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `M01`
  - **Change:** Return explicit unavailable metric evidence for checker launch, configuration, malformed-output, and operational exit failures. Preserve diagnostics only for checker-defined finding exit codes; never translate an operational failure into zero findings.
  - **Scope:** Execution-result handling in lint_metrics.py and type_check.py.
  - **Verify:** Cover clean success, checker-defined findings, launch failure, operational exit, and malformed output for both checkers; assert only the first two produce measured counts and every operational path produces explicit unavailable evidence.
- [ ] `fnd_sig-feat-library-e7dd745c57-16d8_09bda8887a` — **Reprocessing leaves obsolete carried grades on disk when none remain eligible** (high; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `M03`
  - **Change:** Persist the recomputed merged result whenever it differs from the current file, including when no grades are carried.
  - **Scope:** process_problem_carry_forward persistence and checkpoint-processing tests.
  - **Verify:** Test repeated processing as eligibility changes from nonempty to empty, checking disk contents, returned totals, and downstream checkpoint propagation.
- [ ] `fnd_sig-feat-library-e7dd745c57-ede2_721f61c058` — **Router defaults override working OpenRouter configuration with empty strings** (high; api-contract; current triage: contract-mismatch; status: open)
  - **Batch:** `M03`
  - **Change:** Forward only explicitly supplied router overrides. When an override is absent, leave it unset so the selected provider defaults and existing OpenRouter configuration remain authoritative.
  - **Scope:** src/slop_code/metrics/rubric/router.py and routing coverage.
  - **Verify:** Exercise omitted overrides and explicit overrides; assert omitted values preserve configured OpenRouter defaults and supplied values take precedence.
- [ ] `fnd_sig-feat-library-42cc4cda50-7b67_cd703bd06c` — **Unavailable measurements become false percentage changes** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `M02`
  - **Change:** Represent an unavailable percentage delta as `null` in the existing output field, preserving schema shape while distinguishing unavailable evidence from a measured zero.
  - **Scope:** Guard unavailable values in compute_checkpoint_delta and add coverage distinguishing missing measurements from numeric zero.
  - **Verify:** Assert missing baselines serialize the delta field as `null`, measured zero remains numeric zero, and downstream readers preserve the distinction.
- [ ] `fnd_sig-feat-library-42cc4cda50-e3e7_19d4cb341d` — **Deleted files are omitted from checkpoint churn** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `M02`
  - **Change:** Include deleted-file diff entries when aggregating churn. If churn is restricted to measured source files, determine eligibility using both previous and current snapshot paths.
  - **Scope:** Update _compute_distributions and its checkpoint diff aggregation coverage; supply previous snapshot eligibility if filtering requires it.
  - **Verify:** Extend checkpoint churn coverage across additions, modifications, deletions, and mixed changes, asserting that eligible removed paths contribute their full line counts.
- [ ] `fnd_sig-feat-library-566aaab053-8e6a_1b43651504` — **Module variables referenced by functions are marked unused** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `M01`
  - **Change:** Resolve references across lexical scopes: count references to module bindings inside functions and classes while excluding locally shadowed names. Share this accounting between unused and single-use detection.
  - **Scope:** Module binding and reference accounting in waste.py.
  - **Verify:** Cover globals referenced from functions and methods, multiple references, local shadowing, and truly unused module bindings.
- [ ] `fnd_sig-feat-library-566aaab053-90e3_c75e820e17` — **Dotted imports skip executed parent package initializers** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `M01`
  - **Change:** Include existing package initializers along each resolved module path and trace their imports, while allowing namespace-package directories without initializers.
  - **Scope:** Module resolution and dependency collection in imports.py.
  - **Verify:** Cover nested regular packages, namespace packages, and dependencies imported exclusively by parent initializers.
- [ ] `fnd_sig-feat-library-566aaab053-a7e5_9ac31467e7` — **self calls can resolve to another class in the same file** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `M01`
  - **Change:** Resolve self calls against the caller's class first and then its supported inheritance hierarchy; do not select unrelated same-file methods.
  - **Scope:** The self-qualified branch of _resolve_call in graph.py.
  - **Verify:** Test same-named methods across classes and reorder candidate lists; resolution must remain tied to the caller's class.
- [ ] `fnd_sig-feat-library-566aaab053-f079_361c246197` — **Comma-separated imports lose every module after the first** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `M01`
  - **Change:** Return and collect one ImportInfo per imported module, including aliased modules.
  - **Scope:** _parse_import_statement and its collection logic in imports.py.
  - **Verify:** Assert equivalent tracing for separate import statements and comma-separated imports, including aliases and transitive dependencies.
- [ ] `fnd_sig-feat-library-958b9d2532-10ff_b345d0ed33` — **Missing isolated pass rates erase valid strict solve results** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `M02`
  - **Change:** Compute strict, isolated, and core solve results independently so an absent secondary metric cannot erase available strict results.
  - **Scope:** Adjust the early-return logic in compute_solve_rates and cover the resulting compute_run_summary defaults.
  - **Verify:** Exercise combinations of present and absent strict, isolated, and core metrics, asserting that each available metric retains its counts and percentages regardless of the other families.
- [ ] `fnd_sig-feat-library-958b9d2532-5df8_f6f4fc4884` — **Problems without a test category depress that category's average** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `M02`
  - **Change:** Preserve the absence of an applicable problem-level rate until the final aggregation, exclude those problems, and apply the empty-result default only after filtering.
  - **Scope:** Update the problem-level collection and averaging in compute_pass_rates_stats.
  - **Verify:** Verify across test categories that adding problems with no applicable tests leaves the existing problem-level average unchanged, while actual zero-pass results remain included. Also cover the case where every problem lacks the category.
- [ ] `fnd_sig-feat-library-a5ee93839a-a36d_0567ee32b8` — **Replacing a language leaves stale extension mappings** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `M02`
  - **Change:** When replacing a language, remove extension mappings owned by its prior specification, then install the replacement mappings.
  - **Scope:** Update register_language and add behavioral coverage for language registry consistency.
  - **Verify:** Replace a registered language and assert its old extension mappings disappear, new mappings resolve, and unrelated registrations remain unchanged.
- [ ] `fnd_sig-feat-library-e7dd745c57-2c72_f613e51241` — **Single-file JSON responses silently lose all grades** (medium; api-contract; current triage: contract-mismatch; status: open)
  - **Batch:** `M03`
  - **Change:** Implement the documented single-file JSON path when file markers are absent and a file_name is supplied, preserving existing multi-file behavior.
  - **Scope:** Both _extract_grades implementations and their associated tests.
  - **Verify:** Cover both providers with nonempty plain and fenced single-file JSON, valid empty arrays, and multi-file responses; assert grade preservation and filename annotation.
- [ ] `fnd_sig-feat-library-e7dd745c57-7ea2_5ae4e3a98b` — **Zero-context insertions mishandle the unchanged line preceding the insertion** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `M03`
  - **Change:** Handle zero-length old ranges as insertion boundaries after old_start, and distinguish insertions inside a span from insertions immediately outside its endpoints.
  - **Scope:** compute_line_offset, is_span_unchanged, and their existing behavioral test classes.
  - **Verify:** Extend offset and span scenarios with zero-context insertions before, inside, and after spans, including start-of-file and end-of-file insertions.
- [ ] `fnd_sig-feat-library-f8183a2b15-8444_b75a50cc71` — **Extensionless entrypoints leave every file marked as the wrong language** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `M02`
  - **Change:** Resolve the actual entry file before determining its language and measuring files, then use its language extensions consistently.
  - **Scope:** Entry resolution in src/slop_code/metrics/driver.py and existing snapshot measurement tests.
  - **Verify:** Extend snapshot measurement scenarios to compare explicit and extensionless entrypoints in a mixed-language snapshot, asserting identical language flags in returned metrics and saved rows.
- [ ] `fnd_sig-feat-library-f8183a2b15-f0c8_d7509277bf` — **Synchronous grading fails when called inside a running event loop** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `M02`
  - **Change:** When an event loop is active, run the existing synchronous grading bridge in a worker thread with its own event loop; preserve the current synchronous public API.
  - **Scope:** src/slop_code/metrics/grade.py async bridge and snapshot-grading API tests.
  - **Verify:** Call the synchronous grading API both without and inside an active event loop; assert identical results and exception propagation without nesting an event loop.

### WS6 — Dashboard and visualization (15 findings)

- [ ] `fnd_sig-feat-library-cbe7be3794-1629_db13e4cb65` — **Run configuration loading permits arbitrary code execution** (high; security; current triage: confirmed-bug; status: open)
  - **Batch:** `D01`
  - **Change:** Replace unsafe YAML object loading with safe loading, then validate the decoded run-configuration structure before use. Reject unsupported tags and shapes without executing constructors.
  - **Scope:** load_config_metadata and configuration-loading behavioral coverage.
  - **Verify:** Exercise real configuration loading with ordinary configuration mappings and Python object tags; assert ordinary metadata loads and executable tags are rejected without invoking constructors.
- [ ] `fnd_sig-feat-library-cbe7be3794-27d7_739e2904b5` — **Checkpoint classification treats missing evidence and isolated passes as solved** (high; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `D01`
  - **Change:** Make verified strict all-cases success authoritative and classify missing or incomplete pass evidence as unsolved; do not allow isolated results to override strict failure.
  - **Scope:** process_checkpoint_row and its existing behavioral test coverage.
  - **Verify:** Expand checkpoint-classification coverage into a matrix of strict success, strict failure, isolated-only success, missing evidence, and zero-test rows, preserving the existing strict-success scenario.
- [ ] `fnd_sig-feat-library-1cc90d9a69-5744_c8e7386dc9` — **Version selection sorts version strings lexicographically** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `D04`
  - **Change:** Sort using parsed version values while retaining the original version strings in the returned data.
  - **Scope:** Version ordering in select_best_version_per_model.
  - **Verify:** Cover version ordering across patch, minor, and major component boundaries, plus the explicit Opus version selection rule.
- [ ] `fnd_sig-feat-library-1cc90d9a69-8fa2_2b0f15675f` — **Configurable progress bins are clipped by a fixed axis range** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `D04`
  - **Change:** Derive the lower axis bound from the configured bins or show the complete 0–100% progress interval with suitable padding.
  - **Scope:** ProgressLineChartBuilder.build axis configuration.
  - **Verify:** For several supported bin counts, assert that every generated progress point lies within the chart's visible axis range.
- [ ] `fnd_sig-feat-library-1cc90d9a69-cc34_b6ddbcbd26` — **Checkpoint directory names can inject HTML into the diff component** (medium; security; current triage: confirmed-bug; status: open)
  - **Batch:** `D04`
  - **Change:** HTML-escape both header labels before interpolation. Also escape raw source text in the syntax-highlighting exception path so every plain-text insertion remains safe.
  - **Scope:** Text escaping in generate_modern_diff and get_highlighted_line.
  - **Verify:** Exercise diff generation with HTML metacharacters and event-handler payloads in both labels, and with a highlighting failure; assert that untrusted text is escaped while intended highlighting markup remains intact.
- [ ] `fnd_sig-feat-library-55712dbf64-4159_8cdc227be0` — **Missing rubric columns produce misaligned new-flag values** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `D02`
  - **Change:** Construct fallback Series with index=run_df.index, or use scalar zero defaults where appropriate.
  - **Scope:** Rubric fallback Series in comparison.py.
  - **Verify:** Test missing combinations of rubric columns using noncontiguous indices and verify new-flag values remain aligned with their checkpoints.
- [ ] `fnd_sig-feat-library-55712dbf64-4892_7f1f916194` — **Grouped runs generate duplicate traces when run dates differ** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `D02`
  - **Change:** Sort the metadata and then deduplicate by the actual trace identity, display_name, before rendering grouped data.
  - **Scope:** Trace iteration in comparison.py, boxplot.py, and test_pass.py.
  - **Verify:** Exercise grouped repetitions with varying dates and assert one trace per display name per metric, with statistics calculated from every repetition exactly once.
- [ ] `fnd_sig-feat-library-55712dbf64-baed_a67c12c570` — **Logarithmic quality charts hide valid zero-defect results** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `D02`
  - **Change:** Use a zero-capable axis representation for quality metrics and keep annotation coordinates consistent with that representation.
  - **Scope:** Quality scatter axis configuration and associated annotation handling.
  - **Verify:** Cover zero and positive quality metrics together, verifying that all valid runs have representable marker and annotation coordinates in both single and multi-chart rendering.
- [ ] `fnd_sig-feat-library-679419b772-2e49_0b126d99c0` — **Checkpoints with no category tests lower the evolution pass rate** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `D03`
  - **Change:** Treat zero-total category rates as unavailable and exclude them from bin means. Preserve an unavailable state for bins with no evaluated tests.
  - **Scope:** Per-row rate calculation and bin aggregation in update_tests, with focused behavioral coverage.
  - **Verify:** Cover progress bins containing evaluated suites, empty suites, and mixtures. Adding a checkpoint with no category tests must not change that category's measured pass rate.
- [ ] `fnd_sig-feat-library-679419b772-ed06_ac003a360b` — **Missing complexity metrics are displayed as measured zeros** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `D03`
  - **Change:** Pass the original metric columns to build_histogram, or preserve missing values and explicitly display unavailable data. Do not synthesize zero measurements.
  - **Scope:** Metric preparation in update_quality and focused quality-rendering coverage.
  - **Verify:** Exercise quality rendering with present, partially missing, and absent metric data. Assert that only actual measurements contribute to histogram counts and absent metrics produce an empty or unavailable state.
- [ ] `fnd_sig-feat-library-b19129a899-7f89_e16bbb7bee` — **Problem selector ignores the common-problems filter** (medium; bug; current triage: risk; status: open)
  - **Batch:** `D03`
  - **Change:** Make the options callback depend on filter-settings-store and apply the same problem filtering as the chart. Clear or reconcile the selected value when it is excluded.
  - **Scope:** src/slop_code/dashboard/pages/problem_comparison.py and behavioral coverage for its selector/filter interaction
  - **Verify:** Exercise selector and chart callbacks across changes to selected runs and common_problems_only, asserting that selectable problems match the filtered context and that excluded selections are reconciled.
- [ ] `fnd_sig-feat-library-cbe7be3794-97e7_2b3d1361e5` — **Bulk selection switches do not target the groups rendered by the UI** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `D01`
  - **Change:** Parse the JSON component ID once, dispatch on exact type equality, and match groups using the same model_name and prompt_template keys as the UI builder.
  - **Scope:** Bulk-switch dispatch and group matching in _manage_run_selection_logic.
  - **Verify:** Cover model and prompt bulk selection and deselection across multiple models and prompts, using directory names different from model names and asserting unrelated selections remain unchanged.
- [ ] `fnd_sig-feat-library-cbe7be3794-9b4a_3a09d10800` — **Bulk selection overwrites the grouping preference with a list** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `D01`
  - **Change:** Keep the appearance boolean separate from the collection of matching runs and always persist group_runs as a boolean.
  - **Scope:** Local variable naming and saved-settings invariants in _manage_run_selection_logic.
  - **Verify:** For each bulk-selection action, assert both enabled and disabled grouping preferences remain unchanged and boolean, regardless of how many runs match.
- [ ] `fnd_sig-feat-library-d62faeefcf-1913_5bf9f18c3d` — **Missing optional lint data breaks both quality charts** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `D03`
  - **Change:** Check metric availability before selecting columns and return an unavailable or empty figure for missing lint data while rendering the complexity comparison.
  - **Scope:** Metric availability handling in head_to_head_quality.py.
  - **Verify:** Exercise the quality callback with optional metrics present and absent, asserting that unavailable metrics do not prevent available comparisons from rendering.
- [ ] `fnd_sig-feat-library-d62faeefcf-eb08_7acc2861e8` — **Averaging checkpoint states within bins loses cumulative totals** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `D03`
  - **Change:** Sort checkpoints chronologically and retain the last state within each problem/bin before forward filling and averaging across problems. Aggregate rate metrics separately, and preserve actual terminal totals when smoothing cumulative curves.
  - **Scope:** State aggregation in the efficiency and evolution trend builders, including cumulative endpoint handling.
  - **Verify:** Cover multiple checkpoints per bin, shuffled input ordering and different problem lengths; assert that binned states follow the latest checkpoint and terminal cumulative values equal the sum of incurred costs.

### WS7 — Commands, configuration, and maintenance scripts (17 findings)

- [ ] `fnd_sig-feat-library-63b4d53547-40ad_f7dc997921` — **Compression deletes the recovery archive when source removal partially fails** (high; data-loss; current triage: confirmed-bug; status: open)
  - **Batch:** `Q03`
  - **Change:** Separate archive creation cleanup from source deletion handling. Once the archive is complete, retain it if deleting the source fails and report the remaining cleanup work.
  - **Scope:** The exception boundaries and archive cleanup in _compress_agent_dir.
  - **Verify:** Exercise failures during archive creation and during partial source removal; assert that every original file remains recoverable from either the source or the completed archive.
- [ ] `fnd_sig-feat-library-63b4d53547-4975_e839150f01` — **An unchecked problem name can redirect inference overwrite outside the output directory** (high; data-loss; current triage: confirmed-bug; status: open)
  - **Batch:** `Q03`
  - **Change:** Validate the problem against the catalog before modifying output, reject names containing path components, and enforce that the resolved destination lies beneath the resolved output directory.
  - **Scope:** Problem resolution and save_dir validation before the destructive overwrite branch.
  - **Verify:** Parameterize absolute paths, parent traversal, and symlink escapes; assert rejection before any output mutation. Also verify that a valid catalog name can overwrite only its intended output directory.
- [ ] `fnd_sig-feat-library-7307b3db19-edbd_69249a688f` — **Rendering multiple problems overwrites earlier prompts** (high; data-loss; current triage: confirmed-bug; status: open)
  - **Batch:** `Q04`
  - **Change:** Place each problem's rendered files in a distinct problem-named subdirectory.
  - **Scope:** Correct the per-problem output directory in render_prompts.py and cover multi-problem rendering.
  - **Verify:** Render multiple problems with distinct content and unequal checkpoint counts; assert every prompt exists under its own problem directory and no content is overwritten or mixed.
- [ ] `fnd_sig-feat-library-2852349fd3-46ac_15429c4f95` — **Exact mass thresholds count one extra symbol** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `Q05`
  - **Change:** Use the first cumulative sum greater than or equal to the threshold, with side="left".
  - **Scope:** compute_distribution and its behavioral tests.
  - **Verify:** Cover exact and in-between thresholds, repeated masses, trailing zero masses, and empty inputs; assert the returned prefix reaches the target and no shorter prefix does.
- [ ] `fnd_sig-feat-library-2852349fd3-6886_40c9fc0cc8` — **Unknown command exit codes are classified as failures** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `Q05`
  - **Change:** Centralize failure detection and require a known nonzero exit code or positive error evidence. Preserve unknown outcomes separately.
  - **Scope:** Failure predicates in detect_bug_fix_cycles and behavioral coverage for unknown outcomes.
  - **Verify:** Cover zero, nonzero, and unknown exit codes with and without error evidence across run counts, fix cycles, and subsequent-edit metrics.
- [ ] `fnd_sig-feat-library-2852349fd3-9eb2_4402ee7b29` — **Interrupted solution copies are permanently skipped on retry** (medium; data-loss; current triage: confirmed-bug; status: open)
  - **Batch:** `Q05`
  - **Change:** On retry, hash or byte-compare an existing destination with the source. Skip only an exact match; otherwise copy to a sibling temporary file, validate it, and atomically replace the incomplete destination.
  - **Scope:** Solution-copy publication and existing-destination validation in migrate_problem.
  - **Verify:** Retry with an exact destination and assert no rewrite; retry with a truncated or mismatched destination and assert atomic replacement with source-identical bytes and no leftover temporary file.
- [ ] `fnd_sig-feat-library-2852349fd3-d010_6bfa82740e` — **Non-unique symbol keys multiply mass during matching** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `Q05`
  - **Change:** Use a scope-aware identity and enforce one-to-one matching. Resolve ambiguous groups explicitly instead of allowing a Cartesian merge.
  - **Scope:** symbol_key, match_symbols, and matching invariant tests.
  - **Verify:** Exercise repeated names in distinct scopes and ambiguous identities; assert each input symbol participates at most once and reported total mass equals direct calculation from each checkpoint.
- [ ] `fnd_sig-feat-library-487db2da10-fa33_e0a5e10af6` — **Category backfill can destroy existing grades if writing fails** (medium; data-loss; current triage: confirmed-bug; status: open)
  - **Batch:** `Q03`
  - **Change:** Write the complete replacement to a temporary file in the same directory, flush and close it successfully, then atomically replace the original. Clean up the temporary file on failure.
  - **Scope:** Change _save_grades to publish replacements atomically and add behavioral coverage for successful and failed persistence.
  - **Verify:** Test the persistence invariant across failures during writing and before replacement: the original rubric must remain byte-for-byte intact. Also verify that successful replacement produces the complete, parseable grade set.
- [ ] `fnd_sig-feat-library-63b4d53547-740d_9d68609a34` — **Compression and migration return success despite per-file failures** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `Q03`
  - **Change:** After displaying the summary, exit nonzero when any file failed. Keep intentional skips and successful dry runs distinct from failures.
  - **Scope:** Final failure-status handling in both command entrypoints.
  - **Verify:** Test all-success, intentional-skip, mixed-success/failure, and all-failure command runs, asserting a nonzero exit whenever an operation fails.
- [ ] `fnd_sig-feat-library-63b4d53547-9031_f6b012987e` — **Forced consolidation leaves stale CSVs from previous exports** (medium; data-loss; current triage: confirmed-bug; status: open)
  - **Batch:** `Q03`
  - **Change:** Publish a complete replacement export, or explicitly remove command-owned output files that are absent from the new export. Preserve the existing export until collection and validation succeed.
  - **Scope:** Output publication and cleanup of command-owned CSV files in consolidate_runs.
  - **Verify:** Expand the consolidation workflow test to perform successive exports with different optional datasets and verify that every retained output belongs to the latest export.
- [ ] `fnd_sig-feat-library-7307b3db19-56d8_14ab3e3a46` — **Collection metrics command exits successfully after worker failures** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `Q04`
  - **Change:** Continue processing the remaining runs, then raise typer.Exit(1) when run_failures is nonempty.
  - **Scope:** Propagate collection failures through the exit status in static.py and add collection outcome coverage.
  - **Verify:** Cover successful, mixed-success, and all-failed collections, including executor exceptions; verify remaining runs are processed and any failure produces a nonzero exit.
- [ ] `fnd_sig-feat-library-7307b3db19-8f4e_8334cbfbad` — **First/final variance values appear beneath incorrect column headers** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `Q04`
  - **Change:** Render each metric as adjacent first/final columns and construct every row in that same interleaved order.
  - **Scope:** Align column ordering in _render_problem_cv_summary and strengthen its existing test.
  - **Verify:** Use unique first/final values for every metric and assert each row value appears beneath its adjacent, matching header.
- [ ] `fnd_sig-feat-library-a8bc57d38d-87d4_e19adc7a43` — **--problem-name is ignored when resolving a problem directory** (medium; api-contract; current triage: contract-mismatch; status: open)
  - **Batch:** `Q02`
  - **Change:** Use the explicit problem name to resolve the catalog configuration when supplied, and infer from the submission directory only when omitted.
  - **Scope:** Problem resolution in evaluate_problem_dir and focused command coverage.
  - **Verify:** Cover explicit and inferred problem selection, including a submission basename that names a different valid catalog problem, and assert which configuration reaches evaluate_checkpoint.
- [ ] `fnd_sig-feat-library-a8bc57d38d-a566_d7b849dac4` — **--assessment-policy is accepted but has no effect** (medium; api-contract; current triage: contract-mismatch; status: open)
  - **Batch:** `Q02`
  - **Change:** At the evaluation command boundary, accept only explicit `all-cases` and reject every other assessment-policy value before calling evaluation. Update that command’s help and `docs/commands/eval.md`; do not broaden this batch into a repository-wide policy migration. `continue_after_test_failure` remains a separate continuation-only control.
  - **Scope:** The assessment-policy CLI contract in evaluate_agent_run and its command tests.
  - **Verify:** Assert explicit `all-cases` starts strict evaluation; every other value fails before the evaluator, workspace, or output is touched; command help and `docs/commands/eval.md` advertise only `all-cases`; toggling `continue_after_test_failure` changes continuation only.
- [ ] `fnd_sig-feat-library-a8bc57d38d-c91c_c206e737f4` — **Malformed evaluation metadata aborts the entire evaluation run** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `Q02`
  - **Change:** Validate the decoded top-level type and schema-version type before accessing or comparing them. Return false for malformed metadata so normal reevaluation can proceed.
  - **Scope:** _is_evaluation_schema_current and existing schema-helper and selection tests.
  - **Verify:** Expand schema-validation scenarios across non-object JSON, invalid version types, missing fields, and valid metadata; assert invalid artifacts are selected for reevaluation without preventing other problems from being evaluated.
- [ ] `fnd_sig-feat-service-f97fc51238-a0eb_5eca361b9d` — **The loader bypasses raw configuration validation** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `Q01`
  - **Change:** Validate merged top-level keys and thinking configuration before extracting resolved fields, preserving the loader's intentional shorthand and normalization behavior.
  - **Scope:** load_run_config and _get_thinking_values in loader.py, with behavioral coverage in test_loader.py.
  - **Verify:** Extend loader validation scenarios to reject unknown YAML and override keys, invalid thinking input types, and mutually exclusive thinking settings, while accepting supported preset, token-budget, and empty configurations.
- [ ] `fnd_sig-feat-service-f97fc51238-cf30_b6ffd397bf` — **Output-path cleanup rewrites literal user-specified names** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `Q01`
  - **Change:** Restrict missing-version cleanup to the version interpolation and its associated separators; preserve literal template text and unrelated interpolated values.
  - **Scope:** _resolve_save_template in loader.py and output-template scenarios in test_loader.py.
  - **Verify:** Extend custom-template coverage to assert exact preservation of literal path components and distinct destinations, both with and without an agent version, while retaining the default-template missing-version scenario.

### WS8 — Test-suite integrity (29 findings)

- [ ] `fnd_sig-feat-test-suite-091e87b9e7-b_27d6fbe82d` — **Batch-splitting tests do not verify preservation of input files** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `M03`
  - **Change:** Expand both existing scenarios to assert that flattening the batches preserves every input file exactly once, alongside the applicable batch limits.
  - **Scope:** tests/metrics/rubric/driver_test.py::TestBatchFilesBySize
  - **Verify:** Compare the multiset of flattened output paths with the input paths in both split scenarios, and assert each resulting batch respects its configured limit.
- [ ] `fnd_sig-feat-test-suite-091e87b9e7-c_94163531c6` — **Rate-limit test bypasses HTTP response error detection** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `M03`
  - **Change:** Extend the existing retry scenario so post returns the 429 response followed by the successful response, exercising status detection and retry together.
  - **Scope:** tests/metrics/rubric/grade_test.py::test_grade_file_retries_on_rate_limit
  - **Verify:** Return a 429 response followed by a successful grading response, then assert two awaited requests and the expected parsed grades.
- [ ] `fnd_sig-feat-test-suite-11ced79257-3_256ecef6e2` — **Pointer-repair assertions compare the pointer with itself** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `V02`
  - **Change:** Capture the original generation ID before corrupting the pointer and compare the repaired pointer directly against that saved ID.
  - **Scope:** Pointer assertions in the two generation reuse tests.
  - **Verify:** Strengthen both existing reuse scenarios to require the saved generation ID after successful repair or the after_pointer_rename boundary, retaining the stale-pointer expectation before publication.
- [ ] `fnd_sig-feat-test-suite-11ced79257-5_049d695872` — **History-gap scenarios supply expected transition scores as inputs** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `V02`
  - **Change:** Exercise the transition-producing code with the actual produced/missing sequence and compare its resulting components against the golden expectations.
  - **Scope:** The history-gap golden test and its scenario setup.
  - **Verify:** Expand the existing history scenarios to cover edits before and after missing checkpoints, verifying both reset behavior and subsequent repeated-edit tracking.
- [ ] `fnd_sig-feat-test-suite-11ced79257-6_c606653a88` — **Golden benchmark cost cases test a local aggregation implementation** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `V02`
  - **Change:** Build ProblemScoreInput and BenchmarkScoreInput from these golden cases and obtain the actual result through calculate_scores. Keep the fixture values as independent expected outputs.
  - **Scope:** Golden aggregation scenarios in scoring_models_test.py; retain the helper only where constructing ranking inputs is intentional.
  - **Verify:** Route the existing parameterized cost scenarios through production aggregation and assert null propagation, zero contribution from unproduced checkpoints, and the configured checkpoint denominator.
- [ ] `fnd_sig-feat-test-suite-253ca83a3d-9_e96d39be58` — **Exact checkpoint identity test does not cover cross-problem collisions** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `C02`
  - **Change:** Expand the existing scenario with an addition from another problem that shares the selected checkpoint_id, and assert that it is excluded.
  - **Scope:** tests/entrypoints/test_utils_summary.py::test_verified_checkpoint_additions_merge_by_exact_checkpoint_identity
  - **Verify:** Exercise matching and nonmatching combinations of problem_name and checkpoint_id in the existing test, asserting that only additions matching both fields are projected and the source results remain unchanged.
- [ ] `fnd_sig-feat-test-suite-553e2630dd-b_8830adaa68` — **Running-process kill test never verifies termination** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `E01`
  - **Change:** Use an explicit readiness event from a long-running child, retain its process handle, assert it is running, invoke kill(), and assert termination within a bounded deadline before cleanup.
  - **Scope:** TestLocalStreamingRuntimeKill.test_kill_terminates_running_process.
  - **Verify:** Expand this lifecycle scenario to prove readiness and bounded termination, with guaranteed cleanup and explicit stream closure even when assertions fail.
- [ ] `fnd_sig-feat-test-suite-553e2630dd-e_4e82a2d109` — **Workspace reset content assertions check paths against the wrong directory** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `E04`
  - **Change:** Resolve the workspace path once and use it consistently for existence, file-type, and content checks. Assert content unconditionally where the fixture represents files.
  - **Scope:** The three workspace reset scenarios in tests/execution/workspace_test.py.
  - **Verify:** Strengthen the existing reset scenarios to verify every restored file's exact original content, including modified and deleted files, independently of pytest's current directory.
- [ ] `fnd_sig-feat-test-suite-6b63e5f9a4-b_b8e276bd82` — **Failed-checkpoint integration test conflates inference errors with evaluation failures** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `A01`
  - **Change:** Separate inference-error handling from evaluation-failure continuation using a successful agent and explicit continuation settings.
  - **Scope:** tests/agent_runner/test_runner_integration.py failure and continuation scenarios
  - **Verify:** Extend the integration scenarios with successful inference and failed evaluation under ALL_CASES, asserting that the next checkpoint is skipped when continuation is false and executed when continuation is true, while the failed checkpoint remains unsolved.
- [ ] `fnd_sig-feat-test-suite-6b63e5f9a4-d_9cc4434d16` — **Lazy-loading test preloads the catalog before exercising get** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `Q01`
  - **Change:** Keep the catalog unloaded until get is called and route its default loading location to the temporary model directory.
  - **Scope:** tests/agent_runner/llms_test.py::TestModelCatalogYAMLLoading.test_get_triggers_ensure_loaded
  - **Verify:** Revise this scenario to assert the catalog starts unloaded, call get directly, and verify the temporary model is returned and loading occurred.
- [ ] `fnd_sig-feat-test-suite-72bc459f21-1_1902224aee` — **Checkpoint restoration tests do not distinguish core success from all-cases success** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `C01`
  - **Change:** Expand the existing checkpoint restoration scenarios to cover all core tests passing while functionality or regression tests fail. Assert that strict checkpoints_passed remains zero while checkpoints_core_solved remains one.
  - **Scope:** tests/entrypoints/problem_runner/test_driver.py
  - **Verify:** Parameterize the existing restoration coverage across functionality and regression failures with fully passing core tests, checking strict passed counts separately from core-solved counts.
- [ ] `fnd_sig-feat-test-suite-81a5f3fbe0-5_276f4ddd17` — **Tamper-rejection test does not verify that score validation runs** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `D01`
  - **Change:** Use an otherwise loadable checkpoint fixture, assert that the verifier is invoked, and cover successful loading with valid score evidence alongside rejection when verification raises ScoreEvidenceError.
  - **Scope:** tests/dashboard/data_test.py
  - **Verify:** Expand the existing scenario to use the same valid checkpoint input for accepted and rejected score evidence, checking verifier invocation and the corresponding load result.
- [ ] `fnd_sig-feat-test-suite-9ab76ebf59-5_a9305d7693` — **Width-filter test never exercises a rejected interval** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `Q04`
  - **Change:** Expand the existing scenario with eligible metrics whose intervals fall below and above the threshold, and assert the exact retained metrics.
  - **Scope:** tests/entrypoints/commands/test_variance.py::test_collect_ci_entries_filters_by_width
  - **Verify:** Parameterize the existing scenario across below-threshold, above-threshold, and explicitly defined boundary behavior.
- [ ] `fnd_sig-feat-test-suite-9cc78f5be8-c_a495f7d064` — **Package-config resolution tests silently pass when resources are missing** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `Q01`
  - **Change:** Remove conditional guards and require the repository’s bundled YAML and Jinja resources to exist and resolve successfully by bare name.
  - **Scope:** tests/entrypoints/config/test_loader.py: TestResolveConfigPath bare-name tests
  - **Verify:** Assert the bundled configuration and prompt resources exist, then resolve both unconditionally by bare name to their exact package paths.
- [ ] `fnd_sig-feat-test-suite-a6226f638f-1_772338d853` — **Logger level changes leak between tests** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `C05`
  - **Change:** Snapshot and restore the levels of named loggers modified by these tests, and establish the required level explicitly for each capture scenario.
  - **Scope:** tests/logging_test.py fixtures and logger-level setup
  - **Verify:** Verify that logging tests preserve preexisting named-logger levels and that capture scenarios pass independently of preceding logger configuration.
- [ ] `fnd_sig-feat-test-suite-a6226f638f-d_ec388a9235` — **Managed-catalog tests inherit the caller's problem-path override** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `C03`
  - **Change:** Add an autouse fixture that removes SCBENCH_PROBLEMS_PATH with monkeypatch before each catalog test; allow override-specific tests to set their own temporary value.
  - **Scope:** tests/problem_catalog_test.py environment isolation
  - **Verify:** Run the catalog module with an externally configured valid override and verify that managed scenarios remain isolated while explicit override scenarios still pass.
- [ ] `fnd_sig-feat-test-suite-bac390869a-2_f9e11c7c7c` — **Concurrency test can pass when one evaluator caller fails** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `V01`
  - **Change:** Propagate worker exceptions to the test and assert that both callers receive the same environment. Use bounded waits so a locking deadlock fails instead of hanging.
  - **Scope:** tests/evaluation/locked_environment_test.py::test_same_id_concurrency_builds_once
  - **Verify:** Expand the existing concurrency scenario to retrieve every worker result with a timeout, assert two successful results, and verify identical environment identities and one build.
- [ ] `fnd_sig-feat-test-suite-bac390869a-6_24e26b4ab5` — **Dependency identity test changes multiple cache inputs at once** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `V01`
  - **Change:** Keep the project path and project/lock bytes fixed while varying only ProblemConfig.test_dependencies, then verify distinct identities and reuse for repeated identical declarations.
  - **Scope:** tests/evaluation/locked_environment_test.py::test_declared_test_dependencies_are_identity_inputs
  - **Verify:** Expand the existing identity scenario with configurations sharing identical project files and path but differing declared test dependencies; verify separate environments and reuse for identical declarations.
- [ ] `fnd_sig-feat-test-suite-c193b1fe5e-6_1b08ee8e6b` — **Several exclusion tests pass without applying their exclusion patterns** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `M02`
  - **Change:** Use supported .py files inside excluded directories. For extension-glob tests, register the excluded extension and establish that the file is measured without the pattern. Exercise default exclusions with a supported file inside a default-excluded directory.
  - **Scope:** The exclusion fixtures and scenarios in tests/metrics/driver_test.py.
  - **Verify:** Expand the existing exclusion scenarios to compare results with and without each explicit pattern and to verify default exclusion of otherwise measurable files.
- [ ] `fnd_sig-feat-test-suite-c193b1fe5e-8_dcc1ea549c` — **Registry fixtures discard pre-existing language registrations** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `M02`
  - **Change:** Snapshot both dictionaries before clearing them and restore their contents in a finally block after each test.
  - **Scope:** The four registry-mutating fixtures in driver_test.py and models_test.py.
  - **Verify:** Verify fixture isolation with pre-existing language and extension entries, checking that both dictionaries are restored after normal execution and an exception.
- [ ] `fnd_sig-feat-test-suite-c193b1fe5e-e_3c3987ca22` — **Solve-rate tests cannot distinguish strict from isolated assessment** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `M02`
  - **Change:** Extend the existing solve-rate scenarios with checkpoints whose isolated tests all pass but whose strict pass rate is below one.
  - **Scope:** TestRunSummarySolveRates in tests/metrics/summary_test.py.
  - **Verify:** Verify checkpoint, fully solved problem, and partially solved problem counts using a mixture of strictly solved checkpoints and checkpoints that pass isolated tests but fail regression tests.
- [ ] `fnd_sig-feat-test-suite-c79ab5abca-5_2a4309cdc5` — **Grouped runs can produce duplicate bars and legend entries** (medium; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `D02`
  - **Change:** Sort the run metadata first, then deduplicate by the display-group identity used by the loop so each group is rendered once.
  - **Scope:** The sorted_unique_runs construction in build_test_pass_rate_bars and behavioral chart coverage.
  - **Verify:** Exercise grouped data with varying run dates and multiple display groups; assert exactly five traces per display group and verify each aggregate includes every constituent run once.
- [ ] `fnd_sig-feat-test-suite-e18ce0670d-b_a50659e00e` — **Live step tracking test checks state only after streaming finishes** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `A03`
  - **Change:** Extend this scenario with a controlled streaming generator that checks agent.usage.steps after a StepBegin event has been consumed and before yielding subsequent events or process completion.
  - **Scope:** Extend the existing Kimi live-step scenario and its streaming test double.
  - **Verify:** Yield multiple StepBegin events separately and assert the corresponding counter between yields, then verify final reconciliation does not count those steps again.
- [ ] `fnd_sig-feat-test-suite-f758dabed7-e_2b96f9d252` — **Several behavioral tests never assert the computed result** (medium; test-gap; current triage: test-gap; status: open)
  - **Batch:** `M01`
  - **Change:** Extend these existing scenarios with assertions on the intended counters and classifications. Include positive and negative cases so the tests distinguish correct detection from constant or empty results.
  - **Scope:** Existing scenarios in tests/metrics/language/py_symbols_test.py and tests/metrics/language/py_waste_test.py.
  - **Verify:** Assert both expression counters for the existing nested fixture, then vary nesting while preserving the total number of calls. Extend the method and decorated-function fixtures across one and multiple call sites and assert the corresponding single-use classifications.
- [ ] `fnd_sig-feat-test-suite-553e2630dd-e_2d09288998` — **Binary decoding assertion accepts every possible return value** (low; test-gap; current triage: test-gap; status: open)
  - **Batch:** `E04`
  - **Change:** Replace the tautology with an explicit expectation derived from the intended decoding contract and align the test name with that contract.
  - **Scope:** TestDecodeText in tests/execution/snapshot_diff_test.py.
  - **Verify:** Supply non-UTF-8 bytes containing Latin-1 control-byte values and assert the exact Latin-1-decoded string, not merely a string type or non-null result.
- [ ] `fnd_sig-feat-test-suite-71f66ecf7b-0_4e430f7a92` — **Codex command fixture declares a dictionary but returns a list** (low; api-contract; current triage: contract-mismatch; status: open)
  - **Batch:** `A08`
  - **Change:** Change the return annotation to list[dict], preserving the two-event sequence.
  - **Scope:** Correct the return annotation on get_codex_command.
  - **Verify:** Reproduce the reported behavior, exercise the corrected path, and revalidate the finding.
- [ ] `fnd_sig-feat-test-suite-9ab76ebf59-3_0393f0dfc0` — **Relative output-directory test creates persistent workspace state** (low; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `C02`
  - **Change:** Change into tmp_path with monkeypatch.chdir before exercising the relative path.
  - **Scope:** tests/entrypoints/commands/test_run_agent.py::TestResolveOutputDirectory.test_debug_prefix_with_simple_path
  - **Verify:** Expand the existing relative-path scenario to run inside tmp_path and assert that the resolved directory is created there.
- [ ] `fnd_sig-feat-test-suite-c79ab5abca-2_f80d1fce6f` — **Errors axis labels a percentage as a total count** (low; bug; current triage: confirmed-bug; status: open)
  - **Batch:** `D02`
  - **Change:** Label the Errors axis as a pass percentage, consistent with the computed values and chart title.
  - **Scope:** The Errors panel axis title and chart unit-consistency coverage.
  - **Verify:** Verify across all panels that plotted pass percentages and axis units agree, including the error-test panel.
- [ ] `fnd_sig-feat-test-suite-f597c37171-1_3d7116a6c8` — **Default-language assertion passes from the filename alone** (low; test-gap; current triage: test-gap; status: open)
  - **Batch:** `C06`
  - **Change:** Assert the language annotation in its structural location, independently of the filename.
  - **Scope:** tests/common/render_test.py: TestRenderMultiFilePrefix.test_default_language_resolver
  - **Verify:** Expand the existing default-resolver scenario to verify the annotation for multiple file extensions and ensure missing or incorrect annotations fail.

## Approval decision

The repository owner is the approval authority. Approval is recorded by changing this document’s Status line to `Approved — <name>, <date>` before implementation starts. Any newly discovered public-contract decision or scope expansion requires the repository owner to approve an updated Status record before the affected batch starts.
