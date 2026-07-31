# Warning and Error Taxonomy v0

## Errors

### E_UNSUPPORTED_FIELD
The input field is out of profile for the selected runtime mode.

### E_SECURITY_POLICY
The field or requested action violates security or workspace policy.

## Warnings

### W_PARITY_LOSS
The field was accepted, but its realization for the target runtime is approximate rather than semantically exact.

### W_AGENT_EMULATION
The requested behavior is preserved by the agent/runtime layer rather than by native manifest semantics.

## Informational diagnostics

### I_LOCAL_ONLY
The field or behavior is valid in local mode and intentionally omitted from cluster materialization.

## Consumer guidance

- IDE surfaces should show warnings inline and link to the compiled evidence record.
- CI should fail on `E_*` and may optionally fail on `W_PARITY_LOSS`.
- catalog publication should compile with `strict` unsupported mode.
