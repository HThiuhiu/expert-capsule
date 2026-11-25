# Expert Capsule

**English** · [Tiếng Việt](README.vi.md)

[![tests](https://github.com/HThiuhiu/expert-capsule/actions/workflows/tests.yml/badge.svg)](https://github.com/HThiuhiu/expert-capsule/actions/workflows/tests.yml)
[![release](https://img.shields.io/github/v/release/HThiuhiu/expert-capsule)](https://github.com/HThiuhiu/expert-capsule/releases/latest)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

![Expert Capsule: turn your AI chat history into a skill that works your way](assets/banner.png)

**Turn your own ChatGPT, Claude or Gemini chat history into a skill that makes an AI work by your standards, in
your style, in your fields.**

You have corrected AI answers hundreds of times: "too long", "cite the source", "no, use the simpler method", "this
is exactly what I wanted". Each of those moments says something about how you work. Expert Capsule finds them in
your chat export, turns them into rules of the form *"When X, do Y, because Z"*, and packages them as an
[Agent Skill](https://agentskills.io/specification) you can load into Claude Code, Claude.ai, ChatGPT or any system
prompt.

It ships as a Claude Code plugin: install it, hand Claude your export, and Claude runs the whole pipeline with
subagents, with no API key. It reviews every rule with you in the chat, then installs the result.

> **Language note:** the skill's instructions are in English and Claude talks to you in your language, but the
> capsules it writes and the CLI messages are currently in **Vietnamese**. English output is the top item on the
> [roadmap](#roadmap). Contributions welcome.

## Quick start (Claude Code, no API key)

**1. Install** (once), inside Claude Code:

```
/plugin install expert-capsule --marketplace HThiuhiu/expert-capsule
```

On Claude Code older than 2.1.275, run `/plugin marketplace add HThiuhiu/expert-capsule`, then
`/plugin install expert-capsule@expert-capsule`. To skip the plugin system:
`git clone https://github.com/HThiuhiu/expert-capsule ~/.claude/skills/expert-capsule`.

**2. Export your history** and download the zip from the email:
- ChatGPT: Settings > Data controls > Export data.
- Claude: Settings > Privacy > Export data.
- Gemini or anything else: paste conversations into a `.txt` file, one turn per line starting with `User:` or `Gemini:`.

**3. Ask Claude**, in any folder:

> Build my expert capsule from my ChatGPT history, the export is at ~/Downloads/chatgpt-export.zip

(or type `/expert-capsule:expert-capsule`). Claude then:
1. Asks your name and which AI you will use the capsule in.
2. Creates a private `capsule-workspace/` folder (kept out of git) and reads the export.
3. Shows the domains found in your history and lets **you** pick 1 to 4.
4. Runs extraction and synthesis with Haiku and Sonnet subagents.
5. Walks you through **every rule** in the chat: keep, reword, narrow, or delete.
6. Packages the capsule and installs it: Claude Code skill, Claude.ai zip, or text for ChatGPT.
7. Offers a **blind A/B taste test**: you judge which answer sounds more like you, without knowing which one had the capsule.

Interrupted? Say "continue my capsule": `capsule status` tells Claude where you left off.

Requires Python 3.11+ and PyYAML (`pip install pyyaml`). Subagents count against your Claude Code plan (or API
billing, if that is how you run Claude Code); no separate key is needed.

## What you get

```
expert-<you>/
  SKILL.md                     # always-on core: shared rules, writing style, working modes (< 5,000 tokens)
  references/domains/<d>.md    # per domain: coded rules (KT-07), cases, playbooks, open questions
  references/style.md          # style guide: instructions plus verbatim examples of how you write
  references/exemplars.md      # model answers that meet your bar
  exports/                     # custom_instructions.txt, project_instructions.md, system_prompt.md, install guide
  capsule.json                 # version, stats, quick-check result
  private/                     # NEVER shared: evidence quotes, events, edit history
```

See a sample capsule built from synthetic data for a fictional person: [examples/expert-demo/](examples/expert-demo/).

## Why it is different

- **Behaviour, not self-description.** Most "make the AI like me" setups ask you to describe yourself. Expert Capsule
  learns from what you actually did: the answers you rejected, challenged, corrected or accepted.
- **Evidence or it is not a rule.** A rule needs at least 2 events from at least 2 different sessions, each backed by
  a verbatim quote that must match your message exactly. Anything weaker stays a candidate.
- **Your taste, not common sense.** Corrections anyone would make (a bug, a wrong fact) are filtered out. What is left
  is domain standards and personal preferences.
- **You stay in charge.** You choose the domains and review each rule; conflicting demands ("short" here, "detailed"
  there) become questions for you, not guesses.
- **Private by default.** Secrets, emails and phone numbers are masked before any model call. Everything stays in one
  local folder. Evidence quotes stay in `private/`.
- **One capsule, many AIs.** The same rules are exported as an Agent Skill, a Claude.ai zip, ChatGPT custom
  instructions, project instructions and a system prompt.

## How it works

| Step | What happens | Model |
|---|---|---|
| 1. Ingest | Read the export, normalize sessions, keep edited-prompt and regenerate branches, **mask API keys, passwords, emails, phone numbers** | none |
| 2. Domains | Label each session's field, merge similar labels, propose a list for you to choose from | cheap |
| 3. Signal filter | Score every turn (regenerations, correction words, repeated requests, short commands after long answers, specific praise) and pick 200 to 400 turns | none |
| 4. Mining | For each turn: feedback type, targeted aspect, how personal it is (universal / domain norm / personal taste), **verbatim quote** (dropped unless it is an exact substring) | cheap |
| 5. Synthesis | Rules per domain, cases, playbooks (from 6 sessions of the same task), conflicts, shared core, style. Code drops rules with fewer than 2 events or a single session | strong |
| 6. Quick check | On 15 of your past corrections held out from training: how many of your actual criticisms an AI with the capsule anticipates, versus the same AI without it | strong |
| 7. Review | You keep, reword, narrow or delete each rule, and answer the conflict questions | none |
| 8. Package | Generate SKILL.md, domain files and every export from one source; keep the previous version for rollback | none |

Every model answer is cached on disk: reruns, new domains or more turns only pay for what is new.

## Status and limitations

- **Not validated yet.** The built-in quick check is small (15 items), noisy, and judged by the same model family. On
  the first real dataset it did not show the capsule beating the plain AI. A full evaluation is not done yet. The
  blind taste test (`capsule demo --blind`) is the best signal for now. If you try it,
  [share your score](https://github.com/HThiuhiu/expert-capsule/issues) (just the numbers, never your data).
- **Capsules are written in Vietnamese** (see the language note above).
- **Needs data.** Aim for 50+ conversations with some back-and-forth. Domains with fewer than 15 sessions are "thin"
  and only feed the shared core; playbooks need 6 sessions of the same kind of task.
- Many corrections are universal (broken code, wrong facts) and do not become personal rules, so the personal part can
  be small.
- On Claude.ai there are no subagents, so it only suits small histories and skips the quick check.

## Other ways to run it

| Where | How |
|---|---|
| **Claude.ai** | Download `expert-capsule-skill.zip` from [Releases](https://github.com/HThiuhiu/expert-capsule/releases/latest), then Settings > Capabilities > Skills > Upload skill. Experimental: no subagents |
| **Other agents that read Agent Skills** | Unzip the release into the agent's skills folder |
| **Command line with an API key** | Fastest: calls the model in parallel. See below |

```bash
git clone https://github.com/HThiuhiu/expert-capsule.git && cd expert-capsule
pip install -e ".[anthropic]"
capsule init ~/capsule-workspace --owner "Your Name" --mode anthropic
cd ~/capsule-workspace

capsule ingest ~/Downloads/chatgpt-export.zip
capsule domains                         # pick domains from this list
capsule build --domains a,b             # steps 3 to 6
capsule review                          # or: --show, then --keep / --delete / --edit / --answer
capsule package
capsule install --target claude-code    # or --target zip for Claude.ai
capsule demo --blind "a real question from your work"
capsule status                          # where am I, what next
```

| `--mode` | Needs | Notes |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | Haiku for steps 2 and 4, Opus for 5 and 6. Roughly a few USD per run |
| `haiku` | `ANTHROPIC_API_KEY` | Haiku everywhere, under 1 USD per run |
| `openai` | `OPENAI_API_KEY` | ChatGPT Plus/Pro does not include API access; keys come from platform.openai.com |
| `ollama` | [Ollama](https://ollama.com) and a pulled model | Nothing leaves your machine; rule quality depends on the model |
| `agent` | Claude Code | No API calls: subagents answer a queue (the plugin automates this) |

Costs are rough estimates (a Lite run reads about 2M tokens, mostly on the cheap model). Prices live in
`src/pc/config.default.yaml`.

## Putting the capsule into your AI

| Target | How |
|---|---|
| **Claude Code** | `capsule install --target claude-code` copies it to `~/.claude/skills/`. Claude uses it when relevant, or type `/expert-<slug>` |
| **Claude.ai** | `capsule install --target zip`, then Settings > Capabilities > Skills > Upload skill |
| **Claude Projects, ChatGPT Projects, Gemini Gems** | Paste `exports/project_instructions.md` into the instructions; upload `references/domains/*.md` as knowledge |
| **ChatGPT custom instructions** | Paste `exports/custom_instructions.txt` (compressed to 1,500 characters, best-evidenced rules first) |
| **API** | Use `exports/system_prompt.md` as the system prompt |

## Privacy

- Secrets and personal data are masked with regex **at ingest**, before any model call.
- All data lives in your workspace folder; `capsule init` writes a `.gitignore` that keeps the whole folder out of
  git. Delete the folder and it is gone.
- Rules and cases are written in general terms. Verbatim quotes stay in `private/`; `capsule package` flags any long
  quote that leaks elsewhere, and `capsule install` never copies `private/`.
- The style examples in `SKILL.md` are short verbatim lines of yours. Read them before sharing a capsule.

## Roadmap

- English (and other languages) for generated capsules and CLI messages.
- A proper evaluation: capsule versus a self-written prompt, versus retrieval over raw chats, Lite versus Deep mode.
- Learning while you use it (`capsule update` from logged corrections).
- More export formats.

Ideas, bug reports and pull requests are welcome in [Issues](https://github.com/HThiuhiu/expert-capsule/issues).

## Development

```bash
pip install -e ".[dev]"
python -m pytest -q
claude plugin validate .               # check the plugin, skill and agent manifests
claude --plugin-dir .                  # run Claude Code with the skill from this folder
python scripts/build_skill_zip.py      # build dist/expert-capsule-skill.zip
```

Repository layout: `SKILL.md`, `references/` and `agents/` are the skill; `.claude-plugin/` holds the plugin and
marketplace manifests; `scripts/` has the no-install launcher and the zip builder; `src/capsule/` is the Lite
pipeline; `src/pc/` holds shared code (config, ingest, PII masking, LLM calls) and the research-oriented Deep mode.

To release: bump the version in `pyproject.toml`, `src/capsule/__init__.py`, `.claude-plugin/*.json` and `SKILL.md`
(a test checks they match), then push a `v<version>` tag; the release workflow attaches the zip.

## Credits

- [distilly](https://github.com/titanwings/distilly) (MIT): exclusive gates, append-only updates, versioning and
  rollback, packaging as an Agent Skill.
- [Agent Skills specification](https://agentskills.io/specification).
- Research on natural feedback in conversations (arXiv 2407.10944, 2408.15549) and learning preferences from user
  edits (CIPHER, arXiv 2404.15269).

## License

MIT. See [LICENSE](LICENSE).
