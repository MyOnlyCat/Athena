---
status: accepted
---

# Use command and Node-exchange entries for Release Orchestration

The Release Orchestration Module exposes two write entries: `decide(CommandContext, ReleaseIntent)` for user and scheduler decisions, and `exchange(AuthenticatedNode, NodeMessage)` for authenticated Node protocol messages. Read operations belong to a separate Release Queries Module. This small Interface hides approval, scheduling, batching, leases, fencing, signing, host reservations, retries, rollback releases, and Unknown Execution. PostgreSQL current-state tables remain authoritative; Node events are an idempotent inbox and audit trail, not an event-sourced state model.
