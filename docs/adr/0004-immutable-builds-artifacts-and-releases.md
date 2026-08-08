---
status: accepted
---

# Model builds, artifacts, and releases as immutable records

A Build Run binds one configuration snapshot and Source Snapshot, an Artifact is immutable content, and a Release binds one Artifact to an immutable release and target snapshot. Configuration edits only affect later runs; a retry creates a new Release Attempt, and a rollback creates a new Release using a historical Artifact. This costs more records and explicit transitions, but preserves approval meaning, prevents moving branches or configuration edits from changing queued work, and makes every remote side effect auditable.
