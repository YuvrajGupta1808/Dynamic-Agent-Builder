# Template Selection Matrix

## Use `LLM`
- conversational or prompt-driven
- tool choice matters more than deterministic control flow

## Use `AUTO_MANAGED_STATE`
- procedural and sequential
- typed schemas and resumability matter
- no parallel tool rounds

## Use `BLANK`
- explicit lifecycle/state control needed
- parallel tool calls matter
- auto-managed compiler constraints are a bad fit
