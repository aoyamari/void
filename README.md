# VOID

**Everyone counts what launches on NEAR. VOID counts what survives.**

VOID is a re-runnable investment thesis for NEAR, built at NEAR HACKATHON (Investment Thesis track). It treats the ecosystem like a population: projects are born, some keep living, most go quiet. It measures **how long NEAR projects survive, cohort by cohort**, and scores a pre-registered thesis against that evidence every day.

> Most NEAR theses argue from flows: Intents volume, fees, burn, issuance, active accounts. VOID argues from **retention of builders**. A chain whose newer projects outlive its older ones is compounding. A chain that only refills its graveyard is renting activity.

**Live dashboard: https://aoyamari.github.io/void/**

---

## The thesis (written before the data was pulled)

> NEAR's long-term case rests on an ecosystem that keeps what it builds. If projects launched on NEAR survive longer each year, and more are born than buried, the chain is compounding real builders, not renting them with incentives.

Four claims, each with a kill condition. They live in [`thesis.json`](thesis.json) and are re-scored on every rebuild:

| Claim | Killed if |
|---|---|
| **Newer cohorts survive longer** | Latest cohort's 12-month survival is below the oldest cohort's |
| **Not just a graveyard** | Fewer than 10% of projects older than 12 months are alive |
| **Births outpace deaths** | Deaths exceed births over the latest year whose deaths are final |
| **Not one-hit wonders** | Median lifetime is under 6 months |

Each claim resolves to **holds**, **killed**, or **not enough data**, with the numbers behind it on the dashboard.

**Bottom line.** The four verdicts roll up into one call. Two claims are about *direction* (newer cohorts, births vs deaths) and two about *level* (share of old projects alive, median lifetime):

| Direction | Level | Verdict |
|---|---|---|
| holds | holds | Compounding: NEAR keeps what it builds |
| holds | killed | Improving, not yet compounding |
| killed | holds | Durable but stalling |
| killed | killed | Thesis killed: NEAR is renting builders |

**Why these lines.** 10% alive is a deliberately lenient bar: about a third of US business establishments are still operating after ten years (BLS). 6 months is two death windows. 90 days is one quarter of silence. The rationale for each line is in `thesis.json` (added after the first run; the thresholds themselves were not changed). The dashboard also re-scores every claim with a 60-day and a 180-day death window, so you can see whether the verdict depends on that choice.

**Benchmark.** For context, roughly four in five new US business establishments survive their first year and about half survive five years ([BLS Business Employment Dynamics](https://www.bls.gov/opub/ted/2024/34-7-percent-of-business-establishments-born-in-2013-were-still-operating-in-2023.htm)). This is not like-for-like: a DAO costs a few NEAR to create and a business costs far more, so DAOs should die faster. It shows the size of the gap, not a target.

## What it measures

### Chapter 1: the DAO graveyard (no API key)
Every Sputnik DAO is created by the `sputnik-dao.near` factory. VOID lists them all, then reads every proposal's submission time with plain NEAR RPC view calls. No indexer and no third-party API.

- **Birth** = first proposal · **last seen** = latest proposal · **activity** = proposal count
- **Stillborn** = DAOs created that never received a single proposal
- **Sponsor bots are not activity.** Proposals filed by onboarding sponsor accounts (`sponsor.trezu.near`, `sponsor-staging.trezu.near`) are ignored. In 2026 these accounts filed the first proposal of 378 new DAOs; 223 DAOs never saw a single human proposal and are excluded.
- Raw proposals are cached in `data/raw/`, so daily re-runs only fetch what's new

### Chapter 2: the contract graveyard (BigQuery, optional)
From Google's public NEAR dataset (`bigquery-public-data.crypto_near_mainnet_us.receipt_actions`):

- A **contract** is any account that received a `DEPLOY_CONTRACT`
- It is **active** in a month when ≥ 3 distinct accounts call it. This filters single-wallet tests and lone bots.
- It counts as **launched** once any month reaches ≥ 25 callers
- The query is dry-run first and refuses to scan more than `--max-gb`

### Survival math
- A project is **dead** after **90 days** of silence (configurable in `thesis.json`)
- Survival curves use **Kaplan–Meier** with right-censoring: a project that is still alive counts as "survived at least this long", never as dead. That keeps young cohorts from looking worse than they are.
- Cohort = year of first activity. Curves stop once fewer than 10 projects remain under observation.
- **Born vs buried**: births and deaths per quarter. Deaths inside the last 90 days are shown as not yet final.

## Run it

```bash
git clone https://github.com/aoyamari/void && cd void
pip install -r requirements.txt

python -m void dao --limit 50   # smoke test on 50 DAOs
python -m void dao              # all DAOs (first run takes a while, then it is incremental)
python -m void rescore          # re-apply filters to the cache, no RPC
python -m void build            # survival + thesis verdicts -> site/data.json
python -m http.server -d site   # open http://localhost:8000
```

Use a different RPC with `--rpc <url>` or `NEAR_RPC_URL`.

**Chapter 2 (optional):**
```bash
pip install google-cloud-bigquery
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=<your-project>
python -m void contracts --check-schema   # confirm table columns (free)
python -m void contracts --dry-run        # print scan size, run nothing
python -m void contracts                  # run (free tier = 1 TB scanned / month)
python -m void build
```

**Tests:** `pip install pytest && python -m pytest -q`

A GitHub Action (`.github/workflows/void.yml`) re-runs chapter 1 daily, commits the refreshed numbers, and redeploys the dashboard to GitHub Pages.

## Layout

```
void/rpc.py        NEAR JSON-RPC view calls with retry/backoff
void/dao.py        chapter 1: Sputnik factory -> DAOs -> proposals -> entities
void/contracts.py  chapter 2: BigQuery runner (dry-run guard)
sql/contracts.sql  chapter 2 query
void/survival.py   Kaplan-Meier, cohorts, births/deaths, tombstones
void/thesis.py     scores the claims in thesis.json
void/build.py      writes site/data.json
site/index.html    static dashboard (no build step, no dependencies)
```

## Limits (read before you trust it)

- **Silence is not always death.** A DAO that finished its job, or a stable contract with few callers, can be healthy and quiet. VOID measures sustained use, not value.
- **DAO birth is approximated by the first proposal.** The true creation date may be earlier. DAOs with no proposals can't be dated and are reported as stillborn instead.
- **Older DAO contract versions** that don't expose `get_proposals` are counted as unreadable and excluded.
- **Thresholds are judgment calls**: 90 days, 3 callers, 25 callers, 10%, 6 months. They're explicit and editable so anyone can test how sensitive the verdict is.

## License

MIT
