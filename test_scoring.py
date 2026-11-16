"""Tests for the harness's scoring. Run: python test_scoring.py   (standard library only)

A citation counter that miscounts is worse than none: it would report progress that did not
happen, or hide progress that did. Each test is one way it could lie.

Lookalike domains here use the reserved .example top-level domain (RFC 2606), so no real
organisation is named."""
import json
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_citations as rc  # noqa: E402

CFG = {
    "our_site": "morninglabsai.com",
    "names": ["MorningLabs AI"],
    "related": ["github.com/Morninglabsai", "morningfieldventures.com"],
    "lookalikes": ["morninglabs.example", "morning-labs.example"],
    "groups": {
        "metric_1_offer": [6, 7, 8, 9, 10],
        "metric_2_non_brand": [3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "metric_3_brand": [1, 2],
        "added_since_baseline": [13],
    },
}


class Matching(unittest.TestCase):
    def test_our_site_plain_www_and_subdomain(self):
        for u in ("https://morninglabsai.com/", "https://www.morninglabsai.com/resources/x",
                  "morninglabsai.com/safety", "https://blog.morninglabsai.com/post"):
            self.assertTrue(rc.matches(u, "morninglabsai.com"), u)

    def test_lookalikes_are_not_us(self):
        for u in ("https://morninglabs.example/", "https://morning-labs.example/x",
                  "https://notmorninglabsai.com/", "https://morninglabsai.com.attacker.example/"):
            self.assertFalse(rc.matches(u, "morninglabsai.com"), u)

    def test_path_target_matches_whole_segments_only(self):
        # A shorter name that is a prefix of ours must never count as ours.
        self.assertTrue(rc.matches("https://example.com/acmeco", "example.com/acmeco"))
        self.assertTrue(rc.matches("https://example.com/AcmeCo/repo", "example.com/acmeco"))
        self.assertFalse(rc.matches("https://example.com/acme", "example.com/acmeco"))
        self.assertFalse(rc.matches("https://example.com/acme/repo", "example.com/acmeco"))
        self.assertFalse(rc.matches("https://example.com/", "example.com/acmeco"))

    def test_our_code_org_matches(self):
        self.assertTrue(rc.matches("https://github.com/Morninglabsai", "github.com/Morninglabsai"))
        self.assertTrue(rc.matches("https://github.com/morninglabsai/.github", "github.com/Morninglabsai"))

    def test_garbage_does_not_crash(self):
        for u in ("", "not a url", "http://", "https://[::1"):
            self.assertFalse(rc.matches(u, "morninglabsai.com"))


class Scoring(unittest.TestCase):
    def test_cited_us(self):
        s = rc.score_sample({"answer": "x", "citations": ["https://morninglabsai.com/safety"]}, CFG)
        self.assertTrue(s["cited_us"])
        self.assertEqual(s["lookalikes_cited"], [])

    def test_lookalike_is_flagged_and_not_counted_as_us(self):
        s = rc.score_sample({"answer": "", "citations": ["https://morninglabs.example/"]}, CFG)
        self.assertFalse(s["cited_us"])
        self.assertEqual(s["lookalikes_cited"], ["morninglabs.example"])

    def test_both_config_keys_are_read(self):
        # "lookalikes" is the key going forward; "impostors" is an older name, still honoured.
        for key in ("lookalikes", "impostors"):
            cfg = {"our_site": "example.com", "related": [], key: ["examp1e.example"]}
            s = rc.score_sample({"answer": "", "citations": ["https://examp1e.example/"]}, cfg)
            self.assertEqual(s["lookalikes_cited"], ["examp1e.example"], key)

    def test_related_does_not_count_as_our_site(self):
        s = rc.score_sample({"answer": "", "citations": ["https://morningfieldventures.com/"]}, CFG)
        self.assertFalse(s["cited_us"])
        self.assertEqual(s["related_cited"], ["morningfieldventures.com"])

    def test_named_in_text_is_separate_from_cited(self):
        s = rc.score_sample({"answer": "MorningLabs AI builds agents.", "citations": []}, CFG)
        self.assertTrue(s["named_in_answer"])
        self.assertFalse(s["cited_us"])


class Config(unittest.TestCase):
    def test_names_are_configurable_and_default_to_the_domain(self):
        other = {"our_site": "acmeco.example", "related": [], "lookalikes": []}
        s = rc.score_sample({"answer": "Acmeco builds widgets.", "citations": []}, other)
        self.assertTrue(s["named_in_answer"])          # default: first label of the domain
        other["names"] = ["Acme Company"]
        s = rc.score_sample({"answer": "Acmeco builds widgets.", "citations": []}, other)
        self.assertFalse(s["named_in_answer"])         # explicit names replace the default
        s = rc.score_sample({"answer": "ACME COMPANY builds widgets.", "citations": []}, other)
        self.assertTrue(s["named_in_answer"])          # and match case-insensitively

    def test_id_labels_follow_the_config(self):
        self.assertEqual(rc.id_label([6, 7, 8, 9, 10]), "Q6 to Q10")
        self.assertEqual(rc.id_label([1, 2]), "Q1, Q2")
        self.assertEqual(rc.id_label([3, 5, 9]), "Q3, Q5, Q9")
        self.assertEqual(rc.id_label([]), "none")


class Summary(unittest.TestCase):
    def test_brand_clean_needs_us_and_no_lookalike(self):
        clean = rc.score_sample({"answer": "", "citations": ["https://morninglabsai.com/"]}, CFG)
        mixed = rc.score_sample({"answer": "", "citations": ["https://morninglabsai.com/",
                                                             "https://morninglabs.example/"]}, CFG)
        out = rc.summarise({1: [clean], 2: [mixed]}, CFG)
        self.assertEqual(out["metric_3_brand_clean"], (1, 2))
        self.assertEqual(out["metric_4_lookalike_vs_ours"], (1, 2))

    def test_added_questions_never_leak_into_baseline_numbers(self):
        hit = rc.score_sample({"answer": "", "citations": ["https://morninglabsai.com/"]}, CFG)
        out = rc.summarise({13: [hit]}, CFG)
        self.assertEqual(out["metric_1_offer_cited"], (0, 0))
        self.assertEqual(out["metric_2_non_brand_cited"], (0, 0))
        self.assertEqual(out["added_since_baseline_cited"], (1, 1))

    def test_samples_count_individually(self):
        yes = rc.score_sample({"answer": "", "citations": ["https://morninglabsai.com/"]}, CFG)
        no = rc.score_sample({"answer": "", "citations": ["https://example.com/"]}, CFG)
        out = rc.summarise({6: [yes, no, no]}, CFG)
        self.assertEqual(out["metric_1_offer_cited"], (1, 3))


class ExampleConfig(unittest.TestCase):
    def test_example_config_is_consistent(self):
        cfg = json.loads((HERE / "queries.example.json").read_text(encoding="utf-8"))
        ids = {q["id"] for q in cfg["queries"]}
        self.assertEqual(len(ids), len(cfg["queries"]), "duplicate question id")
        for name, members in cfg["groups"].items():
            self.assertTrue(set(members) <= ids, name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
