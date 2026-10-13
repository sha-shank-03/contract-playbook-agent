"""Authored Docs response double; synthetic data only, never a remote client."""
from ..common import canonical


def document_response(document_id, text, revision="synthetic_revision_1", tab_id="t.0"):
    cursor, content = 1, [{"endIndex": 1, "sectionBreak": {"sectionStyle": {}}}]
    for paragraph in text.splitlines(keepends=True):
        end = cursor + sum(2 if ord(char) > 65535 else 1 for char in paragraph)
        content.append({"startIndex": cursor, "endIndex": end, "paragraph": {
            "elements": [{"startIndex": cursor, "endIndex": end, "textRun": {"content": paragraph}}],
            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"}}})
        cursor = end
    return canonical({"documentId": document_id, "revisionId": revision,
                      "suggestionsViewMode": "SUGGESTIONS_INLINE", "tabs": [{
                          "tabProperties": {"tabId": tab_id, "index": 0, "nestingLevel": 0},
                          "documentTab": {"body": {"content": content}}}]})


class ReadDouble:
    mode = "local-double"

    def __init__(self, document_id, response):
        self.document_id, self.response, self.calls = document_id, response, []

    def get_document(self, document_id, params, limit, deadline):
        if document_id != self.document_id:
            raise AssertionError("Double received an unassigned document ID.")
        self.calls.append({"document_id": document_id, "params": params, "limit": limit, "deadline": deadline})
        return self.response
