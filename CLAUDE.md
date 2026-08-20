# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Database migrations

Alembic migration files in `migrations/versions/` use sequential, zero-padded
numeric revision IDs and filenames instead of Alembic's default random hash
IDs.

- Start numbering at `0001` and increment by one per migration (`0001`,
  `0002`, `0003`, ...).
- The filename prefix, the `revision` value, and the `Revision ID:` line in
  the docstring must all match (e.g. `0003_add_foo_table.py` has
  `revision: str = "0003"`).
- `down_revision` must point to the previous migration's numeric ID, keeping
  a linear chain.
- When generating a new migration (e.g. via `alembic revision --autogenerate`),
  rename the resulting file and edit its `revision`/`down_revision`/docstring
  to follow this scheme before committing.
