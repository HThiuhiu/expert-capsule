# Step 7: reviewing rules with the user

The build produces rules of the form "When X, do Y, because Z", each backed by at least two quotes from two
sessions, plus conflict questions where the user once demanded opposite things. The user reviews them; you relay.
Never invent, merge or reword rules on your own: every change comes from the user.

## 1. Show what is pending

`capsule review --show` prints, for each rule not yet reviewed: its code (`KT-03` for a domain rule, `R01` for the
shared core), domain, the rule, its scope and exceptions, and two evidence quotes with dates. At the end it lists
unanswered conflict questions as `M1`, `M2`, ...

Present the rules in small groups (one domain at a time, at most about 8 rules per message). For each rule give the
code, the rule in the user's language, and how many events support it. Offer the evidence quotes when the user
wants to see why a rule exists (`capsule review --show KT-03` prints just that rule).

Ask for decisions in one reply per group, for example: "Reply `ok` to keep all, or list codes to delete, and
rewrites like `KT-04: <new wording>`." A plain "ok" means keep every rule in the group.

## 2. Record decisions

| User wants | Command |
|---|---|
| Keep these | `capsule review --keep KT-01 KT-02` |
| Keep everything still pending | `capsule review --keep-rest` |
| Delete (the same evidence will not produce the rule again) | `capsule review --delete KT-03` |
| Reword | `capsule review --edit KT-04 --do "<new action>"` (also `--when`, `--because`) |
| Narrow where it applies | `capsule review --edit KT-05 --scope "<scope>" --exceptions "<exceptions>"` |
| Answer a conflict | `capsule review --answer M1 "<answer>"` (repeat `--answer` for several) |

One command can combine several flags. Unknown codes are rejected before anything is written. A rule's wording in
the capsule is "When ..., do ..., because ...": keep edits in that shape and in the user's words.

## 3. Conflicts

Ask each conflict question as written (translated if needed). These usually reveal a context switch ("in reports I
want X, in quick chats Y"). Answers only take effect after a rebuild: ask whether to rebuild now
(`capsule build --domains <same domains>`; in agent mode this is one more round of subagents) or package as is.

## 4. Next

When `capsule status` shows step 7 done, run `capsule package`. If the user deleted rules or answered conflicts
and chose to rebuild, rebuild first; already reviewed rules keep their codes and decisions.
