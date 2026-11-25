# Getting the chat history export

Walk the user through the export for the AI they use most. More sessions give more rules: aim for at least 50
conversations with two or more user turns; a few hundred is better. Exports from several sources can be combined
in one workspace (put them all in `<workspace>/data/raw/` and run `capsule ingest` with no path).

Menu names change between app versions; if the user cannot find an item, ask what they see and adapt.

## ChatGPT

1. chatgpt.com: profile menu > Settings > Data controls > Export data > Export (confirm).
2. An email arrives with a download link (it can take minutes to hours; the link expires after about a day).
3. Download the `.zip`. No need to unzip: `capsule ingest "<path to the zip>"`.

The zip contains `conversations.json` (if there are several `conversations*.json` files, the CLI reads them all)
plus files the CLI ignores, such as `chat.html` and `user.json`.

## Claude

1. claude.ai: Settings > Privacy > Export data.
2. Download the `.zip` from the email, then `capsule ingest "<path to the zip>"`.

## Gemini and other chat tools

There is no export that keeps both sides of each conversation in a form the CLI reads, so copy conversations into
text files:

```
=== Title of conversation 1 ===
User: first message
Gemini: answer
User: follow-up, correction, ...
Gemini: ...

=== Title of conversation 2 ===
...
```

Each turn starts at the beginning of a line with `User:` (or `You:`, `Bạn:`, `Tôi:`) or `Gemini:` (or `Model:`,
`AI:`, `Assistant:`, `ChatGPT:`, `Claude:`). Save as `.txt` or `.md` in `<workspace>/data/raw/`. Pick conversations
where the user pushed back, corrected or refined the AI's answer: those carry the signal.

## What happens to the data

`capsule ingest` masks API keys, passwords, emails and phone numbers with regex before anything reaches a model,
and writes the normalized sessions to `<workspace>/data/interim/`. Everything stays in the workspace. In `agent`
mode the model requests are answered by subagents of the user's own Claude Code session; with an API mode they go
to that provider; with `ollama` they stay on the machine.
