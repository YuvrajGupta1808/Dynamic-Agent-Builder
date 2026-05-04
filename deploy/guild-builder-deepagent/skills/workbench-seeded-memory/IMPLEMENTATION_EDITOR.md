## Implementation editor memory
When adapting Guild project files:
- tailor every artifact to the actual user use case
- replace placeholders with concrete domain details
- do not leave generic PROMPT, CONTEXT, or WORKFLOW content after the user has already described the product
- prefer small diffs that make the scaffold usable immediately
- if a template produces boilerplate, rewrite the relevant parts rather than preserving them for later
- keep assumptions explicit and minimal
- do not manually scaffold files outside `agents/<agent-name>/...`

For agent code and prompts:
- match the chosen Guild template
- reflect the actual task boundaries, inputs, outputs, and escalation behavior
- avoid writing "template" or "example" style content unless the user explicitly asked for a stub
