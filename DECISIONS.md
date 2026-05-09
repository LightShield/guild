# Guild — Implementation Decisions

Decisions made during the v0.2 rebuild that aren't covered in REQUIREMENTS.md or ARCHITECTURE.md.

---

## D-01: Anti-looping nudge pattern for local models

**Decision:** After a successful tool call on a simple task, inject a user-role message nudging the model to stop: "The action above succeeded. If this completes your task, please summarize what was done."

**Why:** Local models (gemma4-26b, gemma4-4b) don't reliably emit a text-only response after tool use. They repeat the same tool call indefinitely. Three complementary fixes:
- Fix A: Tool result text includes "If this completes your task, provide your final response"
- Fix B: After all tools succeed on a single-action task, inject a completion nudge
- Fix C: Deduplication guard skips identical calls and tells the model to move on

**Impact:** First real Ollama run went from infinite loop to clean 2-turn completion.

**Reassess when:** Models improve at knowing when to stop. Each model upgrade should test whether the nudge is still needed.

---

## D-02: Permission prompt_fn injection

**Decision:** `PermissionChecker` accepts an optional `prompt_fn` callable for the ASK tier instead of hardcoding `input()`.

**Why:** Hardcoded `input()` is untestable and breaks in non-interactive contexts (pytest, CI, background daemon). Signature: `(tool_name, agent_id, args) -> bool`.

---

## D-03: Tool path resolution against working_dir

**Decision:** All file-based tools resolve relative paths against the agent's `working_dir`.

**Why:** Agents operate in the context of a project directory. Without this, relative paths resolve against the process CWD, which may differ from the project root.

---

## D-04: Pydantic for config boundaries, dataclasses for internals

**Decision:** Use Pydantic models for data that crosses serialization boundaries (config.toml parsing). Use plain dataclasses for internal-only objects (Message, ToolResult, LLMResponse).

**Why:** Pydantic validates types on construction — catches bad config at load time. But it has overhead (slower construction, import time) that isn't worth paying for objects created thousands of times per session internally.

**Reassess when:** A dedicated configs loader library replaces the Pydantic config models.

---

## D-05: DaemonSupervisor doesn't daemonize itself

**Decision:** The supervisor manages lifecycle (PID file, signals, cleanup) but does NOT fork/detach the process. The CLI handles detachment via `subprocess.Popen(start_new_session=True)`.

**Why:** Separating "manage lifecycle within a process" from "become a background process" keeps the supervisor testable without process-management mocking. The CLI layer decides how to launch; the supervisor just runs.

---

## D-06: Resource monitor is on-demand, not a background thread

**Decision:** `ResourceMonitor.wait_if_throttled()` is called synchronously by the agent loop before each LLM call. No background polling thread.

**Why:** A background thread adds complexity (synchronization, thread safety on the messages list) for minimal benefit. The agent loop already yields between turns — checking resources at that yield point is simpler and sufficient.

---

## D-07: Sleep detection via time-drift, not OS notifications

**Decision:** Detect sleep by checking if `time.monotonic()` elapsed >> expected between turns. No platform-specific sleep/wake notification APIs for MVP.

**Why:** Cross-platform OS notifications require different code for macOS (IOKit), Linux (systemd-logind D-Bus), and Windows (power events). Time-drift works everywhere with zero platform code. It's slightly less responsive (detects sleep after wake, not before) but correct enough.

**Known limitation:** This is a temporary approach. OS-specific code is inevitable and should be abstracted behind a `PlatformAdapter` interface — centralized, minimal, and the single source of truth for all platform-specific behavior (idle detection, sleep/wake, thermal state). Time-drift will be replaced with proper OS notifications when the platform adapter is built.

**Reassess when:** Platform adapters are built (REQ-02.4).

---

## D-08: Activity detection uses CPU load as proxy

**Decision:** For MVP, user "activity" is detected via CPU utilization threshold. Not via actual input device monitoring.

**Why:** True idle detection requires platform-specific APIs (IOKit on macOS, /proc/interrupts on Linux, GetLastInputInfo on Windows). CPU load is a rough proxy but works cross-platform with `psutil`. False positives (background compile = "active") are acceptable — they just add delays, not failures.

**TODO:** Validate this claim with real-world testing. Measure how often CPU-as-proxy correctly identifies user activity vs. false positives from background processes (compilers, downloads, updates). If false positive rate is too high, prioritize platform-specific idle detection.

**Reassess when:** Platform adapters are built (REQ-02.4).
