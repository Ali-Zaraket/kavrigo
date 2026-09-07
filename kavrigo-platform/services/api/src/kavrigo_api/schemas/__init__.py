"""Request and response models for the control-plane API.

Kept separate from the database models on purpose: no ORM row is ever serialised directly into
a response (``AGENTS.md`` § API principles). A schema change should be a deliberate contract
change, not a side effect of a column rename.
"""
