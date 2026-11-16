#!/usr/bin/env python3
"""AEO citation harness: run a fixed query set against an AI answer engine and record who it cites.

Why this exists: a citation read done by hand cannot be repeated exactly, so it cannot show a
trend, and a trend is the only thing that proves AEO work did anything. The same script is the
day-one diagnostic of an AEO engagement: point it at a client's domain and query set.

Engines
  perplexity  Perplexity's API (model "sonar"), which returns the URLs it cited. Paid, so it
              needs --yes. Reads the key from the environment variable PERPLEXITY_API_KEY and
              never prints, logs or writes it.
  fixture     Replays a saved JSON of answers and citations. Costs nothing. Use it to test the
              scoring, or to score a run captured another way.

Examples
  python run_citations.py --engine fixture --fixture fixtures/<a-fixture>.json
  python run_citations.py --engine perplexity --samples 3 --yes

Standard library only. Python 3.9 or later.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
PPLX_URL = "https://api.perplexity.ai/chat/completions"
PPLX_MODEL = "sonar"


# --------------------------------------------------------------------------- domains

def host_and_path(url):
    """Lower-case host without www., and the path, for one URL."""
    try:
        p = urllib.parse.urlparse(url if "://" in url else "https://" + url)
    except ValueError:
        return "", ""
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host, (p.path or "").rstrip("/").lower()


def matches(url, target):
    """True if url belongs to target. A target may carry a path, e.g. github.com/Org.

    Subdomains count (blog.example.com belongs to example.com) but only across a dot, so
    notexample.com never matches example.com, and a lookalike that merely contains your name never
    matches yours. Paths compare case-insensitively, which is right for code-hosting orgs, and
    only whole segments match, so example.com/acme is not example.com/acmeco."""
    host, path = host_and_path(url)
    t_host, t_path = host_and_path(target)
    if not host or not (host == t_host or host.endswith("." + t_host)):
        return False
    return t_path == "" or path == t_path or path.startswith(t_path + "/")


# --------------------------------------------------------------------------- engines

class EngineError(RuntimeError):
    pass


def ask_perplexity(question, key, timeout=60):
    body = json.dumps({
        "model": PPLX_MODEL,
        "messages": [{"role": "user", "content": question}],
    }).encode("utf-8")
    req = urllib.request.Request(PPLX_URL, data=body, method="POST", headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Never echo the request: it carries the key in a header.
        if e.code in (401, 403):
            raise EngineError("Perplexity refused the key (HTTP %d). Check PERPLEXITY_API_KEY "
                              "holds a real key; it was not printed." % e.code)
        raise EngineError("Perplexity returned HTTP %d" % e.code)
    except urllib.error.URLError as e:
        raise EngineError("could not reach Perplexity: %s" % e.reason)

    answer = ""
    try:
        answer = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        pass
    urls = []
    for u in data.get("citations") or []:
        if isinstance(u, str):
            urls.append(u)
    for r in data.get("search_results") or []:
        if isinstance(r, dict) and r.get("url"):
            urls.append(r["url"])
    seen, ordered = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    return {"answer": answer, "citations": ordered, "usage": data.get("usage")}


def load_fixture(path):
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return {int(k): v for k, v in data["answers"].items()}, data


# --------------------------------------------------------------------------- scoring

def brand_names(cfg):
    """Names to look for in the answer text. Defaults to the site's first label."""
    names = cfg.get("names") or [cfg["our_site"].split(".")[0]]
    return [n.lower() for n in names if n.strip()]


def id_label(ids):
    """[6, 7, 8, 9, 10] -> 'Q6 to Q10'; [1, 2] -> 'Q1, Q2'; [] -> 'none'."""
    ids = sorted(ids)
    if not ids:
        return "none"
    if len(ids) > 2 and ids == list(range(ids[0], ids[-1] + 1)):
        return "Q%d to Q%d" % (ids[0], ids[-1])
    return ", ".join("Q%d" % i for i in ids)


def score_sample(sample, cfg):
    cits = sample.get("citations") or []
    answer = (sample.get("answer") or "").lower()
    ours = [u for u in cits if matches(u, cfg["our_site"])]
    related = sorted({t for t in cfg["related"] for u in cits if matches(u, t)})
    lookalike_list = cfg.get("lookalikes", cfg.get("impostors", []))
    lookalikes = sorted({t for t in lookalike_list for u in cits if matches(u, t)})
    return {
        "cited_us": bool(ours),
        "our_urls": ours,
        "related_cited": related,
        "lookalikes_cited": lookalikes,
        "named_in_answer": any(n in answer for n in brand_names(cfg)),
        "cited_domains": sorted({host_and_path(u)[0] for u in cits if host_and_path(u)[0]}),
        "n_citations": len(cits),
    }


def summarise(results, cfg):
    """results: {qid: [scored sample, ...]}. Returns the scoreboard lines."""
    def rate(ids, test):
        hit = tot = 0
        for q in ids:
            for s in results.get(q, []):
                tot += 1
                hit += 1 if test(s) else 0
        return hit, tot

    g = cfg["groups"]
    m1 = rate(g["metric_1_offer"], lambda s: s["cited_us"])
    m2 = rate(g["metric_2_non_brand"], lambda s: s["cited_us"])
    m3 = rate(g["metric_3_brand"], lambda s: s["cited_us"] and not s["lookalikes_cited"])
    imp = sum(len(s["lookalikes_cited"]) for v in results.values() for s in v)
    ours = sum(1 for v in results.values() for s in v if s["cited_us"])
    extra = rate(g.get("added_since_baseline", []), lambda s: s["cited_us"])
    return {
        "metric_1_offer_cited": m1,
        "metric_2_non_brand_cited": m2,
        "metric_3_brand_clean": m3,
        "metric_4_lookalike_vs_ours": (imp, ours),
        "added_since_baseline_cited": extra,
    }


# --------------------------------------------------------------------------- report

def write_report(out_dir, stamp, engine, cfg, questions, results, raw, summary, samples, note):
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / ("%s_%s" % (stamp, engine))
    base.with_suffix(".json").write_text(json.dumps({
        "stamp": stamp, "engine": engine, "model": PPLX_MODEL if engine == "perplexity" else None,
        "samples_per_query": samples, "query_set_version": cfg["version"], "note": note,
        "summary": {k: list(v) for k, v in summary.items()},
        "raw": raw, "scored": {str(k): v for k, v in results.items()},
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    def frac(t):
        return "%d / %d" % t

    L = []
    L.append("# Citation run, %s, engine: %s" % (stamp, engine))
    L.append("")
    if note:
        L.append("> " + note)
        L.append("")
    g = cfg["groups"]
    L.append("Query set version %d, %d sample(s) per query. **One engine.** Not comparable to a "
             "run on any other engine, and one sample per query is directional, not a rate."
             % (cfg["version"], samples))
    L.append("")
    L.append("| Metric | Result |")
    L.append("|---|---|")
    L.append("| 1. Offer queries citing %s (%s) | %s |" % (
        cfg["our_site"], id_label(g["metric_1_offer"]), frac(summary["metric_1_offer_cited"])))
    L.append("| 2. Any non-brand query citing us (%s) | %s |" % (
        id_label(g["metric_2_non_brand"]), frac(summary["metric_2_non_brand_cited"])))
    L.append("| 3. Brand queries citing us with no lookalike-name company (%s) | %s |" % (
        id_label(g["metric_3_brand"]), frac(summary["metric_3_brand_clean"])))
    L.append("| 4. Lookalike-name citations : ours | %d : %d |" % summary["metric_4_lookalike_vs_ours"])
    L.append("| Added since the first run (%s) | %s |" % (
        id_label(g.get("added_since_baseline", [])), frac(summary["added_since_baseline_cited"])))
    L.append("")
    L.append("## Per query")
    L.append("")
    L.append("| Q | Cited us | Named us | Lookalikes | Who was cited |")
    L.append("|---|---|---|---|---|")
    for q in sorted(results):
        ss = results[q]
        cu = sum(1 for s in ss if s["cited_us"])
        nu = sum(1 for s in ss if s["named_in_answer"])
        imp = sorted({d for s in ss for d in s["lookalikes_cited"]})
        doms = sorted({d for s in ss for d in s["cited_domains"]})
        L.append("| Q%d | %d/%d | %d/%d | %s | %s |" % (
            q, cu, len(ss), nu, len(ss), ", ".join(imp) or "none",
            ", ".join(doms[:8]) + (" (+%d)" % (len(doms) - 8) if len(doms) > 8 else "") or "none"))
    L.append("")
    L.append("## The questions")
    L.append("")
    for q in sorted(questions):
        L.append("- Q%d. %s" % (q, questions[q]))
    base.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return base


# --------------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--engine", choices=["perplexity", "fixture"], required=True)
    ap.add_argument("--fixture", help="path to a fixture JSON (engine fixture)")
    default_q = HERE / "queries.json"
    if not default_q.exists():
        default_q = HERE / "queries.example.json"
    ap.add_argument("--queries", default=str(default_q))
    ap.add_argument("--only", help="comma-separated query ids to run, e.g. 6,7,13")
    ap.add_argument("--samples", type=int, default=1, help="answers per query; 3 gives a rate")
    ap.add_argument("--out", default=str(HERE / "runs"))
    ap.add_argument("--yes", action="store_true", help="required to spend money on a paid engine")
    ap.add_argument("--pause", type=float, default=1.0, help="seconds between paid calls")
    a = ap.parse_args(argv)

    cfg = json.loads(pathlib.Path(a.queries).read_text(encoding="utf-8"))
    questions = {q["id"]: q["text"] for q in cfg["queries"]}
    ids = sorted(questions)
    if a.only:
        want = {int(x) for x in a.only.split(",") if x.strip()}
        unknown = want - set(questions)
        if unknown:
            sys.exit("unknown query id(s): %s" % sorted(unknown))
        ids = sorted(want)

    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    raw, results, note = {}, {}, ""

    if a.engine == "fixture":
        if not a.fixture:
            sys.exit("--engine fixture needs --fixture PATH")
        answers, fx = load_fixture(a.fixture)
        note = fx.get("note", "")
        ids = [q for q in ids if q in answers]
        if not ids:
            sys.exit("the fixture holds none of the requested query ids")
        for q in ids:
            entries = answers[q] if isinstance(answers[q], list) else [answers[q]]
            raw[str(q)] = entries
            results[q] = [score_sample(s, cfg) for s in entries]
        samples = max(len(v) for v in results.values())

    else:
        key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
        if not key:
            sys.exit("PERPLEXITY_API_KEY is not set in the environment. Set it there; this "
                     "script never reads it from a file and never prints it.")
        calls = len(ids) * a.samples
        print("Plan: %d quer%s x %d sample(s) = %d paid call(s) to Perplexity (%s)."
              % (len(ids), "y" if len(ids) == 1 else "ies", a.samples, calls, PPLX_MODEL))
        if not a.yes:
            sys.exit("Nothing sent. Re-run with --yes to spend on these calls.")
        samples = a.samples
        for q in ids:
            raw[str(q)], results[q] = [], []
            for i in range(a.samples):
                try:
                    s = ask_perplexity(questions[q], key)
                except EngineError as e:
                    sys.exit("Stopped at Q%d: %s" % (q, e))
                raw[str(q)].append(s)
                results[q].append(score_sample(s, cfg))
                print("  Q%-2d sample %d: %d citations, cited us: %s"
                      % (q, i + 1, results[q][-1]["n_citations"], results[q][-1]["cited_us"]))
                time.sleep(a.pause)

    summary = summarise(results, cfg)
    base = write_report(pathlib.Path(a.out), stamp, a.engine, cfg,
                        {q: questions[q] for q in ids}, results, raw, summary, samples, note)
    g = cfg["groups"]
    print("\nMetric 1 (offer, %s): %d / %d" % ((id_label(g["metric_1_offer"]),) + tuple(summary["metric_1_offer_cited"])))
    print("Metric 2 (non-brand, %s): %d / %d" % ((id_label(g["metric_2_non_brand"]),) + tuple(summary["metric_2_non_brand_cited"])))
    print("Metric 3 (brand clean, %s): %d / %d" % ((id_label(g["metric_3_brand"]),) + tuple(summary["metric_3_brand_clean"])))
    print("Metric 4 (lookalike : ours): %d : %d" % summary["metric_4_lookalike_vs_ours"])
    print("\nWrote %s.json and .md" % base)


if __name__ == "__main__":
    main()
