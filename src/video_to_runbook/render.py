"""The Renderer: Jinja over a RunStatus, no model calls."""

from jinja2 import Environment, PackageLoader, select_autoescape

from video_to_runbook.models import RunStatus


def mmss(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60:02d}:{whole % 60:02d}"


_html = Environment(
    loader=PackageLoader("video_to_runbook", "templates"),
    autoescape=select_autoescape(["html"]),
)
_html.filters["mmss"] = mmss


def render_fragment(status: RunStatus) -> str:
    """The right-hand column of the page: state message or the runbook table."""
    return _html.get_template("runbook.html.j2").render(status=status)
