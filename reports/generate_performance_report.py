"""
Regenerates paper_trading_performance.xlsx from the latest cleaned closed-
trade data. Rerunnable: pull fresh artifacts, overwrite paper_trades_final.csv
(same schema dedupe_and_clean.py already produces), then run this again.

Layout:
  - Summary: overall KPIs, wallet vs our simulated performance, at a glance.
  - Daily Performance: one row per calendar day, with the two charts.
  - By Wallet: one row per tracked wallet.
  - Raw Trades: the underlying per-trade data everything else is built from.

Every aggregate is a formula (SUMIFS/COUNTIFS/AVERAGEIFS) referencing Raw
Trades -- nothing here is a Python-computed number baked into a cell, so the
workbook recalculates correctly if Raw Trades is ever edited or extended by
hand. Day-list and wallet-list *labels* are computed in Python and written
as literal values (needed since SORT/UNIQUE aren't safe to rely on for
recalculation), matching the pattern for row-label/index columns, not for
the actual aggregate figures next to them.
"""

import datetime
import sys

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else "paper_trades_final.csv"
OUT_PATH = sys.argv[2] if len(sys.argv) > 2 else "paper_trading_performance.xlsx"

FONT_NAME = "Arial"
EXCEL_EPOCH_OFFSET = 25569  # days between 1899-12-30 (Excel serial 0) and 1970-01-01 (Unix epoch)

HEADER_FONT = Font(name=FONT_NAME, bold=True, color="FFFFFF")
HEADER_FILL = "1F4E78"
TITLE_FONT = Font(name=FONT_NAME, bold=True, size=14)
LABEL_FONT = Font(name=FONT_NAME, bold=True)
BODY_FONT = Font(name=FONT_NAME)

SOL_FMT = '#,##0.000;(#,##0.000);"-"'
PCT_FMT = "0.0%"
DATE_FMT = "yyyy-mm-dd"
DATETIME_FMT = "yyyy-mm-dd hh:mm"

STALE_HOURS = 12  # flag if the newest trade is older than this -- likely means the CI pipeline stopped


def style_header_row(ws, row, n_cols):
    from openpyxl.styles import PatternFill
    fill = PatternFill(start_color=HEADER_FILL, end_color=HEADER_FILL, fill_type="solid")
    for c in range(1, n_cols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = HEADER_FONT
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center")


def autosize(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def epoch_ms_to_day_serial(epoch_ms):
    return int(epoch_ms / 86400000 + EXCEL_EPOCH_OFFSET)


def main():
    df = pd.read_csv(CSV_PATH)
    df = df.sort_values("epoch_ms").reset_index(drop=True)
    n = len(df)

    newest_epoch_ms = int(df["epoch_ms"].max())
    age_hours = (datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000 - newest_epoch_ms) / 3600000
    if age_hours > STALE_HOURS:
        print(f"WARNING: newest trade is {age_hours:.1f}h old (> {STALE_HOURS}h) -- "
              f"the data-collection pipeline may have stopped. Check `gh run list` / the "
              f"ci-broken issues before trusting this as current.", file=sys.stderr)

    day_serials = sorted(df["epoch_ms"].apply(epoch_ms_to_day_serial).unique())
    day_dates = [datetime.date(1899, 12, 30) + datetime.timedelta(days=int(d)) for d in day_serials]
    wallets = sorted(df["wallet_label"].unique())

    wb = Workbook()

    # ---------------------------------------------------------------- Raw Trades
    raw = wb.active
    raw.title = "Raw Trades"
    raw_headers = ["epoch_ms", "Date", "Wallet", "Mint", "Sell Signature", "Buy Count", "Hold (ms)",
                   "Wallet Token Amt", "Wallet Lamports Spent", "Wallet Lamports Received", "Wallet PnL (SOL)",
                   "Our Lamports Spent", "Our Lamports Received", "Our PnL (SOL)", "Wallet Win", "Our Win"]
    raw.append(raw_headers)
    style_header_row(raw, 1, len(raw_headers))

    has_sig = "sell_signature" in df.columns
    for i, row in df.iterrows():
        r = i + 2
        raw.cell(row=r, column=1, value=int(row["epoch_ms"]))
        raw.cell(row=r, column=2, value=f"=INT(A{r}/86400000+{EXCEL_EPOCH_OFFSET})").number_format = DATE_FMT
        raw.cell(row=r, column=3, value=row["wallet_label"])
        raw.cell(row=r, column=4, value=row["mint"])
        raw.cell(row=r, column=5, value=row["sell_signature"] if has_sig and pd.notna(row.get("sell_signature")) else "")
        raw.cell(row=r, column=6, value=int(row["buy_count"]))
        raw.cell(row=r, column=7, value=int(row["hold_duration_ms"]))
        raw.cell(row=r, column=8, value=float(row["wallet_token_amount"]))
        raw.cell(row=r, column=9, value=int(row["wallet_lamports_spent"])).number_format = "#,##0"
        raw.cell(row=r, column=10, value=int(row["wallet_lamports_received"])).number_format = "#,##0"
        raw.cell(row=r, column=11, value=float(row["wallet_pnl_sol"])).number_format = SOL_FMT
        raw.cell(row=r, column=12, value=float(row["our_lamports_spent"])).number_format = "#,##0"
        raw.cell(row=r, column=13, value=float(row["our_lamports_received"])).number_format = "#,##0"
        raw.cell(row=r, column=14, value=float(row["our_pnl_sol"])).number_format = SOL_FMT
        raw.cell(row=r, column=15, value=f"=IF(K{r}>0,1,0)")
        raw.cell(row=r, column=16, value=f"=IF(N{r}>0,1,0)")
        for c in range(1, 17):
            raw.cell(row=r, column=c).font = BODY_FONT

    last_raw_row = n + 1
    autosize(raw, [14, 12, 12, 14, 20, 9, 10, 16, 18, 20, 13, 16, 18, 13, 10, 8])
    raw.freeze_panes = "A2"

    # ---------------------------------------------------------- Daily Performance
    daily = wb.create_sheet("Daily Performance")
    daily_headers = ["Date", "Trades Closed", "Wallet Wins", "Wallet Win Rate", "Wallet PnL (SOL)",
                      "Our Wins", "Our Win Rate", "Our PnL (SOL)", "Cumulative Wallet PnL",
                      "Cumulative Our PnL"]
    daily.append(daily_headers)
    style_header_row(daily, 1, len(daily_headers))

    raw_date_col = f"'Raw Trades'!$B$2:$B${last_raw_row}"
    raw_wwin_col = f"'Raw Trades'!$O$2:$O${last_raw_row}"
    raw_owin_col = f"'Raw Trades'!$P$2:$P${last_raw_row}"
    raw_wpnl_col = f"'Raw Trades'!$K$2:$K${last_raw_row}"
    raw_opnl_col = f"'Raw Trades'!$N$2:$N${last_raw_row}"

    for i, d in enumerate(day_dates):
        r = i + 2
        daily.cell(row=r, column=1, value=d).number_format = DATE_FMT
        daily.cell(row=r, column=2, value=f"=COUNTIFS({raw_date_col},A{r})")
        daily.cell(row=r, column=3, value=f"=SUMIFS({raw_wwin_col},{raw_date_col},A{r})")
        daily.cell(row=r, column=4, value=f"=IFERROR(C{r}/B{r},0)").number_format = PCT_FMT
        daily.cell(row=r, column=5, value=f"=SUMIFS({raw_wpnl_col},{raw_date_col},A{r})").number_format = SOL_FMT
        daily.cell(row=r, column=6, value=f"=SUMIFS({raw_owin_col},{raw_date_col},A{r})")
        daily.cell(row=r, column=7, value=f"=IFERROR(F{r}/B{r},0)").number_format = PCT_FMT
        daily.cell(row=r, column=8, value=f"=SUMIFS({raw_opnl_col},{raw_date_col},A{r})").number_format = SOL_FMT
        daily.cell(row=r, column=9, value=f"=SUM($E$2:E{r})").number_format = SOL_FMT
        daily.cell(row=r, column=10, value=f"=SUM($H$2:H{r})").number_format = SOL_FMT
        for c in range(1, 11):
            daily.cell(row=r, column=c).font = BODY_FONT

    last_daily_row = len(day_dates) + 1
    autosize(daily, [12, 13, 12, 15, 15, 10, 14, 14, 19, 16])
    daily.freeze_panes = "A2"

    # Chart 1: daily P&L, wallet vs ours (clustered bar)
    bar = BarChart()
    bar.type = "col"
    bar.grouping = "clustered"
    bar.title = "Daily P&L: Wallet (real) vs Our Simulated Copy"
    bar.y_axis.title = "SOL"
    bar.x_axis.title = "Date"
    bar.height, bar.width = 10, 24
    data = Reference(daily, min_col=5, max_col=5, min_row=1, max_row=last_daily_row)
    data2 = Reference(daily, min_col=8, max_col=8, min_row=1, max_row=last_daily_row)
    cats = Reference(daily, min_col=1, min_row=2, max_row=last_daily_row)
    bar.add_data(data, titles_from_data=True)
    bar.add_data(data2, titles_from_data=True)
    bar.set_categories(cats)
    daily.add_chart(bar, f"L2")

    # Chart 2: cumulative P&L over time, wallet vs ours (equity curve)
    line = LineChart()
    line.title = "Cumulative P&L Over Time"
    line.y_axis.title = "SOL"
    line.x_axis.title = "Date"
    line.height, line.width = 10, 24
    cdata = Reference(daily, min_col=9, max_col=10, min_row=1, max_row=last_daily_row)
    line.add_data(cdata, titles_from_data=True)
    line.set_categories(cats)
    daily.add_chart(line, f"L22")

    # ------------------------------------------------------------------- By Wallet
    bywallet = wb.create_sheet("By Wallet")
    bw_headers = ["Wallet", "Trades Closed", "Wallet Win Rate", "Wallet PnL (SOL)", "Wallet Avg PnL/Trade",
                  "Our Win Rate", "Our PnL (SOL)", "Our Avg PnL/Trade"]
    bywallet.append(bw_headers)
    style_header_row(bywallet, 1, len(bw_headers))

    raw_wallet_col = f"'Raw Trades'!$C$2:$C${last_raw_row}"
    for i, wname in enumerate(wallets):
        r = i + 2
        bywallet.cell(row=r, column=1, value=wname)
        bywallet.cell(row=r, column=2, value=f"=COUNTIFS({raw_wallet_col},A{r})")
        bywallet.cell(row=r, column=3, value=f"=IFERROR(SUMIFS({raw_wwin_col},{raw_wallet_col},A{r})/B{r},0)").number_format = PCT_FMT
        bywallet.cell(row=r, column=4, value=f"=SUMIFS({raw_wpnl_col},{raw_wallet_col},A{r})").number_format = SOL_FMT
        bywallet.cell(row=r, column=5, value=f"=IFERROR(D{r}/B{r},0)").number_format = SOL_FMT
        bywallet.cell(row=r, column=6, value=f"=IFERROR(SUMIFS({raw_owin_col},{raw_wallet_col},A{r})/B{r},0)").number_format = PCT_FMT
        bywallet.cell(row=r, column=7, value=f"=SUMIFS({raw_opnl_col},{raw_wallet_col},A{r})").number_format = SOL_FMT
        bywallet.cell(row=r, column=8, value=f"=IFERROR(G{r}/B{r},0)").number_format = SOL_FMT
        for c in range(1, 9):
            bywallet.cell(row=r, column=c).font = BODY_FONT

    last_bw_row = len(wallets) + 1
    autosize(bywallet, [14, 14, 15, 15, 18, 13, 14, 17])
    bywallet.freeze_panes = "A2"

    bw_chart = BarChart()
    bw_chart.type = "col"
    bw_chart.grouping = "clustered"
    bw_chart.title = "Total P&L by Wallet: Real vs Our Simulated Copy"
    bw_chart.y_axis.title = "SOL"
    bw_chart.height, bw_chart.width = 10, 24
    bwdata = Reference(bywallet, min_col=4, max_col=4, min_row=1, max_row=last_bw_row)
    bwdata2 = Reference(bywallet, min_col=7, max_col=7, min_row=1, max_row=last_bw_row)
    bwcats = Reference(bywallet, min_col=1, min_row=2, max_row=last_bw_row)
    bw_chart.add_data(bwdata, titles_from_data=True)
    bw_chart.add_data(bwdata2, titles_from_data=True)
    bw_chart.set_categories(bwcats)
    bywallet.add_chart(bw_chart, "K2")

    # ---------------------------------------------------------------------- Summary
    summary = wb.create_sheet("Summary", 0)
    summary["A1"] = "Paper Trading Performance Summary"
    summary["A1"].font = TITLE_FONT
    summary["A2"] = f"Generated from {n} closed trades across {len(wallets)} tracked wallets."
    summary["A2"].font = Font(name=FONT_NAME, italic=True, size=9)

    summary["A4"] = "Date range"
    summary["A4"].font = LABEL_FONT
    summary["B4"] = f"='Daily Performance'!A2"
    summary["C4"] = f"='Daily Performance'!A{last_daily_row}"
    summary["B4"].number_format = DATE_FMT
    summary["C4"].number_format = DATE_FMT

    summary["A5"] = "Total trades closed"
    summary["B5"] = f"=SUM('Daily Performance'!B2:B{last_daily_row})"
    summary["A6"] = "Days with activity"
    summary["B6"] = f"=COUNTA('Daily Performance'!A2:A{last_daily_row})"
    summary["A7"] = "Avg trades / active day"
    summary["B7"] = "=B5/B6"
    summary["B7"].number_format = "0.0"

    summary["B9"] = "Wallet (real)"
    summary["C9"] = "Our simulated copy"
    summary["B9"].font = LABEL_FONT
    summary["C9"].font = LABEL_FONT

    summary["A10"] = "Overall win rate"
    summary["B10"] = f"=SUM('Daily Performance'!C2:C{last_daily_row})/B5"
    summary["C10"] = f"=SUM('Daily Performance'!F2:F{last_daily_row})/B5"
    summary["B10"].number_format = PCT_FMT
    summary["C10"].number_format = PCT_FMT

    summary["A11"] = "Total P&L (SOL)"
    summary["B11"] = f"=SUM('Daily Performance'!E2:E{last_daily_row})"
    summary["C11"] = f"=SUM('Daily Performance'!H2:H{last_daily_row})"
    summary["B11"].number_format = SOL_FMT
    summary["C11"].number_format = SOL_FMT

    summary["A12"] = "Avg P&L / trade (SOL)"
    summary["B12"] = "=B11/B5"
    summary["C12"] = "=C11/B5"
    summary["B12"].number_format = SOL_FMT
    summary["C12"].number_format = SOL_FMT

    summary["A13"] = "Avg P&L / active day (SOL)"
    summary["B13"] = "=B11/B6"
    summary["C13"] = "=C11/B6"
    summary["B13"].number_format = SOL_FMT
    summary["C13"].number_format = SOL_FMT

    for r in range(4, 14):
        summary.cell(row=r, column=1).font = LABEL_FONT if r not in (9,) else LABEL_FONT
        for c in (2, 3):
            cell = summary.cell(row=r, column=c)
            if cell.value is not None and cell.font.name != FONT_NAME:
                cell.font = BODY_FONT

    # Live freshness check: unlike everything above, this is meant to
    # recompute every time the file is *opened*, not just every time it's
    # regenerated -- NOW() is volatile by design here, since the whole point
    # is "does this look current right now," not "was it current when
    # generated." Directly answers the failure mode where the CI pipeline
    # silently stops and nobody notices until someone opens this file.
    summary["A15"] = "Data freshness"
    summary["A15"].font = LABEL_FONT

    summary["A16"] = "Newest trade timestamp"
    summary["B16"] = f"=MAX('Raw Trades'!A2:A{last_raw_row})/86400000+{EXCEL_EPOCH_OFFSET}"
    summary["B16"].number_format = DATETIME_FMT

    summary["A17"] = "Hours since newest trade"
    summary["B17"] = "=(NOW()-B16)*24"
    summary["B17"].number_format = "0.0"

    summary["A18"] = "Status"
    summary["B18"] = (f'=IF(B17>{STALE_HOURS},"STALE -- check `gh run list` / ci-broken issues","OK")')

    for r in (15, 16, 17, 18):
        summary.cell(row=r, column=1).font = LABEL_FONT
        if summary.cell(row=r, column=2).value is not None:
            summary.cell(row=r, column=2).font = BODY_FONT

    summary["A20"] = ("Note: 'Our simulated copy' assumes copying every closed trade at the configured "
                       "execution_lag_ms, on top of the free poll engine's own ~17s median detection lag "
                       "(see lag_experiment results) -- not a filtered/model-selected subset. See the "
                       "experiment/lgbm-trade-classifier branch for what a filtered strategy's numbers look like.")
    summary["A20"].font = Font(name=FONT_NAME, italic=True, size=9)
    summary["A20"].alignment = Alignment(wrap_text=True)
    summary.merge_cells("A20:H20")
    summary.row_dimensions[20].height = 45

    autosize(summary, [26, 18, 20])

    wb.save(OUT_PATH)
    print(f"Wrote {OUT_PATH}: {n} trades, {len(day_dates)} days, {len(wallets)} wallets")


if __name__ == "__main__":
    main()
