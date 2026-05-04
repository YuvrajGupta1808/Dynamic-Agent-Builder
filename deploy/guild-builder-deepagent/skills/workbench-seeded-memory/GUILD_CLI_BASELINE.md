## Guild CLI baseline
Use this file as the default command memory for common Guild workflows.

Common per-agent flow:
1. `guild auth status`
2. create or enter `agents/<agent-name>/`
3. `guild agent init --name <agent-name> --template <template>`
4. edit generated files under `agents/<agent-name>/...` so they match the actual use case
5. `guild agent test --ephemeral`
6. if needed, patch the smallest file and rerun the test
7. `guild agent save`

Common workspace flow after local validation:
1. `guild workspace list`
2. `guild workspace create <workspace-name>` or `guild workspace select <workspace-name-or-id>`
3. `guild workspace current` or `guild workspace get <workspace-name-or-id>` to verify the selected remote workspace
4. `guild workspace agent add <identifier>`
5. `guild workspace agent list`
6. optional shared context flow with `guild workspace context list/get/edit/publish`
7. optional live validation with `guild workspace current` or `guild workspace get <workspace-name-or-id>` to confirm the identifier, then `guild chat --workspace <workspace-id-or-full-name> --once "<prompt>"` plus `guild session list/get/events/tasks/send`

Do not rediscover these with repeated `guild --help` unless the task depends on an uncommon command or exact CLI edge case.
