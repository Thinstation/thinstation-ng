# GitLab to GitHub publishing and workstation reconciliation

GitLab is the source of truth; GitHub is a mirror. Treat workstation checkouts as potentially stale and dirty.

1. Query both remote heads before any push and fetch GitLab's current ref into a separate tracking ref, not by overwriting a local branch. Avoid relying on stale origin/*.
2. Verify the GitHub head is an ancestor of the GitLab head with `git merge-base --is-ancestor`. Push the verified GitLab ref to GitHub without force; re-query the GitHub remote SHA after push.
3. For divergence, inspect `git log --left-right --cherry-pick upstream...local` and identify unique local commits versus already-incorporated patches. Preserve unique work on a clearly named backup branch before rebase/reset.
4. Separate authored package/configuration files from generated chroot/package roots. Never stage wholesale build outputs, never clean untracked files blindly, and never rewrite a dirty checkout without safeguarding changes.
5. If rebase encounters conflicts, prefer tested current design over obsolete configuration; preserve unique improvements explicitly. Verify status, hashes, and tests after completion.
6. Root-owned build outputs can prevent user Git operations. Inspect ownership; use privileged Git only when necessary, and do not recursively chown generated build roots merely to complete a rebase.
7. An SSH key loaded in one interactive shell may not be available to remote/automation shells. Inspect `SSH_AUTH_SOCK`, verify with `ssh-add -l`, and confirm `ssh -T git@github.com` before publication. Never print/copy private keys or bypass host-key verification.

For a divergent local branch whose commits are already upstream, retaining a backup and updating the branch to the verified upstream ref is sufficient. Do not manufacture duplicate commits.
