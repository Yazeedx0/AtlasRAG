from sqlalchemy.exc import IntegrityError


def is_integrity_error_for_constraint(
    *,
    error: IntegrityError,
    constraint_name: str,
) -> bool:
    """Return whether an integrity error was raised for a named constraint."""
    origin = error.orig
    error_constraint_name = getattr(origin, "constraint_name", None)
    if error_constraint_name is None:
        diagnostic = getattr(origin, "diag", None)
        error_constraint_name = getattr(diagnostic, "constraint_name", None)

    if error_constraint_name is not None:
        return error_constraint_name == constraint_name

    return constraint_name in str(origin)
