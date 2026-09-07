"""Render the snapshot into a single self-contained HTML file.

The dashboard ships its data inline so the file works offline and can be opened
straight off disk - no local server, no fetch, no CORS.
"""

import json

from . import config

PLACEHOLDER = "/*__SNAPSHOT__*/ null"

TEMPLATE_PATH = config.ROOT_DIR / "stonk" / "template.html"

# The template is body-only so it can also be published as an Artifact, which
# supplies its own document shell. A file opened from disk gets no such shell, and
# without an explicit charset the browser guesses and mangles the Chinese labels.
DOC_OPEN = (
  '<!doctype html>\n<html lang="zh-CN">\n<head>\n'
  '<meta charset="utf-8">\n'
  '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
)
DOC_MID = "</head>\n<body>\n"
DOC_CLOSE = "\n</body>\n</html>\n"


def _inline_json(payload):
  """Serialise for embedding inside a <script> block.

  Escaping the tag-opening characters keeps API-supplied strings from ending the
  script element early.
  """
  text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
  return text.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _wrap_document(body_only_html):
  """Split the template at </style> so <title>/<link>/<style> land in <head>."""
  head, separator, body = body_only_html.partition("</style>")
  if not separator:
    raise ValueError("template must contain a </style> tag to split on")
  return DOC_OPEN + head + separator + "\n" + DOC_MID + body + DOC_CLOSE


def render(snapshot, template_path=TEMPLATE_PATH, output_path=config.DASHBOARD_PATH, standalone=True):
  """Write the dashboard. standalone=False emits the body-only Artifact form."""
  template = template_path.read_text(encoding="utf-8")
  if PLACEHOLDER not in template:
    raise ValueError(f"snapshot placeholder missing from {template_path}")

  html = template.replace(PLACEHOLDER, _inline_json(snapshot))
  if standalone:
    html = _wrap_document(html)
  output_path.parent.mkdir(parents=True, exist_ok=True)
  output_path.write_text(html, encoding="utf-8")
  return output_path
