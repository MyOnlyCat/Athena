---
status: accepted
---

# Separate release preparation from side-effect activation

Each Release Batch uses two signed authorization stages. A Prepare directive permits only artifact download, lease-isolated staging, hashing, disk and drift checks; after every target in the batch is ready, Master atomically records and signs a Node-specific Activate envelope containing a separate activation grant for each Target Attempt. This adds an orchestration barrier and per-target checkpoints, but ensures no target can modify its managed path before the whole batch is ready. Once any activation grant may have been delivered, loss of proof produces Unknown Execution rather than automatic retry.
