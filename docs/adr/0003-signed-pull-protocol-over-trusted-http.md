---
status: accepted
---

# Use a signed pull protocol over trusted-network HTTP

Nodes will continue to initiate every Master interaction and will long-poll for work; Master will not call Nodes. The deployment environment has no TLS, so all Athena endpoints use HTTP and are supported only on an isolated trusted management network. Node requests remain HMAC-authenticated, executable Node Tasks are additionally signed by Master with Ed25519 and protected by audience, time, lease, and replay checks, and artifact bytes are authorized per Node and verified by a signed SHA-256 digest. These controls can prevent direct task forgery only while administrator credentials, Node Tokens, and Master private keys remain secret. HTTP can expose an administrator session that an attacker could use to request a legitimately signed malicious Release, so network isolation is a mandatory security control. Athena deliberately makes no transport-confidentiality claim.
