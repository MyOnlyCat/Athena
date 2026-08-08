---
status: accepted
---

# Use PostgreSQL on Master and SQLite on Nodes

Athena-Master will use PostgreSQL as its only supported production database because scheduling, approval, leases, cross-Node state, and event ingestion require reliable concurrent transactions. Athena-Node will keep SQLite so each Node can execute and retain unacknowledged results while disconnected from Master. Existing Master SQLite data will move through an explicit offline migration; Master will not maintain dual-database production compatibility.
