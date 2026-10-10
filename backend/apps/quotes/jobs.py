from apps.core.jobs import periodic

from .services import expire_due


@periodic("quotes.expire")
def expire_quotations():
    """Quotations past their validity date become expired (the customer is told)."""
    return f"{expire_due()} expired"
