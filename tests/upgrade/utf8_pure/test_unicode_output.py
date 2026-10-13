"""Pure Unicode stdout checks; no CLI, actor, transport, SQL, subprocess or native replay."""
from copy import deepcopy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from evaluation.upgrade.u2b_accounting import encode,digest

ROOT=Path(__file__).resolve().parents[3]


class UnicodeReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory=ROOT/"evaluation/upgrade/u2c_full_campaign_evidence"
        cls.files={p.name:p.read_bytes() for p in directory.glob("*.json")}
        cls.summary=json.loads(cls.files["RECONCILIATION.json"])
        cls.source=(ROOT/"fixtures/upgrade/u2b/development/D22/agreement.txt").read_bytes()
        cls.doc=(ROOT/"docs/U2C_FULL_CAMPAIGN_RECONCILIATION.md").read_bytes().decode()

    def setUp(self):
        self.guards=[patch("sqlite3.connect",side_effect=AssertionError("SQL forbidden")),
            patch("socket.socket",side_effect=AssertionError("socket forbidden")),
            patch("subprocess.Popen",side_effect=AssertionError("process forbidden")),
            patch("contract_playbook.comparison.run_actor",side_effect=AssertionError("actor forbidden")),
            patch("builtins.open",side_effect=AssertionError("file I/O forbidden")),
            patch("pathlib.Path.open",side_effect=AssertionError("path I/O forbidden"))]
        for guard in self.guards:guard.start()
        self.addCleanup(lambda:[g.stop() for g in reversed(self.guards)])
        self.payload={"mode":"scripted-local-double","source":self.source.decode(),
                      "observed_counts":deepcopy(self.summary["remaining_campaign"]),"actual_cost_usd":None}

    def test_actual_fixture_contains_astral_combining_greek_and_crlf(self):
        text=self.payload["source"]
        self.assertIn("\U0001f9fe",text);self.assertIn("Cafe\u0301",text)
        self.assertIn("\u03a9",text);self.assertIn(b"\r\n",self.source)

    def test_cp1252_print_reproduces_unicode_error_without_changing_payload(self):
        before=encode(self.payload);buffer=io.BytesIO()
        stream=io.TextIOWrapper(buffer,encoding="cp1252",errors="strict")
        with self.assertRaises(UnicodeEncodeError):print(encode(self.payload).decode(),file=stream)
        stream.flush();self.assertEqual(buffer.getvalue(),b"")
        self.assertEqual(encode(self.payload),before);stream.detach()

    def test_utf8_print_preserves_exact_json_and_original_source_bytes(self):
        before=encode(self.payload);buffer=io.BytesIO()
        stream=io.TextIOWrapper(buffer,encoding="utf-8",errors="strict",newline="\n")
        print(before.decode(),file=stream);stream.flush();output=buffer.getvalue();stream.detach()
        self.assertEqual(output,before+b"\n")
        restored=json.loads(output)
        self.assertEqual(restored,self.payload)
        self.assertEqual(restored["source"].encode(),self.source)
        self.assertEqual(digest(encode(restored)),digest(before))
        self.assertIsNone(restored["actual_cost_usd"])

    def test_print_reconfigure_to_utf8_changes_encoding_only(self):
        original=encode(self.payload);buffer=io.BytesIO()
        stream=io.TextIOWrapper(buffer,encoding="cp1252",errors="strict",newline="\n")
        stream.reconfigure(encoding="utf-8",errors="strict")
        print(original.decode(),file=stream);stream.flush()
        self.assertEqual(buffer.getvalue(),original+b"\n");stream.detach()
        self.assertEqual(encode(self.payload),original)

    def test_exact_documented_argv_matches_actual_main_utf8_receipt(self):
        receipt=json.loads(self.files["S09_UTF8_REPORT_COMMAND.redacted.json"])
        expected=["py","-3.11","-X","utf8","-B","scripts/u2c_coordinator.py","report","--campaign","work/upgrade-u2c"]
        self.assertEqual(receipt["argv"],expected);self.assertEqual(receipt["exit_code"],0)
        self.assertIn(" ".join(expected),self.doc)
        self.assertFalse(receipt["actor_replayed"]);self.assertFalse(receipt["source_edited"])
        self.assertTrue(receipt["raw_unchanged"])

    def test_original_failure_unknown_counters_not_zero_or_actor_failure(self):
        error=json.loads(self.files["S09_DEFAULT_REPORT_ERROR.json"])
        self.assertEqual(error["exception_class"],"UnicodeEncodeError")
        self.assertIsNone(error["observed_counts"]);self.assertIsNone(error["safety"])
        native=json.loads(self.files["S09_NATIVE_EXECUTION.redacted.json"])
        self.assertEqual([c["exit_code"] for c in native["commands"]],[0,1])
        self.assertEqual(self.summary["report_failure"]["utf8_report_exit"],0)

    def test_reconciled_denominators_and_negative_result_keep_history_separate(self):
        current=self.summary["remaining_campaign"];old=self.summary["historical_separate"]
        self.assertEqual((current["unique_existing_catalog_tasks"],current["terminal_slots"],current["pending_slots"]),(34,68,0))
        self.assertEqual(current["required_handoffs"]+current["unnecessary_handoffs"],68)
        self.assertEqual((current["authored_local_callbacks"],current["pair_ties"],current["business_completions"]),(560,34,0))
        self.assertEqual((old["actor_slots"],old["authored_local_callbacks"]),(4,33))
        self.assertEqual(old["task_ids"],["D15","C11"])
        self.assertFalse(set(old["task_ids"])&set(self.summary["task_order"]))
        self.assertFalse(self.summary["semantic_quality_evidence"])
        self.assertIsNone(current["actual_cost_usd"]);self.assertIsNone(current["cost_per_completed_task_usd"])

    def test_copied_receipts_bound_and_private_values_redacted(self):
        p=json.loads(self.files["PROVENANCE.json"])
        self.assertEqual(len(p["entries"]),7);self.assertFalse(p["full_raw_campaign_republished"])
        for e in p["entries"]:
            raw=self.files[e["path"]]
            self.assertEqual(digest(raw),e["sha256"]);self.assertEqual(len(raw),e["bytes"])
            self.assertNotIn(b"Users",raw);self.assertNotIn(b"coordination",raw)
            if e["redaction"]=="none":self.assertEqual(e["original_sha256"],e["sha256"])
        self.assertEqual(self.summary["evidence_provenance_sha256"],digest(self.files["PROVENANCE.json"]))


if __name__=="__main__":unittest.main()
