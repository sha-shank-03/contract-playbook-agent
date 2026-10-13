"""Guarded pure controls. All new callback results are synthetic, not business execution."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from contract_playbook.comparison import PairLimits
from evaluation.upgrade.u2b_accounting import Journal,execute_once,encode,digest,AccountingInvalid
from evaluation.upgrade.u2c_campaign import (
    create_campaign,validate_campaign,CampaignJournal,make_slice,campaign_report,persist_report,finalize_slice)
from evaluation.upgrade.u2c_review import reviewed_history,reviewer_markdown

ROOT=Path(__file__).resolve().parents[3]


def raw_for(plan,slot_id):
    slot=next(s for s in plan["slots"] if s["slot_id"]==slot_id)
    task=next(t for t in plan["tasks"] if t["task_id"]==slot["task_id"])
    return {"mode":"scripted-local-double","model":plan["model"],"limits":deepcopy(plan["limits"]),
        "strategy":slot["strategy"],"context_sha256":task["context_sha256"],"failure":None,
        "state":{"source_sha256":task["source_sha256"],"current_state":"HANDOFF"},
        "packet":{"model":plan["model"],"strategy":slot["strategy"],"config_sha256":plan["config_sha256"],
            "context_sha256":task["context_sha256"],"manifest_sha256":task["manifest_sha256"],
            "playbook":{"sha256":task["policy_sha256"]},"proposal_sha256":"6"*64},
        "usage":{"local_double_requests":1,"model_calls":0,"prompt_tokens":None,"completion_tokens":None},
        "elapsed_seconds":0.25}


def score_for(raw,complete=False):
    return {"mechanical_verification":"passed","semantic_quality_evidence":False,"raw_label_exact":False,
        "proposal_sha256":raw["packet"]["proposal_sha256"],"unsafe_proposal_attempts":0,"executed_unsafe_actions":0,
        "pending_approval":False,"verified_completion":complete,"required_handoff_preserved":False,"unnecessary_handoff":True}


class PureU2C(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Only static source/evidence byte reads. No actor, native DB, subprocess or CLI execution.
        cls.catalog_raw=(ROOT/"evaluation/upgrade/U2B_INPUTS.json").read_bytes()
        catalog=json.loads(cls.catalog_raw)
        cls.bindings=json.loads((ROOT/"evaluation/upgrade/U2C_BINDINGS.json").read_bytes())
        cls.config=json.loads((ROOT/"evaluation/upgrade/U2C_CONFIG.json").read_bytes())
        cls.saved_markdown=(ROOT/"docs/U2C_REVIEW_REPORT.md").read_bytes()
        cls.saved_report=json.loads((ROOT/"evaluation/upgrade/U2C_REVIEW_REPORT.json").read_bytes())
        cls.remaining_spec=json.loads((ROOT/"evaluation/upgrade/U2C_REMAINING_SPEC.json").read_bytes())
        directory=ROOT/"evaluation/upgrade/u2c_evidence"
        cls.files={p.relative_to(directory).as_posix():p.read_bytes() for p in directory.rglob("*.json")}
        labels={}
        for entry in catalog["scorer_only_labels"].values():
            labels.update({v["task_id"]:v for v in json.loads((ROOT/entry["path"]).read_bytes())["labels"]})
        cls.fixture_inputs={}
        for case in catalog["cases"]:
            if case["task_id"] not in {"D15","C11"}:continue
            base=ROOT/case["case_path"];mr=(base/"manifest.json").read_bytes()
            cls.fixture_inputs[case["task_id"]]={"sources":{d["id"]:(base/d["file"]).read_bytes() for d in json.loads(mr)["documents"]},
                "manifest_raw":mr,"policy_raw":(ROOT/"fixtures/playbooks/buyer-services-v2.json").read_bytes(),
                "label":labels[case["task_id"]]}

    def setUp(self):
        self.guards=[patch("sqlite3.connect",side_effect=AssertionError("SQL forbidden")),
            patch("socket.socket",side_effect=AssertionError("network forbidden")),
            patch("subprocess.Popen",side_effect=AssertionError("process forbidden")),
            patch("contract_playbook.comparison.run_actor",side_effect=AssertionError("actor journey forbidden")),
            patch("builtins.open",side_effect=AssertionError("file I/O forbidden")),
            patch("pathlib.Path.open",side_effect=AssertionError("path I/O forbidden"))]
        for g in self.guards:g.start()
        self.addCleanup(lambda:[g.stop() for g in reversed(self.guards)])
        self.history=reviewed_history(self.files,self.fixture_inputs)
        self.c=create_campaign(self.catalog_raw,self.bindings,self.config,self.history,"a"*64)
        self.saved=[];self.j=CampaignJournal.create(self.c,self.saved.append);self.slices={}

    def complete_slice(self,ids,complete=False):
        reservation=self.j.reserve(ids,self.slices);saved=[]
        journal=Journal.create(reservation["plan"],saved.append)
        for slot in journal.plan["slots"]:
            execute_once(journal,slot["slot_id"],lambda s=slot:raw_for(journal.plan,s["slot_id"]))
        for slot in journal.plan["slots"]:
            journal.scored(slot["slot_id"],score_for(journal.view()[slot["slot_id"]]["raw_result"],complete))
        self.slices[reservation["slice_id"]]=saved
        self.j.finish(reservation["slice_id"],saved)
        return reservation,journal

    def test_complete_34_remaining_and_68_slots_exclude_old_tasks(self):
        self.assertEqual((len(self.c["tasks"]),len(self.c["slots"])),(34,68))
        self.assertFalse(set(self.c["task_order"]) & {"D15","C11"})
        self.assertEqual(self.c["per_split"],{"development":23,"capability":11})

    def test_first_slice_and_six_family_rotation(self):
        self.assertEqual(self.c["task_order"][:2],["D01","C03"])
        self.assertEqual(len({t["family"] for t in self.c["tasks"][:6]}),6)
        self.assertEqual(sum(self.c["per_family"].values()),34)

    def test_equal_unchanged_model_and_limits(self):
        self.assertEqual(encode(self.c["limits"]),encode(PairLimits(seconds=20).public()))
        self.assertEqual(make_slice(self.c,["D01","C03"])["config_sha256"],digest(encode(self.config)))

    def test_catalog_digest_drift_refused(self):
        with self.assertRaises(AccountingInvalid):
            create_campaign(self.catalog_raw+b" ",self.bindings,self.config,self.history,"a"*64)

    def test_source_or_manifest_binding_drift_refused(self):
        for field,value in (("source_sha256",{"agreement":"b"*64}),("manifest_sha256","b"*64),("family","wrong")):
            b=deepcopy(self.bindings);b["tasks"][0][field]=value
            with self.subTest(field=field),self.assertRaises(AccountingInvalid):
                create_campaign(self.catalog_raw,b,self.config,self.history,"a"*64)

    def test_historical_source_context_drift_refused(self):
        b=deepcopy(self.bindings);b["tasks"][14]["context_sha256"]="b"*64
        with self.assertRaises(AccountingInvalid):
            create_campaign(self.catalog_raw,b,self.config,self.history,"a"*64)

    def test_configuration_drift_refused(self):
        config=deepcopy(self.config);config["tools"]=1
        with self.assertRaises(AccountingInvalid):
            create_campaign(self.catalog_raw,self.bindings,config,self.history,"a"*64)

    def test_old_task_or_completion_relabel_refused(self):
        for key,value in (("task_ids",["D15","D01"]),("verified_task_completions",1),("business_unique_tasks",3)):
            h=deepcopy(self.history);h[key]=value
            with self.subTest(key=key),self.assertRaises(AccountingInvalid):
                create_campaign(self.catalog_raw,self.bindings,self.config,h,"a"*64)

    def test_saved_plan_denominator_or_source_drift_refused(self):
        for field,value in (("intended_remaining_actor_slots",64),("source_manifest_sha256","b"*64),
                            ("task_order",self.c["task_order"][1:])):
            c=deepcopy(self.c);c[field]=value
            with self.subTest(field=field),self.assertRaises(AccountingInvalid):validate_campaign(c,self.c)

    def test_historical_tasks_and_three_pair_slice_refused(self):
        for ids in (["D15"],["C11"],["D01","C03","D09"],["D01","D01"],[]):
            with self.subTest(ids=ids),self.assertRaises(AccountingInvalid):make_slice(self.c,ids)

    def test_selection_omission_or_wrong_order_refused(self):
        for ids in (["D09"],["C03","D01"]):
            with self.subTest(ids=ids),self.assertRaises(AccountingInvalid):self.j.reserve(ids,{})

    def test_complete_intent_durable_before_reservation(self):
        self.assertEqual(len(self.saved[0]["payload"]["campaign"]["slots"]),68)
        self.j.reserve(["D01","C03"],{})
        self.assertEqual([r["kind"] for r in self.saved],["INTENDED","RESERVED"])

    def test_intended_checkpoint_failure_never_creates_state(self):
        calls=[]
        def failed(record):calls.append(record);raise OSError("writer refused")
        with self.assertRaises(OSError):CampaignJournal.create(self.c,failed)
        self.assertEqual(len(calls),1);self.assertEqual(calls[0]["kind"],"INTENDED")

    def test_reserved_acknowledgement_loss_blocks_replay_and_later_dispatch(self):
        def lost(record):self.saved.append(record);raise OSError("ack lost")
        self.j.persist=lost
        with self.assertRaises(OSError):self.j.reserve(["D01","C03"],{})
        self.assertEqual(len(self.j.records),1)
        reconciled=CampaignJournal(self.c,self.saved,lambda _:None)
        with self.assertRaises(AccountingInvalid):reconciled.reserve(["D01","C03"],{})
        with self.assertRaises(AccountingInvalid):reconciled.reserve(["D09"],{})
        result=campaign_report(self.c,self.saved,{})
        self.assertEqual(result["reserved_unknown_slots"],4);self.assertIsNone(result["observed_counts"]["started_actor_slots"])

    def test_missing_reserved_prefix_unknown_not_zero(self):
        self.j.reserve(["D01","C03"],{})
        result=campaign_report(self.c,self.j.records,{})
        self.assertEqual(result["known_unexecuted_slots"],64);self.assertEqual(result["paired"]["reserved_unknown"],2)
        self.assertIsNone(result["unexecuted_slots"]);self.assertIsNone(result["local_double_requests"])
        self.assertIsNone(result["safety"]["executed_unsafe_actions"])

    def test_no_execution_report_keeps_old_four_slots_separate(self):
        r=campaign_report(self.c,self.j.records,{})
        self.assertEqual((r["observed_counts"]["started_actor_slots"],r["unexecuted_slots"]),(0,68))
        self.assertEqual(r["historical_evidence"]["actor_slots"],4)
        self.assertEqual(r["historical_evidence"]["verified_task_completions"],0)
        self.assertEqual(r["observed_scored_outcomes"]["verified_completions"],0)
        self.assertIsNone(r["remaining_verified_completion_rate"]);self.assertIsNone(r["actual_cost_usd"])

    def test_complete_slice_handoff_tie_does_not_complete_campaign(self):
        self.complete_slice(["D01","C03"])
        r=campaign_report(self.c,self.j.records,self.slices)
        self.assertEqual(r["paired"]["ties"],2);self.assertEqual(r["unexecuted_slots"],64)
        self.assertEqual(r["observed_counts"]["scored_slots"],4);self.assertFalse(r["complete"])
        self.assertEqual(r["observed_scored_outcomes"]["unnecessary_handoffs"],4)
        self.assertIsNone(r["safety"]["executed_unsafe_actions"])

    def test_all_68_mock_scored_slots_complete_fixed_denominator(self):
        # In-memory synthetic callbacks only. No native actor/model/business results.
        for offset in range(0,34,2):self.complete_slice(self.c["task_order"][offset:offset+2],complete=True)
        r=campaign_report(self.c,self.j.records,self.slices)
        self.assertTrue(r["complete"]);self.assertEqual(r["observed_counts"]["scored_slots"],68)
        self.assertEqual(r["observed_scored_outcomes"]["verified_completions"],68)
        self.assertEqual(r["remaining_verified_completion_rate"],1)
        self.assertEqual(r["historical_evidence"]["verified_task_completions"],0)
        self.assertIsNone(r["actual_cost_usd"]);self.assertFalse(r["semantic_quality_evidence"])

    def test_failed_raw_checkpoint_preserved_and_remaining_denominator_fixed(self):
        res=self.j.reserve(["D01","C03"],{});saved=[];j=Journal.create(res["plan"],saved.append)
        sentinel={"failure":"REQUEST_DEADLINE","state":{"current_state":"FAILED"},"events":[{"diagnostic":"synthetic_failure_sentinel"}]}
        execute_once(j,"D01/adaptive",lambda:sentinel);self.slices[res["slice_id"]]=saved
        self.j.finish(res["slice_id"],saved)
        r=campaign_report(self.c,self.j.records,self.slices)
        self.assertEqual((r["observed_counts"]["failed_actor_slots"],r["unexecuted_slots"]),(1,67))
        self.assertEqual(r["rows"][0]["states"]["adaptive"]["raw_result"],sentinel)
        self.assertEqual(sum(r["paired"].values()),34);self.assertIsNone(r["actual_cost_usd"])
        with self.assertRaises(AccountingInvalid):self.j.reserve(["D09"],self.slices)

    def test_unclosed_start_interrupted_unknown_blocks_next_slice(self):
        res=self.j.reserve(["D01"],{});saved=[];j=Journal.create(res["plan"],saved.append);j.start("D01/adaptive")
        self.slices[res["slice_id"]]=saved
        r=campaign_report(self.c,self.j.records,self.slices)
        self.assertEqual(r["observed_counts"]["interrupted_unknown_slots"],1)
        self.assertEqual(r["paired"]["interrupted_unknown"],1)
        with self.assertRaises(AccountingInvalid):self.j.reserve(["C03"],self.slices)

    def test_ungraded_results_distinct_from_ties(self):
        res=self.j.reserve(["D01"],{});saved=[];j=Journal.create(res["plan"],saved.append)
        for slot in j.plan["slots"]:execute_once(j,slot["slot_id"],lambda s=slot:raw_for(j.plan,s["slot_id"]))
        self.slices[res["slice_id"]]=saved;self.j.finish(res["slice_id"],saved)
        r=campaign_report(self.c,self.j.records,self.slices)
        self.assertEqual(r["paired"]["ungraded"],1);self.assertNotIn("ties",r["paired"])
        self.assertIsNone(r["safety"]["executed_unsafe_actions"])

    def test_finish_acknowledgement_loss_report_reconciles_without_replay(self):
        res=self.j.reserve(["D01"],{});saved=[];j=Journal.create(res["plan"],saved.append)
        for slot in j.plan["slots"]:execute_once(j,slot["slot_id"],lambda s=slot:raw_for(j.plan,s["slot_id"]))
        for slot in j.plan["slots"]:j.scored(slot["slot_id"],score_for(j.view()[slot["slot_id"]]["raw_result"]))
        self.slices[res["slice_id"]]=saved
        def lost(record):self.saved.append(record);raise OSError("ack lost")
        self.j.persist=lost
        with self.assertRaises(OSError):self.j.finish(res["slice_id"],saved)
        r=campaign_report(self.c,self.saved,self.slices)
        self.assertEqual(r["all_scored_slice_prefixes"],1)
        reloaded=CampaignJournal(self.c,self.saved,lambda _:None)
        with self.assertRaises(AccountingInvalid):reloaded.reserve(["D01"],self.slices)

    def test_failed_report_writer_keeps_records_and_does_not_retry(self):
        self.complete_slice(["D01"])
        old=deepcopy(self.j.records);calls=[]
        def failed(value):calls.append(value);raise OSError("report write failed")
        with self.assertRaises(OSError):persist_report(self.c,self.j.records,self.slices,failed)
        self.assertEqual(self.j.records,old);self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]["intended_remaining_actor_slots"],68)

    def test_slice_report_failure_blocks_finished_and_next_dispatch(self):
        res=self.j.reserve(["D01"],{});saved=[];j=Journal.create(res["plan"],saved.append)
        for slot in j.plan["slots"]:execute_once(j,slot["slot_id"],lambda s=slot:raw_for(j.plan,s["slot_id"]))
        for slot in j.plan["slots"]:j.scored(slot["slot_id"],score_for(j.view()[slot["slot_id"]]["raw_result"]))
        self.slices[res["slice_id"]]=saved;before=deepcopy(self.j.records);calls=[]
        def failed(report):calls.append(report);raise OSError("slice report refused")
        with self.assertRaises(OSError):finalize_slice(self.j,res["slice_id"],saved,failed)
        self.assertEqual(self.j.records,before);self.assertEqual(len(calls),1)
        with self.assertRaises(AccountingInvalid):self.j.reserve(["C03"],self.slices)
        self.assertEqual(campaign_report(self.c,self.j.records,self.slices)["observed_counts"]["scored_slots"],2)

    def test_slice_report_ack_loss_preserves_raw_and_refuses_replay(self):
        res=self.j.reserve(["D01"],{});saved=[];j=Journal.create(res["plan"],saved.append)
        for slot in j.plan["slots"]:execute_once(j,slot["slot_id"],lambda s=slot:raw_for(j.plan,s["slot_id"]))
        for slot in j.plan["slots"]:j.scored(slot["slot_id"],score_for(j.view()[slot["slot_id"]]["raw_result"]))
        self.slices[res["slice_id"]]=saved;reports=[]
        def lost(report):reports.append(report);raise OSError("report ack lost")
        with self.assertRaises(OSError):finalize_slice(self.j,res["slice_id"],saved,lost)
        self.assertEqual(reports[0]["retained_raw_results"],2)
        with self.assertRaises(AccountingInvalid):self.j.reserve(["D01"],self.slices)

    def test_report_acknowledgement_loss_never_counts_extra_task(self):
        self.complete_slice(["D01"])
        calls=[]
        def lost(value):calls.append(value);raise OSError("ack lost")
        with self.assertRaises(OSError):persist_report(self.c,self.j.records,self.slices,lost)
        actual=campaign_report(self.c,self.j.records,self.slices)
        self.assertEqual(actual,calls[0]);self.assertEqual(actual["observed_counts"]["started_actor_slots"],2)

    def test_coordinator_chain_omission_duplicate_or_reorder_refused(self):
        self.complete_slice(["D01"])
        for records in (self.j.records[:1]+self.j.records[2:],self.j.records+[self.j.records[-1]],
                        [self.j.records[0],self.j.records[2],self.j.records[1]]):
            with self.subTest(records=len(records)),self.assertRaises(AccountingInvalid):
                campaign_report(self.c,records,self.slices)

    def test_finished_hash_or_foreign_slice_drift_refused(self):
        res,_=self.complete_slice(["D01"])
        changed=deepcopy(self.slices);changed[res["slice_id"]][-1]["record_sha256"]="b"*64
        with self.assertRaises(AccountingInvalid):campaign_report(self.c,self.j.records,changed)
        changed=deepcopy(self.slices);changed["9999"]=[]
        with self.assertRaises(AccountingInvalid):campaign_report(self.c,self.j.records,changed)

    def test_source_slot_plan_mismatch_refused(self):
        res=self.j.reserve(["D01"],{});p=deepcopy(res["plan"]);p["tasks"][0]["context_sha256"]="b"*64
        from evaluation.upgrade.u2b_accounting import create_plan
        p=create_plan(p["tasks"],p["limits"],p["source_manifest_sha256"],p["catalog_sha256"])
        saved=[];Journal.create(p,saved.append)
        with self.assertRaises(AccountingInvalid):campaign_report(self.c,self.j.records,{res["slice_id"]:saved})

    def test_review_exact_negative_quality_result_reproduced(self):
        self.assertEqual((self.history["pair_ties"],self.history["verified_task_completions"],
                          self.history["required_handoffs"],self.history["unnecessary_handoffs"]),(2,0,2,2))
        self.assertEqual(self.history["dispositions"],{"correct":2,"total":12})
        self.assertEqual(self.history["obligation_atoms"],{"correct":6,"total":28})
        self.assertEqual(self.history["model_calls"],0);self.assertEqual(self.history["local_double_requests"],33)

    def test_saved_report_exactly_reproducible_from_original_raw_evidence(self):
        self.assertEqual(self.saved_report,self.history)
        self.assertEqual(self.saved_markdown,reviewer_markdown(self.history).encode())

    def test_shipped_remaining_spec_preserves_complete_selection_and_binding(self):
        for key in ("tasks","slots","task_order","per_family","per_split","config_sha256","catalog_sha256","bindings_sha256"):
            self.assertEqual(self.remaining_spec[key],self.c[key],key)
        self.assertEqual(self.remaining_spec["historical"]["task_ids"],["D15","C11"])
        self.assertEqual(self.remaining_spec["new_native_slots_executed"],0)
        self.assertNotIn("source_manifest_sha256",self.remaining_spec)

    def test_old_pregrading_archive_remains_ungraded(self):
        raw=json.loads(self.files["reviewed-scripted-four-slots/raw-outcomes.json"])
        self.assertTrue(all(r["status"]=="returned_ok_ungraded" for r in raw))
        self.assertFalse(self.history["semantic_quality_evidence"])
        self.assertIn("one execution with two snapshots",reviewer_markdown(self.history))

    def test_redacted_receipt_has_original_hash_and_no_private_paths(self):
        provenance=json.loads(self.files["PROVENANCE.json"])
        main=next(e for e in provenance["entries"] if e["path"]=="MAIN_REVIEW.redacted.json")
        self.assertEqual(main["original_sha256"],self.history["main_review_sha256"])
        self.assertNotEqual(main["original_sha256"],main["sha256"])
        self.assertNotIn(b"Users",self.files["MAIN_REVIEW.redacted.json"])

    def test_evidence_modification_or_missing_artifact_refused(self):
        files=deepcopy(self.files);files["reviewed-scripted-four-slots/raw-outcomes.json"]+=b" "
        with self.assertRaises(AccountingInvalid):reviewed_history(files,self.fixture_inputs)
        files=deepcopy(self.files);del files["mocked-actor-real-persistence/accounting-journal/000002.json"]
        with self.assertRaises(AccountingInvalid):reviewed_history(files,self.fixture_inputs)

    def test_diagnostic_one_callback_adds_zero_business_tasks(self):
        f=self.history["failure_regression"]
        self.assertEqual((f["mocked_actor_callbacks"],f["business_unique_tasks_added"],f["unexecuted_slots"]),(1,0,3))
        self.assertTrue(f["failed_raw_retained"]);self.assertTrue(self.history["original_failed_probe_preserved"])
        self.assertIsNone(f["safety"]["executed_unsafe_actions"]);self.assertIsNone(f["actual_cost_usd"])


if __name__=="__main__":unittest.main()
