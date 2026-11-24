"""Safe, bounded Markdown and WoW command-snippet tokenizer for Tk text views."""

from dataclasses import dataclass
import re
from urllib.parse import urlsplit

MAX_MARKDOWN_CHARS = 100_000

_FENCE_RE = re.compile(r"^```([A-Za-z0-9_+-]*)\s*$")
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)[-*]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^(\s*)(\d+\.)\s+(.*)$")
_INLINE_RE = re.compile(
    r"(`[^`\n]+`)"
    r"|(\[[^\]\n]+\]\(([^)\s]+)\))"
    r"|(\*\*[^*\n]+\*\*)"
    r"|(?<!\w)(\*[^*\n]+\*)(?!\w)"
    r"|(https?://[^\s<>\"']+)"
)
_SLASH_CMD_RE = re.compile(
    r"^/(?:console|dump|run|script|way|jrm|aajs|reload|combatlog|cast|use|macro|target|focus|assist|equip|stopcasting)\b.*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class InlineSpan:
    text: str
    style: str = "plain"   # plain | bold | italic | code | link
    url: str = ""
    copy_text: str = ""


@dataclass(frozen=True)
class Block:
    kind: str              # paragraph | heading | list_item | code_block
    spans: tuple = ()
    text: str = ""         # raw text for code_block
    level: int = 0         # heading level (1-4) or list indent
    prefix: str = ""       # bullet or number prefix
    copy_text: str = ""    # slash command or code block copy payload


def valid_http_url(raw):
    """Validate an http/https URL strictly; reject javascript:, file:, or control chars."""
    if not isinstance(raw, str):
        return ""
    url = raw.strip()
    if not url or len(url) > 4096 or any(ord(c) < 32 or c.isspace() for c in url):
        return ""
    while url and url[-1] in ".,;:!?)]}":
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            break
        url = url[:-1]
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc or "." not in parsed.netloc:
        return ""
    if "@" in parsed.netloc:
        return ""
    return url


def is_wow_command(text):
    value = (text or "").strip()
    return bool(value and "\n" not in value and len(value) <= 500 and _SLASH_CMD_RE.match(value))


def extract_commands(text):
    """Extract unique WoW slash commands and fenced code snippets from assistant text."""
    if not isinstance(text, str) or not text:
        return []
    commands = []
    seen = set()

    def add(value):
        cleaned = value.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            commands.append(cleaned)

    for block in parse_markdown(text):
        if block.kind == "code_block" and block.copy_text:
            for line in block.copy_text.splitlines():
                if is_wow_command(line):
                    add(line)
            if not any(is_wow_command(line) for line in block.copy_text.splitlines()):
                add(block.copy_text)
        else:
            if block.copy_text:
                add(block.copy_text)
            for span in block.spans:
                if span.copy_text:
                    add(span.copy_text)
    return commands


def has_formatting(text):
    """Fast check so plain messages with no Markdown render identically to raw text."""
    if not text or len(text) > MAX_MARKDOWN_CHARS:
        return False
    if any(tok in text for tok in ("**", "`", "```", "http://", "https://", "](")):
        return True
    for line in text.splitlines():
        if _HEADING_RE.match(line) or _BULLET_RE.match(line) or _SLASH_CMD_RE.match(line.strip()):
            return True
    return False


def parse_inline(text):
    spans = []
    pos = 0
    for match in _INLINE_RE.finditer(text):
        if match.start() > pos:
            spans.append(InlineSpan(text[pos:match.start()]))
        code, md_link, md_url, bold, italic, bare_url = match.groups()
        if code:
            inner = code[1:-1]
            spans.append(InlineSpan(inner, "code", copy_text=inner.strip() if is_wow_command(inner) else ""))
        elif md_link:
            label = md_link[1:md_link.index("](")]
            safe = valid_http_url(md_url)
            if safe:
                spans.append(InlineSpan(label, "link", url=safe))
            else:
                spans.append(InlineSpan(md_link))
        elif bold:
            spans.append(InlineSpan(bold[2:-2], "bold"))
        elif italic:
            spans.append(InlineSpan(italic[1:-1], "italic"))
        elif bare_url:
            safe = valid_http_url(bare_url)
            if safe:
                trailing = bare_url[len(safe):]
                spans.append(InlineSpan(safe, "link", url=safe))
                if trailing:
                    spans.append(InlineSpan(trailing))
            else:
                spans.append(InlineSpan(bare_url))
        pos = match.end()
    if pos < len(text):
        spans.append(InlineSpan(text[pos:]))
    return tuple(spans)


def parse_markdown(text):
    """Parse bounded Markdown text into a flat tuple of renderable Blocks."""
    if not isinstance(text, str):
        return ()
    body = text.strip("\n")
    if not body:
        return ()
    if len(body) > MAX_MARKDOWN_CHARS or not has_formatting(body):
        return (Block("paragraph", spans=(InlineSpan(body),)),)

    blocks = []
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if _FENCE_RE.match(line):
            code_lines = []
            i += 1
            while i < len(lines) and not _FENCE_RE.match(lines[i]):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            raw_code = "\n".join(code_lines)
            blocks.append(Block("code_block", text=raw_code, copy_text=raw_code.strip()))
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            blocks.append(Block("heading", spans=parse_inline(heading.group(2).strip()),
                                level=len(heading.group(1))))
            i += 1
            continue
        bullet = _BULLET_RE.match(line)
        if bullet:
            indent = min(4, len(bullet.group(1)) // 2)
            content = bullet.group(2)
            copy = content.strip() if is_wow_command(content) else ""
            blocks.append(Block("list_item", spans=parse_inline(content), level=indent,
                                prefix="  " * indent + "• ", copy_text=copy))
            i += 1
            continue
        numbered = _NUMBERED_RE.match(line)
        if numbered:
            indent = min(4, len(numbered.group(1)) // 2)
            content = numbered.group(3)
            copy = content.strip() if is_wow_command(content) else ""
            blocks.append(Block("list_item", spans=parse_inline(content), level=indent,
                                prefix="  " * indent + numbered.group(2) + " ", copy_text=copy))
            i += 1
            continue
        stripped = line.strip()
        if not stripped:
            blocks.append(Block("paragraph", spans=(InlineSpan(""),)))
            i += 1
            continue
        copy = stripped if is_wow_command(stripped) else ""
        blocks.append(Block("paragraph", spans=parse_inline(line), copy_text=copy))
        i += 1
    return tuple(blocks)
