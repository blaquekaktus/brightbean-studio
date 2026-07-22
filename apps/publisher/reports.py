"""White-label publishing reports for a workspace.

Aggregates a workspace's published activity over a date range and renders it as
a self-contained, print-ready HTML report themed with the workspace's own brand
colours — a white-label client deliverable an SMB can hand to their own client.

No PDF dependency: the HTML carries ``@page`` rules so any browser prints it to
PDF. Two layers, mirroring the ecosystem's deck generators:

- ``build_report_data`` — aggregates the ORM into a plain dict (no HTML).
- ``render_report_html`` — pure, deterministic HTML from that dict + workspace.
"""

from __future__ import annotations

from html import escape

from django.db.models import Count

# Brand fallbacks when a workspace hasn't set its white-label colours.
_FALLBACK_PRIMARY = "#1F2937"
_FALLBACK_SECONDARY = "#6366F1"


def build_report_data(workspace, start, end) -> dict:
    """Aggregate a workspace's published posts in ``[start, end)``.

    Args:
        workspace: The Workspace instance to report on.
        start: Timezone-aware datetime, inclusive lower bound.
        end: Timezone-aware datetime, exclusive upper bound.

    Returns:
        A plain dict (JSON-safe except datetimes) describing published activity.
    """
    from apps.composer.models import PlatformPost, Post

    published = PlatformPost.Status.PUBLISHED
    platform_posts = PlatformPost.objects.filter(
        post__workspace=workspace,
        status=published,
        published_at__gte=start,
        published_at__lt=end,
    )

    by_platform = [
        {"platform": row["social_account__platform"] or "unknown", "count": row["count"]}
        for row in platform_posts.values("social_account__platform")
        .annotate(count=Count("id"))
        .order_by("-count", "social_account__platform")
    ]
    total_platform_posts = sum(row["count"] for row in by_platform)

    post_ids = list(platform_posts.values_list("post_id", flat=True).distinct())
    posts = []
    for post in Post.objects.filter(id__in=post_ids).prefetch_related("platform_posts__social_account"):
        pub = [pp for pp in post.platform_posts.all() if pp.status == published]
        when = post.published_at or max((pp.published_at for pp in pub if pp.published_at), default=None)
        platforms = sorted({pp.social_account.platform for pp in pub})
        posts.append(
            {
                "title": (post.title or post.caption or "(untitled)").strip()[:80],
                "published_at": when,
                "platforms": platforms,
            }
        )
    # Newest first; posts without a date sort last (deterministic tiebreak on title).
    posts.sort(key=lambda p: (p["published_at"] is not None, p["published_at"], p["title"]), reverse=True)

    return {
        "workspace_name": workspace.name,
        "start": start,
        "end": end,
        "total_platform_posts": total_platform_posts,
        "total_posts": len(posts),
        "by_platform": by_platform,
        "posts": posts,
    }


def _fmt_date(value) -> str:
    return value.date().isoformat() if value is not None else "—"


def render_report_html(report: dict, workspace) -> str:
    """Render a report dict to a self-contained, print-ready white-label HTML page.

    Pure and deterministic given ``report`` and the workspace's brand fields.
    """
    primary = (getattr(workspace, "primary_color", "") or "").strip() or _FALLBACK_PRIMARY
    secondary = (getattr(workspace, "secondary_color", "") or "").strip() or _FALLBACK_SECONDARY
    name = escape(report.get("workspace_name") or workspace.name or "Workspace")
    period = f"{_fmt_date(report.get('start'))} → {_fmt_date(report.get('end'))}"

    max_count = max((row["count"] for row in report.get("by_platform", [])), default=0)
    platform_rows = ""
    for row in report.get("by_platform", []):
        pct = round(100 * row["count"] / max_count) if max_count else 0
        platform_rows += (
            f'<div class="bar-row"><span class="bar-label">{escape(str(row["platform"]))}</span>'
            f'<span class="bar-track"><span class="bar-fill" style="width:{pct}%"></span></span>'
            f'<span class="bar-count">{row["count"]}</span></div>\n'
        )
    if not platform_rows:
        platform_rows = '<p class="empty">No posts published in this period.</p>'

    post_rows = ""
    for post in report.get("posts", []):
        platforms = escape(", ".join(post["platforms"])) or "—"
        post_rows += (
            f"<tr><td>{escape(post['title'])}</td>"
            f'<td class="nowrap">{_fmt_date(post["published_at"])}</td>'
            f"<td>{platforms}</td></tr>\n"
        )
    if not post_rows:
        post_rows = '<tr><td colspan="3" class="empty">No published posts.</td></tr>'

    css = f"""
*{{margin:0;padding:0;box-sizing:border-box;}}
@page{{size:A4;margin:18mm 16mm;}}
body{{font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#111827;
  font-size:14px;line-height:1.5;}}
.header{{border-top:6px solid {primary};padding-top:20px;margin-bottom:28px;}}
.brand{{font-size:24px;font-weight:700;color:{primary};letter-spacing:-.01em;}}
.sub{{color:#6B7280;font-size:13px;margin-top:2px;}}
.headline{{display:flex;align-items:baseline;gap:12px;margin:24px 0 8px;}}
.headline .n{{font-size:56px;font-weight:800;color:{primary};line-height:1;}}
.headline .l{{font-size:15px;color:#374151;}}
h2{{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#6B7280;
  margin:28px 0 12px;border-bottom:1px solid #E5E7EB;padding-bottom:6px;}}
.bar-row{{display:flex;align-items:center;gap:12px;margin:8px 0;}}
.bar-label{{width:120px;text-transform:capitalize;font-weight:600;}}
.bar-track{{flex:1;height:14px;background:#F3F4F6;border-radius:7px;overflow:hidden;}}
.bar-fill{{display:block;height:100%;background:{secondary};border-radius:7px;}}
.bar-count{{width:40px;text-align:right;font-variant-numeric:tabular-nums;color:#374151;}}
table{{width:100%;border-collapse:collapse;font-size:13px;}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #F3F4F6;vertical-align:top;}}
th{{color:#6B7280;font-size:11px;text-transform:uppercase;letter-spacing:.06em;}}
td.nowrap{{white-space:nowrap;color:#374151;}}
.empty{{color:#9CA3AF;font-style:italic;}}
.footer{{margin-top:36px;padding-top:12px;border-top:1px solid #E5E7EB;color:#9CA3AF;font-size:11px;}}
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{name} — Publishing Report</title>
<style>{css}</style>
</head>
<body>
<div class="header">
  <div class="brand">{name}</div>
  <div class="sub">Publishing report · {escape(period)}</div>
</div>

<div class="headline">
  <span class="n">{report.get("total_posts", 0)}</span>
  <span class="l">posts published across {report.get("total_platform_posts", 0)} platform destinations</span>
</div>

<h2>By platform</h2>
{platform_rows}

<h2>Published posts</h2>
<table>
  <thead><tr><th>Post</th><th>Published</th><th>Platforms</th></tr></thead>
  <tbody>
{post_rows}
  </tbody>
</table>

<div class="footer">Generated by brightbean-studio · {escape(period)}</div>
</body>
</html>
"""


def generate_report(workspace, start, end) -> str:
    """Convenience: build + render a workspace report as HTML."""
    return render_report_html(build_report_data(workspace, start, end), workspace)
