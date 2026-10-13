"""Static exposed input inventory. No actor, network, database or score execution."""
import hashlib
import json
from pathlib import PurePosixPath


class InputsInvalid(ValueError):
    pass


def require(condition):
    if not condition: raise InputsInvalid("U2B_INPUT_INVENTORY_INVALID")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_path(value, prefix):
    require(isinstance(value,str) and value.startswith(prefix) and "\\" not in value
            and not PurePosixPath(value).is_absolute() and all(p not in {".",".."} for p in value.split("/")))


def referenced_paths(catalog):
    result=["evaluation/upgrade/U2B_INPUTS.json"]
    for case in catalog["cases"]:
        path=case["case_path"];safe_path(path,"fixtures/upgrade/u2b/")
        result.extend([path+"/manifest.json",path+"/PROVENANCE.json"])
        result.extend(path+"/"+key+".txt" for key in case["document_sha256"])
    for value in catalog["scorer_only_labels"].values():
        safe_path(value["path"],"evaluation/upgrade/u2b_labels/")
        result.append(value["path"])
    return result


def validate_catalog(catalog_raw, files):
    try:
        return _validate(json.loads(catalog_raw),files)
    except InputsInvalid: raise
    except Exception: raise InputsInvalid("U2B_INPUT_INVENTORY_INVALID") from None


def _validate(catalog,files):
    require(catalog["schema_version"]==1 and catalog["version"]=="U2-B-1.0"
            and catalog["fictional"] is True and catalog["label_exposed"] is True
            and catalog["counts"]=={"development":24,"capability":12})
    require(catalog["historical_v1"]["case_count"]==42
            and catalog["historical_v1"]["freeze_sha256"]=="8ae16854230fd754760c38a205f698857fdbdb3f75e0da92ee16cd9daac3b666")
    require(catalog["main_unseen"]=={"owner":"main","authored_by_worker":False,"paths_supplied":False,"worker_access":False})
    cases=catalog["cases"]
    require(len(cases)==36 and len({c["task_id"] for c in cases})==36 and len({c["case_path"] for c in cases})==36)
    require(len(catalog["families"])==6 and len(set(catalog["families"]))==6)
    cohorts={}; fingerprints=set(); labels={}
    for split,entry in catalog["scorer_only_labels"].items():
        require(split in {"development","capability"})
        safe_path(entry["path"],"evaluation/upgrade/u2b_labels/")
        raw=files[entry["path"]];require(digest(raw)==entry["sha256"])
        value=json.loads(raw);require(value["split"]==split and value["label_exposed"] is True)
        labels[split]={v["task_id"]:v for v in value["labels"]}
        require(len(labels[split])==catalog["counts"][split]==len(value["labels"]))
    for case in cases:
        split,family,path=case["split"],case["family"],case["case_path"]
        safe_path(path,"fixtures/upgrade/u2b/"+split+"/")
        require(split in {"development","capability"} and family in catalog["families"])
        cohorts[split,family]=cohorts.get((split,family),0)+1
        mr=files[path+"/manifest.json"];pr=files[path+"/PROVENANCE.json"]
        require(digest(mr)==case["manifest_sha256"] and digest(pr)==case["provenance_sha256"])
        manifest,provenance=json.loads(mr),json.loads(pr)
        require(manifest["schema_version"]==1 and manifest["fictional"] is True
                and 1<=len(manifest["documents"])<=3)
        hashes={}
        blocks=0;total=0
        for i,entry in enumerate(manifest["documents"]):
            key=entry["id"];require(key=="agreement" if i==0 else key in {"A1","A2"})
            require(entry["file"]==key+".txt" and entry["type"]==("base" if i==0 else "amendment") and key not in hashes)
            raw=files[path+"/"+key+".txt"];txt=raw.decode("utf-8")
            require(b"\x00" not in raw and len(raw)<=65536 and txt.startswith("Authored fictional"))
            count=sum(line.startswith("Section ") for line in txt.splitlines())
            require(1<=count<=48);blocks+=count+1;total+=len(raw);hashes[key]=digest(raw)
        require(total<=65536 and blocks<=48 and hashes==case["document_sha256"])
        require(hashes["agreement"] not in fingerprints);fingerprints.add(hashes["agreement"])
        require(provenance["task_id"]==case["task_id"] and provenance["split"]==split
                and provenance["family"]==family and provenance["documents"]==hashes
                and provenance["manifest_sha256"]==digest(mr) and provenance["license"]=="MIT"
                and provenance["fictional"] is True and provenance["external_data"] is False
                and provenance["near_duplicate_review"]["independent_samples"] is False)
        label=labels[split][case["task_id"]]
        require(label["source_sha256"]==hashes and label["fictional"] is True
                and label["label_exposed"] is True and label["worker_authored"] is True)
    require(all(cohorts.get(("development",f))==4 and cohorts.get(("capability",f))==2 for f in catalog["families"]))
    return {"status":"passed","development_tasks":24,"capability_tasks":12,"families":6,
            "unique_source_digests":len(fingerprints),"label_exposure":"worker-authored/exposed synthetic fiction",
            "historical_v1_cases":42,"main_unseen_accessed":False,"actor_calls":0,"outcome_scores":0}
