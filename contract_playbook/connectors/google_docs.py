"""U2-A pure Docs copy/edit contracts. No OAuth, HTTP or remote write executor."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re
import time

from ..common import ReviewError, canonical, parse_json, sha256
from ..proposal_check import ProposalInvalid, check_proposal

DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DOCS_HOST = "docs.googleapis.com"
DRIVE_HOST = "www.googleapis.com"
MIME = "application/vnd.google-apps.document"
MAX_RESPONSE_BYTES = 256 * 1024
MAX_TEXT_BYTES = 64 * 1024
GET_PARAMS = {"includeTabsContent": True, "suggestionsViewMode": "SUGGESTIONS_INLINE"}
_EMPTY = {"headers", "footers", "footnotes", "lists", "namedRanges", "inlineObjects",
          "positionedObjects", "suggestedDocumentStyleChanges", "suggestedNamedStylesChanges",
          "commentAnchors", "dropdownDefinitions", "comments", "suggestions"}


class DocsFailure(ValueError):
    """Only host-authored status codes are emitted."""
    def __init__(self, status):
        self.status = status
        super().__init__(status)


def require(condition, status="DOCUMENT_SCHEMA_REJECTED"):
    if not condition:
        raise DocsFailure(status)


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value), "INVALID_OPERATOR_IDENTIFIER")
    return value


def opaque_revision(value):
    require(isinstance(value, str) and 0 < len(value) <= 256
            and all(33 <= ord(char) <= 126 for char in value), "REVISION_REQUIRED")
    return value


def utf16_units(text):
    require(isinstance(text, str) and not any(0xD800 <= ord(char) <= 0xDFFF for char in text), "INVALID_UNICODE")
    return len(text.encode("utf-16-le")) // 2


def docs_index(text, codepoint_offset):
    require(type(codepoint_offset) is int and 0 <= codepoint_offset <= len(text), "INVALID_OFFSET")
    return 1 + utf16_units(text[:codepoint_offset])


@dataclass(frozen=True)
class OperatorScope:
    account_id: str
    source_document_id: str
    sandbox_folder_id: str
    run_id: str
    copy_name: str

    def __post_init__(self):
        for value in (self.account_id, self.source_document_id, self.sandbox_folder_id, self.run_id):
            identifier(value)
        require(isinstance(self.copy_name, str) and 0 < len(self.copy_name) <= 120
                and not any(ord(char) < 32 for char in self.copy_name), "INVALID_COPY_NAME")


@dataclass(frozen=True)
class LocalGrant:
    account_id: str
    scopes: frozenset[str]
    mode: str = "local-double"

    def __post_init__(self):
        identifier(self.account_id)
        require(type(self.scopes) is frozenset, "SCOPE_DENIED")


def check_grant(grant, operator):
    require(isinstance(grant, LocalGrant) and grant.mode == "local-double", "REMOTE_DISABLED")
    require(grant.account_id == operator.account_id, "ACCOUNT_DRIFT")
    require(grant.scopes == frozenset({DRIVE_FILE_SCOPE}), "SCOPE_DENIED")


def remote_auth(main_runtime_loader):
    """Future main-owned loader seam; never reads credentials in U2-A."""
    raise DocsFailure("REMOTE_DISABLED")


@dataclass(frozen=True)
class Snapshot:
    account_id: str
    document_id: str
    revision_id: str
    tab_id: str
    text: str
    body_sha256: str

    @property
    def text_sha256(self):
        return sha256(self.text.encode("utf-8"))


def keys(value, required, optional=frozenset()):
    require(isinstance(value, dict) and required <= set(value) and not set(value) - required - optional)


def empty_fields(value, allowed):
    for name in allowed & set(value):
        require(value[name] in ({}, []))


def decode_document(raw, account_id, expected_document_id):
    """Parse an unmasked includeTabsContent response, never the legacy first-tab body."""
    identifier(account_id)
    identifier(expected_document_id)
    try:
        require(type(raw) is bytes and len(raw) <= MAX_RESPONSE_BYTES, "RESPONSE_LIMIT")
        document = parse_json(raw, MAX_RESPONSE_BYTES)
        keys(document, {"documentId", "revisionId", "tabs", "suggestionsViewMode"},
             {"title", "commentsViewMode", "body", "documentStyle", "namedStyles"} | _EMPTY)
        require(document["documentId"] == expected_document_id, "DOCUMENT_IDENTITY_DRIFT")
        require(document["suggestionsViewMode"] == "SUGGESTIONS_INLINE")
        empty_fields(document, _EMPTY | {"body", "documentStyle", "namedStyles"})
        require(document.get("commentsViewMode", "COMMENTS_VIEW_MODE_OMITTED") == "COMMENTS_VIEW_MODE_OMITTED")
        tabs = document["tabs"]
        require(isinstance(tabs, list) and len(tabs) == 1, "UNSUPPORTED_TABS")
        tab = tabs[0]
        keys(tab, {"tabProperties", "documentTab"}, {"childTabs"})
        require(tab.get("childTabs", []) == [], "UNSUPPORTED_TABS")
        properties = tab["tabProperties"]
        keys(properties, {"tabId"}, {"title", "index", "nestingLevel", "parentTabId", "iconEmoji"})
        require(properties.get("parentTabId", "") == "" and properties.get("nestingLevel", 0) == 0
                and properties.get("index", 0) == 0
                and type(properties.get("index", 0)) is int
                and type(properties.get("nestingLevel", 0)) is int, "UNSUPPORTED_TABS")
        tab_id = properties["tabId"]
        require(isinstance(tab_id, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,128}", tab_id))
        content_tab = tab["documentTab"]
        keys(content_tab, {"body"}, _EMPTY | {"documentStyle", "namedStyles"})
        empty_fields(content_tab, _EMPTY)
        require(isinstance(content_tab.get("documentStyle", {}), dict)
                and isinstance(content_tab.get("namedStyles", {}), dict))
        # Global styles are not changed. Header/footer links and suggested styles are unsupported.
        require(not any("HeaderId" in name or "FooterId" in name
                        for name in content_tab.get("documentStyle", {})))
        body = content_tab["body"]
        keys(body, {"content"})
        content = body["content"]
        require(isinstance(content, list) and 2 <= len(content) <= 129)
        section = content[0]
        keys(section, {"endIndex", "sectionBreak"}, {"startIndex"})
        require(type(section.get("startIndex", 0)) is int and section.get("startIndex", 0) == 0
                and type(section["endIndex"]) is int and section["endIndex"] == 1)
        keys(section["sectionBreak"], set(), {"sectionStyle"})
        section_style = section["sectionBreak"].get("sectionStyle", {})
        require(isinstance(section_style, dict) and all(
            name in {"sectionType", "contentDirection", "columnSeparatorStyle"}
            and value == {"sectionType": "CONTINUOUS", "contentDirection": "LEFT_TO_RIGHT",
                          "columnSeparatorStyle": "NONE"}[name] for name, value in section_style.items()))
        cursor, chunks = 1, []
        for paragraph in content[1:]:
            keys(paragraph, {"startIndex", "endIndex", "paragraph"})
            require(type(paragraph["startIndex"]) is int and paragraph["startIndex"] == cursor)
            props = paragraph["paragraph"]
            keys(props, {"elements"}, {"paragraphStyle"})
            style = props.get("paragraphStyle", {})
            require(isinstance(style, dict) and all(
                name in {"namedStyleType", "direction"}
                and value == {"namedStyleType": "NORMAL_TEXT", "direction": "LEFT_TO_RIGHT"}[name]
                for name, value in style.items()))
            elements = props["elements"]
            require(isinstance(elements, list) and 1 <= len(elements) <= 64)
            paragraph_text = []
            for element in elements:
                keys(element, {"startIndex", "endIndex", "textRun"})
                require(type(element["startIndex"]) is int and element["startIndex"] == cursor)
                keys(element["textRun"], {"content"}, {"textStyle"})
                require(element["textRun"].get("textStyle", {}) == {})
                text = element["textRun"]["content"]
                require(isinstance(text, str) and bool(text) and "\r" not in text
                        and not any(ord(char) < 32 and char not in "\n\t" for char in text))
                cursor += utf16_units(text)
                require(type(element["endIndex"]) is int and element["endIndex"] == cursor)
                paragraph_text.append(text)
            joined = "".join(paragraph_text)
            require(joined.endswith("\n") and "\n" not in joined[:-1])
            require(type(paragraph["endIndex"]) is int and paragraph["endIndex"] == cursor)
            chunks.append(joined)
        text = "".join(chunks)
        require(len(text.encode("utf-8")) <= MAX_TEXT_BYTES, "TEXT_LIMIT")
        return Snapshot(account_id, expected_document_id, opaque_revision(document["revisionId"]),
                        tab_id, text, sha256(canonical(body)))
    except DocsFailure:
        raise
    except (ReviewError, KeyError, TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        raise DocsFailure("DOCUMENT_SCHEMA_REJECTED") from None


def read_local(operator, grant, double, *, seconds=5, clock=time.monotonic, cancel=lambda: False):
    check_grant(grant, operator)
    require(getattr(double, "mode", None) == "local-double", "REMOTE_DISABLED")
    require(type(seconds) in (int, float) and math.isfinite(seconds) and 0 < seconds <= 10, "INVALID_DEADLINE")
    deadline = clock() + seconds
    require(not cancel(), "CANCELLED")
    try:
        raw = double.get_document(operator.source_document_id, dict(GET_PARAMS), MAX_RESPONSE_BYTES, deadline)
    except KeyboardInterrupt:
        raise DocsFailure("CANCELLED") from None
    except Exception:
        raise DocsFailure("LOCAL_READ_FAILED") from None
    require(not cancel(), "CANCELLED")
    require(clock() < deadline, "READ_DEADLINE")
    result = decode_document(raw, grant.account_id, operator.source_document_id)
    require(not cancel(), "CANCELLED")
    require(clock() < deadline, "READ_DEADLINE")
    return result


@dataclass(frozen=True)
class Intent:
    encoded: bytes

    @property
    def sha256(self):
        return sha256(self.encoded)

    @property
    def value(self):
        return parse_json(self.encoded, 96 * 1024)


def make_intent(value):
    raw = canonical(value)
    require(len(raw) <= 96 * 1024, "INTENT_LIMIT")
    return Intent(raw)


def validate_approval(intent, approval):
    keys(approval, {"decision", "intent_sha256", "account_id"}, {"reviewer_label"})
    value = intent.value
    require(approval["decision"] == "approve" and approval["intent_sha256"] == intent.sha256
            and approval["account_id"] == value["operator"]["account_id"], "APPROVAL_REQUIRED")
    return {"approval_bound": True, "reviewer_identity": "operator_annotation_not_authenticated"}


def mechanical(snapshot, packet, policy_raw, manifest_raw):
    try:
        report = check_proposal(packet, {"agreement": snapshot.text.encode()}, policy_raw, manifest_raw)
    except ProposalInvalid:
        raise DocsFailure("PROPOSAL_REJECTED") from None
    require(packet["domain_status"] == "PENDING_REVIEW" and bool(packet["patches"]), "INCOMPLETE_OR_NO_EDIT")
    return report


def prepare_copy(operator, grant, source, packet, policy_raw, manifest_raw):
    check_grant(grant, operator)
    require(source.account_id == operator.account_id and source.document_id == operator.source_document_id, "DOCUMENT_IDENTITY_DRIFT")
    report = mechanical(source, packet, policy_raw, manifest_raw)
    binding = {"schema_version": 1, "kind": "copy", "mode": "local-double",
               "operator": asdict(operator), "source_revision": source.revision_id,
               "source_tab_id": source.tab_id, "source_body_sha256": source.body_sha256,
               "source_sha256": source.text_sha256, "proposal_sha256": packet["proposal_sha256"],
               "expected_copy_sha256": report["expected_copy_sha256"]}
    marker = sha256(canonical(binding))
    value = {**binding, "copy_marker": marker, "request": {"host": DRIVE_HOST, "method": "POST",
        "path": "/drive/v3/files/" + operator.source_document_id + "/copy",
        "query": {"fields": "id,mimeType,parents,appProperties,trashed", "copyComments": False},
        "body": {"name": operator.copy_name, "parents": [operator.sandbox_folder_id],
                 "appProperties": {"cp_intent": marker, "cp_run": sha256(operator.run_id.encode())}}}}
    return make_intent(value)


def matching_copy(copy_intent, metadata, target_document_id):
    value = copy_intent.value
    require(value["kind"] == "copy", "INTENT_KIND")
    identifier(target_document_id)
    keys(metadata, {"id", "mimeType", "parents", "appProperties", "trashed"})
    require(metadata["id"] == target_document_id and target_document_id != value["operator"]["source_document_id"], "COPY_TARGET_REQUIRED")
    require(metadata["mimeType"] == MIME and metadata["trashed"] is False
            and metadata["parents"] == [value["operator"]["sandbox_folder_id"]]
            and metadata["appProperties"] == value["request"]["body"]["appProperties"], "COPY_PROVENANCE_MISMATCH")


def reconcile_copy(copy_intent, listing, operator_target_document_id):
    keys(listing, {"files"}, {"kind", "nextPageToken", "incompleteSearch"})
    require(len(canonical(listing)) <= 32 * 1024, "RESPONSE_LIMIT")
    require(listing.get("kind", "drive#fileList") == "drive#fileList"
            and type(listing.get("incompleteSearch", False)) is bool
            and isinstance(listing.get("nextPageToken", ""), str), "DOCUMENT_SCHEMA_REJECTED")
    if listing.get("incompleteSearch", False) or listing.get("nextPageToken"):
        return {"disposition": "RECONCILIATION_REQUIRED", "automatic_retry": False}
    candidates = listing["files"]
    require(isinstance(candidates, list) and len(candidates) <= 2, "RECONCILIATION_REQUIRED")
    if len(candidates) != 1:
        return {"disposition": "RECONCILIATION_REQUIRED", "automatic_retry": False}
    matching_copy(copy_intent, candidates[0], operator_target_document_id)
    return {"disposition": "COPY_METADATA_CONFIRMED", "automatic_retry": False,
            "target_document_id": operator_target_document_id, "body_readback_required": True}


def prepare_edit(operator, grant, copy_intent, copy_approval, operator_target_document_id,
                 copy_metadata, target, source_now, packet, policy_raw, manifest_raw):
    check_grant(grant, operator)
    validate_approval(copy_intent, copy_approval)
    value = copy_intent.value
    require(value["operator"] == asdict(operator), "OPERATOR_DRIFT")
    matching_copy(copy_intent, copy_metadata, operator_target_document_id)
    require(source_now.document_id == operator.source_document_id
            and source_now.account_id == target.account_id == operator.account_id
            and target.document_id == operator_target_document_id, "DOCUMENT_IDENTITY_DRIFT")
    require(source_now.revision_id == value["source_revision"]
            and source_now.text_sha256 == value["source_sha256"]
            and source_now.body_sha256 == value["source_body_sha256"], "SOURCE_REVISION_DRIFT")
    require(target.text == source_now.text and target.body_sha256 == source_now.body_sha256, "COPY_PREIMAGE_MISMATCH")
    report = mechanical(source_now, packet, policy_raw, manifest_raw)
    require(packet["proposal_sha256"] == value["proposal_sha256"]
            and report["expected_copy_sha256"] == value["expected_copy_sha256"], "PROPOSAL_DRIFT")
    requests = []
    for edit in sorted(packet["patches"], key=lambda patch: patch["start"], reverse=True):
        start, end, replacement = edit["start"], edit["end"], edit["replacement"]
        require(end <= len(target.text) - 1 and "\n" not in target.text[start:end]
                and "\n" not in replacement and "\r" not in replacement
                and not any(ord(char) < 32 or 0xE000 <= ord(char) <= 0xF8FF for char in replacement), "UNSUPPORTED_EDIT")
        first, last = docs_index(target.text, start), docs_index(target.text, end)
        requests.extend(({"deleteContentRange": {"range": {"startIndex": first, "endIndex": last, "tabId": target.tab_id}}},
                         {"insertText": {"location": {"index": first, "tabId": target.tab_id}, "text": replacement}}))
    require(report["expected_copy_sha256"] != target.text_sha256, "INCOMPLETE_OR_NO_EDIT")
    return make_intent({"schema_version": 1, "kind": "edit", "mode": "local-double",
        "operator": asdict(operator), "copy_intent_sha256": copy_intent.sha256,
        "target_document_id": target.document_id, "target_tab_id": target.tab_id,
        "target_revision": target.revision_id, "source_revision": source_now.revision_id,
        "source_tab_id": source_now.tab_id, "source_body_sha256": source_now.body_sha256,
        "target_body_sha256": target.body_sha256,
        "source_sha256": source_now.text_sha256, "proposal_sha256": packet["proposal_sha256"],
        "preimage_sha256": target.text_sha256, "expected_copy_sha256": report["expected_copy_sha256"],
        "request": {"host": DOCS_HOST, "method": "POST", "path": "/v1/documents/" + target.document_id + ":batchUpdate",
                    "body": {"requests": requests, "writeControl": {"requiredRevisionId": target.revision_id}}}})


def validate_edit_preconditions(edit_intent, approval, target, source_now):
    validate_approval(edit_intent, approval)
    value = edit_intent.value
    require(value["kind"] == "edit", "INTENT_KIND")
    require(target.document_id == value["target_document_id"]
            and target.document_id != value["operator"]["source_document_id"]
            and target.account_id == source_now.account_id == value["operator"]["account_id"]
            and target.tab_id == value["target_tab_id"], "DOCUMENT_IDENTITY_DRIFT")
    require(source_now.document_id == value["operator"]["source_document_id"]
            and source_now.revision_id == value["source_revision"]
            and source_now.text_sha256 == value["source_sha256"]
            and source_now.tab_id == value["source_tab_id"]
            and source_now.body_sha256 == value["source_body_sha256"], "SOURCE_REVISION_DRIFT")
    require(target.revision_id == value["target_revision"] and target.text_sha256 == value["preimage_sha256"]
            and target.body_sha256 == value["target_body_sha256"], "TARGET_REVISION_DRIFT")
    return {"preconditions": "passed", "remote_execution": "disabled"}


def reconcile_edit(edit_intent, readback):
    value = edit_intent.value
    require(value["kind"] == "edit", "INTENT_KIND")
    require(readback.document_id == value["target_document_id"]
            and readback.account_id == value["operator"]["account_id"]
            and readback.tab_id == value["target_tab_id"], "DOCUMENT_IDENTITY_DRIFT")
    if readback.text_sha256 == value["expected_copy_sha256"] and readback.revision_id != value["target_revision"]:
        state = "POSTIMAGE_VERIFIED"
    elif readback.text_sha256 == value["preimage_sha256"] and readback.revision_id == value["target_revision"]:
        state = "PREIMAGE_UNCHANGED_NO_RETRY"
    else:
        state = "RECONCILIATION_REQUIRED"
    return {"disposition": state, "automatic_retry": False, "remote_execution": "disabled"}


def dispatch_remote(intent, approval, main_runtime_loader, transport):
    """Deliberately no remote POST path, retry, URL override or credential loading."""
    raise DocsFailure("REMOTE_DISABLED")

