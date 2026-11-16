# AEO citation harness

Ask an AI answer engine the questions your buyers ask, and record which websites the answer
cites. Run the same questions every month, and you can see whether your work on answer-engine
optimisation (AEO) is changing anything.

Built by [MorningLabs AI](https://morninglabsai.com). We use it on our own site.

## Why it exists

A citation check done by hand cannot be repeated exactly, so it cannot show a trend. And a trend
is the only thing that shows AEO work did anything. This script asks a fixed set of questions,
the same way each time, and scores the result.

Two things we learned running it, which shaped what it measures:

- **Being indexed is not being cited.** A page can rank, be findable by its own title, and still
  never be quoted in an AI answer.
- **Narrow questions and broad questions are cited differently.** On a broad "who builds X"
  question, engines tend to cite lists and directories. On a narrow, specific question, they
  tend to read the page that answers it most precisely, even on a small site. So the script
  records what kind of page won, not only whether you did.

## What it records

For every question: every domain the answer cited, whether your site was among them, whether
your name appears in the answer text (reported separately, because being named without a link is
a weaker result), and whether a company with a lookalike name was cited instead.

It then scores the run on four numbers:

1. Offer questions that cite your site.
2. Any non-brand question that cites your site.
3. Brand questions that cite you, with no lookalike-name company mixed in.
4. Lookalike-name citations against yours.

## Running it

Python 3.9 or later. Standard library only; nothing to install.

Test the scoring first:

```bash
python test_scoring.py
```

A dry run on the sample answers, which costs nothing:

```bash
python run_citations.py --engine fixture --fixture fixtures/example.json --queries queries.example.json
```

A live run on Perplexity's API. It costs money, so it prints the number of calls and stops unless
you add `--yes`:

```bash
python run_citations.py --engine perplexity --queries queries.example.json --samples 3 --yes
```

The script reads your key from the environment variable `PERPLEXITY_API_KEY`. It never reads a
key from a file, never prints it, and if the key is refused it says so without echoing the
request.

## Pointing it at your own site

Copy `queries.example.json` and change:

- `our_site`: your domain.
- `names`: how your company is written in an answer's text, for the "named but not cited"
  check. Defaults to the first part of your domain.
- `related`: other domains that belong to you, such as a parent company or your code-hosting
  organisation. These are reported, but never counted as your site.
- `lookalikes`: domains of other organisations whose names resemble yours. They are listed so
  that a citation to them is never counted as yours, and so that you can see when an engine
  confuses you with them. Add one only when a run actually shows it.
- `queries`: the questions your buyers ask, in their words.
- `groups`: which question ids feed which number.

## Rules that keep the numbers comparable

1. **Never edit a question in place.** A reworded question is a new question: give it a new id
   and bump `version`.
2. **One sample is a hint; three give a rate.** Answers change between calls. Use `--samples 3`
   for the number you report.
3. **One engine is not every engine.** A run on one engine compares with other runs on that
   engine, and with nothing else. The report says which engine it came from.

## How matching works

Matching is the part that can quietly lie, so it is tested:

- Subdomains count as yours (`blog.example.com` belongs to `example.com`), but only across a dot,
  so a lookalike domain that merely contains your name never does.
- A target with a path, such as a code-hosting organisation, matches whole path segments only, so
  an organisation with a similar name is never counted as yours.
- The tests are mutation-checked: removing the dot from the subdomain rule, or matching a prefix
  instead of a whole segment, each makes a test fail.

## Limits

It measures one engine at a time; Perplexity is the only live adapter so far. It cannot tell you
whether a citation sent anyone to your site, or why an engine chose another page over yours.

## Licence

MIT. See `LICENSE`.
