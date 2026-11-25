---
name: expert-capsule
description: Distills the user's own AI chat history (ChatGPT, Claude or Gemini export) into a personal "expert capsule", an Agent Skill that makes an AI work by their standards, style and domain rules, then installs it into Claude Code, Claude.ai, ChatGPT or a system prompt. Use when the user wants to turn their chat history into a skill or persona of themselves, wants an AI that answers "like me" or "in my style", wants to learn their working rules from past conversations, or mentions capsule, chưng cất lịch sử chat, tạo skill phong cách của tôi, AI làm việc giống tôi.
license: MIT
compatibility: Needs Python 3.11+ with PyYAML. Without any API key it runs inside Claude Code (subagents answer the model requests); otherwise it needs an Anthropic or OpenAI API key, or a local Ollama model.
metadata:
  version: "0.3.0"
  repository: "https://github.com/HThiuhiu/expert-capsule"
---

# Expert Capsule

Turn the user's chat history into `expert-<slug>/`: an Agent Skill folder (`SKILL.md`, one rule file per domain, a
style guide, sample answers, exports for ChatGPT and system prompts). Rules are learned from behaviour, not
self-description: the moments the user corrected, rejected, challenged or accepted an AI answer. Every rule needs
at least 2 verbatim quotes from 2 different sessions; the quotes stay in a private folder.

A bundled CLI does the work. You set it up, run it, relay results, and collect the user's decisions.

## Ground rules

- Talk to the user in their language. CLI messages are in Vietnamese: translate or summarize them as needed.
- The user decides which domains to distill and which rules to keep. Never choose for them.
- Privacy: the workspace holds the user's raw chat history. Never commit, upload or share it. Never read the raw
  export or the agent bundles into your own context, and never paste chat content into replies beyond the evidence
  quotes shown during review. Nothing under `private/` ever leaves the workspace.
- Report results honestly, including a quick check where the capsule does worse than the plain AI.

## Setup

1. **The CLI.** Below, `capsule` means `python "<skill dir>/scripts/capsule.py" -C "<workspace>"`, where
   `<skill dir>` is the directory containing this SKILL.md (use `python3` if `python` is missing). Check it with
   `python "<skill dir>/scripts/capsule.py" --version`. Missing PyYAML: `python -m pip install pyyaml`.
2. **Ask the user** (one round of questions; skip what they already said):
   - The name to show in the capsule ("Cách làm việc của <name>").
   - Where their export is. No export yet: walk them through [references/export-guide.md](references/export-guide.md).
     Exports arrive by email and can take a while; you can stop here and resume later with `capsule status`.
   - Which AI will use the capsule: Claude Code, Claude.ai, ChatGPT, Gemini, API, other.
   - How to run the model calls. Default to `agent` when you can spawn subagents (no API key needed; uses the
     user's Claude Code plan). Offer `haiku` or `anthropic` if `ANTHROPIC_API_KEY` is set and they want it faster,
     `openai` with `OPENAI_API_KEY`, `ollama` to keep everything on their machine.
3. **Workspace**: a folder for this person's data, outside `<skill dir>` (plugin updates replace that folder).
   Default: `capsule-workspace` in the current directory, unless the user names one. Create it with
   `capsule init --owner "<name>" --mode <mode>`: it writes `config.local.yaml`, `data/raw/` and a `.gitignore`
   that keeps the folder out of git.

## Pipeline

`capsule status` prints the finished steps and the next command. Run it first when resuming, and whenever unsure.

| Step | Command | Your part |
|---|---|---|
| 1 Ingest | `capsule ingest "<export path>"` | Report the session count. Under 50 sessions: warn that few rules will have enough evidence |
| 2 Domains | `capsule domains` | Show the table. Ask which 1 to 4 domains to distill (multi-select). Thin domains only feed the shared core |
| 3-6 Build | `capsule build --domains a,b` | Slow: several model rounds. Then summarize the report: rules per domain, conflicts, quick-check headline |
| 7 Review | `capsule review --show`, then `--keep/--delete/--edit/--answer` | Follow [references/review-guide.md](references/review-guide.md) |
| 8 Package | `capsule package` | Writes `<workspace>/expert/expert-<slug>/` |
| 9 Install | `capsule install --target claude-code` or `--target zip` | Per target: [references/install-targets.md](references/install-targets.md) |
| 10 Taste test | `capsule demo --blind "<question>" ...`, then `capsule demo --reveal A B ...` | Optional, recommended. See below |

Custom domains: when the user wants a capsule for a way of working that cuts across fields (research style, how
they learn, how they review code), add a `custom_domains` entry to `<workspace>/config.local.yaml` (commented
example in that file; match on the raw labels shown by `capsule domains`), then rerun `capsule domains`.

Exit codes: `0` done; `1` every model call failed (usually a missing key: the message lists fixes); `2` missing
input or wrong usage (read the message); `3` waiting for subagents (next section).

## When a command stops for subagents (exit code 3)

Happens only in `agent` mode. The command queued its model requests; subagents answer them; the rerun reads the
answers from the cache, so finished work is never paid for twice.

1. `capsule queue bundle`. It prints one line per bundle: `<bundle path>  model=<haiku|sonnet>  n=<requests>`.
2. For **each** bundle start one **fresh** subagent with that model, all in parallel (batches of up to 10):
   - Installed as a Claude Code plugin: the `capsule-worker` agent (it has the instructions). Prompt:
     `Answer the Expert Capsule bundle at <absolute bundle path>.` Pass the model from the line.
   - Otherwise: a general-purpose subagent with the prompt in [references/agent-loop.md](references/agent-loop.md).
3. When all have finished: `capsule queue import`, then rerun the exact command that stopped. Repeat until it exits 0.

Never answer a bundle yourself and never edit answer files: the quick check stays blind only because the capsule,
no-capsule and judge bundles go to different fresh subagents. Bad answers are re-asked automatically on the rerun.
No subagents in this host (for example Claude.ai): follow "Without subagents" in references/agent-loop.md.

## Taste test (step 10)

The built-in quick check is small (15 held-out corrections, judged by the same model family) and noisy. The
best evidence is the user's own judgement. Ask for 3 to 5 real questions from their work, run
`capsule demo --blind "<q1>" "<q2>" ...`, show each pair A/B without saying which has the capsule, record their pick
per question, then `capsule demo --reveal <picks>` and tell them the score.

## Finish

Tell the user: where the capsule is and how it was installed; the quick-check and taste-test numbers with their
limits; that they can log a correction later with `capsule correct "<what the right way is>" --domain <slug>`;
and that `private/` and the workspace must stay private. Problems: [references/troubleshooting.md](references/troubleshooting.md).
