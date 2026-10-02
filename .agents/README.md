# AI agent material

This directory contains public, project-native guidance for using the ThinStation NG repository effectively.

## Scope

The skills may document:

- repository structure and package mechanics,
- how to accept a server, desktop, kiosk, or appliance target definition,
- how to create/update ThinStation build configuration,
- package/profile selection,
- image construction,
- local QEMU/`bt` testing,
- debugging and qualification,
- preparing a source change for the repository's normal branch/MR/CI workflow.

The skills must not document a maintainer's private deployment topology, internal host inventory, infrastructure organization, addresses, credentials, connector layout, or relationships to unrelated private repositories.

## Layout

```text
AGENTS.md
.agents/
  README.md
  skills/
    <skill-name>/
      SKILL.md
      agents/openai.yaml
      references/
```

`AGENTS.md` is the small always-on repository guide. Reusable task-specific knowledge lives under `.agents/skills/`.

## Publishing rules

- Keep `SKILL.md` concise and task-oriented; put detail in `references/`.
- Prefer repository-relative paths and portable local methods.
- Build examples may use concrete software targets when they teach reusable ThinStation mechanics.
- Remove environment-specific names, addresses, IDs, device inventories, deployment topology, and private repo relationships.
- Update skills when real engineering work establishes a durable repository invariant, failure mode, or validation technique.
- Validate frontmatter, relative references, and scripts before merging.

## Rectify skills

When a maintainer says **Rectify skills**, update only durable ThinStation NG repository/build knowledge in this directory. Do not propagate private operational context into the public skill bundle.
