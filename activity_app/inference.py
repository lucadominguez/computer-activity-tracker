"""Explicit-click context inference against one OpenAI-compatible endpoint.

Text leaves this computer only when the person clicks Infer context: the text
read from the chosen moments, their window titles, app names and timestamps.
Screenshots, window geometry, file paths and the vault key are never part of the
request. The reply is untrusted input and is validated field by field before the
UI may render it.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_MOMENTS = 20
MAX_PROMPT_CHARS = 12000
MAX_MOMENT_CHARS = 1800
MAX_REPLY_BYTES = 262144
TIMEOUT_SECONDS = 45
ATTEMPTS = 2
CONFIDENCES = ("low", "medium", "high")
TEXT_LIMITS = {"summary": 600, "activity": 200, "task": 300, "next_step": 300}
LIST_LIMITS = {"entities": 12, "open_loops": 8}
ITEM_CHARS = 120
FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
LOOPBACK = ("127.0.0.1", "localhost", "::1")

SYSTEM = (
    "You reconstruct what someone was doing from text read off their own screen. "
    "Use only the supplied moments: never invent names, file paths, URLs or numbers. "
    "Reply with one JSON object and nothing else, with exactly these keys: "
    '{"summary": "one or two sentences on what this work was", '
    '"activity": "the concrete activity", "task": "the task, thread or document in play", '
    '"entities": ["names, files, sites or topics that actually appear in the text"], '
    '"open_loops": ["unfinished threads visible in the text"], '
    '"next_step": "what the person was most likely about to do next", '
    '"confidence": "low"|"medium"|"high", "evidence": ["moment ids you used"]}. '
    "When the text is thin or ambiguous, say so in the summary and use low confidence. "
    "Keep every string under 300 characters."
)
REPAIR = (
    "Your previous reply was rejected: it was not one JSON object with the required keys. "
    "Reply with the JSON object only, no prose and no markdown."
)


class InferenceError(Exception):
    """Base class for the typed failure classes below."""


class NotConfigured(InferenceError):
    """Inference is switched off, or the endpoint is unusable."""


class TransportError(InferenceError):
    """The endpoint could not be reached, refused the request, or answered badly."""


class ShapeError(InferenceError):
    """The provider envelope or its message content is not usable text."""


class SchemaError(InferenceError):
    """The reply is text, but not the required object."""


def endpoint(base_url):
    """Return the chat-completions URL for a configured base address."""
    if not isinstance(base_url, str) or not base_url.strip():
        raise NotConfigured("Add a model endpoint in Settings before using inference.")
    parts = urllib.parse.urlsplit(base_url.strip())
    local = parts.hostname in LOOPBACK
    if parts.username or parts.password or parts.query or parts.fragment:
        raise NotConfigured("The endpoint must not carry credentials, a query or a fragment.")
    if not (parts.hostname and (parts.scheme == "https" or (parts.scheme == "http" and local))):
        raise NotConfigured("Use an https address, or http only for 127.0.0.1.")
    path = (parts.path or "").rstrip("/")
    if not path.endswith("/chat/completions"):
        path = (path or "") + "/chat/completions"
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path or "/chat/completions", "", ""))


def host_label(url):
    return urllib.parse.urlsplit(url).netloc


def _clean(value, limit):
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()[:limit]


def moment_block(items):
    """One text block per moment. Only text, titles, apps and times are used."""
    blocks = []
    for item in items:
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(item["ts"])))
        text = _clean(item.get("text", ""), MAX_MOMENT_CHARS)
        blocks.append(
            f"[{item['id']}] app: {_clean(item.get('app', ''), 80)} | "
            f"title: {_clean(item.get('title', ''), 200)} | at: {when}\n{text}"
        )
    while len(blocks) > 1 and len("\n\n".join(blocks)) > MAX_PROMPT_CHARS:
        blocks.pop(0)
    return "\n\n".join(blocks)[:MAX_PROMPT_CHARS]


def parse_reply(raw, allowed_ids):
    """Validate untrusted model content into the one context object the UI renders."""
    if not isinstance(raw, str) or not raw.strip():
        raise ShapeError("The model returned no usable text.")
    text = raw.strip()
    fenced = FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        reply = json.loads(text)
    except ValueError as exc:
        raise SchemaError("The model reply was not valid JSON.") from exc
    if not isinstance(reply, dict):
        raise SchemaError("The model reply was not a JSON object.")
    context = {}
    for key, limit in TEXT_LIMITS.items():
        value = reply.get(key, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise SchemaError(f"The model reply field {key} was not text.")
        context[key] = _clean(value, limit)
    for key, limit in LIST_LIMITS.items():
        value = reply.get(key, [])
        if value is None:
            value = []
        if not isinstance(value, list):
            raise SchemaError(f"The model reply field {key} was not a list.")
        context[key] = [
            _clean(entry, ITEM_CHARS) for entry in value[:limit] if isinstance(entry, (str, int, float))
        ]
    confidence = reply.get("confidence", "low")
    context["confidence"] = (
        confidence.strip().lower() if isinstance(confidence, str) else "low"
    )
    if context["confidence"] not in CONFIDENCES:
        context["confidence"] = "low"
    evidence = reply.get("evidence", [])
    if not isinstance(evidence, list):
        raise SchemaError("The model reply field evidence was not a list.")
    allowed = list(allowed_ids)
    context["evidence"] = [
        entry for entry in dict.fromkeys(e for e in evidence if isinstance(e, str)) if entry in allowed
    ][:MAX_MOMENTS]
    context["unsourced"] = not context["evidence"]
    if not any(context[key] for key in TEXT_LIMITS):
        raise SchemaError("The model reply carried no context text.")
    return context


def _payload(model, system, user, structured=True):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 700,
    }
    if structured:
        payload["response_format"] = {"type": "json_object"}
    return payload


def complete(url, key, payload, opener):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    if key:
        request.add_header("Authorization", "Bearer " + key)
    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_REPLY_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 400 and "response_format" in payload:
            raise _UnsupportedFormat() from exc
        raise TransportError(
            "The endpoint rejected the request (%s). Check the address, model and key." % exc.code
        ) from exc
    except urllib.error.URLError as exc:
        raise TransportError("The endpoint could not be reached: %s." % exc.reason) from exc
    except (TimeoutError, OSError) as exc:
        raise TransportError("The endpoint did not answer in time.") from exc
    if len(body) > MAX_REPLY_BYTES:
        raise ShapeError("The model reply was too large to be usable.")
    try:
        envelope = json.loads(body.decode("utf-8", "replace"))
    except ValueError as exc:
        raise ShapeError("The endpoint did not return JSON.") from exc
    if not isinstance(envelope, dict) or not isinstance(envelope.get("choices"), list):
        raise ShapeError("The endpoint reply had no choices.")
    if not envelope["choices"]:
        raise ShapeError("The endpoint returned an empty choice list.")
    message = envelope["choices"][0].get("message") if isinstance(envelope["choices"][0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        # Reasoning models can spend the whole budget and leave content null.
        raise ShapeError("The model returned no answer text.")
    return content


class _UnsupportedFormat(Exception):
    """The endpoint refused response_format; retry without it."""


def infer(items, url, model, key="", opener=None):
    """Run one bounded inference. Raises a typed error instead of guessing."""
    opener = opener or urllib.request.urlopen
    if not items:
        raise NotConfigured("Choose at least one saved moment first.")
    if not isinstance(model, str) or not model.strip():
        raise NotConfigured("Add the model name in Settings before using inference.")
    target = endpoint(url)
    user = "Moments, newest last:\n\n" + moment_block(items)
    characters = len(user.encode("utf-8"))
    allowed = [item["id"] for item in items]
    last = None
    for attempt in range(ATTEMPTS):
        raw = None
        try:
            raw = complete(target, key, _payload(model.strip(), SYSTEM, user), opener)
        except _UnsupportedFormat:
            # Some OpenAI-compatible servers refuse response_format; ask again plainly.
            try:
                raw = complete(target, key, _payload(model.strip(), SYSTEM, user, structured=False), opener)
            except InferenceError as exc:
                last = exc
        except InferenceError as exc:
            last = exc
        if raw is not None:
            try:
                context = parse_reply(raw, allowed)
            except InferenceError as exc:
                last = exc
                user = user + "\n\n" + REPAIR
            else:
                return {
                    "context": context,
                    "model": model.strip(),
                    "endpoint": host_label(target),
                    "moments": len(items),
                    "characters": characters,
                    "attempts": attempt + 1,
                }
        if attempt + 1 >= ATTEMPTS:
            break
    raise last or InferenceError("Inference did not complete.")