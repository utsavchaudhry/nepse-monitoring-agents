"""
Minimal read-only dashboard for the news cache.

Run:
    python dashboard/app.py
Then open http://localhost:8050

No live-push needed -- data only changes 4-5x/day via the pipeline, so a
manual/interval refresh is plenty.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dash import Dash, html, dcc, Input, Output
import db

app = Dash(__name__)
app.title = "NEPSE News Feed"

app.layout = html.Div([
    html.H2("NEPSE Company News (last 7 days)"),
    dcc.Interval(id="refresh", interval=5 * 60 * 1000),  # refresh every 5 min
    html.Div(id="feed"),
], style={"maxWidth": "900px", "margin": "0 auto", "fontFamily": "sans-serif", "padding": "20px"})


def render_feed():
    grouped = db.get_news_grouped_by_symbol()
    if not grouped:
        return html.P("No news matched yet. Run pipeline.py first.")

    blocks = []
    for symbol, items in sorted(grouped.items()):
        cards = []
        for item in items[:10]:  # cap per-symbol display
            cards.append(html.Div([
                html.A(item["title"], href=item["url"], target="_blank",
                       style={"fontWeight": "bold", "textDecoration": "none"}),
                html.Div(f"{item['source_site']} · {item['scraped_at']}",
                          style={"fontSize": "12px", "color": "#777"}),
                html.Div(item["summary"] or "", style={"fontSize": "13px", "marginTop": "4px"}),
            ], style={"padding": "10px 0", "borderBottom": "1px solid #eee"}))

        blocks.append(html.Div([
            html.H4(symbol),
            html.Div(cards),
        ], style={"marginBottom": "24px"}))

    return blocks


@app.callback(Output("feed", "children"), Input("refresh", "n_intervals"))
def update_feed(_):
    return render_feed()


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=8050)
