# Agent mode: answering model requests with subagents

In `agent` mode (`capsule init --mode agent`) the CLI never calls an API. Each step that needs a model writes its
requests to `<workspace>/.cache/agent_queue/`, prints `Dừng ở <step>: N yêu cầu chờ subagent` and exits with code 3.

## The loop

1. `capsule queue bundle` groups pending requests into bundle files, never mixing two tags (for example the
   with-capsule and without-capsule systems of the quick check). One line per bundle:
   `<bundle path>  model=<haiku|sonnet>  n=<requests>`. The same list is in `.cache/agent_bundles/index.json`.
2. Start one fresh subagent per bundle, in parallel, with the model from its line:
   - Claude Code with the plugin installed: the `capsule-worker` agent, prompt
     `Answer the Expert Capsule bundle at <absolute bundle path>.`
   - Any other host with subagents: a general-purpose subagent with the prompt below.
3. After all subagents finish: `capsule queue import` loads the answers into the cache.
4. Rerun the command that stopped (`capsule status` shows it). It reads the cached answers and either finishes or
   stops again for the next round. A full build takes several rounds.

If a subagent fails or writes bad lines, do not repair anything by hand: import what exists and rerun the command.
Unanswered requests stay queued and are bundled again; invalid answers are re-asked once with a correction note.

## Prompt for a general-purpose subagent

> Read the file <ABSOLUTE PATH TO THE BUNDLE .md> completely (it is long: use offset/limit until the line
> "=== END OF BUNDLE ===") and follow the instructions in its header exactly. You act as the language model for
> every request in it: for each request, behave as an assistant whose system prompt is the SYSTEM text (or SHARED
> BLOCK) of that request, and answer its USER text. Write all answers, as JSON Lines, to the answers file named in
> the header, with one Write call. The answers file must contain only JSON lines (never the "END OF BUNDLE" line).
> Verbatim quotes must be copied character-for-character. Do not read any other file, do not run code, do not
> modify any other file. When finished, reply only with "done <number of lines written>".

## Models

The model hint comes from `config.local.yaml`: `agent/claude-haiku` gives `model=haiku`, `agent/claude-sonnet`
gives `model=sonnet`. `capsule init --mode agent` uses Haiku for labeling and mining (many cheap calls), Sonnet for
synthesis and the quick-check systems, Haiku for the judge. To spend less, set `strong` to `agent/claude-haiku`;
changing a model invalidates the cached answers of that role only.

## Without subagents (for example Claude.ai)

You can answer the bundles yourself, but your context fills up fast and the quick check is no longer blind (you
have seen the capsule). Only do this for small exports, and tell the user:

1. In `config.local.yaml` set `capsule.quickcheck_n: 0` (skips the quick check) and build with fewer turns:
   `capsule build --domains <a,b> --turns 120`.
2. Make bundles small: `capsule queue bundle --max-chars 30000`.
3. Answer one bundle at a time exactly as the subagent prompt above says, write its answers file, then move on.
   After each round: `capsule queue import` and rerun the command.

Offer the taste test (`capsule demo --blind`) at the end instead of the quick check.
