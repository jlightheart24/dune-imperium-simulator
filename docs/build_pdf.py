"""Build the submission PDF from project-definition.md.

    python3 docs/build_pdf.py                   # project-definition.md
    python3 docs/build_pdf.py vertical-slice    # vertical-slice.md

The PDF cites the current git HEAD as the submitted commit.

Uses only the standard library plus an installed Google Chrome (headless) to print.
Handles the Markdown subset the document uses: headings, paragraphs, tables, fenced code,
bullet/numbered lists, bold, italic, inline code, images, bare links and rules.
"""
import html
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# python3 docs/build_pdf.py [project-definition | vertical-slice]
DOC = sys.argv[1] if len(sys.argv) > 1 else "project-definition"
SRC = os.path.join(HERE, DOC + ".md")
OUT_NAME = "lightheart-jonny-%s.pdf" % DOC
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

CSS = """
@page { size: Letter; margin: 0.8in 0.85in; }
body { font: 10.5pt/1.45 -apple-system, "Helvetica Neue", Arial, sans-serif; color: #1a1a1a; }
h1 { font-size: 20pt; margin: 0 0 4pt; }
h2 { font-size: 14pt; margin: 20pt 0 6pt; padding-bottom: 3pt; border-bottom: 1px solid #bbb;
     break-after: avoid; }
h3 { font-size: 11.5pt; margin: 14pt 0 4pt; break-after: avoid; }
p { margin: 0 0 8pt; }
ul, ol { margin: 0 0 8pt; padding-left: 20pt; }
li { margin-bottom: 3pt; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0 10pt; font-size: 9.5pt;
        break-inside: avoid; }
th, td { border: 1px solid #c8c8c8; padding: 4pt 6pt; text-align: left; vertical-align: top; }
th { background: #f0f0f0; }
thead tr.empty { display: none; }
code { font: 9pt Menlo, Consolas, monospace; background: #f3f3f3; padding: 0 2pt; border-radius: 2pt; }
pre { background: #f6f6f6; border: 1px solid #ddd; border-radius: 3pt; padding: 7pt 9pt;
      font: 7pt/1.35 Menlo, Consolas, monospace; white-space: pre; overflow: hidden;
      break-inside: avoid; margin: 4pt 0 10pt; }
pre code { background: none; padding: 0; font: inherit; }
img { max-width: 100%; border: 1px solid #ccc; margin: 4pt 0; }
hr { border: 0; border-top: 1px solid #bbb; margin: 12pt 0; }
a { color: #1a4f9c; text-decoration: none; }
"""


def inline(text):
    codes = []

    def stash(m):
        codes.append(m.group(1))
        return "\x00%d\x00" % (len(codes) - 1)

    text = re.sub(r"`([^`]+)`", stash, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img alt="\1" src="\2">', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r'(?<!["=])(https?://[^\s<]+[^\s<.,)])', r'<a href="\1">\1</a>', text)
    return re.sub(r"\x00(\d+)\x00", lambda m: "<code>%s</code>" % html.escape(codes[int(m.group(1))]), text)


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def convert(md):
    lines = md.split("\n")
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            j = i + 1
            while not lines[j].startswith("```"):
                j += 1
            out.append("<pre><code>%s</code></pre>" % html.escape("\n".join(lines[i + 1:j])))
            i = j + 1
        elif re.match(r"#{1,3} ", ln):
            n = len(ln) - len(ln.lstrip("#"))
            out.append("<h%d>%s</h%d>" % (n, inline(ln[n + 1:]), n))
            i += 1
        elif ln.strip() == "---":
            out.append("<hr>")
            i += 1
        elif ln.startswith("|") and i + 1 < len(lines) and re.match(r"\|[\s:|-]+\|$", lines[i + 1].strip()):
            head = cells(ln)
            cls = ' class="empty"' if not any(head) else ""
            rows = ["<thead><tr%s>%s</tr></thead><tbody>" % (cls, "".join("<th>%s</th>" % inline(c) for c in head))]
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c) for c in cells(lines[i])))
                i += 1
            out.append("<table>%s</tbody></table>" % "".join(rows))
        elif re.match(r"(- |\d+\. )", ln):
            tag = "ul" if ln.startswith("- ") else "ol"
            items = []
            while i < len(lines) and (re.match(r"(- |\d+\. )", lines[i]) or
                                      (lines[i].startswith("  ") and lines[i].strip())):
                if re.match(r"(- |\d+\. )", lines[i]):
                    items.append(re.sub(r"^(- |\d+\. )", "", lines[i]))
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            out.append("<%s>%s</%s>" % (tag, "".join("<li>%s</li>" % inline(t) for t in items), tag))
        elif not ln.strip() or ln.startswith("<!--"):
            i += 1
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(r"(```|#{1,3} |\||- |\d+\. )", lines[i]):
                para.append(lines[i].strip())
                i += 1
            out.append("<p>%s</p>" % inline(" ".join(para)))
    return "\n".join(out)


def main():
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    md = open(SRC).read().replace("COMMIT_HASH_IN_PDF", "`%s`" % commit)
    page = ("<!doctype html><html lang='en'><head><meta charset='utf-8'><title>%s</title>" % DOC.replace("-", " ").title() +
            "<style>%s</style></head><body>%s</body></html>" % (CSS, convert(md)))
    tmp = os.path.join(HERE, "_project-definition.html")  # next to img/ so the image resolves
    with open(tmp, "w") as fh:
        fh.write(page)
    out = os.path.join(HERE, OUT_NAME)
    try:
        subprocess.check_call([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                               "--print-to-pdf=" + out, "file://" + tmp],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        os.remove(tmp)
    print("wrote %s (submitted commit %s)" % (out, commit))


if __name__ == "__main__":
    sys.exit(main())
