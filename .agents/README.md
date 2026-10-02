# AI agent material

This directory contains project-native guidance intended for AI coding/engineering agents.

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

`AGENTS.md` is the small always-on repository guide. Reusable, task-specific knowledge lives in `.agents/skills/` and follows the Agent Skills `SKILL.md` format.

The Agent Skills specification defines the contents of a skill, not a mandatory install path. `.agents/skills/` is the cross-client project convention recommended by current Agent Skills implementation guidance and used by compatible clients. Keep this directory canonical instead of maintaining duplicate vendor-specific copies.

Client-specific compatibility links or copies may be generated locally when needed (for example `.claude/skills/`), but do not commit divergent copies.

## Publishing rules

- Keep `SKILL.md` concise; put detailed architecture and diagnostics in `references/`.
- Include only durable, reusable knowledge. Exclude transient PIDs, temporary log paths, secrets, and one-off lab state.
- Prefer repository-relative paths and portable methods.
- Update skills when a real engineering session establishes a new invariant, failure mode, or validation method.
- Validate YAML frontmatter, relative reference paths, and executable scripts before merging.

## Rectify skills

When a maintainer says **Rectify skills**, review recent ThinStation work and update the relevant project skills here. Also update the broader `automation/thinstation-infra` skill when the lesson affects infrastructure, CI, or operational architecture beyond this repository.
