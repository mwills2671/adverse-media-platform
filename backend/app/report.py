"""PDF case report (ReportLab). Contains only what the screening record holds: no new research happens here."""
import io
import os
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT, BOLD = "Helvetica", "Helvetica-Bold"
for d in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu"):
    if os.path.exists(f"{d}/DejaVuSans.ttf"):
        try:
            pdfmetrics.registerFont(TTFont("DejaVu", f"{d}/DejaVuSans.ttf"))
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", f"{d}/DejaVuSans-Bold.ttf"))
            FONT, BOLD = "DejaVu", "DejaVu-Bold"
        except Exception:
            pass
        break

STATUS_COLOUR = {"GREEN": colors.HexColor("#15803d"), "AMBER": colors.HexColor("#b45309"),
                 "RED": colors.HexColor("#b91c1c"), "FAILED": colors.HexColor("#4b5563")}
ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName=BOLD, fontSize=16, spaceAfter=6)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName=BOLD, fontSize=12, spaceBefore=10, spaceAfter=4)
H3 = ParagraphStyle("h3", parent=ss["Heading3"], fontName=BOLD, fontSize=9.5, spaceBefore=6, spaceAfter=2)
B = ParagraphStyle("b", parent=ss["BodyText"], fontName=FONT, fontSize=8.5, leading=11, alignment=TA_LEFT)
S = ParagraphStyle("s", parent=B, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#374151"))
Q = ParagraphStyle("q", parent=S, leftIndent=8, textColor=colors.HexColor("#1f2937"), fontName=FONT)


def p(t, st=B, raw=False):
    t = str(t if t is not None else "—")
    return Paragraph(t if raw else escape(t).replace("\n", "<br/>"), st)


def _tbl(rows, widths, head=True):
    t = Table(rows, colWidths=widths, repeatRows=1 if head else 0)
    style = [("FONT", (0, 0), (-1, -1), FONT, 7.5), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
             ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    if head:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")), ("FONT", (0, 0), (-1, 0), BOLD, 7.5)]
    t.setStyle(TableStyle(style))
    return t


def _finding(f: dict) -> list:
    cat = ", ".join(c["label"] for c in f.get("categories") or []) or "No adverse category detected"
    head = f"#{f['rank'] + 1}  {f['title']}"
    meta = (f"{f.get('source_name') or f.get('domain') or ''} · {f.get('published_at') or 'date unknown'} · "
            f"Tier {f['credibility_tier']} ({f.get('credibility_note') or ''}) · via {', '.join(f.get('providers') or [f['provider']])}")
    rows = [["Category", p(cat, S)], ["Event status", p(f["event_status"].replace("_", " "), S)],
            ["Implication", p(f"{f['implication'].replace('_', ' ')} — {f.get('implication_note') or ''}", S)],
            ["Identity", p(f"{f['identity_level']} ({f['identity_points']} pts). " +
                           "; ".join(e["detail"] for e in f.get("identity_evidence") or [] if e.get("type") == "_summary"), S)],
            ["Evidence", p("; ".join(f"{e['detail']} ({e['points']:+d})" for e in f.get("identity_evidence") or []
                                     if e.get("type") != "_summary") or "—", S)],
            ["Contradictions", p("; ".join(c["detail"] for c in f.get("contradictions") or []) or "None found", S)],
            ["Text basis", p(f"{f['text_source']}{' — ' + f['fetch_note'] if f.get('fetch_note') else ''}", S)],
            ["Corroboration", p(f"{f['independent_sources']} independent source(s)" +
                                ("; also: " + "; ".join(c.get("source") or c.get("domain") or "" for c in f["corroborating"][:6])
                                 if f.get("corroborating") else ""), S)],
            ["Rule trace", p("<br/>".join(("[PASS] " if r.get("ok") else "[fail] ") + escape(r.get("rule", "")) for r in (f.get("material_reasons") or []) if isinstance(r, dict)) or "—", S, raw=True)]]
    if f.get("decision"):
        rows.append(["Analyst decision", p(f"{f['decision'].replace('_', ' ')} by {f['decided_by']} — {f.get('decision_reason') or ''}", S)])
    if f.get("escalated"):
        rows.append(["Escalated", p("Yes", S)])
    if f.get("notes"):
        rows.append(["Notes", p(f["notes"], S)])
    out = [p(head, H3), p(meta, S), p(f["url"], S), Spacer(1, 2), _tbl(rows, [28 * mm, 147 * mm], head=False)]
    for qt in (f.get("quotes") or [])[:3]:
        out.append(p(f"“{qt['text']}”", Q))
    out.append(Spacer(1, 5))
    return [KeepTogether(out[:5])] + out[5:]


def build_pdf(s: dict, exported_by: str) -> bytes:
    buf = io.BytesIO()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def footer(c, d):
        c.saveState()
        c.setFont(FONT, 7)
        c.setFillColor(colors.HexColor("#6b7280"))
        c.drawString(15 * mm, 10 * mm, f"{s['id']} · CONFIDENTIAL — financial crime compliance · exported {ts} by {exported_by}")
        c.drawRightString(195 * mm, 10 * mm, f"Page {d.page}")
        c.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=17 * mm,
                            title=f"Adverse media screening {s['id']}", author="Adverse Media Screening Platform")
    st = s.get("final_status") or s.get("auto_status") or "—"
    el = [p("Adverse Media Screening Report", H1)]
    badge = Table([[p(f"<b>{st}</b>", ParagraphStyle('x', parent=B, textColor=colors.white, fontName=BOLD, fontSize=12), raw=True)]],
                  colWidths=[30 * mm])
    badge.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), STATUS_COLOUR.get(st, colors.grey)), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    ids = s.get("identifiers") or {}
    info = [["Screening ID", s["id"]], ["Subject", f"{s['subject_name']} ({s['subject_type']})"],
            ["Identifiers supplied", "; ".join(f"{k.replace('_', ' ')}: {', '.join(v) if isinstance(v, list) else v}" for k, v in ids.items()) or "None"],
            ["Screened", f"{s.get('created_at', '')[:19].replace('T', ' ')} UTC by {s['created_by']}"],
            ["Automated status", s.get("auto_status") or "—"],
            ["Final status", st + (f" (override by {s['override_by']}: {s['override_reason']})" if s.get("override_status") else "")],
            ["Analysis mode", s.get("analysis_mode")], ["Case state", f"{s['review_state']}" + (f" — {s['disposition']} by {s['reviewed_by']}" if s.get("disposition") else "")],
            ["Result hash (SHA-256)", s.get("result_hash") or "—"]]
    if s.get("test_mode"):
        info.insert(0, ["TEST MODE", "This screening used labelled test fixtures / fault injection. Not a real screening."])
    el += [badge, Spacer(1, 4), _tbl([[p(a, S), p(b, S)] for a, b in info], [38 * mm, 137 * mm], head=False)]
    cov = s.get("coverage") or {}
    if cov.get("incomplete") or st == "FAILED":
        el += [Spacer(1, 4), p("<b>INCOMPLETE RESEARCH:</b> " + escape("; ".join(cov.get("notes") or [])) +
                               " — this result must not be treated as clear.", ParagraphStyle("w", parent=B, textColor=colors.HexColor("#b45309")), raw=True)]
    el += [p("Reasons", H2)] + [p("• " + r) for r in s.get("auto_reasons") or []]
    el += [p("Narrative", H2), p(s.get("narrative") or "—")]
    if s.get("analyst_notes"):
        el += [p("Analyst notes", H2), p(s["analyst_notes"])]
    el += [p("Source coverage", H2)]
    rows = [["Provider", "Kind", "Status", "Results", "Notes"]]
    for r in s.get("provider_runs") or []:
        rows.append([p(r.get("name"), S), p(r.get("kind", ""), S), p(r.get("status"), S), p(r.get("results", 0), S),
                     p(r.get("error") or r.get("coverage_note") or "", S)])
    el.append(_tbl(rows, [36 * mm, 24 * mm, 22 * mm, 13 * mm, 80 * mm]))
    m = s.get("metrics") or {}
    el.append(p(f"Raw results {m.get('raw_results', 0)} → {m.get('clusters', 0)} de-duplicated stories; article text retrieved "
                f"{m.get('fetched_ok', 0)}/{m.get('fetch_attempted', 0)}. Queries: " + "; ".join(f"[{q.get('provider')}] {q.get('query')}" if isinstance(q, dict) else str(q) for q in s.get("queries") or [])[:1500], S))
    fs = s.get("findings") or []
    groups = [("Requires review", [f for f in fs if f["bucket"] == "review"]),
              ("Mitigating / exculpatory", [f for f in fs if f["bucket"] == "mitigating"])]
    for title, lst in groups:
        el += [PageBreak() if title == "Requires review" else Spacer(1, 6), p(f"{title} ({len(lst)})", H2)]
        if not lst:
            el.append(p("None."))
        for f in lst[:60]:
            el += _finding(f)
        if len(lst) > 60:
            el.append(p(f"… {len(lst) - 60} further item(s) are available in the application.", S))
    low = [f for f in fs if f["bucket"] == "low"]
    el += [p(f"Low relevance / not adverse ({len(low)})", H2)]
    if low:
        rows = [["#", "Title", "Source", "Identity", "Why low"]]
        for f in low[:80]:
            rows.append([p(f["rank"] + 1, S), p(f["title"][:160], S), p(f.get("source_name") or f.get("domain"), S),
                         p(f["identity_level"], S), p("; ".join(f.get("relevance_reasons") or [])[:200], S)])
        el.append(_tbl(rows, [8 * mm, 78 * mm, 30 * mm, 18 * mm, 41 * mm]))
    lo = cov.get("link_outs") or {}
    el += [p("Manual checks — link-outs (not machine-searched)", H2)]
    for l in lo.get("adverse_media_manual", []):
        el.append(p(f"• {l['name']}: {l['url']} — {l['note']}", S))
    el += [p("Sanctions / PEP reference (separate module — NOT adverse media, NOT screened here)", H3)]
    for l in lo.get("sanctions_pep_reference", []):
        el.append(p(f"• {l['name']}: {l['url']} — {l['note']}", S))
    el += [p("Method and limitations", H2), p(
        "Searches use free public news indexes and official sources listed above; keyed sources are only searched when configured. "
        "Article text is retrieved only where robots.txt permits and the page is freely accessible; paywalled or restricted pages "
        "are never bypassed and are analysed from the headline/snippet only. Identity is assessed with an explainable points "
        "model; a name-only match can never exceed 'Possible'. GREEN means no relevant adverse media was found in the sources "
        "actually searched — it is not proof of absence. This report supports, and does not replace, analyst judgement.", S)]
    doc.build(el, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
