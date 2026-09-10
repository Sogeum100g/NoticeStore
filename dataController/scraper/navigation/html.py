"""Resolve HTML controls to stable HTTP detail URLs without executing JavaScript.

The resolver intentionally understands a small, declarative subset of browser
navigation.  It never evaluates page JavaScript.  Direct links, literal
``onclick`` navigation, simple function wrappers, standard forms, and the
common jQuery ``data-* -> hidden input -> form.submit()`` pattern are supported.
Unknown code fails closed and returns ``None``.
"""

from __future__ import annotations

import ast
import functools
import re
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import soupsieve
from bs4 import BeautifulSoup, Tag


_PLACEHOLDER_HREFS = {"", "#", "/#"}
_DIRECT_URL_ATTRIBUTES = (
    "href",
    "formaction",
    "data-href",
    "data-url",
    "data-link",
    "data-target-url",
    "data-detail-url",
)
_DETAIL_PATH_HINT_RE = re.compile(
    r"(?:detail|view|read|info|article|boardview|select[^/?#]*info)",
    re.IGNORECASE,
)
_LIST_PATH_HINT_RE = re.compile(r"(?:list|search|index|main)", re.IGNORECASE)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def _http_url(base_url: str, candidate: object) -> Optional[str]:
    value = " ".join(str(candidate or "").split()).strip()
    if not value or value.casefold().startswith("javascript:"):
        return None
    absolute = urljoin(base_url, value)
    parsed = urlsplit(absolute)
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return absolute


def is_http_detail_url(value: object) -> bool:
    parsed = urlsplit(str(value or "").strip())
    return bool(
        parsed.scheme.casefold() in {"http", "https"}
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
    )


def is_placeholder_navigation(element: Tag) -> bool:
    href = " ".join(str(element.get("href") or "").split()).strip()
    parsed = urlsplit(href)
    return bool(
        href in _PLACEHOLDER_HREFS
        or href.casefold().startswith("javascript:")
        or (
            parsed.path in {"", "/"}
            and not parsed.scheme
            and not parsed.netloc
            and not parsed.query
            and bool(parsed.fragment)
        )
    )


def has_navigation_metadata(element: Tag) -> bool:
    if any(
        _http_url("https://resolver.invalid/", element.get(name))
        for name in _DIRECT_URL_ATTRIBUTES
    ):
        return True
    href = str(element.get("href") or "").strip()
    if href.casefold().startswith("javascript:"):
        payload = href.split(":", 1)[1].strip()
        if (
            re.search(r"[A-Za-z_$][\w$]*\s*\(", payload)
            and not re.fullmatch(r"void\s*\(\s*0?\s*\)\s*;?", payload, re.IGNORECASE)
        ):
            return True
    if element.get("onclick"):
        return True
    if element.get("role") == "link" or element.get("formaction") or element.get("form"):
        return True
    return any(
        str(name).casefold().startswith("data-") and str(value or "").strip()
        for name, value in element.attrs.items()
    )


def _balanced_block(source: str, opening_brace: int) -> Optional[str]:
    depth = 0
    quote: Optional[str] = None
    escaped = False
    for index in range(opening_brace, len(source)):
        char = source[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[opening_brace + 1 : index]
    return None


def _split_arguments(value: str) -> Optional[List[str]]:
    parts: List[str] = []
    start = 0
    depth = 0
    quote: Optional[str] = None
    escaped = False
    for index, char in enumerate(value):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
    if quote or depth != 0:
        return None
    parts.append(value[start:].strip())
    return parts


def _literal(value: str) -> Optional[str]:
    compact = value.strip()
    if not compact:
        return ""
    try:
        parsed = ast.literal_eval(compact)
    except (SyntaxError, ValueError):
        if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", compact):
            return compact
        return None
    return str(parsed) if isinstance(parsed, (str, int, float)) else None


def _split_concat(expression: str) -> Optional[List[str]]:
    parts: List[str] = []
    start = 0
    depth = 0
    quote: Optional[str] = None
    escaped = False
    for index, char in enumerate(expression):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "+" and depth == 0:
            parts.append(expression[start:index].strip())
            start = index + 1
    if quote or depth != 0:
        return None
    parts.append(expression[start:].strip())
    return parts


def _evaluate_expression(
    expression: str,
    *,
    element: Tag,
    variables: Dict[str, str],
) -> Optional[str]:
    terms = _split_concat(expression.strip().rstrip(";"))
    if not terms:
        return None
    values: List[str] = []
    for term in terms:
        literal = _literal(term)
        if literal is not None:
            values.append(literal)
            continue
        if term in variables:
            values.append(variables[term])
            continue
        attr_match = re.fullmatch(
            r"\$\(\s*this\s*\)\.(?:attr|data)\(\s*(['\"])([^'\"]+)\1\s*\)",
            term,
        )
        if attr_match:
            attribute = attr_match.group(2)
            if ".data(" in term:
                attribute = "data-" + re.sub(
                    r"[A-Z]", lambda match: "-" + match.group(0).lower(), attribute
                )
            value = element.get(attribute)
            if value is None:
                return None
            values.append(str(value))
            continue
        dataset_match = re.fullmatch(r"this\.dataset\.([A-Za-z_$][\w$]*)", term)
        if dataset_match:
            attribute = "data-" + re.sub(
                r"[A-Z]",
                lambda match: "-" + match.group(0).lower(),
                dataset_match.group(1),
            )
            value = element.get(attribute)
            if value is None:
                return None
            values.append(str(value))
            continue
        encoded_match = re.fullmatch(r"encodeURIComponent\(([^()]+)\)", term)
        if encoded_match and encoded_match.group(1).strip() in variables:
            from urllib.parse import quote

            values.append(quote(variables[encoded_match.group(1).strip()], safe=""))
            continue
        return None
    return "".join(values)


def _navigation_expressions(code: str) -> Iterable[str]:
    patterns = (
        re.compile(r"(?:window\.)?location(?:\.href)?\s*=\s*([^;\n]+)"),
        re.compile(r"(?:window\.)?location\.(?:assign|replace)\(\s*([^;\n]+?)\s*\)"),
    )
    for pattern in patterns:
        for match in pattern.finditer(code):
            yield match.group(1).strip()
    for match in re.finditer(r"window\.open\(\s*(.+?)\s*\)\s*;?", code):
        arguments = _split_arguments(match.group(1))
        if arguments:
            yield arguments[0]


_FUNCTION_EXPRESSION_ASSIGN_RE_TEMPLATE = (
    r"(?:^|[;\n])\s*(?:var|let|const)?\s*{name}\s*=\s*"
    r"(?:function\s*\((?P<fn_params>[^)]*)\)"
    r"|\((?P<arrow_params>[^)]*)\)\s*=>)"
    r"\s*\{{"
)


def _function_definition(source: str, name: str) -> Optional[Tuple[List[str], str]]:
    match = re.search(
        rf"\bfunction\s+{re.escape(name)}\s*\((?P<params>[^)]*)\)\s*\{{",
        source,
    )
    params_text: Optional[str] = match.group("params") if match else None
    if match is None:
        # ``let goDetail = function(seq){...}`` or an arrow-function
        # assignment, the common alternative to a named function declaration.
        expr_match = re.search(
            _FUNCTION_EXPRESSION_ASSIGN_RE_TEMPLATE.format(name=re.escape(name)),
            source,
        )
        if expr_match is None:
            return None
        match = expr_match
        params_text = expr_match.group("fn_params")
        if params_text is None:
            params_text = expr_match.group("arrow_params")
    if params_text is None:
        return None
    body = _balanced_block(source, match.end() - 1)
    if body is None:
        return None
    params = [value.strip() for value in params_text.split(",") if value.strip()]
    if any(not _IDENTIFIER_RE.fullmatch(value) for value in params):
        return None
    return params, body


_FORM_ACTION_ASSIGN_RE = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\.\s*action\s*=\s*([^;\n]+)")
_FORM_FIELD_VALUE_ASSIGN_RE = re.compile(
    r"\b([A-Za-z_$][\w$]*)\s*\.\s*([A-Za-z_$][\w$]*)\s*\.\s*value\s*=\s*([^;\n]+)"
)


_FORM_ALIAS_RE = re.compile(
    r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*document\s*\.\s*"
    r"(?:forms\s*\[\s*(['\"])(?P<bracket_name>[\w:-]+)\2\s*\]"
    r"|forms\s*\.\s*(?P<dot_forms_name>[A-Za-z_$][\w$]*)"
    r"|(?P<dot_name>[A-Za-z_$][\w$]*))"
)


def _resolve_form_reference(
    document: BeautifulSoup, scripts: str, identifier: str
) -> Optional[Tag]:
    """Resolve a JS identifier to its ``<form>``.

    Handles both a form referenced by its own ``name``/``id`` (e.g. a
    jQuery-style ``$('#frm')`` target used directly) and the common
    ``var f = document.forms['frm'];`` alias idiom, where the identifier
    used in the handler is a local alias rather than the form's own name.
    """
    for match in _FORM_ALIAS_RE.finditer(scripts):
        if match.group(1) != identifier:
            continue
        real_name = (
            match.group("bracket_name")
            or match.group("dot_forms_name")
            or match.group("dot_name")
        )
        if real_name:
            form = _find_named_form(document, real_name)
            if form is not None:
                return form
    return _find_named_form(document, identifier)


def _find_named_form(document: BeautifulSoup, identifier: str) -> Optional[Tag]:
    form = document.find("form", attrs={"name": identifier})
    if form is None:
        form = document.find("form", id=identifier)
    return form


def _assigned_form_navigation_url(
    base_url: str,
    element: Tag,
    document: Optional[BeautifulSoup],
    scripts: str,
    code: str,
    variables: Dict[str, str],
) -> Optional[str]:
    """Resolve the vanilla-JS ``form.field.value = expr; form.action = expr;
    form.submit()`` idiom: the native-DOM analogue of the jQuery
    ``$('#id').val(...)`` / ``$('#form').attr('action', ...)`` pattern that
    ``_script_form_navigation_url`` already handles. A hidden form is
    populated from the handler's own variables and submitted, without any
    usable ``href``.
    """
    if document is None:
        return None

    action_match = _FORM_ACTION_ASSIGN_RE.search(code)
    if not action_match:
        return None
    form_ref = action_match.group(1)
    if not re.search(rf"\b{re.escape(form_ref)}\s*\.\s*submit\s*\(\s*\)", code):
        return None

    form = _resolve_form_reference(document, scripts, form_ref)
    if form is None:
        return None

    action_value = _evaluate_expression(
        action_match.group(2).strip(), element=element, variables=variables
    )
    resolved = _http_url(base_url, action_value)
    if not resolved:
        return None

    field_values: Dict[str, str] = {}
    for match in _FORM_FIELD_VALUE_ASSIGN_RE.finditer(code):
        if match.group(1) != form_ref:
            continue
        value = _evaluate_expression(
            match.group(3).strip(), element=element, variables=variables
        )
        if value is None:
            continue
        field_values[match.group(2)] = value
    if not field_values:
        return None

    parameters: List[Tuple[str, str]] = list(field_values.items())
    for control in form.select("input[name], button[name], select[name]"):
        if control.has_attr("disabled"):
            continue
        name = str(control.get("name"))
        if name in field_values:
            continue
        control_type = str(control.get("type") or "").casefold()
        if control_type in {"submit", "button", "image", "file", "reset"}:
            continue
        if control_type in {"checkbox", "radio"} and not control.has_attr("checked"):
            continue
        value = control.get("value")
        if value is None or str(value) == "":
            continue
        parameters.append((name, str(value)))

    parsed = urlsplit(resolved)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in field_values
    ]
    query.extend(parameters)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


_MAX_EXTERNAL_SCRIPTS = 8
_MAX_EXTERNAL_SCRIPT_BYTES = 2_000_000


@functools.lru_cache(maxsize=256)
def _fetch_external_script_text(url: str) -> str:
    """Best-effort fetch of a same-origin ``<script src>`` file's text.

    Only used so ``_function_definition`` can find a handler that a page
    defines in an external file instead of inline (e.g. reservation.knps.or.kr's
    ``goDetail``). The script is never executed, only scanned as text with the
    same allowlisted patterns used for inline code. Cached per absolute URL so
    a page with many records fetches each script at most once.
    """
    try:
        import requests

        from dataController.security.url_safety import safe_request

        session = requests.Session()
        response = safe_request(
            session,
            "GET",
            url,
            timeout=8,
            max_response_bytes=_MAX_EXTERNAL_SCRIPT_BYTES,
        )
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text
    except Exception:
        return ""


def _external_scripts_text(document: BeautifulSoup, base_url: str) -> str:
    base_host = urlsplit(base_url).netloc
    urls: List[str] = []
    for tag in document.find_all("script", src=True):
        absolute = _http_url(base_url, tag.get("src"))
        if not absolute or urlsplit(absolute).netloc != base_host:
            continue
        if absolute not in urls:
            urls.append(absolute)
        if len(urls) >= _MAX_EXTERNAL_SCRIPTS:
            break
    return "\n".join(_fetch_external_script_text(url) for url in urls)


_LOCATION_HREF_QUERY_RE = re.compile(
    r"location(?:\.href)?\s*=\s*[\"']\?[\"']\s*\+\s*[A-Za-z_$][\w$]*\s*;?"
)
_REPLACE_QUERY_STRING_RE = re.compile(
    r"\.fn_replaceQueryString\s*\(\s*[A-Za-z_$][\w$]*\s*,\s*"
    r"(['\"])(?P<key>[^'\"]+)\1\s*,\s*(?P<value>[^)]+)\)"
)


def _query_param_mutation_navigation_url(
    base_url: str,
    element: Tag,
    code: str,
    variables: Dict[str, str],
) -> Optional[str]:
    """Resolve ``location.href = '?' + query`` built from the current page's
    own query string via chained ``fn_replaceQueryString(query, key, value)``
    calls - a common eGovFrame (Korean government site framework) idiom for
    "reopen this page in detail mode". The helper that reads the starting
    query string (``fn_get_query`` or similar) only ever returns the current
    page's own, so ``base_url``'s query string is used as that starting point.
    """
    if not _LOCATION_HREF_QUERY_RE.search(code):
        return None
    params: Dict[str, str] = {}
    for match in _REPLACE_QUERY_STRING_RE.finditer(code):
        value = _evaluate_expression(
            match.group("value").strip(), element=element, variables=variables
        )
        if value is None:
            return None
        params[match.group("key")] = value
    if not params:
        return None
    parsed = urlsplit(base_url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in params
    ]
    query.extend(params.items())
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def _inline_navigation_url(
    base_url: str,
    element: Tag,
    document: Optional[BeautifulSoup],
) -> Optional[str]:
    code_values = [str(element.get("onclick") or "").strip()]
    href = str(element.get("href") or "").strip()
    if href.casefold().startswith("javascript:"):
        code_values.append(href.split(":", 1)[1].strip())
    code_values = [value for value in code_values if value]
    if not code_values:
        return None
    scripts = (
        "\n".join(
            script.get_text("\n") for script in document.find_all("script")
        )
        if document is not None
        else ""
    )
    for code in code_values:
        for expression in _navigation_expressions(code):
            value = _evaluate_expression(expression, element=element, variables={})
            resolved = _http_url(base_url, value)
            if resolved:
                return resolved

        resolved = _assigned_form_navigation_url(
            base_url, element, document, scripts, code, {}
        )
        if resolved:
            return resolved

        resolved = _query_param_mutation_navigation_url(base_url, element, code, {})
        if resolved:
            return resolved

        call = re.fullmatch(
            r"(?:return\s+)?([A-Za-z_$][\w$]*)\s*\((.*)\)\s*;?"
            r"(?:\s*return\s+false\s*;?)?",
            code,
            re.DOTALL,
        )
        if not call or document is None:
            continue
        raw_arguments = _split_arguments(call.group(2))
        if raw_arguments is None:
            continue
        arguments = [_literal(value) for value in raw_arguments]
        if any(value is None for value in arguments):
            continue
        definition = _function_definition(scripts, call.group(1))
        if definition is None:
            external_text = _external_scripts_text(document, base_url)
            if external_text:
                scripts = f"{scripts}\n{external_text}"
                definition = _function_definition(scripts, call.group(1))
        if definition is None:
            continue
        parameters, body = definition
        if len(parameters) != len(arguments):
            continue
        variables = dict(zip(parameters, (value or "" for value in arguments)))
        for expression in _navigation_expressions(body):
            value = _evaluate_expression(expression, element=element, variables=variables)
            resolved = _http_url(base_url, value)
            if resolved:
                return resolved

        resolved = _assigned_form_navigation_url(
            base_url, element, document, scripts, body, variables
        )
        if resolved:
            return resolved

        resolved = _jquery_form_navigation_url(
            base_url, document, body, body, variables
        )
        if resolved:
            return resolved

        resolved = _query_param_mutation_navigation_url(
            base_url, element, body, variables
        )
        if resolved:
            return resolved
    return None


_DIRECT_HANDLER_RE = re.compile(
    r"\$\(\s*(['\"])(?P<selector>[^'\"]+)\1\s*\)\s*\."
    r"(?:click\s*\(\s*function|on\s*\(\s*['\"]click['\"]\s*,\s*function)"
    r"[^\{]*\{",
    re.IGNORECASE,
)
_DELEGATED_HANDLER_RE = re.compile(
    r"\$\(\s*document\s*\)\s*\.on\s*\(\s*['\"]click['\"]\s*,\s*"
    r"(['\"])(?P<selector>[^'\"]+)\1\s*,\s*function[^\{]*\{",
    re.IGNORECASE,
)


def _matches(element: Tag, selector: str) -> bool:
    try:
        return soupsieve.match(selector, element)
    except Exception:
        return False


def _handler_bodies(source: str, element: Tag) -> List[str]:
    bodies: List[str] = []
    for pattern in (_DIRECT_HANDLER_RE, _DELEGATED_HANDLER_RE):
        for match in pattern.finditer(source):
            if not _matches(element, match.group("selector")):
                continue
            body = _balanced_block(source, match.end() - 1)
            if body is not None:
                bodies.append(body)
    return bodies


def _reachable_code(source: str, handler: str) -> str:
    chunks = [handler]
    seen = set()
    frontier = [handler]
    ignored = {"if", "for", "while", "switch", "function", "attr", "val", "show", "hide"}
    for _ in range(3):
        next_frontier: List[str] = []
        for chunk in frontier:
            for name in re.findall(r"\b([A-Za-z_$][\w$]*)\s*\(", chunk):
                if name in ignored or name in seen:
                    continue
                seen.add(name)
                definition = _function_definition(source, name)
                if definition is None:
                    continue
                body = definition[1]
                chunks.append(body)
                next_frontier.append(body)
        frontier = next_frontier
        if not frontier:
            break
    return "\n".join(chunks)


def _attribute_variables(handler: str, element: Tag) -> Dict[str, str]:
    variables: Dict[str, str] = {}
    jquery = re.compile(
        r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*\$\(\s*this\s*\)\."
        r"(?:(?:attr)\(\s*(['\"])(data-[^'\"]+)\2\s*\)|"
        r"(?:data)\(\s*(['\"])([^'\"]+)\4\s*\))"
    )
    for match in jquery.finditer(handler):
        attribute = match.group(3)
        if not attribute:
            attribute = "data-" + re.sub(
                r"[A-Z]", lambda item: "-" + item.group(0).lower(), match.group(5)
            )
        value = element.get(attribute)
        if value is not None:
            variables[match.group(1)] = str(value)
    native = re.compile(
        r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*this\.dataset\."
        r"([A-Za-z_$][\w$]*)"
    )
    for match in native.finditer(handler):
        attribute = "data-" + re.sub(
            r"[A-Z]", lambda item: "-" + item.group(0).lower(), match.group(2)
        )
        value = element.get(attribute)
        if value is not None:
            variables[match.group(1)] = str(value)
    return variables


def _form_actions(code: str) -> List[Tuple[str, str]]:
    pattern = re.compile(
        r"\$\(\s*(['\"])#(?P<form_id>[A-Za-z_][\w:-]*)\1\s*\)\s*\."
        r"attr\(\s*(['\"])action\3\s*,\s*(['\"])(?P<action>[^'\"]+)\4\s*\)"
        r"(?:\s*\.submit\s*\(\s*\))?",
        re.IGNORECASE,
    )
    return [(match.group("form_id"), match.group("action")) for match in pattern.finditer(code)]


def _action_score(action: str) -> int:
    path = urlsplit(action).path
    return (
        (20 if _DETAIL_PATH_HINT_RE.search(path) else 0)
        - (15 if _LIST_PATH_HINT_RE.search(path) else 0)
        + len(path) // 40
    )


_JQUERY_VAL_ASSIGN_RE = re.compile(
    r"\$\(\s*(['\"])#(?P<input_id>[A-Za-z_][\w:-]*)\1\s*\)"
    r"\.val\(\s*(?P<variable>[A-Za-z_$][\w$]*)\s*\)"
)


def _jquery_form_navigation_url(
    base_url: str,
    document: BeautifulSoup,
    handler: str,
    reachable: str,
    variables: Dict[str, str],
) -> Optional[str]:
    """Resolve ``$('#field').val(x); $('#form').attr('action', y).submit()``.

    ``variables`` may come from data-* attributes read off the clicked
    element (the jQuery click-handler case) or from a traced function's own
    call arguments (the ``goDetail(seq)``-style inline onclick case) -
    either way this is the same jQuery hidden-form population idiom.
    """
    if not variables:
        return None
    actions = _form_actions(reachable)
    if not actions:
        return None
    form_id, action = max(actions, key=lambda item: _action_score(item[1]))
    form = document.find("form", id=form_id)
    if form is None:
        form = document.find("form", attrs={"name": form_id})

    parameters: List[Tuple[str, str]] = []
    for assignment in _JQUERY_VAL_ASSIGN_RE.finditer(handler):
        variable = assignment.group("variable")
        if variable not in variables:
            continue
        input_id = assignment.group("input_id")
        input_tag = (
            form.find(id=input_id) if form is not None else document.find(id=input_id)
        )
        name = str(input_tag.get("name") or input_id) if input_tag else input_id
        parameters.append((name, variables[variable]))

    if not parameters:
        return None
    resolved = _http_url(base_url, action)
    if not resolved:
        return None
    parsed = urlsplit(resolved)
    query = list(parse_qsl(parsed.query, keep_blank_values=True))
    query.extend(parameters)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def _script_form_navigation_url(
    base_url: str,
    element: Tag,
    document: Optional[BeautifulSoup],
) -> Optional[str]:
    if document is None:
        return None
    for script_tag in document.find_all("script"):
        source = script_tag.get_text("\n")
        for handler in _handler_bodies(source, element):
            variables = _attribute_variables(handler, element)
            if not variables:
                continue
            reachable = _reachable_code(source, handler)
            resolved = _jquery_form_navigation_url(
                base_url, document, handler, reachable, variables
            )
            if resolved:
                return resolved
    return None


def _standard_form_navigation_url(
    base_url: str,
    element: Tag,
    document: Optional[BeautifulSoup],
) -> Optional[str]:
    form = element.find_parent("form")
    action = element.get("formaction")
    if form is None and element.get("form"):
        form = document.find("form", id=element.get("form")) if document else None
    if not action and form is not None:
        action = form.get("action")
    resolved = _http_url(base_url, action)
    if not resolved or form is None:
        return resolved

    parameters: List[Tuple[str, str]] = []
    for control in form.select("input[name], button[name], select[name]"):
        if control.has_attr("disabled"):
            continue
        control_type = str(control.get("type") or "").casefold()
        if (
            control_type in {"submit", "button", "image", "file", "reset"}
            and control is not element
        ):
            continue
        if control_type in {"checkbox", "radio"} and not control.has_attr("checked"):
            continue
        value = control.get("value")
        if value is None or str(value) == "":
            continue
        parameters.append((str(control.get("name")), str(value)))
    parsed = urlsplit(resolved)
    query = list(parse_qsl(parsed.query, keep_blank_values=True))
    query.extend(parameters)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def resolve_html_navigation_url(
    base_url: str,
    element: Tag,
    *,
    document: Optional[BeautifulSoup] = None,
) -> Optional[str]:
    """Return a stable HTTP(S) URL for a link/button, or ``None``.

    Page code is treated as untrusted data.  Only allowlisted navigation shapes
    are parsed, and no JavaScript is evaluated.
    """

    for attribute in _DIRECT_URL_ATTRIBUTES:
        value = element.get(attribute)
        if attribute == "href" and is_placeholder_navigation(element):
            continue
        resolved = _http_url(base_url, value)
        if resolved:
            return resolved

    resolved = _inline_navigation_url(base_url, element, document)
    if resolved:
        return resolved
    resolved = _standard_form_navigation_url(base_url, element, document)
    if resolved:
        return resolved
    return _script_form_navigation_url(base_url, element, document)
