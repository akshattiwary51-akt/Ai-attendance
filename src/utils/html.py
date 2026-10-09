"""HTML escaping for the few places we use unsafe_allow_html."""
from html import escape


def esc(value: object) -> str:
    return escape(str(value), quote=True)
