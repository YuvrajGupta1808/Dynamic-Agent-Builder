# Official Docs Fetch Checklist

## Fetch method

Use the shell via `execute` to fetch the Guild docs because the official docs are not stored locally by default.
Do not use `quick_search` or broad web search for Guild docs discovery.

Examples:
- `curl -fsSL https://docs.guild.ai/llms.txt`
- `curl -fsSL https://docs.guild.ai/cli/commands.md`

## Always fetch docs before

- running uncommon Guild CLI commands
- generating non-LLM Guild agent code
- integration work
- workspace context publishing
- trigger creation or update
- custom integration design
- troubleshooting CLI/auth/versioning edge cases

## Selection rule

- Start with the index
- Pick only the 2-4 most relevant pages
- Prefer specific reference/how-to pages over broad overviews

## Materialization rule

- Do not mirror the docs into the workspace by default
- Create a local reference note only if the task is long-running or the same rules will be reused repeatedly
