"""HTML sanitization for previews. Removes scripts, event handlers, unsafe URLs and remote images."""

import nh3

_ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "caption", "center", "code", "div", "em", "font", "h1", "h2", "h3",
    "h4", "h5", "h6", "hr", "i", "li", "ol", "p", "pre", "s", "small", "span", "strong", "sub", "sup",
    "table", "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul",
}  # fmt: skip
_ALLOWED_ATTRS = {
    "a": {"href", "title"},
    "td": {"colspan", "rowspan", "align"},
    "th": {"colspan", "rowspan", "align"},
    "p": {"align"},
    "div": {"align"},
    "font": {"color"},
}


def sanitize_html(html: str) -> str:
    """Return sanitized HTML safe for display inside a sandboxed iframe.

    - no script/style/iframe/object/form/img (remote tracking pixels are dropped entirely)
    - no event handlers or style attributes
    - links limited to http/https/mailto and forced to rel="noopener noreferrer nofollow"
    """
    return nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer nofollow",
        strip_comments=True,
    )
