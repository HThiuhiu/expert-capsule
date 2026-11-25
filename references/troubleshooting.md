# Troubleshooting

Start with `capsule status`: it reads the workspace and prints the next command, including after an interruption.

| Symptom | Fix |
|---|---|
| `python` not found, or a version below 3.11 | Try `python3` or `py -3` (Windows). Install Python 3.11+ if needed |
| `Thiếu PyYAML` | `python -m pip install pyyaml` |
| `Thiếu thư viện anthropic` | API mode needs `python -m pip install anthropic`; `agent` mode does not |
| Exit 1, `mọi lệnh gọi model đều lỗi` | The message lists fixes. Usually a missing or invalid `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`, Ollama not running (`ollama serve`, then `ollama pull <model>`), or an OpenAI model name the account does not have. Nothing was saved; fix and rerun |
| `0 phiên` after ingest | Wrong file. Point `capsule ingest` at the export `.zip` itself (or `conversations.json`), not `chat.html`. Text files need `User:` / `Gemini:` turn markers (see export-guide.md) |
| Few domains, or every domain marked thin | Not enough sessions per domain (15 needed). Distill the biggest ones, combine sources, or define a custom domain that cuts across fields |
| `Không có lĩnh vực: ...` | Use the slugs from `capsule domains`, comma separated without spaces |
| Exit 3 again and again | Normal: each build round queues new requests. If the same requests keep coming back, check that subagents wrote the answers file named in each bundle header, then `capsule queue import` |
| Few or no rules after build | Rules need 2 events from 2 sessions. Add history or raise `--turns` (the design range is 200 to 400). Standards seen in one session only are counted as candidates in the report and become rules once more evidence arrives |
| Quick check: capsule loses | Report it as is: 15 items, same model family as the judge, noisy. Use the taste test (`capsule demo --blind`) for the user's own judgement |
| Garbled Vietnamese in a Windows console | Cosmetic. Set `PYTHONUTF8=1`, or read the reports in `<workspace>/reports/` |
| Start over | Delete the workspace folder. Nothing else is stored elsewhere, except an installed capsule in the skills folder |
