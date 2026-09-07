"""Data access.

Every method here scopes by ``workspace_id`` explicitly even though row-level security would
also enforce it. The redundancy is deliberate: RLS is the safety net, not the plan, and an
explicit predicate keeps the intent visible in review and the query plan sane.
"""
