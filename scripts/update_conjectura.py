"""Refresh the bilingual profile from Conjectura's public summary (stdlib only)."""
import argparse
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

SOURCE = "https://raw.githubusercontent.com/gustavobernardo1/conjectura/research/research/summary.json"
START = "<!-- conjectura:begin -->"
END = "<!-- conjectura:end -->"
LIMIT = 2_000_000
FIELDS = ("lemmas", "theorems", "counterexamples", "other")
FILES = {"en": "README.md", "pt": "README.pt-BR.md"}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def link_url(value):
    if value is None:
        return None
    require(isinstance(value, str), "Invalid URL type")
    parsed = urlsplit(value)
    require(
        parsed.scheme == "https" and parsed.netloc == "github.com"
        and parsed.path.startswith("/gustavobernardo1/conjectura/")
        and not any(c.isspace() or c in '<>()"\\' for c in value),
        "Unexpected Conjectura URL",
    )
    return value


def count_group(value, keys):
    require(isinstance(value, dict), "Invalid count group")
    for key in (*keys, "total"):
        require(type(value.get(key)) is int and value[key] >= 0, "Invalid count: " + key)
    require(value["total"] == sum(value[k] for k in keys), "Inconsistent count total")
    return value


def record(value, prefix, established=False):
    if value is None:
        return None
    require(isinstance(value, dict), "Invalid record")
    require(isinstance(value.get("id"), str) and re.fullmatch(prefix + r"-\d+", value["id"]), "Invalid record ID")
    require(isinstance(value.get("title"), str) and value["title"].strip(), "Missing record title")
    require("url" in value, "Missing record URL")
    link_url(value["url"])
    status = value.get("status")
    require(isinstance(status, dict) and all(isinstance(status.get(k), str) for k in
            ("mathematical", "formal", "novelty", "external_review")), "Missing record status")
    if established:
        require(status["mathematical"] in ("proved", "disproved")
                and status["novelty"] == "no-prior-resolution-found", "Latest result is not eligible")
    return value


def validate(data):
    require(isinstance(data, dict), "Invalid summary")
    public = data.get("public")
    require(isinstance(public, dict) and type(public.get("schema_version")) is int
            and public["schema_version"] == 1, "Unsupported public summary contract")
    generated = data.get("generated")
    require(isinstance(generated, dict) and isinstance(generated.get("sources"), dict)
            and "revision" in generated and "sources_committed" in generated,
            "Missing source provenance")
    require(generated["revision"] is None or isinstance(generated["revision"], str),
            "Invalid source revision")
    require(generated["sources_committed"] is None or type(generated["sources_committed"]) is bool,
            "Invalid source provenance")
    discoveries = count_group(public.get("established_original_discoveries"), FIELDS)
    count_group(public.get("resolved_conjectures"), ("proved", "disproved"))
    for key in ("active_investigations", "primary_investigation",
                "latest_established_original_discovery", "research_catalogue_url", "reviewed_results_url"):
        require(key in public, "Missing field: " + key)
    active = public["active_investigations"]
    require(isinstance(active, list), "Invalid active investigations")
    for item in active:
        require(record(item, "CJ") is not None, "Null active investigation")
    primary = record(public["primary_investigation"], "CJ")
    require(primary == (active[0] if active else None), "Inconsistent primary investigation")
    latest = record(public["latest_established_original_discovery"], "MD", established=True)
    require((latest is None) == (discoveries["total"] == 0), "Inconsistent latest discovery")
    link_url(public["research_catalogue_url"])
    link_url(public["reviewed_results_url"])
    return public


def markdown(value):
    # No HTML or Markdown injection from upstream titles.
    value = html.escape(" ".join(value.split()), quote=False)
    return re.sub(r"([\\\x60*_{}\[\]()#+.!|~])", r"\\\1", value)


def linked(title, url):
    return "[" + markdown(title) + "](" + url + ")" if url else markdown(title)


def render(public, lang):
    pt = lang == "pt"
    d = public["established_original_discoveries"]
    primary = public["primary_investigation"]
    latest = public["latest_established_original_discovery"]
    current = "—"
    if primary:
        title = primary["title"]
        # Keep the familiar compact label for the initial investigation.
        if primary["id"] == "CJ-0001" and title == "Collins–Shor conjecture on the peak of the distance characteristic polynomial of a tree":
            title = "Conjectura Collins–Shor" if pt else "Collins–Shor conjecture"
        current = linked(title, link_url(primary["url"]))
    last = "—" if latest is None else linked(latest["id"] + " — " + latest["title"], link_url(latest["url"]))
    headers = ("Lemas", "Teoremas", "Contraexemplos", "Outros resultados") if pt else (
        "Lemmas", "Theorems", "Counterexamples", "Other results")
    labels = ("Conjecturas resolvidas", "Em investigação", "Última descoberta") if pt else (
        "Conjectures resolved", "Currently investigating", "Latest discovery")
    catalogue = "Catálogo de pesquisas" if pt else "Research catalogue"
    results = "Resultados revisados" if pt else "Reviewed results"
    links = " · ".join((linked(catalogue, link_url(public["research_catalogue_url"])),
                        linked(results, link_url(public["reviewed_results_url"]))))
    return "\n".join((
        "| " + " | ".join(headers) + " |",
        "| :---: | :---: | :---: | :---: |",
        "| " + " | ".join(str(d[k]) for k in FIELDS) + " |",
        "",
        "**" + labels[0] + ":** " + str(public["resolved_conjectures"]["total"]) + "  ",
        "**" + labels[1] + ":** " + current + "  ",
        "**" + labels[2] + ":** " + last,
        "", links,
    ))


def replace_block(content, block):
    require(content.count(START) == 1 and content.count(END) == 1,
            "Expected exactly one pair of Conjectura markers")
    start = content.index(START) + len(START)
    end = content.index(END)
    require(start < end, "Invalid Conjectura marker order")
    return content[:start] + "\n\n" + block + "\n\n" + content[end:]


def refresh(data, root):
    public = validate(data)
    pending = []
    # Validate and render both files before touching either.
    for lang, filename in FILES.items():
        path = root / filename
        old = path.read_text(encoding="utf-8")
        new = replace_block(old, render(public, lang))
        if new != old:
            pending.append((path, new))
    for path, new in pending:
        path.write_text(new, encoding="utf-8")
    return len(pending)


def load_summary(path=None):
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    request = Request(SOURCE, headers={"User-Agent": "Conjectura-profile-sync/1", "Accept": "application/json"})
    with urlopen(request, timeout=30) as response:
        raw = response.read(LIMIT + 1)
    require(len(raw) <= LIMIT, "Summary exceeds size limit")
    return json.loads(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, help="Optional local JSON for offline tests")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        changed = refresh(load_summary(args.summary), args.root)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print("Profile sync failed; no commit will be made: " + str(exc), file=sys.stderr)
        return 1
    print(f"Updated {changed} README file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
