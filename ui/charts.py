from typing import Any, Dict, List
import altair as alt
import pandas as pd
import streamlit as st


def render_debt_chart(data: List[Dict[str, Any]]) -> None:
    # render a bar chart showing passes owed per member in dark mode
    if not data:
        return

    df = pd.DataFrame(data)
    chart = (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, color="#38BDF8")
        .encode(
            x=alt.X(
                "passes_owed:Q",
                title="Passes Owed",
                axis=alt.Axis(
                    tickMinStep=1,
                    grid=True,
                    gridColor="#334155",
                    labelColor="#94A3B8",
                    titleColor="#94A3B8",
                ),
            ),
            y=alt.Y(
                "member:N",
                title=None,
                sort="-x",
                axis=alt.Axis(
                    labelLimit=180,
                    labelColor="#F8FAFC",
                ),
            ),
            tooltip=[
                alt.Tooltip("member:N", title="Member"),
                alt.Tooltip("passes_owed:Q", title="Passes Owed"),
            ],
        )
        .properties(height=max(160, len(df) * 32))
        .configure_view(strokeWidth=0, fill="transparent")
        .configure_axis(
            labelFont="Inter, sans-serif",
            titleFont="Inter, sans-serif",
            labelFontSize=12,
            titleFontSize=12,
            domainColor="#334155",
        )
    )

    st.altair_chart(chart, width="stretch")
