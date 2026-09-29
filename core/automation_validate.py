"""
Clean the AI's automation output before rendering: make every name a valid
TypeScript identifier and turn any step the renderer could not express
(unknown page/locator, missing field) into a `todo` step with a warning.
Never raises on AI output.
"""
import re
import unicodedata

STRATEGIES = {"role", "label", "placeholder", "text", "test_id", "css"}
# A secret the generated project reads from .env: the whole value is ${ENV:NAME}.
ENV_VALUE = re.compile(r"^\$\{ENV:([A-Z][A-Z0-9_]*)\}$")

# Fields each action needs (see the spec's action table).
ACTION_FIELDS = {
    "goto": ("page",),
    "click": ("page", "locator"),
    "check": ("page", "locator"),
    "uncheck": ("page", "locator"),
    "expect_visible": ("page", "locator"),
    "expect_hidden": ("page", "locator"),
    "fill": ("page", "locator", "value"),
    "select": ("page", "locator", "value"),
    "press": ("page", "locator", "value"),
    "expect_text": ("page", "locator", "value"),
    "expect_value": ("page", "locator", "value"),
    "expect_url": ("value",),
    "todo": (),
}

# The roles Playwright's getByRole accepts; anything else fails type-checking.
ARIA_ROLES = frozenset("""
alert alertdialog application article banner blockquote button caption cell
checkbox code columnheader combobox complementary contentinfo definition
deletion dialog directory document emphasis feed figure form generic grid
gridcell group heading img insertion link list listbox listitem log main
marquee math meter menu menubar menuitem menuitemcheckbox menuitemradio
navigation none note option paragraph presentation progressbar radio
radiogroup region row rowgroup rowheader scrollbar search searchbox
separator slider spinbutton status strong subscript superscript switch tab
table tablist tabpanel term textbox time timer toolbar tooltip tree treegrid
treeitem
""".split())

TS_RESERVED = frozenset("""
break case catch class const continue debugger default delete do else enum
export extends false finally for function if import in instanceof new null
return super switch this throw true try typeof var void while with as
implements interface let package private protected public static yield
await any boolean number string symbol type
""".split())
# Names the generated code itself uses: page-object members and test globals.
MEMBER_RESERVED = TS_RESERVED | {"page", "path", "goto", "constructor", "test", "expect", "process"}
# Page classes are imported into specs, so they must not shadow globals the specs use.
CLASS_RESERVED = {"Page", "Locator", "RegExp"}
# Device names Windows 10 cannot extract as files (con.ts, nul.spec.ts, ...).
WINDOWS_RESERVED = frozenset(
    ["con", "prn", "aux", "nul"] + [f"com{n}" for n in range(1, 10)] + [f"lpt{n}" for n in range(1, 10)]
)


def ascii_fold(text: str) -> str:
    """Drop diacritics so Vietnamese and other Latin text keeps its letters."""
    text = str(text).replace("đ", "d").replace("Đ", "D")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", ascii_fold(text))


def _cap(word: str) -> str:
    return word[0].upper() + word[1:]


def to_pascal(text: str) -> str:
    name = "".join(_cap(word) for word in _words(text))
    if not name:
        return "UnnamedPage"
    if name[0].isdigit():
        name = "Page" + name
    if name in CLASS_RESERVED:
        name += "Object"
    elif name.lower() in WINDOWS_RESERVED:
        name += "Page"
    return name


def to_camel(text: str) -> str:
    words = _words(text)
    if not words:
        return "element"
    name = words[0][0].lower() + words[0][1:] + "".join(_cap(word) for word in words[1:])
    if name[0].isdigit():
        name = "el" + name
    if name in MEMBER_RESERVED:
        name += "Locator"
    return name


def _page_var(class_name: str) -> str:
    name = class_name[0].lower() + class_name[1:]
    return name + "Page" if name in MEMBER_RESERVED else name


def _unique(name: str, used: set[str]) -> str:
    """Append 2, 3, ... until the name is free; compared case-insensitively
    because page names become file names on case-insensitive file systems."""
    candidate, number = name, 2
    while candidate.casefold() in used:
        candidate = f"{name}{number}"
        number += 1
    used.add(candidate.casefold())
    return candidate


class _Lookup:
    """Resolves a name the AI used in a step: exact raw names win over cleaned
    ones, so "LoginPage" finds the page the AI called "LoginPage" even when an
    earlier "Login Page" was also cleaned to "LoginPage"."""

    def __init__(self):
        self.raw: dict[str, object] = {}
        self.cleaned: dict[str, object] = {}

    def add(self, raw_name: str, cleaned_name: str, value) -> None:
        self.raw[raw_name] = value
        self.cleaned.setdefault(cleaned_name, value)

    def __contains__(self, raw_name: str) -> bool:
        return raw_name in self.raw

    def get(self, name: str):
        for candidate in dict.fromkeys((name, name.strip())):
            if candidate in self.raw:
                return self.raw[candidate]
        return self.cleaned.get(name.strip())


def _text(value) -> str:
    return "" if value is None else str(value)


def _todo(source: str) -> dict:
    return {"action": "todo", "page": "", "locator": "", "value": "", "source": source}


def validate_automation(result: dict, modules: dict[str, str]) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    pages, lookup = _clean_pages(result.get("pages") or [], warnings)
    tests = _clean_tests(result.get("tests") or [], lookup, modules, warnings)
    questions = [_text(q) for q in result.get("open_questions") or [] if _text(q).strip()]
    return {"pages": pages, "tests": tests, "open_questions": questions}, warnings


def _clean_pages(raw_pages: list[dict], warnings: list[str]):
    pages: list[dict] = []
    lookup = _Lookup()
    used_names: set[str] = set()
    used_vars: set[str] = set()
    for raw in raw_pages:
        raw_name = _text(raw.get("name"))
        if raw_name in lookup:
            warnings.append(f"Duplicate page '{raw_name}' ignored; the first definition is kept.")
            continue
        name = _unique(to_pascal(raw_name), used_names)
        locators, keys = _clean_locators(name, raw.get("locators") or [], warnings)
        page = {
            "name": name,
            "var": _unique(_page_var(name), used_vars),
            "path": _text(raw.get("path")).strip() or "/",
            "locators": locators,
        }
        pages.append(page)
        lookup.add(raw_name, name, (page, keys))
    return pages, lookup


def _clean_locators(page_name: str, raw_locators: list[dict], warnings: list[str]):
    locators: list[dict] = []
    keys = _Lookup()
    used: set[str] = set()
    for raw in raw_locators:
        raw_key = _text(raw.get("key"))
        if raw_key in keys:
            warnings.append(f"{page_name}: duplicate locator '{raw_key}' ignored; the first definition is kept.")
            continue
        key = _unique(to_camel(raw_key), used)
        locator = {
            "key": key,
            "strategy": _text(raw.get("strategy")),
            "role": _text(raw.get("role")).strip().lower(),
            "value": _text(raw.get("value")),
            "confident": bool(raw.get("confident")),
        }
        if locator["strategy"] not in STRATEGIES:
            warnings.append(f"{page_name}.{key}: unknown strategy '{locator['strategy']}'; using a text locator.")
            locator.update(strategy="text", confident=False)
        if locator["strategy"] == "role" and locator["role"] not in ARIA_ROLES:
            if locator["role"]:
                warnings.append(f"{page_name}.{key}: unknown ARIA role '{locator['role']}'; using a text locator.")
            locator.update(strategy="text", confident=False)
        if locator["strategy"] != "role":
            locator["role"] = ""
        locators.append(locator)
        keys.add(raw_key, key, key)
    return locators, keys


def _clean_tests(raw_tests, lookup, modules, warnings) -> list[dict]:
    tests: list[dict] = []
    used_ids: set[str] = set()
    returned_ids: set[str] = set()
    for raw in raw_tests:
        raw_id = _text(raw.get("test_id")).strip() or "TC"
        if raw_id not in modules and raw_id not in returned_ids:
            warnings.append(f"{raw_id} was not among the selected test cases.")
        returned_ids.add(raw_id)
        test_id, number = raw_id, 2
        while test_id in used_ids:
            test_id = f"{raw_id}_{number}"
            number += 1
        used_ids.add(test_id)
        if test_id != raw_id:
            warnings.append(f"Duplicate test id '{raw_id}' renamed to '{test_id}'.")
        steps = [
            _clean_step(test_id, index, step, lookup, warnings)
            for index, step in enumerate(raw.get("steps") or [], start=1)
        ]
        if not steps:
            warnings.append(f"{test_id}: no steps were returned; marked as fixme.")
            steps = [_todo("No automatable steps were returned for this test case.")]
        tests.append({
            "test_id": test_id,
            "title": _text(raw.get("title")).strip(),
            "module": _text(modules.get(raw_id, "")),
            "steps": steps,
        })
    for selected_id in modules:
        if selected_id and selected_id not in returned_ids:
            warnings.append(f"{selected_id} was selected but the AI returned no test for it.")
    return tests


def _clean_step(test_id, index, step, lookup, warnings) -> dict:
    action = _text(step.get("action"))
    source = _text(step.get("source"))
    prefix = f"{test_id} step {index}"
    if action not in ACTION_FIELDS:
        warnings.append(f"{prefix}: unknown action '{action}'.")
        return _todo(source or action)
    required = ACTION_FIELDS[action]
    if action == "todo":
        return _todo(source)
    missing = [field for field in required if not _text(step.get(field)).strip()]
    if missing:
        warnings.append(f"{prefix}: {action} is missing {', '.join(missing)}.")
        return _todo(source or action)

    cleaned = {"action": action, "page": "", "locator": "", "value": _text(step.get("value")), "source": source}
    if action == "expect_url" and ENV_VALUE.match(cleaned["value"]):
        warnings.append(
            f"{prefix}: expect_url does not read environment values; '{cleaned['value']}' is matched literally."
        )
    if "page" in required:
        entry = lookup.get(_text(step.get("page")))
        if entry is None:
            warnings.append(f"{prefix}: unknown page '{step.get('page')}'.")
            return _todo(source or action)
        page, keys = entry
        cleaned["page"] = page["name"]
        if "locator" in required:
            key = keys.get(_text(step.get("locator")))
            if key is None:
                warnings.append(f"{prefix}: unknown locator '{step.get('locator')}' on {page['name']}.")
                return _todo(source or action)
            cleaned["locator"] = key
    return cleaned
