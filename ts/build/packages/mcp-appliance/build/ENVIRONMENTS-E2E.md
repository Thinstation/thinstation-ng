# Environments end-to-end validation (internal GitLab only)

This procedure validates the disposable chroot lifecycle without publishing to GitHub.

## Gates

1. Run `test-mcp-environments` on the feature branch; require green Python + frontend tests.
2. Merge to local `7.4-Stable` only after integration review; no GitHub mirror push.
3. Build MCP appliance image from local GitLab with `BUILD_MCP_APPLIANCE=1`. Keep publication and rotation separate.
4. Deploy a disposable test VM with a fresh persistent volume and no production credentials.
5. Verify Environments > Installed / Catalog / Settings, CSRF protections, and saved package URLs across restart.
6. Check a known Fedora 44 chroot using upstream, then configured Foreman repository URLs. Verify effective package source and job logs.
7. Simulate Foreman unavailability on the **test VM**; ensure the job reports failure rather than claiming updates succeeded. Automatic fallback requires independent implementation and validation.
8. Verify that a failed staged rebuild preserves the old environment, including when a required path is missing or an active mount blocks activation.
9. Verify that manifests contain no durable data paths; mount credentials, models, work files and results externally.
10. Once approved, confirm running processes are drained before replacing any chroot, validate required binaries after activation, and test recovery from an interrupted rename.
11. Only after the rebuild worker is explicitly integrated and validated, exercise catalog install, rebuild and cleanup through the UI.
12. Finally rotate an appliance test VM, confirm persistent data and MCP reconnect; never push this development change to public GitHub until stable.

## Known limitations

- The staged rebuild builder is not connected to the persistent worker.
- Snapshot rollback has been superseded by disposable rebuild; old chroot is retained until explicit cleanup.
- Daily checks, automatic Foreman-to-upstream fallback, and catalog provisioning remain to be finished.
- A green frontend/logic pipeline is not a replacement for exercising the complete package lifecycle on a test VM.
- No test step should alter the active production appliance.
