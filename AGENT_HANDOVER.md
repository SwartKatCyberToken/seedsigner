# Handover — seedsigner-pgp

Committed repo facts. The code-audit skill reads this file at the repo root as `AGENT_HANDOVER.md`.

Progress, review findings, and the current task go in `AGENT_HANDOVER.session.md`, which is gitignored. Do not put session notes in this file.

Standing rules live on the CyberToken wiki and in the code-audit skill. This file records facts and exceptions for **this** repo and links to those rules. It does not paste them. Do not invent facts from other repos, other chats, user memories, or user rules.

## Repo summary

[2–6 sentences: what this repo is, who it is for, and how it is meant to be run. Update only when the product itself changes.]

- **Purpose:**
- **Stack:**
- **Local entry points:**
- **Tests:** [command that runs the unit suite, and the coverage command]
- **Coverage bar:** [metric and floor, e.g. line coverage must not drop. `n/a` only if this repo has no unit tests yet]
- **Key modules:**

## DFT (do not touch)

Do not modify these unless the user explicitly names them in this chat.

| Path or thing | Why frozen | Allowed exceptions |
|---|---|---|
| | | |

Also frozen unless the user explicitly asks:

- Unrelated files (no drive-by refactors or reformats)
- Public APIs, CLI flags, env var names, and on-disk data formats
- Dependency sources and versions (no irreplaceable SaaS; no unpin to `latest`)
- Secrets, credentials, and machine-local paths belonging to another repo

## Repo-specific consistency

- **Layout:**
- **Naming:**
- **Exceptions:** [standing rule that does not apply here, and why. Leave blank when there are none.]

## Standing rules

Apply these on every session. Record checklist results and code-shape findings on the session file, not here.

- **Digital autonomy:** walk https://gitlab.com/software1015210/cybertoken-wiki/-/wikis/Guidelines/Checklist and record each item as holds, not applicable (why), or violated. Optional items stay optional when the reason is written on the session file.
- **Code shape:** apply https://gitlab.com/software1015210/cybertoken-wiki/-/wikis/Guidelines/Code-shape to files this change added or substantially edited. A size split is a separate next action marked "behavior unchanged."
- **Unit tests:** a behavior change includes unit tests in this repo's existing suite. Coverage must not fall below **Coverage bar**. The procedure lives in the code-audit skill.
- **Entry points:** `install` / `setup` / `deploy` / `run` / `debug` at the repo root or in `scripts/` / `bin/`; idempotent; `-h`/`--help`; documented in `README.md`.

## Out of bounds

- Do not open, search, or summarise a different repo under `CyberToken` unless the user names that repo in this chat.
- Do not treat user rules, memories, or other chats as facts about **this** repo.

## Pointers

- Digital autonomy checklist: https://gitlab.com/software1015210/cybertoken-wiki/-/wikis/Guidelines/Checklist
- Code shape: https://gitlab.com/software1015210/cybertoken-wiki/-/wikis/Guidelines/Code-shape
- Session progress: `AGENT_HANDOVER.session.md` (gitignored, not in this commit)
