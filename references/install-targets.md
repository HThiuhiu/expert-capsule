# Step 9: putting the capsule into an AI

`capsule package` writes `<workspace>/expert/expert-<slug>/`. Everything except `private/` is safe to load into an
AI. Each capsule also contains `exports/HUONG_DAN_CAI.md`, a step-by-step install guide in Vietnamese.

| Target | How |
|---|---|
| Claude Code | `capsule install --target claude-code` copies the capsule to `~/.claude/skills/expert-<slug>/` (or `$CLAUDE_CONFIG_DIR/skills`). It loads in the next session; Claude uses it when a request matches, or the user types `/expert-<slug>`. `--dir <path>/.claude/skills` installs it for one project only |
| Claude.ai (web, desktop) | `capsule install --target zip` writes `expert/dist/expert-<slug>.zip` (without `private/`). Then Settings > Capabilities: turn on code execution, Skills > Upload skill, choose the zip, enable it |
| ChatGPT custom instructions | Settings > Personalization > Custom instructions: paste `exports/custom_instructions.txt` (compressed to 1,500 characters: core rules and style first) |
| ChatGPT Projects, custom GPTs | Paste `exports/project_instructions.md` into the instructions field; upload `references/domains/*.md`, `references/style.md` and `references/exemplars.md` as files or knowledge |
| Claude Projects, Gemini Gems | Same as ChatGPT Projects: instructions from `exports/project_instructions.md`, domain files as knowledge |
| API or own bot | `exports/system_prompt.md` as the system prompt (core plus every domain) |
| Other agents that read Agent Skills | Copy the `expert-<slug>/` folder, without `private/`, into that tool's skills folder |

Menu names in vendor apps change between versions; adapt to what the user sees.

## Keeping it up to date

- When the AI gets something wrong while using the capsule: `capsule correct "<what the right way is>" --domain <slug>`.
  Corrections are stored in `private/corrections.jsonl`; turning them into rule updates is planned (`capsule update`).
- With a newer export: put it in `data/raw/`, run `capsule ingest`, `capsule domains`, `capsule build --domains ...`.
  Cached model answers are reused, reviewed rules keep their decisions, and `capsule package` keeps the previous
  version in `private/versions/` for rollback. Reinstall with the same `capsule install` command.
