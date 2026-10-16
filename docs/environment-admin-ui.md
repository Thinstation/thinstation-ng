# Environment administration interface

## Scope

Installed, Catalog, Staging & recovery, Operations, and Settings share the existing
appliance page, panel, typography, tab and button styles. Environment-specific
responsive rules live in `environments.css`; view-model helpers are separately tested.
Long environment IDs wrap within table cells instead of spilling across the page.
On narrow screens, OS/base information moves below the environment or profile name.

## Operations

Installed uses search, row selection, a global Check all updates action, and confirmed
Update selected / Redeploy selected actions. Select-all means visible eligible rows;
Check all updates includes eligible installed rows regardless of the filter.
The confirmation explicitly lists the eligible target subset.

Bulk submission is sequential within this browser page, not a persistent global queue.
A failed job stops remaining submissions. Missing job status pauses progress. Leaving
the Environments component stops submitting the remaining browser queue but does not
cancel an already submitted backend job. Other clients retain the backend's existing
per-environment lock behavior; no new cross-client scheduler is claimed.

Redeploy is offered only for a stored definition with a valid package list. The worker
still performs its own source, manifest, and replacement checks. This change does not
alter the package/update/rebuild worker. Delete remains unavailable because the worker
has no guarded deletion endpoint. Catalog profile installation is not exposed either.

## Read-only metadata

Inventory separates dot-prefixed staging and retained directories from installed roots,
reports matching job metadata when available, and never claims an untracked stage is a
failed deployment. Nothing is deleted or automatically cleaned. Job metadata is loaded
once per inventory request. Recent job summaries omit owner and raw log/error content.
The existing authenticated job endpoint supplies details on request.

Worker completion and available package updates are separate states. A successful check
without a machine-readable result says to inspect its log, not Up to date. Later update
or rebuild jobs invalidate a prior update observation. Redeploy availability describes
the stored definition, not a guarantee that a deployment will succeed.

## Settings

Repository drafts survive inventory refresh and tab switches. Reset changes restores
the last loaded/saved values; Save changes retains existing HTTPS validation. No package
operation is triggered by saving sources. Automatic mirror fallback remains unsupported.

## Validation

Run `npm test` and `npm run build` from the frontend directory. The fixture-only browser
suite `tests/environment-browser.cjs` requires Playwright Chromium and tests all five
views, long names, selection across filters, modal confirmation, serialized submission,
stop-on-failure, stale inventory, and draft preservation. It never contacts a live
appliance or runs a real environment action. `ENV_QA_OUTPUT` chooses screenshot/report
output outside the source tree. The tested viewports are 1440x1000, 844x390, and 390x844.

Deploy the UI and `mcp_environments.py` together for all metadata. With an older backend,
dot directories still separate correctly, but history and definition-dependent redeploy
controls remain unavailable until the metadata endpoint is updated.

## Lifecycle completion

Installed roots and recognized .stage-, .previous-, and .deleting- directories now
expose individual and selected deletion. The server verifies the exact root identity
and typed confirmation, refuses active jobs/mounts/processes/open files, and rechecks
after an atomic no-replace quarantine rename. Definition files are archived with the
job. No external mounted paths are intentionally removed. Deletion is irreversible.

Catalog Create opens a naming/base/release wizard and a server-generated package
review. Names cannot collide with a root or stored definition. Creation uses a
pinned source-definition digest, signed repository recipes and atomic no-replace
activation; it is not a rebuild of an existing environment. Profile notes explain
base-only AI tools and separately installed engines, and supported distro limitations.
Catalog installation does not run a downloaded initialization script.

Package operations run the package manager inside its own root using its configured
repositories, with private runtime mounts and bounded subprocess timeouts. Ubuntu
Update now actually upgrades packages, after an index refresh, then simulates another
upgrade to record remaining/held packages. DNF records 0/100 query results. Rocky
minor versions are accepted and never receive Fedora mirror overrides. All terminal
worker paths record completion times and errors. Old update jobs without a check are
shown as Updated; check required. Failed checks are reported as failed, not unchecked.

Check-all continues after individual failures; mutating batches stop after a failure.
The creation wizard, typed deletion, staging selection and status persistence are
covered by a local-only HTTP browser fixture. Destructive worker guards and package
commands are tested with mocks; no existing appliance root is deleted in these tests.

## Delete-confirmation feedback

The dialog displays the complete phrase in a selectable block, lists each target
once, and explains exactly which requirement is missing. Both review acknowledgment
and the phrase are still required. Outer whitespace and action-word capitalization
are normalized in the UI; target names and bulk counts remain exact. The API still
receives the canonical per-target `DELETE <name>` confirmation and identity token.
The click handler repeats the same validation used to enable the button, and stale
inventory or pending submissions block confirmation. No backend deletion rules changed.

The old UI was reproduced enabling the button only with exact text and the checked
review box; a trailing space or lowercase action silently kept it disabled. This
is a confirmed usability defect, not evidence of an always-disabled Svelte binding.
Dedicated local-fixture tests cover single/bulk confirmation, mismatch feedback,
acknowledgment, whitespace, stale state, disabled-button events and narrow viewports.

## Single acknowledgment (review follow-up)

Deletion now requires only the review checkbox followed by the final Delete button,
for both individual and bulk operations. The typed phrase field has been removed.
This supersedes the earlier dual-checkbox-and-phrase confirmation description.
Selected targets and warnings remain visible, and acknowledgment resets when a
new operation is opened. In-flight and stale-inventory guards remain unchanged.
The request still carries canonical per-target confirmation and directory tokens
for backend validation; no authentication or worker safety check has changed.
