# Auto-Managed State Checklist

- Confirm the task is sequential and typed
- Use `"use agent"` when required by the template/runtime pattern
- Define input/output schemas clearly
- Avoid Promise.all / Promise.any / Promise.race style parallel control flow
- Prefer this model only when explicit procedural logic is needed
