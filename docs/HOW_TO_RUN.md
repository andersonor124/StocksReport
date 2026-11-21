# How to run StocksReport

This guide walks you through installing StocksReport and using it to create stock reports — an **HTML
report**, an **Excel workbook** and a **PowerPoint deck** — and through the **interactive web app**. No
programming knowledge is needed: you only copy and paste commands.

Everything is free. No accounts, subscriptions or API keys are required.

> 🎬 **Prefer to watch?** A 5-minute captioned video walks through every step below:
> [video/how_to_run.mp4](video/how_to_run.mp4) (subtitles: [video/how_to_run.srt](video/how_to_run.srt)).
> See [Video chapters](#video-chapters) at the end.

---

## Contents

1. [What you need](#1-what-you-need)
2. [One-time setup](#2-one-time-setup)
3. [Generate the reports](#3-generate-the-reports)
4. [Open the results](#4-open-the-results)
5. [Options](#5-options)
6. [Use the interactive web app](#6-use-the-interactive-web-app)
7. [Check data accuracy](#7-check-data-accuracy)
8. [How to read a report](#8-how-to-read-a-report)
9. [Troubleshooting](#9-troubleshooting)
10. [Running the tests (optional)](#10-running-the-tests-optional)

---

## 1. What you need

| Tool | Why | How to get it |
|---|---|---|
| **Python 3.10 or newer** | runs the program | [python.org/downloads](https://www.python.org/downloads/) — on Windows tick **"Add python.exe to PATH"** during install |
| **Git** | downloads the project | [git-scm.com/downloads](https://git-scm.com/downloads) |
| **Internet connection** | fetches market data | — |
| Excel / PowerPoint *(optional)* | opens the `.xlsx` / `.pptx` files | LibreOffice, Google Sheets/Slides or Apple Numbers/Keynote also work |

**Open a terminal**

* **Windows:** press the Start key, type **PowerShell**, press Enter.
* **Mac:** press ⌘ + Space, type **Terminal**, press Enter.
* **Linux:** open your Terminal app.

**Check that Python and Git are installed** — type each line and press Enter:

| Mac / Linux | Windows (PowerShell) |
|---|---|
| `python3 --version` | `python --version` |
| `git --version` | `git --version` |

You should see something like `Python 3.13.1` and `git version 2.43.0`.

> 🍎 **Mac users:** macOS has no `python` command — always type **`python3`** until the environment is
> switched on (Step 3 below). If `python3 --version` says *command not found* or a window offers to
> install developer tools, install Python from [python.org/downloads](https://www.python.org/downloads/)
> (or click **Install** in that window / run `xcode-select --install`), then close and reopen Terminal.

---

## 2. One-time setup

You only do this once per computer.

**Step 1 — download the project**

```bash
git clone https://github.com/andersonor124/StocksReport.git
cd StocksReport
git checkout claude/youthful-mayer-y9e5sg
```

**Step 2 — create a private Python environment** (keeps this project's packages separate)

| Mac / Linux | Windows (PowerShell) |
|---|---|
| `python3 -m venv .venv` | `python -m venv .venv` |

**Step 3 — switch the environment on**

| Mac / Linux | Windows (PowerShell) |
|---|---|
| `source .venv/bin/activate` | `.venv\Scripts\Activate.ps1` |

Your prompt now starts with `(.venv)`. **You must do this step every time you open a new terminal.**

From here on, plain `python` and `pip` work on every computer (including Mac), because they come from the
environment you just switched on — so the remaining commands are the same for everyone.

**Step 4 — install the required packages** (takes 1–3 minutes)

```bash
pip install -r requirements.txt
```

It finishes with a line starting `Successfully installed ...`.

**Step 5 — tell the SEC who you are**

The U.S. Securities and Exchange Commission (SEC) — one of the free data sources used to double-check the
numbers — asks every program to identify itself with a name and email. Use your own:

| Mac / Linux | Windows (PowerShell) |
|---|---|
| `export SEC_USER_AGENT="Jane Doe jane@example.com"` | `$env:SEC_USER_AGENT="Jane Doe jane@example.com"` |

This lasts until you close the terminal. To make it permanent:

* **Mac / Linux:** add the `export ...` line to the end of `~/.zshrc` (Mac) or `~/.bashrc` (Linux).
* **Windows:** run `setx SEC_USER_AGENT "Jane Doe jane@example.com"` once, then open a new PowerShell window.

✅ Setup is done.

---

## 3. Generate the reports

Make sure you are in the `StocksReport` folder and the environment is on (`(.venv)` in your prompt). Then
simply run:

```bash
python cli.py
```

The program **asks you which company to analyse**. Type a **company name** (e.g. `nvidia`, `coca cola`)
or a **ticker** (e.g. `NVDA`), then press Enter. Next it asks which files to create — just press Enter
for all three (HTML, Excel and PowerPoint):

```text
Which stock(s) do you want to analyse?
Enter a company name or ticker (separate several with commas, q to quit): nvidia
  'nvidia' → NVDA    NVIDIA Corporation (NMS)
Which formats? html, xlsx, pptx — press Enter for all three:
Analysing NVDA ...
NVDA   Buy  score  87.9  price $125.53  fair value $261.65  | data verification: 25/32 checks passed
   -> reports/NVDA_2026-11-21.html
   -> reports/NVDA_2026-11-21.pptx
   -> reports/NVDA_2026-11-21.xlsx
```

*(Your numbers will differ — they are live market data. It takes about 20 seconds per company.)*

* **Several companies:** separate them with commas, e.g. `apple, microsoft, jp morgan` — you also get a
  side-by-side comparison in Excel.
* **Name matches more than one company?** You'll see a short numbered list — type the number you want
  (or press Enter for the first one):

  ```text
    'berkshire' matches several companies:
        1) BRK-B   Berkshire Hathaway Inc. New (NYQ)
        2) BRK-A   Berkshire Hathaway Inc. (NYQ)
      Choose 1-2 [1]:
  ```
* **Not found?** Check the spelling and try again, or use the ticker (look it up on finance.yahoo.com).
* Type `q` (or just press Enter) to quit.

**Shortcut — everything in one line** (skips the questions): put the companies, then the options:

```bash
python cli.py <company or ticker> [more companies] --format html xlsx pptx
```

For example `python cli.py nvidia --format html xlsx pptx` or `python cli.py "coca cola" TSLA --format html`
(use quotes around names with spaces). Without `--format` the one-line form creates the HTML report only.

**What gets created** — all files go into the `reports` folder:

| File | What it is |
|---|---|
| `<TICKER>_<date>.html` | the full report for one stock, opens in any web browser |
| `<TICKER>_<date>.pptx` | a 10-slide PowerPoint deck for one stock |
| `comparison_<date>.xlsx` | one Excel workbook for all the stocks you asked for (named `<TICKER>_<date>.xlsx` if you analysed only one) |

Files are named after the company's ticker and today's date, e.g. `NVDA_2026-11-21.html`. Running again on
the same day overwrites that day's files.

---

## 4. Open the results

**Open the `reports` folder**

| Windows | Mac | Linux |
|---|---|---|
| `start reports` | `open reports` | `xdg-open reports` |

Then double-click a file.

**HTML report** (opens in your browser) — one long page with:
header with the **Buy / Hold / Sell** verdict and score → summary → company overview → key metrics →
performance vs the S&P 500 and the sector ETF (table + chart) → peer comparison → score breakdown →
**pros & cons** → **retail investor view** and **portfolio manager view** → risks & catalysts →
**fair value & entry price** → analyst actions and news headlines → **data verification**.

**Excel workbook** — sheets:

| Sheet | Contents |
|---|---|
| `Comparison` | one row per stock: price, score, verdict, valuation, margins, returns, fair value, verification rate (only when you ran 2+ stocks) |
| `<TICKER> Summary` | verdict, score, pillar scores, fair value, entry price, investor views |
| `<TICKER> Metrics` | every metric with its source (computed / yfinance / SEC) |
| `<TICKER> Benchmark` | returns vs S&P 500 and sector ETF, peer table, price chart |
| `<TICKER> Pros-Cons` | pros, cons, risks, catalysts, analyst actions, headlines with sentiment |
| `<TICKER> Verification` | every data check, colour-coded PASS / WARN / FAIL |

**PowerPoint deck** — 10 slides: title & verdict · company overview · key metrics · benchmark chart ·
score breakdown · pros & cons · investor views · verdict & fair value · data verification · disclaimer.

---

## 5. Options

These options go after the company names in the one-line form (`python cli.py <company> --option ...`).

| Option | What it does | Example |
|---|---|---|
| `--format` | which files to make: any of `html`, `xlsx`, `pptx` (default: `html` only) | `python cli.py nvidia --format xlsx` |
| `--peers` | compare against your own choice of peer companies | `python cli.py NVDA --peers AMD AVGO INTC QCOM` |
| `--out` | save to a different folder (default: `reports`) | `python cli.py tesla --out my_reports` |
| `--no-verify` | skip the SEC / Nasdaq accuracy checks (faster) | `python cli.py "coca cola" --no-verify` |
| `--no-cache` | fetch fresh data instead of reusing data from the last 12 hours | `python cli.py amazon --no-cache` |

See all options any time with `python cli.py --help`.

---

## 6. Use the interactive web app

Prefer clicking to typing? Start the web app:

```bash
streamlit run app.py
```

Your browser opens at **http://localhost:8501** (if it doesn't, open that address yourself). The first
time, Streamlit may ask for an email in the terminal — just press Enter to skip.

1. In the left sidebar, under **Company name or ticker**, type the company you want — a name such as
   `apple` or a ticker such as `AAPL`. Separate several with commas to compare them. The sidebar shows
   which company it found; if a name matches more than one, pick the right one from the
   **"Which company did you mean?"** list.
2. *(Optional)* type your own peer companies, e.g. `MSFT, GOOGL`.
3. Keep **Verify data against SEC/Nasdaq** ticked for checked numbers.
4. Click **Analyze** and wait a few seconds.

* **One company** → tabs: *Overview*, *Metrics & Benchmark*, *Pros/Cons*, *Investor Views*,
  *Verdict & Fair Value*, *Data Verification*, plus buttons to **download** the HTML, Excel and
  PowerPoint files.
* **Several companies** → a **comparison table**, a **Download Excel workbook** button and an expandable
  section per stock.

To stop the app, go back to the terminal and press **Ctrl + C**.

---

## 7. Check data accuracy

Every report already includes a *Data verification* section. To produce a stand-alone accuracy report:

```bash
python cli.py verify
```

It asks which company to check (name or ticker), just like report generation — or give them directly:
`python cli.py verify nvidia "coca cola"`. It prints a summary per stock and writes `reports/verification_<date>.xlsx` and `.html`. Each number taken
from Yahoo Finance is compared with an original source:

* **SEC filing** — the figure in the company's official 10-K / 10-Q report filed with the SEC
* **Price** — daily closing prices compared with Nasdaq's records
* **Derived ratio** — our calculated ratios compared with Yahoo's own
* **Internal consistency** — accounting checks such as *assets = liabilities + equity*

| Status | Meaning |
|---|---|
| **PASS** | matches the source (within 0.5%; EPS to the cent) |
| **WARN** | small difference, usually a different definition — explained in the note |
| **FAIL** | a real difference — the report uses the official SEC value instead and says so under *Corrections applied* |
| **SKIP** | the source doesn't publish that number (e.g. non-U.S. companies) |

---

## 8. How to read a report

* **Score (0–100)** — combines six areas: *Valuation, Growth, Profitability, Financial health, Momentum,
  Analyst consensus*. Each one is shown separately with the numbers behind it.
* **Verdict** — **Buy** if the score is 65 or more, **Sell** below 45, otherwise **Hold**.
  *Confidence* says how far the score is from those lines.
* **Fair value** — mostly the analysts' average price target, cross-checked with what peers' valuations
  imply. **Upside** is how far that is above (+) or below (−) today's price.
* **Entry price** — fair value minus a 10% safety margin: a price at which the stock would look more
  attractive.
* **Pros / Cons** — every point lists the exact figure that triggered it (e.g. *"Net margin 32.5% vs peer
  median 28.1%"*).
* **Corrections applied** — appears when the official SEC numbers were used instead of Yahoo's.

> ⚠️ Reports are generated automatically for educational purposes and are **not financial advice**.

---

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| Mac: `zsh: command not found: python` (or `pip`) | Before Step 3 use `python3` (e.g. `python3 -m venv .venv`). After activating the environment (`source .venv/bin/activate`), `python` and `pip` work. |
| `python` / `pip` is not recognised (Windows) | Python isn't installed or isn't on PATH. Re-install Python and tick *Add python.exe to PATH*, then open a new PowerShell window. |
| `No module named ...` | The environment isn't switched on. Run Step 3 of the setup again (`source .venv/bin/activate` or `.venv\Scripts\Activate.ps1`). |
| Windows: *"running scripts is disabled on this system"* when activating | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, answer **Y**, then activate again. |
| Warning `SEC_USER_AGENT not set` or *403* errors from the SEC | Do Step 5 of the setup with your own name and email. |
| `No market data found for ticker 'XYZ'` / `No reports produced.` | The ticker is wrong. Check it on finance.yahoo.com. Share classes use a dash: `BRK-B`. |
| Verification shows *company not found in SEC EDGAR* / many SKIPs | Normal for non-U.S. companies — the report is still produced. |
| `invalid choice` error | Put the companies before the options: `python cli.py nvidia --format html`, not `--format html nvidia`. Or just run `python cli.py` and answer the questions. |
| `No company found for '...'` | Check the spelling, or use the ticker symbol (find it on finance.yahoo.com). Share classes use a dash: `BRK-B`. |
| The chart area says *Chart unavailable* | The HTML report loads its chart library from the internet; open it while online. |
| Numbers look out of date | Data is reused for 12 hours. Add `--no-cache`. |
| Web app: *port 8501 is already in use* | Another copy is running — close it, or run `streamlit run app.py --server.port 8502`. |

---

## 10. Running the tests (optional)

```bash
pytest           # quick offline tests (uses recorded data)
pytest --live    # also re-checks live data against the SEC and Nasdaq
```

---

## Video chapters

[video/how_to_run.mp4](video/how_to_run.mp4) — captioned, no sound needed.

| Time | Chapter | Guide section |
|---|---|---|
| 0:00 | Introduction | — |
| 0:09 | 1. What you need — and opening a terminal | [§1](#1-what-you-need) |
| 0:21 | 2. One-time setup | [§2](#2-one-time-setup) |
| 0:55 | 3. Generate the reports | [§3](#3-generate-the-reports) |
| 1:25 | 4. Open the HTML report | [§4](#4-open-the-results) |
| 2:09 | 5. Open the Excel workbook | [§4](#4-open-the-results) |
| 2:46 | 6. Open the PowerPoint deck | [§4](#4-open-the-results) |
| 3:15 | 7. Use the interactive web app | [§6](#6-use-the-interactive-web-app) |
| 4:15 | 8. Check data accuracy | [§7](#7-check-data-accuracy) |
| 4:48 | 9. Troubleshooting | [§9](#9-troubleshooting) |

Total length 5:12. The commands and outputs shown are from a real run; your prices and scores will differ.
The video uses the one-line form (`python cli.py AAPL MSFT JPM --format html xlsx pptx`); running plain `python cli.py` instead asks you which company to analyse, as described in [§3](#3-generate-the-reports).
To show the subtitles as a separate track, load `how_to_run.srt` in your video player (e.g. VLC: *Subtitle → Add Subtitle File*).
