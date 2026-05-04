# Failure Playbook

1. Capture the failed command exactly
2. Summarize the failure in chat unless the user explicitly asked for a file
3. Identify the smallest relevant file to change
4. Patch that file
5. Rerun the narrowest command that proves the fix
6. Keep validation notes concise and operator-readable
