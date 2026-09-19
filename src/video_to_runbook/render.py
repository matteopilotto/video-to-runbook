"""The Renderer: Jinja over a RunStatus, no model calls."""

from jinja2 import Environment, PackageLoader, select_autoescape

from video_to_runbook.models import RunStatus


def mmss(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60:02d}:{whole % 60:02d}"


def cell(text: str) -> str:
    """Keep a value on one line and inside its Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


_html = Environment(
    loader=PackageLoader("video_to_runbook", "templates"),
    autoescape=select_autoescape(["html", "html.j2"]),
)
_html.filters["mmss"] = mmss

_markdown = Environment(loader=PackageLoader("video_to_runbook", "templates"), autoescape=False)
_markdown.filters["mmss"] = mmss
_markdown.filters["cell"] = cell


def render_fragment(status: RunStatus) -> str:
    """The right-hand column of the page: state message or the runbook table."""
    return _html.get_template("runbook.html.j2").render(status=status)


def render_markdown(status: RunStatus) -> str:
    """The export: the same status as a Markdown document with each step's check status."""
    if status.runbook is None:
        raise ValueError("no runbook yet")
    return _markdown.get_template("runbook.md.j2").render(status=status, runbook=status.runbook)
