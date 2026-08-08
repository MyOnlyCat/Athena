---
status: accepted
---

# Use a single Master with a local Build Worker and Artifact Store

Athena will remain a permanently single-Master system. The Master deployment contains a separate API process and local Build Worker process, while artifacts and logs remain on Master-managed local storage. This keeps deployment and operations simple and lets builds use administrator-managed host caches; it deliberately rejects a registered Runner pool, object storage, multi-Master operation, and high availability. The API process never receives Docker access, and production builds are restricted to trusted internal code because containers on the Master host are not a hostile-code security boundary.
