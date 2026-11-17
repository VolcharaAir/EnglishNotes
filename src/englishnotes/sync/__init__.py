"""Reserved boundary for a future sync adapter. No cloud code runs in this release.

The local application depends only on application.ports. A future sync worker
must use its own database connection, explicit change tracking, server-side
authorization and conflict resolution. See docs/architecture.md.
"""
