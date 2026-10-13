"""Pure accounting failures only: mocked callbacks/writers; no files or actor/SQL/process."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from contract_playbook.comparison import PairLimits
from evaluation.upgrade.u2b_accounting import (
    Journal,create_plan,execute_once,report,AccountingInvalid,encode,digest,MAX_RECORD_BYTES)


def plan():
    tasks=[{"task_id":"D15","family":"competing-amendments","source_sha256":{"agreement":"a"*64,"A1":"b"*64,"A2":"c"*64},
            "manifest_sha256":"d"*64,"policy_sha256":"e"*64,"context_sha256":"f"*64},
           {"task_id":"C11","family":"injection-unicode-preservation","source_sha256":{"agreement":"1"*64},
            "manifest_sha256":"2"*64,"policy_sha256":"e"*64,"context_sha256":"3"*64}]
    return create_plan(tasks,PairLimits(seconds=20).public(),"4"*64,"5"*64)


def raw_for(p,slot_id,failure=None):
    slot=next(s for s in p["slots"] if s["slot_id"]==slot_id)
    task=next(t for t in p["tasks"] if t["task_id"]==slot["task_id"])
    packet=None if failure else {"model":p["model"],"strategy":slot["strategy"],"config_sha256":p["config_sha256"],
        "context_sha256":task["context_sha256"],"manifest_sha256":task["manifest_sha256"],
        "playbook":{"sha256":task["policy_sha256"]},"proposal_sha256":"6"*64}
    return {"schema_version":1,"mode":"scripted-local-double","strategy":slot["strategy"],"model":p["model"],
        "limits":deepcopy(p["limits"]),"context_sha256":task["context_sha256"],"packet":packet,
        "state":{"source_sha256":deepcopy(task["source_sha256"]),"current_state":"FAILED" if failure else "PENDING_REVIEW"},
        "failure":failure,"events":[{"diagnostic":"synthetic_failure_sentinel" if failure else "pure_return_control"}],
        "usage":{"steps":3,"local_double_requests":2,"completion_tokens_reserved":4096,
                 "prompt_tokens":None,"completion_tokens":None,"actual_cost_usd":None,"estimated_cost_usd":None},
        "elapsed_seconds":5 if failure=="REQUEST_DEADLINE" else .5}


def score_for(raw,exact=True):
    return {"mechanical_verification":"passed","semantic_quality_evidence":False,
        "raw_label_exact":exact,"proposal_sha256":raw["packet"]["proposal_sha256"],
        "unsafe_proposal_attempts":0,"executed_unsafe_actions":0,
        "pending_approval":True,"verified_completion":False,"required_handoff_preserved":False,"unnecessary_handoff":False}


class PureAccounting(unittest.TestCase):
    def setUp(self):
        self.guards=[patch("sqlite3.connect",side_effect=AssertionError("SQL forbidden")),
                     patch("socket.socket",side_effect=AssertionError("sockets forbidden")),
                     patch("subprocess.Popen",side_effect=AssertionError("children forbidden")),
                     patch("contract_playbook.comparison.run_actor",side_effect=AssertionError("journey forbidden")),
                     patch("builtins.open",side_effect=AssertionError("file I/O forbidden"))]
        for guard in self.guards:guard.start()
        self.addCleanup(lambda:[g.stop() for g in reversed(self.guards)])
        self.p=plan();self.persisted=[];self.j=Journal.create(self.p,self.persisted.append)
        self.first="D15/adaptive"

    def test_intended_four_slots_before_callback_and_started_before_invocation(self):
        def actor():
            self.assertEqual([r["kind"] for r in self.persisted],["INTENDED","STARTED"])
            self.assertEqual(len(self.persisted[0]["payload"]["plan"]["slots"]),4)
            return raw_for(self.p,self.first,"REQUEST_DEADLINE")
        result=execute_once(self.j,self.first,actor)
        self.assertEqual(result["status"],"failed_returned")
        self.assertEqual(self.persisted[-1]["kind"],"RETURNED")

    def test_exact_main_probe_sentinel_retained_before_stop(self):
        sentinel={"failure":"REQUEST_DEADLINE","state":{"current_state":"FAILED"},
                  "events":[{"diagnostic":"synthetic_failure_sentinel"}]}
        result=execute_once(self.j,self.first,lambda:sentinel)
        self.assertEqual(result["raw_result"],sentinel)
        self.assertEqual(result["binding_failure"],"MODE_BINDING")
        r=report(self.j)
        self.assertEqual((r["intended_unique_tasks"],r["intended_actor_slots"],r["started_actor_slots"],
                         r["retained_raw_results"],r["failed_actor_slots"],r["unexecuted_slots"]),(2,4,1,1,1,3))

    def test_deadline_telemetry_and_reservations_are_not_zeroed(self):
        raw=raw_for(self.p,self.first,"REQUEST_DEADLINE")
        execute_once(self.j,self.first,lambda:raw)
        slot=self.j.view()[self.first]
        self.assertEqual(slot["raw_result"]["usage"]["completion_tokens_reserved"],4096)
        self.assertIsNone(slot["raw_result"]["usage"]["prompt_tokens"])
        r=report(self.j)
        self.assertEqual(r["latency_seconds"]["censored_deadlines"],1)
        self.assertIsNone(r["actual_cost_usd"]);self.assertIsNone(r["safety"]["executed_unsafe_actions"])

    def test_exception_before_return_is_recorded_without_exception_body(self):
        def actor():raise RuntimeError("untrusted private diagnostic")
        execute_once(self.j,self.first,actor)
        result=self.j.view()[self.first]
        self.assertEqual(result["status"],"failed_exception");self.assertIsNone(result["raw_result"])
        self.assertEqual(self.persisted[-1]["payload"],{"exception_class":"RuntimeError"})
        self.assertNotIn(b"untrusted private diagnostic",encode(self.persisted))

    def test_keyboard_interrupt_is_interrupted_unknown(self):
        def actor():raise KeyboardInterrupt()
        execute_once(self.j,self.first,actor)
        r=report(self.j)
        self.assertEqual((r["interrupted_unknown_slots"],r["failed_actor_slots"],r["unexecuted_slots"]),(1,0,3))

    def test_unclosed_start_is_interrupted_on_read_only_reload(self):
        self.j.start(self.first)
        loaded=Journal(self.p,self.persisted,lambda _:self.fail("read must not write"))
        r=report(loaded)
        self.assertEqual((r["started_actor_slots"],r["interrupted_unknown_slots"],r["returned_actor_slots"]),(1,1,0))
        self.assertEqual(r["paired"]["interrupted_unknown"],1)
        self.assertEqual(r["paired"]["both_unexecuted"],1)

    def test_interrupted_closure_persists_without_dispatch(self):
        self.j.start(self.first)
        self.j.close_interrupted()
        self.assertEqual(self.persisted[-1]["kind"],"INTERRUPTED_UNKNOWN")
        self.assertEqual(self.j.view()[self.first]["status"],"interrupted_unknown")

    def test_started_slot_and_remaining_slots_cannot_be_retried(self):
        self.j.start(self.first)
        calls=[]
        for slot in (self.first,"D15/fixed-full-context"):
            with self.assertRaises(AccountingInvalid):execute_once(self.j,slot,lambda:calls.append("called"))
        self.assertEqual(calls,[])

    def test_completed_slot_cannot_be_rerun(self):
        execute_once(self.j,self.first,lambda:raw_for(self.p,self.first))
        with self.assertRaises(AccountingInvalid):execute_once(self.j,self.first,lambda:self.fail("rerun"))

    def test_failure_stops_remaining_slot_dispatch(self):
        execute_once(self.j,self.first,lambda:raw_for(self.p,self.first,"REQUEST_DEADLINE"))
        with self.assertRaises(AccountingInvalid):execute_once(self.j,"D15/fixed-full-context",lambda:self.fail("next actor"))
        self.assertEqual(report(self.j)["unexecuted_slots"],3)

    def test_duplicate_return_refused(self):
        execute_once(self.j,self.first,lambda:raw_for(self.p,self.first))
        with self.assertRaises(AccountingInvalid):self.j.returned(self.first,raw_for(self.p,self.first))

    def test_omitted_record_refused(self):
        execute_once(self.j,self.first,lambda:raw_for(self.p,self.first,"REQUEST_DEADLINE"))
        with self.assertRaises(AccountingInvalid):Journal(self.p,[self.persisted[0],self.persisted[2]],lambda _:None)

    def test_duplicate_record_refused(self):
        self.j.start(self.first)
        with self.assertRaises(AccountingInvalid):Journal(self.p,self.persisted+[self.persisted[-1]],lambda _:None)

    def test_record_reordering_refused(self):
        execute_once(self.j,self.first,lambda:raw_for(self.p,self.first))
        with self.assertRaises(AccountingInvalid):Journal(self.p,[self.persisted[0],self.persisted[2],self.persisted[1]],lambda _:None)

    def test_modified_hash_prefix_refused(self):
        self.j.start(self.first);bad=deepcopy(self.persisted);bad[-1]["slot_id"]="C11/adaptive"
        with self.assertRaises(AccountingInvalid):Journal(self.p,bad,lambda _:None)

    def test_missing_planned_slot_refused_even_after_resigning(self):
        bad=deepcopy(self.p);bad["slots"].pop()
        bad["plan_sha256"]=digest(encode({k:v for k,v in bad.items() if k!="plan_sha256"}))
        with self.assertRaises(AccountingInvalid):Journal.create(bad,lambda _:None)

    def test_duplicate_task_identity_refused(self):
        with self.assertRaises(AccountingInvalid):create_plan([self.p["tasks"][0]]*2,self.p["limits"],"4"*64,"5"*64)

    def test_source_plan_replay_refused(self):
        tasks=deepcopy(self.p["tasks"]);tasks[0]["context_sha256"]="7"*64
        other=create_plan(tasks,self.p["limits"],"4"*64,"5"*64)
        with self.assertRaises(AccountingInvalid):Journal(other,self.persisted,lambda _:None)

    def test_started_ack_loss_does_not_dispatch_and_reloads_unknown(self):
        def persist(record):
            self.persisted.append(record)
            if record["kind"]=="STARTED":raise OSError("lost acknowledgement")
        loaded=Journal(self.p,self.persisted,persist);calls=[]
        with self.assertRaises(OSError):execute_once(loaded,self.first,lambda:calls.append("called"))
        self.assertEqual(calls,[])
        reconciled=Journal(self.p,self.persisted,lambda _:None)
        self.assertEqual(reconciled.view()[self.first]["status"],"interrupted_unknown")
        with self.assertRaises(AccountingInvalid):execute_once(reconciled,self.first,lambda:self.fail("retry"))

    def test_return_ack_loss_keeps_failed_raw_result_in_persisted_prefix(self):
        def persist(record):
            self.persisted.append(record)
            if record["kind"]=="RETURNED":raise OSError("lost acknowledgement")
        loaded=Journal(self.p,self.persisted,persist)
        raw=raw_for(self.p,self.first,"REQUEST_DEADLINE")
        with self.assertRaises(OSError):execute_once(loaded,self.first,lambda:raw)
        reloaded=Journal(self.p,self.persisted,lambda _:None)
        self.assertEqual(reloaded.view()[self.first]["raw_result"],raw)
        self.assertEqual(report(reloaded)["retained_raw_results"],1)

    def test_source_identity_mismatch_retained_failed(self):
        raw=raw_for(self.p,self.first);raw["state"]["source_sha256"]["agreement"]="8"*64
        execute_once(self.j,self.first,lambda:raw)
        result=self.j.view()[self.first]
        self.assertEqual(result["binding_failure"],"SOURCE_BINDING");self.assertEqual(result["raw_result"],raw)

    def test_model_config_and_boolean_budget_mismatch_retained(self):
        for mutate in (lambda r:r.update(model="local/other"),
                       lambda r:r["limits"].update(requests=1),
                       lambda r:r["limits"].update(review_decisions=True)):
            p=plan();events=[];j=Journal.create(p,events.append);raw=raw_for(p,self.first);mutate(raw)
            execute_once(j,self.first,lambda:raw)
            self.assertEqual(j.view()[self.first]["binding_failure"],"CONFIG_BINDING")

    def test_context_binding_mismatch_retained_failed(self):
        raw=raw_for(self.p,self.first);raw["context_sha256"]="9"*64
        execute_once(self.j,self.first,lambda:raw)
        self.assertEqual(self.j.view()[self.first]["binding_failure"],"CONTEXT_BINDING")

    def test_manifest_policy_and_packet_config_mismatches(self):
        for mutate in (lambda p:p.update(manifest_sha256="7"*64),
                       lambda p:p["playbook"].update(sha256="7"*64),
                       lambda p:p.update(config_sha256="7"*64)):
            p=plan();events=[];j=Journal.create(p,events.append);raw=raw_for(p,self.first);mutate(raw["packet"])
            execute_once(j,self.first,lambda:raw)
            self.assertEqual(j.view()[self.first]["binding_failure"],"PACKET_IDENTITY_BINDING")

    def test_missing_raw_result_retention_is_explicit(self):
        execute_once(self.j,self.first,lambda:object())
        slot=self.j.view()[self.first]
        self.assertEqual(slot["retention"],"unserializable")
        self.assertEqual((report(self.j)["returned_actor_slots"],report(self.j)["retained_raw_results"]),(1,0))
        self.assertIsNone(report(self.j)["safety"]["executed_unsafe_actions"])

    def test_oversized_return_retains_hash_and_unknown_not_zero(self):
        raw=raw_for(self.p,self.first,"REQUEST_DEADLINE");raw["events"]=[{"large":"x"*MAX_RECORD_BYTES}]
        execute_once(self.j,self.first,lambda:raw)
        slot=self.j.view()[self.first]
        self.assertEqual(slot["retention"],"oversized_not_retained");self.assertEqual(slot["raw_result_sha256"],digest(encode(raw)))
        self.assertEqual(slot["status"],"failed_returned")

    def test_pair_failure_unexecuted_and_fixed_denominator_not_successful_tie(self):
        execute_once(self.j,self.first,lambda:raw_for(self.p,self.first,"REQUEST_DEADLINE"))
        r=report(self.j)
        self.assertEqual(sum(r["paired"].values()),2)
        self.assertEqual((r["paired"]["failure_with_unexecuted"],r["paired"]["both_unexecuted"],r["paired"]["ties"]),(1,1,0))
        self.assertEqual(r["per_family"]["injection-unicode-preservation"]["intended_tasks"],1)

    def test_returns_without_scoring_stay_ungraded_and_safety_unknown(self):
        for slot in self.p["slots"]:execute_once(self.j,slot["slot_id"],lambda s=slot:raw_for(self.p,s["slot_id"]))
        r=report(self.j)
        self.assertEqual((r["returned_actor_slots"],r["scored_slots"],r["paired"]["ungraded"]),(4,0,2))
        self.assertIsNone(r["safety"]["executed_unsafe_actions"])

    def test_scored_pairs_report_observed_wins_and_ties_only(self):
        for slot in self.p["slots"]:execute_once(self.j,slot["slot_id"],lambda s=slot:raw_for(self.p,s["slot_id"]))
        for slot in self.p["slots"]:
            raw=self.j.view()[slot["slot_id"]]["raw_result"]
            self.j.scored(slot["slot_id"],score_for(raw,exact=slot["slot_id"]!="D15/fixed-full-context"))
        r=report(self.j)
        self.assertEqual((r["scored_slots"],r["paired"]["adaptive_wins"],r["paired"]["ties"]),(4,1,1))
        self.assertIsNone(r["cost_per_verified_completion_usd"]);self.assertFalse(r["semantic_quality_evidence"])

    def test_scorer_rejection_preserves_raw_before_pair_failure(self):
        execute_once(self.j,self.first,lambda:raw_for(self.p,self.first))
        self.j.scored(self.first)
        r=report(self.j)
        self.assertEqual(r["failed_actor_slots"],1);self.assertEqual(r["retained_raw_results"],1)
        self.assertEqual(r["paired"]["failure_with_unexecuted"],1)

    def test_empty_or_foreign_prefix_not_zero_run_pass(self):
        with self.assertRaises(AccountingInvalid):Journal(self.p,[],lambda _:None)
        bad=deepcopy(self.persisted);bad[0]["payload"]["plan"]["source_manifest_sha256"]="7"*64
        with self.assertRaises(AccountingInvalid):Journal(self.p,bad,lambda _:None)


if __name__=="__main__":unittest.main()
