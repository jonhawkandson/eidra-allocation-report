#!/usr/bin/env python3
"""
Eidra Float Allocation Report — Compute & Generate
====================================================
Reads Float data (people, allocations, time-offs, projects) and generates
eidra_allocation_report.html — a single-file report with an OpCo switcher
in the top nav and one set of slides per OpCo.

Run from Terminal:
    python3 eidra_compute_chargeability.py

Data sources (checked in order):
  1. DATA_DIR/*.json  — written by the daily scheduled Cowork task
  2. CACHE/           — Float MCP session cache (valid during a Cowork session)

Update CACHE path to the current Cowork session if running interactively.
"""

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from eidra_opco_config import OPCOS, OPCO_ORDER, GENERIC_ROLE_LEVEL

# ── Config sanity checks ─────────────────────────────────────────────────────────
# Catch a typo in eidra_opco_config.py loudly here, instead of a confusing
# KeyError deep in compute_opco() or a silently-missing opco in the report.
_order_set, _opcos_set = set(OPCO_ORDER), set(OPCOS)
if _order_set != _opcos_set:
    _missing_from_order = _opcos_set - _order_set
    _missing_from_opcos = _order_set - _opcos_set
    _msgs = []
    if _missing_from_order:
        _msgs.append(f"in OPCOS but missing from OPCO_ORDER (will be silently excluded from the report): {sorted(_missing_from_order)}")
    if _missing_from_opcos:
        _msgs.append(f"in OPCO_ORDER but missing from OPCOS (will crash with a KeyError): {sorted(_missing_from_opcos)}")
    raise SystemExit("eidra_opco_config.py: OPCOS and OPCO_ORDER don't match — " + "; ".join(_msgs))

# Catch the same Float department ID assigned to two different opcos/groups —
# this would silently double-count that person in both places with no warning.
_dept_id_owner: dict[int, str] = {}
for _ok, _ocfg in OPCOS.items():
    _ids_here = [_ocfg["dept_id"]]
    for _g in _ocfg["groups"].values():
        _ids_here.extend(_g["ids"])
    for _did in _ids_here:
        if _did in _dept_id_owner and _dept_id_owner[_did] != _ok:
            raise SystemExit(
                f"eidra_opco_config.py: dept ID {_did} is assigned to both "
                f"{_dept_id_owner[_did]!r} and {_ok!r} — this would double-count "
                f"that department's people in both opcos' reports."
            )
        _dept_id_owner[_did] = _ok

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE = Path(__file__).parent

# Scheduled-run data directory
DATA_DIR = BASE / "data"

# Float MCP session-cache fallback — update this path to the active Cowork session
# when running interactively (the path changes every session).
CACHE = Path(
    "/var/folders/68/7hl978rn4kngznplzd1v_l7c0000gp/T/claude-hostloop-plugins"
    "/61a5bed2aab7afd9/projects"
    "/-Users-jonhakansson-Library-Application-Support-Claude-local-agent-mode-sessions"
    "-34fc4df7-cd41-4e41-986a-71795306ee9a-b38bf451-7419-43d9-85b7-2a32e6cb06ac"
    "-local-6c612b67-22b5-4826-84df-dde7d31644e8-ou-3c9nuo"
    "/e6474311-e97b-4199-9657-88c341506f72/tool-results"
)
# NOTE: Update CACHE above to the current Cowork session's tool-results path.
# The path changes each session. Find it by looking at the most recent
# tool-result file path shown in this Cowork conversation.

HTML_OUT = BASE / "eidra_allocation_report.html"

# ── Per-opco standalone pages ─────────────────────────────────────────────────
# Maps opco_key → GitHub Pages subfolder name.
# Each entry gets its own password-protected index.html at /{subfolder}/.
PER_OPCO_PAGES = {
    "above-se":            "above",
    "curious-mind-se":     "curiousmind",
    "curamando-se":        "curamando",
    "conversionista-se":   "conversionista",
    "eidra-consulting-se": "eidra-consulting",
    "frojd-se":            "frojd",
    "eidra-dach":          "eidra-dach",
}

# ── Weeks: 20 rolling weeks from this Monday ──────────────────────────────────
def _rolling_weeks(n=20):
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    weeks = []
    for i in range(n):
        ws = monday + timedelta(weeks=i)
        we = ws + timedelta(days=4)
        wnum = ws.isocalendar()[1]
        weeks.append((f"W{wnum}", ws, we))
    return weeks

WEEKS = _rolling_weeks(20)
print(f"Week range: {WEEKS[0][0]} ({WEEKS[0][1]}) → {WEEKS[-1][0]} ({WEEKS[-1][2]})")

# Week-visibility split: 12 visible by default, 8 collapsible
N_VISIBLE  = 12
WEEKS_MAIN = WEEKS[:N_VISIBLE]
WEEKS_EXT  = WEEKS[N_VISIBLE:]

# ── Helpers ────────────────────────────────────────────────────────────────────
def pd(s):
    return date.fromisoformat(str(s)[:10])

def _pd_or_none(s):
    return date.fromisoformat(str(s)[:10]) if s else None

def workdays(s1, e1, s2, e2):
    lo, hi = max(s1, s2), min(e1, e2)
    if lo > hi:
        return 0
    n, d = 0, lo
    while d <= hi:
        if d.weekday() < 5:
            n += 1
        d += timedelta(1)
    return n

# ── Load data ──────────────────────────────────────────────────────────────────
print("Loading data files…")

def _load_list(data_file, cache_glob_prefix, result_key):
    """Load a list from DATA_DIR (scheduled run) or CACHE (session fallback)."""
    if data_file.exists():
        print(f"  ✓ {data_file.name} [scheduled data]")
        return json.loads(data_file.read_text())
    # Find matching files in CACHE — merge ALL for allocations (fetched in two halves)
    matches = sorted(CACHE.glob(f"{cache_glob_prefix}*.txt"), key=lambda p: p.stat().st_mtime)
    if matches:
        merged = []
        seen_ids = set()
        for f in matches:
            print(f"  ✓ {f.name} [session cache]")
            raw = json.loads(f.read_text())
            arr = raw["result"][result_key]
            for item in arr:
                iid = item.get(f"{result_key[:-1]}_id") or item.get("id") or id(item)
                if iid not in seen_ids:
                    seen_ids.add(iid)
                    merged.append(item)
        return merged
    print(f"  ✗ Missing both {data_file.name} and cache for {cache_glob_prefix}")
    print("    Run the report from a Cowork session, or ensure the daily task has run.")
    raise SystemExit(1)

DATA_DIR.mkdir(exist_ok=True)
# NOTE: 2026-08-20 scheduled run (TS=1787229249) — canonical filenames were
# overwritable this run, so loaders point at the canonical people/allocations/
# timeoffs/projects.json (refreshed in place). If a future run hits the
# immutability issue again, fall back to pointing these at that run's
# timestamped data/<name>_<TS>.json files instead.
people_raw   = _load_list(DATA_DIR / "people.json",      "mcp-37bd71bd-ebfa-4f23-aa89-e28d357dd790-get_people_list-",   "people")
alloc_raw    = _load_list(DATA_DIR / "allocations.json",  "mcp-37bd71bd-ebfa-4f23-aa89-e28d357dd790-get_allocation_list-","allocations")
timeoff_raw  = _load_list(DATA_DIR / "timeoffs.json",     "mcp-37bd71bd-ebfa-4f23-aa89-e28d357dd790-get_timeoffs_list-", "timeoffs")
projects_raw = _load_list(DATA_DIR / "projects.json",     "mcp-37bd71bd-ebfa-4f23-aa89-e28d357dd790-get_projects_list-", "projects")

# Clients — optional; gracefully missing if not yet fetched
_clients_file = DATA_DIR / "clients.json"
clients_raw = json.loads(_clients_file.read_text()) if _clients_file.exists() else []
if not clients_raw:
    print("  ⚠  clients.json missing — project labels will show project name only")

# ── Data-completeness check ──────────────────────────────────────────────────────
# The extraction step writes data/_fetch_meta.json recording, per dataset, how many
# records Float actually returned vs how many it reported existing (total_records).
# If those ever disagree, the report is built on incomplete data and would silently
# undercount. We don't abort — we surface a visible warning banner in the report so
# nobody trusts a partial pull by accident. Missing/old meta file → no banner.
_fetch_warnings = []
_meta_file = DATA_DIR / "_fetch_meta.json"
if _meta_file.exists():
    try:
        _meta = json.loads(_meta_file.read_text())
        for _name, _m in _meta.items():
            _got, _tot = _m.get("returned"), _m.get("total_records")
            if _tot is not None and _got is not None and _got != _tot:
                _fetch_warnings.append(f"{_name}: {_got:,} of {_tot:,} records")
    except Exception as _e:
        _fetch_warnings.append(f"could not read fetch metadata ({_e})")

if _fetch_warnings:
    print("  ⚠️  DATA INCOMPLETE: " + "; ".join(_fetch_warnings))
    banner_html = (
        '<div id="data-warning-banner" style="'
        'background:#b3261e;color:#fff;padding:10px 16px;font-size:13px;'
        'font-weight:600;text-align:center;line-height:1.4">'
        '⚠️ Data may be incomplete — this report was built on a partial Float pull '
        'and may undercount allocations. Affected: '
        + "; ".join(_fetch_warnings)
        + '. Re-run the daily refresh before relying on these numbers.'
        '</div>'
    )
else:
    banner_html = ""

# ── Build global lookups ───────────────────────────────────────────────────────
client_map  = {c["client_id"]: c["name"] for c in clients_raw}
proj_map    = {p["project_id"]: p for p in projects_raw}
pid_name    = {p["people_id"]: p["name"]       for p in people_raw}
pid_role_id = {p["people_id"]: p.get("role_id") for p in people_raw}
pid_active  = {p["people_id"]: p.get("active", True) for p in people_raw}
# people_type_id: 1=Employee, 3=Placeholder — exclude placeholders from availability
pid_type    = {p["people_id"]: p.get("people_type_id", 1) for p in people_raw}
pid_dates   = {
    p["people_id"]: (_pd_or_none(p.get("start_date")), _pd_or_none(p.get("end_date")))
    for p in people_raw
}
# dept_id → set of employee people_ids assigned there (people_type_id==1 only)
dept_people: dict[int, set] = {}
# dept_id → set of contractor people_ids (people_type_id==2 only)
contractor_dept_people: dict[int, set] = {}
for p in people_raw:
    if not p.get("active", True):
        continue
    dept = p.get("department") or {}
    did = dept.get("department_id")
    if not did:
        continue
    pt = p.get("people_type_id", 1)
    if pt == 1:
        dept_people.setdefault(did, set()).add(p["people_id"])
    elif pt == 2:
        contractor_dept_people.setdefault(did, set()).add(p["people_id"])

# ── Unknown-department check ───────────────────────────────────────────────────
# Warn if any active person's dept_id is not covered by any opco's groups or
# exclude_dept_ids. These people are silently dropped from the report.
_known_dept_ids: set[int] = set()
for _ocfg in OPCOS.values():
    for _grp in _ocfg["groups"].values():
        _known_dept_ids.update(_grp["ids"])
    _known_dept_ids.update(_ocfg.get("exclude_dept_ids", []))

_unknown_depts: dict[int, dict] = {}   # dept_id → {name, people}
for p in people_raw:
    if not p.get("active", True):
        continue
    dept = p.get("department") or {}
    did  = dept.get("department_id")
    if did and did not in _known_dept_ids:
        entry = _unknown_depts.setdefault(did, {"name": dept.get("name", "?"), "people": []})
        entry["people"].append(p.get("name", "?"))

if _unknown_depts:
    print()
    print("  ⚠  UNKNOWN DEPT IDs — active people not shown in any report:")
    for _did, _info in sorted(_unknown_depts.items()):
        _names = ", ".join(_info["people"][:4])
        _more  = f" +{len(_info['people'])-4} more" if len(_info["people"]) > 4 else ""
        print(f"     {_did}  '{_info['name']}' — {len(_info['people'])} people: {_names}{_more}")
    print("  → Add these dept IDs to eidra_opco_config.py to include them.")
    print()

# Expand allocations — including recurring ones.
# Float returns recurring allocations as a single record (first occurrence) with:
#   repeat_state:    0=none, 1=weekly, 2=monthly (~4wks), 3=biweekly, 4/6=unknown
#   repeat_end_date: last date the recurrence runs to
# Without expansion, only the first occurrence is counted.
_repeat_deltas = {
    1: timedelta(weeks=1),   # weekly
    2: timedelta(weeks=4),   # monthly (approximated as 4 weeks)
    3: timedelta(weeks=2),   # biweekly (every 2 weeks)
}
_repeat_unknown: set = set()
allocs = []
for a in alloc_raw:
    pids = list(a.get("people_ids") or [])
    if a.get("people_id") and a["people_id"] not in pids:
        pids.append(a["people_id"])
    repeat_state = a.get("repeat_state", 0)
    delta        = _repeat_deltas.get(repeat_state)
    if repeat_state and not delta:
        _repeat_unknown.add(repeat_state)   # log once; treat as non-repeating
    repeat_end = pd(a["repeat_end_date"]) if delta and a.get("repeat_end_date") else None
    dur        = pd(a["end_date"]) - pd(a["start_date"])
    for pid in pids:
        occ_start = pd(a["start_date"])
        while True:
            allocs.append({
                "pid":        pid,
                "start":      occ_start,
                "end":        occ_start + dur,
                "hpd":        float(a.get("hours") or 0),
                "status":     a.get("status", 0),
                "billable":   a.get("billable", 0),
                "project_id": a.get("project_id"),
            })
            if not delta or not repeat_end:
                break
            occ_start += delta
            if occ_start > repeat_end:
                break

if _repeat_unknown:
    print(f"  ⚠  Unknown repeat_state values (treated as non-repeating): {sorted(_repeat_unknown)}")

# Time-offs per person — including recurring ones (same expansion as allocations
# above; Float uses the same repeat_state codes but names the end-date field
# "repeat_end" instead of "repeat_end_date"). Without expansion, only the first
# occurrence of a weekly/monthly/biweekly recurring time-off is counted.
timeoffs_by_pid: dict[int, list] = {}
_to_repeat_unknown: set = set()
for t in timeoff_raw:
    pids = list(t.get("people_ids") or [])
    if not pids and t.get("people_id"):   # same fallback as allocations
        pids = [t["people_id"]]
    if not pids:
        continue
    h = t.get("hours")
    hpd = 8.0 if (t.get("full_day") == 1 or h is None or h == 0) else float(h)
    repeat_state = t.get("repeat_state", 0)
    delta        = _repeat_deltas.get(repeat_state)
    if repeat_state and not delta:
        _to_repeat_unknown.add(repeat_state)   # log once; treat as non-repeating
    repeat_end = pd(t["repeat_end"]) if delta and t.get("repeat_end") else None
    dur = pd(t["end_date"]) - pd(t["start_date"])
    occ_start = pd(t["start_date"])
    while True:
        entry = {"start": occ_start, "end": occ_start + dur, "hpd": hpd}
        for pid in pids:
            timeoffs_by_pid.setdefault(pid, []).append(entry)
        if not delta or not repeat_end:
            break
        occ_start += delta
        if occ_start > repeat_end:
            break

if _to_repeat_unknown:
    print(f"  ⚠  Unknown repeat_state values in timeoffs (treated as non-repeating): {sorted(_to_repeat_unknown)}")

# Project label helper
def project_label(project_id):
    """Return (client, project) tuple of full names for a Float project_id, or None."""
    if not project_id:
        return None
    proj = proj_map.get(project_id, {})
    proj_name   = (proj.get("name", "") or "").strip()
    client_id   = proj.get("client_id")
    client_name = (client_map.get(client_id, "") if client_id else "").strip()
    if not proj_name and not client_name:
        return None
    return (client_name, proj_name)

def format_project_labels(label_set):
    """
    Render a set of (client, project) tuples as HTML.
    - 1 project  → client up to 10 chars (bold) + space + project up to 10 chars
    - 2+ projects → client up to 5 chars (bold) + space + project up to 5 chars, one per line
    Returns "–" if empty.
    """
    if not label_set:
        return "–"
    items = sorted(label_set)  # sort by (client, project)
    n = len(items)
    cap = 10 if n == 1 else 5
    parts = []
    for client, proj in items:
        c = client[:cap].strip()
        p = proj[:cap].strip()
        if c and p:
            parts.append(f"<b>{c}</b> {p}")
        elif c:
            parts.append(f"<b>{c}</b>")
        else:
            parts.append(p)
    return "<br>".join(parts)

# ── Per-opco computation ───────────────────────────────────────────────────────
def is_active_in_range(pid):
    p_start, p_end = pid_dates.get(pid, (None, None))
    for _, ws, we in WEEKS:
        if (p_start is None or we >= p_start) and (p_end is None or ws <= p_end):
            return True
    return False

def compute_opco(opco_key):
    """
    Returns (results_by_group, consultants_by_group, excluded_by_group,
             pid_conf_text, pid_tent_text, pid_level)
    """
    cfg = OPCOS[opco_key]
    groups      = cfg["groups"]
    exclude_ids = set(cfg.get("exclude_dept_ids", []))
    role_lv_map = {**GENERIC_ROLE_LEVEL, **cfg.get("role_level_map", {})}

    # Build group → people sets
    group_all: dict[str, set] = {}
    for gk, gv in groups.items():
        pids: set = set()
        for did in gv["ids"]:
            pids |= dept_people.get(did, set())
        group_all[gk] = pids

    group_active = {
        gk: {pid for pid in pids
             if is_active_in_range(pid) and pid_type.get(pid, 1) == 1}
        for gk, pids in group_all.items()
    }

    # Level per person for this opco
    pid_level = {
        pid: role_lv_map.get(pid_role_id.get(pid), "")
        for group_pids in group_active.values()
        for pid in group_pids
    }

    # Sorted consultant lists per group. Carries pid through explicitly (not
    # just name+level) so downstream slide rendering never has to re-look-up
    # a person by matching their display name — two people anywhere in the
    # company sharing an exact name would otherwise silently collide.
    consultants_by_group = {
        gk: sorted(
            [(pid, pid_name[pid], pid_level.get(pid, "")) for pid in pids if pid in pid_name],
            key=lambda x: (_lsort(x[2]), x[1])
        )
        for gk, pids in group_active.items()
    }

    # Project labels within the report window
    window_start = WEEKS[0][1]
    window_end   = WEEKS[-1][2]
    all_pids: set = set()
    for pids in group_active.values():
        all_pids |= pids

    _conf_projs: dict = {}
    _tent_projs: dict = {}
    for a in allocs:
        if a["pid"] not in all_pids:
            continue
        if a["start"] > window_end or a["end"] < window_start:
            continue
        label = project_label(a.get("project_id"))
        if not label:
            continue
        if a["status"] == 2:
            _conf_projs.setdefault(a["pid"], set()).add(label)
        elif a["status"] == 1:
            _tent_projs.setdefault(a["pid"], set()).add(label)

    pid_conf_text = {pid: format_project_labels(labels) for pid, labels in _conf_projs.items()}
    pid_tent_text = {pid: format_project_labels(labels) for pid, labels in _tent_projs.items()}

    # Compute metrics per group per week
    results: dict[str, dict] = {}
    for gk, gpids in group_active.items():
        results[gk] = {"weeks": {}}
        for wname, ws, we in WEEKS:
            p_date_cache = {pid: pid_dates.get(pid, (None, None)) for pid in gpids}
            week_pids = {
                pid for pid in gpids
                if (p_date_cache[pid][0] is None or p_date_cache[pid][0] <= we)
                and (p_date_cache[pid][1] is None or p_date_cache[pid][1] >= ws)
            }
            total_fte = len(week_pids)

            to_h = {}
            for pid in week_pids:
                h = sum(
                    workdays(t["start"], t["end"], ws, we) * t["hpd"]
                    for t in timeoffs_by_pid.get(pid, [])
                )
                to_h[pid] = h

            conf_by_pid: dict = {}
            tent_by_pid: dict = {}
            conf_h = tent_h = 0.0

            for a in allocs:
                if a["pid"] not in week_pids:
                    continue
                ov = workdays(a["start"], a["end"], ws, we)
                if not ov:
                    continue
                h = ov * a["hpd"]
                if a["status"] == 2:
                    conf_by_pid[a["pid"]] = conf_by_pid.get(a["pid"], 0.0) + h
                    if a["billable"] == 1:
                        conf_h += h
                elif a["status"] == 1:
                    tent_by_pid[a["pid"]] = tent_by_pid.get(a["pid"], 0.0) + h
                    if a["billable"] == 1:
                        tent_h += h

            # Per-person contracted cap: prorate for people who start/end mid-week
            def _pcap(pid):
                ps, pe = pid_dates.get(pid, (None, None))
                d_s = max(ws, ps) if ps else ws
                d_e = min(we, pe) if pe else we
                return workdays(d_s, d_e, ws, we) * 8.0

            cap_h    = sum(_pcap(p) for p in week_pids)
            tent_fte = round(tent_h / 40, 1)

            sum_unbooked = sum(
                max(0.0, _pcap(p) - to_h.get(p, 0) - conf_by_pid.get(p, 0))
                for p in week_pids
            )
            sum_unbooked_incl = sum(
                max(0.0, _pcap(p) - to_h.get(p, 0) - conf_by_pid.get(p, 0) - tent_by_pid.get(p, 0))
                for p in week_pids
            )
            avail_pct_sold = round(sum_unbooked      / cap_h * 100) if cap_h > 0 else None
            avail_pct_incl = round(sum_unbooked_incl / cap_h * 100) if cap_h > 0 else None
            # avail_fte and avail_heads use incl-tentative to match Float's definition:
            # tentative bookings are treated as committed capacity.
            avail_fte      = round(sum_unbooked_incl / 40.0, 1)
            avail_heads_50 = sum(
                1 for p in week_pids
                if max(0.0, _pcap(p) - to_h.get(p, 0) - conf_by_pid.get(p, 0) - tent_by_pid.get(p, 0)) >= 20.0
            )

            sum_timeoff  = sum(to_h.values())
            avail_cap_h  = cap_h - sum_timeoff
            charge_pct      = round(conf_h / avail_cap_h * 100) if avail_cap_h > 0 else None
            charge_incl_pct = round((conf_h + tent_h) / avail_cap_h * 100) if avail_cap_h > 0 else None

            results[gk]["weeks"][wname] = {
                "total_fte":        total_fte,
                "avail_fte":        avail_fte,
                "tent_fte":         tent_fte,
                "conf_h":           round(conf_h, 1),
                "tent_h":           round(tent_h, 1),
                "avail_pct_sold":   avail_pct_sold,
                "avail_pct_incl":   avail_pct_incl,
                "avail_heads_50":   avail_heads_50,
                "sum_unbooked":     sum_unbooked,
                "sum_unbooked_incl":sum_unbooked_incl,
                "cap_h":            cap_h,
                "sum_timeoff":      round(sum_timeoff, 1),
                "charge_pct":       charge_pct,
                "charge_incl_pct":  charge_incl_pct,
                "person_conf":      conf_by_pid,
                "person_tent":      tent_by_pid,
                "person_timeoff":   dict(to_h),
            }

    return results, consultants_by_group, pid_conf_text, pid_tent_text, pid_level


def compute_contractors(opco_key):
    """
    Compute availability for contractors in this opco.
    Contractors are NOT included in opco KPIs — this data drives a separate
    'Contractors' slide appended after the regular group slides.
    Returns (results, consultants, pid_conf_text, pid_tent_text)
    or None if the opco has no contractors.
    """
    cfg         = OPCOS[opco_key]
    exclude_ids = set(cfg.get("exclude_dept_ids", []))
    role_lv_map = {**GENERIC_ROLE_LEVEL, **cfg.get("role_level_map", {})}

    # All dept_ids that belong to this opco (groups + top-level, minus excludes)
    opco_dept_ids: set = {cfg["dept_id"]}
    for gv in cfg["groups"].values():
        opco_dept_ids.update(gv["ids"])
    opco_dept_ids -= exclude_ids

    all_ctrs: set = set()
    for did in opco_dept_ids:
        all_ctrs |= contractor_dept_people.get(did, set())
    if not all_ctrs:
        return None

    active_ctrs = {pid for pid in all_ctrs if is_active_in_range(pid)}
    if not active_ctrs:
        return None

    # Build pid → dept name for contractors
    pid_dept_label: dict[int, str] = {}
    for p in people_raw:
        if p.get("people_type_id") != 2:
            continue
        dept = p.get("department") or {}
        pid_dept_label[p["people_id"]] = dept.get("name") or ""

    # Group contractors by sub-department, sorted by dept name then level then name
    from collections import defaultdict as _dd
    _by_dept: dict[str, list] = _dd(list)
    for pid in active_ctrs:
        if pid not in pid_name:
            continue
        lv = role_lv_map.get(pid_role_id.get(pid), "")
        _by_dept[pid_dept_label.get(pid, "")].append((pid, pid_name[pid], lv))
    for _members in _by_dept.values():
        _members.sort(key=lambda x: (_lsort(x[2]), x[1]))
    # dept_groups: [(dept_label, [(pid, name, level), ...]), ...] ordered by dept name.
    # pid carried through explicitly — see comment on consultants_by_group above.
    dept_groups = sorted(_by_dept.items(), key=lambda x: x[0])

    # Project labels for the window
    window_start, window_end = WEEKS[0][1], WEEKS[-1][2]
    _conf_projs: dict = {}
    _tent_projs: dict = {}
    for a in allocs:
        if a["pid"] not in active_ctrs:
            continue
        if a["start"] > window_end or a["end"] < window_start:
            continue
        lbl = project_label(a.get("project_id"))
        if not lbl:
            continue
        if a["status"] == 2:
            _conf_projs.setdefault(a["pid"], set()).add(lbl)
        elif a["status"] == 1:
            _tent_projs.setdefault(a["pid"], set()).add(lbl)
    pid_conf_text = {pid: format_project_labels(v) for pid, v in _conf_projs.items()}
    pid_tent_text = {pid: format_project_labels(v) for pid, v in _tent_projs.items()}

    # Weekly metrics — identical logic to compute_opco's inner loop
    results: dict = {"weeks": {}}
    for wname, ws, we in WEEKS:
        p_date_cache = {pid: pid_dates.get(pid, (None, None)) for pid in active_ctrs}
        week_pids = {
            pid for pid in active_ctrs
            if (p_date_cache[pid][0] is None or p_date_cache[pid][0] <= we)
            and (p_date_cache[pid][1] is None or p_date_cache[pid][1] >= ws)
        }
        total_fte = len(week_pids)

        to_h: dict = {}
        for pid in week_pids:
            to_h[pid] = sum(
                workdays(t["start"], t["end"], ws, we) * t["hpd"]
                for t in timeoffs_by_pid.get(pid, [])
            )

        conf_by_pid: dict = {}
        tent_by_pid: dict = {}
        conf_h = tent_h = 0.0
        for a in allocs:
            if a["pid"] not in week_pids:
                continue
            ov = workdays(a["start"], a["end"], ws, we)
            if not ov:
                continue
            h = ov * a["hpd"]
            if a["status"] == 2:
                conf_by_pid[a["pid"]] = conf_by_pid.get(a["pid"], 0.0) + h
                if a["billable"] == 1:
                    conf_h += h
            elif a["status"] == 1:
                tent_by_pid[a["pid"]] = tent_by_pid.get(a["pid"], 0.0) + h
                if a["billable"] == 1:
                    tent_h += h

        def _pcap(pid):
            ps, pe = pid_dates.get(pid, (None, None))
            d_s = max(ws, ps) if ps else ws
            d_e = min(we, pe) if pe else we
            return workdays(d_s, d_e, ws, we) * 8.0

        cap_h             = sum(_pcap(p) for p in week_pids)
        tent_fte          = round(tent_h / 40, 1)
        sum_unbooked      = sum(max(0.0, _pcap(p) - to_h.get(p, 0) - conf_by_pid.get(p, 0)) for p in week_pids)
        sum_unbooked_incl = sum(max(0.0, _pcap(p) - to_h.get(p, 0) - conf_by_pid.get(p, 0) - tent_by_pid.get(p, 0)) for p in week_pids)
        avail_pct_sold    = round(sum_unbooked      / cap_h * 100) if cap_h > 0 else None
        avail_pct_incl    = round(sum_unbooked_incl / cap_h * 100) if cap_h > 0 else None
        avail_fte         = round(sum_unbooked_incl / 40.0, 1)
        avail_heads_50    = sum(
            1 for p in week_pids
            if max(0.0, _pcap(p) - to_h.get(p, 0) - conf_by_pid.get(p, 0) - tent_by_pid.get(p, 0)) >= 20.0
        )

        results["weeks"][wname] = {
            "total_fte":         total_fte,
            "avail_fte":         avail_fte,
            "tent_fte":          tent_fte,
            "conf_h":            round(conf_h, 1),
            "tent_h":            round(tent_h, 1),
            "avail_pct_sold":    avail_pct_sold,
            "avail_pct_incl":    avail_pct_incl,
            "avail_heads_50":    avail_heads_50,
            "sum_unbooked":      sum_unbooked,
            "sum_unbooked_incl": sum_unbooked_incl,
            "cap_h":             cap_h,
            "person_conf":       conf_by_pid,
            "person_tent":       tent_by_pid,
            "person_timeoff":    dict(to_h),
        }

    return results, dept_groups, pid_conf_text, pid_tent_text


# ── Colour helpers ─────────────────────────────────────────────────────────────
def lerp(a, b, t):
    return round(a + t * (b - a))

def heat_sold(h):
    h = max(0.0, min(float(h), 40.0))
    if h == 0:
        return "#ffffff", "#1a1a1a"
    t = h / 40.0
    gb = lerp(255, 80, t)
    bg = f"#ff{gb:02x}{gb:02x}"
    fg = "#ffffff" if t > 0.6 else "#1a1a1a"
    return bg, fg

def heat_tent(h):
    h = max(0.0, min(float(h), 40.0))
    if h == 0:
        return "#ffffff", "#1a1a1a"
    t = h / 40.0
    r = lerp(255, 41, t)
    g = lerp(255, 128, t)
    b = lerp(255, 185, t)
    bg = f"#{r:02x}{g:02x}{b:02x}"
    fg = "#ffffff" if t > 0.55 else "#1a1a1a"
    return bg, fg

def avail_row_color(pct):
    pct = max(0, min(100, pct))
    if pct <= 35:
        t = pct / 35.0
        r = lerp(56,  255, t)
        g = lerp(142, 255, t)
        b = lerp(60,  255, t)
    else:
        t = (pct - 35) / 65.0
        r = lerp(255, 204, t)
        g = lerp(255, 0,   t)
        b = lerp(255, 0,   t)
    bg = f"#{r:02x}{g:02x}{b:02x}"
    fg = "#ffffff" if pct < 18 or pct > 65 else "#1a1a1a"
    return bg, fg

def charge_row_color(pct):
    """Reversed scale: 85%+ = green, ≤40% = red.
    Maps chargeability to the same palette as avail_row_color but inverted:
    100% chargeability → avail_row_color(0) = deep green
    0% chargeability   → avail_row_color(100) = deep red
    """
    # Map chargeability pct so that 85→0 and 40→100 on the avail scale
    low, high = 25.0, 70.0
    pct_clamped = max(0.0, min(100.0, float(pct)))
    avail_equiv = 100.0 - max(0.0, min(100.0, (pct_clamped - low) / (high - low) * 100.0))
    return avail_row_color(avail_equiv)

def fmt_h(h):
    return str(int(h)) if h == int(h) else f"{h:.1f}"

# Level sort: L6 first → L0 → everything else (Lx, Intern, blank…) last
_LEVEL_ORDER = {"L6": 0, "L5": 1, "L4": 2, "L3": 3, "L2": 4, "L1": 5, "L0": 6}

def _lsort(level: str) -> tuple:
    """Return (bucket, level_str) so L6…L0 sort high-to-low, then others alphabetically."""
    return (_LEVEL_ORDER.get(level, 7), level)

def fmt_fte(v):
    return str(int(v)) if v == int(v) else f"{v:.1f}"

def make_inactive_cell(extra_cls=""):
    return (
        f'<td class="wk{extra_cls}" style="background:repeating-linear-gradient('
        '45deg,#d0d0d0,#d0d0d0 2px,#ebebeb 2px,#ebebeb 8px)"></td>'
    )

def make_wk_cell(unbooked_h, tent_h, timeoff_h=0.0, extra_cls=""):
    if timeoff_h >= 40.0:
        return f'<td class="wk{extra_cls}" style="background:#e0e0e0;color:#1a1a1a"></td>'
    if unbooked_h <= 0:
        return f'<td class="wk{extra_cls}" style="background:#ffffff;color:#1a1a1a"></td>'
    sb, sf = heat_sold(unbooked_h)
    unbooked_str = fmt_h(unbooked_h)
    if tent_h <= 0:
        return f'<td class="wk{extra_cls}" style="background:{sb};color:{sf}">{unbooked_str}</td>'
    tb, tf = heat_tent(tent_h)
    tent_str = fmt_h(tent_h)
    return (
        f'<td class="wk{extra_cls}" style="position:relative;padding:0;overflow:hidden">'
        f'<div style="position:absolute;inset:0;'
        f'background:linear-gradient(135deg,{sb} 50%,{tb} 50%)"></div>'
        f'<span style="position:absolute;top:2px;left:4px;'
        f'font-size:10px;color:{sf};z-index:1">{unbooked_str}</span>'
        f'<span style="position:absolute;bottom:2px;right:4px;'
        f'font-size:10px;color:{tf};z-index:1">{tent_str}</span>'
        f'</td>'
    )

# ── Month headers ──────────────────────────────────────────────────────────────
MONTH_NAMES = ["","January","February","March","April","May","June",
               "July","August","September","October","November","December"]

def week_dominant_month(ws, we):
    counts = {}
    d = ws
    while d <= we:
        if d.weekday() < 5:
            counts[d.month] = counts.get(d.month, 0) + 1
        d += timedelta(1)
    return max(counts, key=counts.get) if counts else ws.month

# ── Slide generators ───────────────────────────────────────────────────────────

def _toggle_td():
    """Thin clickable divider cell between visible and extended weeks."""
    return '<td class="wk-toggle-col" onclick="toggleExtWeeks()"></td>'

def _toggle_th(show_label=False):
    """Toggle <th> for header rows."""
    inner = '<span class="wk-toggle-label"></span>' if show_label else ''
    return (
        f'<th class="wk-toggle-col" onclick="toggleExtWeeks()" '
        f'title="Show / hide weeks {WEEKS_EXT[0][0]}–{WEEKS_EXT[-1][0]}">{inner}</th>'
    )

def _week_ths():
    main = "\n".join(f'<th class="wk">{w}</th>' for w, _, _ in WEEKS_MAIN)
    ext  = "\n".join(f'<th class="wk wk-ext">{w}</th>' for w, _, _ in WEEKS_EXT)
    return main + "\n" + _toggle_th(show_label=False) + "\n" + ext

def _month_row(name_cols=1):
    """Month header row, split at N_VISIBLE with a clickable toggle column between main and ext.
    name_cols: how many fixed left-hand columns to span with the first <th> (default 1).
    """
    month_seq = [week_dominant_month(ws, we) for _, ws, we in WEEKS]
    # Build groups as [month, start_idx, end_idx]
    groups: list[list] = []
    for i, m in enumerate(month_seq):
        if groups and groups[-1][0] == m:
            groups[-1][2] = i
        else:
            groups.append([m, i, i])

    cs = f' colspan="{name_cols}"' if name_cols > 1 else ''
    cells = [f'<th class="tname"{cs} style="background:#444;color:#fff;min-width:220px"></th>']
    toggle_added = False
    color_idx    = 0
    for m, s, e in groups:
        bg    = "#555" if color_idx % 2 == 0 else "#4a4a4a"
        style = f'background:{bg};color:#fff;text-align:center;font-size:10px;padding:4px'
        color_idx += 1
        main_cnt = sum(1 for i in range(s, e + 1) if i < N_VISIBLE)
        ext_cnt  = sum(1 for i in range(s, e + 1) if i >= N_VISIBLE)
        if main_cnt:
            cells.append(f'<th colspan="{main_cnt}" style="{style}">{MONTH_NAMES[m]}</th>')
        if ext_cnt and not toggle_added:
            cells.append(_toggle_th(show_label=True))
            toggle_added = True
        if ext_cnt:
            cells.append(f'<th colspan="{ext_cnt}" class="wk-ext" style="{style}">{MONTH_NAMES[m]}</th>')
    if not toggle_added:
        cells.append(_toggle_th(show_label=True))

    return '<tr class="month-hdr">' + "".join(cells) + '</tr>'

def _pct_cell(v, colorize=True, ext=False):
    cls = "wk sum-val" + (" wk-ext" if ext else "")
    if v is None:
        return f'<td class="{cls}">–</td>'
    if colorize:
        bg, fg = avail_row_color(v)
        return f'<td class="{cls}" style="background:{bg};color:{fg};font-weight:700">{v}%</td>'
    return f'<td class="{cls}">{v}%</td>'

def _val_cell(v, ext=False):
    cls = "wk sum-val" + (" wk-ext" if ext else "")
    return f'<td class="{cls}">{v}</td>'

def _kpi_cells_val(fn):
    """Build a run of KPI value cells: main | toggle | ext."""
    main = "".join(_val_cell(fn(w))       for w in [w for w, _, _ in WEEKS_MAIN])
    ext  = "".join(_val_cell(fn(w), True) for w in [w for w, _, _ in WEEKS_EXT])
    return main + _toggle_td() + ext

def _kpi_cells_pct(fn, colorize=True):
    """Build a run of KPI pct cells: main | toggle | ext."""
    main = "".join(_pct_cell(fn(w), colorize)       for w in [w for w, _, _ in WEEKS_MAIN])
    ext  = "".join(_pct_cell(fn(w), colorize, True) for w in [w for w, _, _ in WEEKS_EXT])
    return main + _toggle_td() + ext

def _pct_cell_charge(v, colorize=True, ext=False):
    """Like _pct_cell but uses charge_row_color (reversed: high = green)."""
    cls = "wk sum-val" + (" wk-ext" if ext else "")
    if v is None:
        return f'<td class="{cls}">–</td>'
    if colorize:
        bg, fg = charge_row_color(v)
        return f'<td class="{cls}" style="background:{bg};color:{fg};font-weight:700">{v}%</td>'
    return f'<td class="{cls}">{v}%</td>'

def _kpi_cells_pct_charge(fn, colorize=True):
    """Build chargeability KPI cells: main | toggle | ext."""
    main = "".join(_pct_cell_charge(fn(w), colorize)       for w in [w for w, _, _ in WEEKS_MAIN])
    ext  = "".join(_pct_cell_charge(fn(w), colorize, True) for w in [w for w, _, _ in WEEKS_EXT])
    return main + _toggle_td() + ext


def generate_summary_slide(opco_key, results):
    cfg    = OPCOS[opco_key]
    groups = cfg["groups"]
    wnames = [w for w, _, _ in WEEKS]
    wnames_main = [w for w, _, _ in WEEKS_MAIN]
    wnames_ext  = [w for w, _, _ in WEEKS_EXT]
    n      = len(wnames)
    # Total cols: name + N_VISIBLE + toggle + ext = 1 + 12 + 1 + 8 = 22
    _total_cols = 1 + N_VISIBLE + 1 + len(WEEKS_EXT)

    # Opco-level aggregates (still computed across all 20 weeks)
    agg = {}
    for wname in wnames:
        raw_ub   = sum(results[g]["weeks"][wname]["sum_unbooked"]      for g in groups if g in results)
        raw_ubi  = sum(results[g]["weeks"][wname]["sum_unbooked_incl"] for g in groups if g in results)
        cap      = sum(results[g]["weeks"][wname]["cap_h"]             for g in groups if g in results)
        conf_h   = sum(results[g]["weeks"][wname]["conf_h"]            for g in groups if g in results)
        tent_h   = sum(results[g]["weeks"][wname]["tent_h"]            for g in groups if g in results)
        to_total = sum(results[g]["weeks"][wname]["sum_timeoff"]       for g in groups if g in results)
        avail_cap = cap - to_total
        agg[wname] = {
            "total_fte":       sum(results[g]["weeks"][wname]["total_fte"]      for g in groups if g in results),
            "avail_fte":       round(sum(results[g]["weeks"][wname]["avail_fte"] for g in groups if g in results), 1),
            "avail_heads_50":  sum(results[g]["weeks"][wname]["avail_heads_50"] for g in groups if g in results),
            "tent_fte":        round(sum(results[g]["weeks"][wname]["tent_fte"] for g in groups if g in results), 1),
            "avail_pct_sold":  round(raw_ub  / cap * 100) if cap > 0 else None,
            "avail_pct_incl":  round(raw_ubi / cap * 100) if cap > 0 else None,
            "charge_pct":      round(conf_h / avail_cap * 100) if avail_cap > 0 else None,
            "charge_incl_pct": round((conf_h + tent_h) / avail_cap * 100) if avail_cap > 0 else None,
        }

    def make_agg_rows():
        rows = []
        rows.append(
            '<tr class="sumrow"><td class="tname sum-label">Total FTE</td>'
            + _kpi_cells_val(lambda w: fmt_fte(agg[w]["total_fte"])) + '</tr>'
        )
        rows.append(
            '<tr class="sumrow"><td class="tname sum-label">Availability FTE Sum</td>'
            + _kpi_cells_val(lambda w: fmt_fte(agg[w]["avail_fte"])) + '</tr>'
        )
        rows.append(
            '<tr class="sumrow"><td class="tname sum-label">Available heads (50%+)</td>'
            + _kpi_cells_val(lambda w: str(agg[w]["avail_heads_50"])) + '</tr>'
        )
        rows.append(
            '<tr class="sumrow"><td class="tname sum-label">Tentative FTE Sum</td>'
            + _kpi_cells_val(lambda w: fmt_fte(agg[w]["tent_fte"])) + '</tr>'
        )
        rows.append(
            '<tr class="sumrow"><td class="tname sum-label">Availability</td>'
            + _kpi_cells_pct(lambda w: agg[w]["avail_pct_sold"], True) + '</tr>'
        )
        rows.append(
            '<tr class="sumrow"><td class="tname sum-label">Availability incl Tentative</td>'
            + _kpi_cells_pct(lambda w: agg[w]["avail_pct_incl"], False) + '</tr>'
        )
        rows.append(
            '<tr class="sumrow"><td class="tname sum-label">Chargeability</td>'
            + _kpi_cells_pct_charge(lambda w: agg[w]["charge_pct"], True) + '</tr>'
        )
        rows.append(
            '<tr class="sumrow"><td class="tname sum-label">Chargeability incl Tentative</td>'
            + _kpi_cells_pct_charge(lambda w: agg[w]["charge_incl_pct"], False) + '</tr>'
        )
        return "\n".join(rows)

    def make_dept_rows(wdata):
        rows = []
        rows.append(
            '<tr class="sumrow"><td class="tname sum-label">Available heads (50%+)</td>'
            + _kpi_cells_val(lambda w: str(wdata[w]["avail_heads_50"])) + '</tr>'
        )
        rows.append(
            '<tr class="sumrow"><td class="tname sum-label">Availability</td>'
            + _kpi_cells_pct(lambda w: wdata[w]["avail_pct_sold"], True) + '</tr>'
        )
        rows.append(
            '<tr class="sumrow"><td class="tname sum-label">Availability incl Tentative</td>'
            + _kpi_cells_pct(lambda w: wdata[w]["avail_pct_incl"], False) + '</tr>'
        )
        rows.append(
            '<tr class="sumrow"><td class="tname sum-label">Chargeability</td>'
            + _kpi_cells_pct_charge(lambda w: wdata[w]["charge_pct"], True) + '</tr>'
        )
        rows.append(
            '<tr class="sumrow"><td class="tname sum-label">Chargeability incl Tentative</td>'
            + _kpi_cells_pct_charge(lambda w: wdata[w]["charge_incl_pct"], False) + '</tr>'
        )
        return "\n".join(rows)

    def _colored_wk_cells(color, is_ext=False):
        cls = "wk sum-val" + (" wk-ext" if is_ext else "")
        return f'<td class="{cls}" style="background:{color};border-color:#555"></td>'

    def _tinted_wk_cells(tint, is_ext=False):
        cls = "wk sum-val" + (" wk-ext" if is_ext else "")
        return f'<td class="{cls}" style="background:{tint}"></td>'

    tbody = []
    opco_color = cfg["color"]
    tbody.append(
        f'<tr style="background:{opco_color}">'
        f'<td class="tname" style="color:#fff;font-weight:700;font-size:13px;'
        f'letter-spacing:.3px;padding:6px 8px">{cfg["display_name"]} (All Departments)</td>'
        + "".join(_colored_wk_cells(opco_color)       for _ in wnames_main)
        + _toggle_td()
        + "".join(_colored_wk_cells(opco_color, True) for _ in wnames_ext)
        + '</tr>'
    )
    tbody.append(make_agg_rows())

    for gk, gv in groups.items():
        if gk not in results:
            continue
        color = gv["color"]
        tint  = color + "28"
        tbody.append(f'<tr><td colspan="{_total_cols}" style="height:5px;background:#ddd;padding:0"></td></tr>')
        tbody.append(
            f'<tr style="background:{tint}">'
            f'<td class="tname" style="font-weight:700;font-size:12px;color:#222;'
            f'padding:5px 8px;border-left:4px solid {color}">{gv["label"]}</td>'
            + "".join(_tinted_wk_cells(tint)       for _ in wnames_main)
            + _toggle_td()
            + "".join(_tinted_wk_cells(tint, True) for _ in wnames_ext)
            + '</tr>'
        )
        tbody.append(make_dept_rows(results[gk]["weeks"]))

    return (
        f'<section id="opco-{opco_key}-summary" class="slide">\n'
        f'<div class="slide-label"><span>{cfg["display_name"]}</span></div>\n'
        f'<div class="slide-content">\n'
        f'<div class="slide-title">Allocation Summary</div>\n'
        f'<div class="tbl-wrap">\n'
        f'<table>\n'
        f'<thead>\n'
        + _month_row() + '\n'
        + '<tr class="hdr"><th class="tname">Department / Metric</th>\n'
        + _week_ths() + '\n</tr>\n'
        + '</thead>\n<tbody>\n'
        + "\n".join(tbody)
        + '\n</tbody>\n</table>\n</div>\n</div>\n</section>\n'
    )


def generate_all_consultants_slide(opco_key, results, consultants_by_group,
                                    pid_conf_text, pid_tent_text):
    """Flat, sortable list of all active non-contractor consultants in this opco.

    Columns: Consultant | Sub-Department | Level | weekly heatmap | Confirmed | Tentative
    Sorted by level descending (L6 first) then name.
    """
    cfg    = OPCOS[opco_key]
    groups = cfg["groups"]

    lvl_td_style = "text-align:center;font-size:11px;color:#555;background:#f5f5f5;min-width:52px"
    subdept_td_style = "font-size:11px;color:#555;background:#f5f5f5;min-width:110px;max-width:140px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis"

    # Build flat list: (pid, name, level, subdept_label)
    all_people = []
    for gk, gv in groups.items():
        for pid, name, level in consultants_by_group.get(gk, []):
            all_people.append((pid, name, level, gv["label"]))

    # Sort: level desc (L6→L0→other), then name asc
    all_people.sort(key=lambda x: (_lsort(x[2]), x[1]))

    rows = []
    for pid, name, level, subdept in all_people:
        p_start, p_end = pid_dates.get(pid, (None, None))
        cells = ""
        for i, (wname, ws, we) in enumerate(WEEKS):
            if i == N_VISIBLE:
                cells += _toggle_td()
            ext = " wk-ext" if i >= N_VISIBLE else ""
            if (p_start and we < p_start) or (p_end and ws > p_end):
                cells += make_inactive_cell(ext)
                continue
            # Find which group this person's wdata lives in
            wd = None
            for gk in groups:
                if gk in results and pid in results[gk]["weeks"][wname].get("person_conf", {}):
                    wd = results[gk]["weeks"][wname]
                    break
            if wd is None:
                # Try person_timeoff as fallback key
                for gk in groups:
                    if gk in results and pid in results[gk]["weeks"][wname].get("person_timeoff", {}):
                        wd = results[gk]["weeks"][wname]
                        break
            if wd is None:
                cells += f'<td class="wk{ext}"></td>'
                continue
            timeoff  = wd["person_timeoff"].get(pid, 0.0)
            conf     = wd["person_conf"].get(pid, 0.0)
            tent     = wd["person_tent"].get(pid, 0.0)
            unbooked = max(0.0, 40.0 - timeoff - conf)
            cells += make_wk_cell(unbooked, tent, timeoff, ext)

        conf_t = pid_conf_text.get(pid, "–")
        tent_t = pid_tent_text.get(pid, "–")
        rows.append(
            f'<tr class="prow">'
            f'<td class="tname">{name}</td>'
            f'<td class="wk level-val" style="{subdept_td_style}">{subdept}</td>'
            f'<td class="wk level-val" style="{lvl_td_style}">{level}</td>'
            + cells
            + f'<td class="tclients">{conf_t}</td>'
            + f'<td class="tclients proj-tent">{tent_t}</td>'
            + '</tr>'
        )

    slide_id = f"opco-{opco_key}-all-consultants"
    return (
        f'<section id="{slide_id}" class="slide">\n'
        f'<div class="slide-label"><span>All Consultants</span></div>\n'
        f'<div class="slide-content">\n'
        f'<div class="slide-title">All Consultants ({len(all_people)})</div>\n'
        f'<div class="tbl-wrap">\n'
        f'<table>\n'
        f'<thead>\n'
        + _month_row(name_cols=3) + '\n'
        + '<tr class="hdr">'
        + '<th class="tname">Consultant</th>'
        + '<th class="wk level-col" style="text-align:center;font-size:11px">Capability/SkillTrack</th>'
        + '<th class="wk level-col" style="text-align:center;font-size:11px">Level</th>'
        + _week_ths() + '\n'
        + '<th class="tclients">Confirmed projects</th>'
        + '<th class="tclients">Tentative projects</th>'
        + '</tr>\n'
        + '</thead>\n<tbody>\n'
        + "\n".join(rows)
        + '\n</tbody>\n</table>\n</div>\n</div>\n</section>\n'
    )


def generate_graph_slide(opco_key, results):
    cfg    = OPCOS[opco_key]
    groups = cfg["groups"]
    wnames = [w for w, _, _ in WEEKS]

    agg = {}
    for wname in wnames:
        raw_ub  = sum(results[g]["weeks"][wname]["sum_unbooked"]      for g in groups if g in results)
        raw_ubi = sum(results[g]["weeks"][wname]["sum_unbooked_incl"] for g in groups if g in results)
        cap     = sum(results[g]["weeks"][wname]["cap_h"]             for g in groups if g in results)
        agg[wname] = {
            "avail_pct_sold": round(raw_ub  / cap * 100) if cap > 0 else None,
            "avail_pct_incl": round(raw_ubi / cap * 100) if cap > 0 else None,
        }

    datasets = []
    for gk, gv in groups.items():
        if gk not in results:
            continue
        vals  = [round(results[gk]["weeks"][w]["avail_fte"], 2) for w in wnames]
        short = gv["label"].split("–")[-1].strip() if "–" in gv["label"] else gv["label"]
        datasets.append({
            "type": "bar", "label": short, "data": vals,
            "backgroundColor": gv["color"], "stack": "s",
            "yAxisID": "y", "barPercentage": 0.85
        })
    datasets.append({
        "type": "line", "label": "Availability %",
        "data": [agg[w]["avail_pct_sold"] for w in wnames],
        "borderColor": "#111", "backgroundColor": "transparent",
        "borderWidth": 2.5, "pointRadius": 4,
        "yAxisID": "y2", "tension": 0.3, "order": 0
    })
    datasets.append({
        "type": "line", "label": "Availability incl Tent. %",
        "data": [agg[w]["avail_pct_incl"] for w in wnames],
        "borderColor": "#888", "backgroundColor": "transparent",
        "borderWidth": 1.5, "pointRadius": 3, "borderDash": [5, 4],
        "yAxisID": "y2", "tension": 0.3, "order": 0
    })

    chart_json = json.dumps({"labels": wnames, "datasets": datasets})
    canvas_id  = f"chart-{opco_key}"

    # ── Per-sub-dept mini charts ───────────────────────────────────────────────
    mini_html   = ""
    mini_script = ""
    active_groups = [gk for gk in groups if gk in results]

    for gk in active_groups:
        gv       = groups[gk]
        mid      = f"minichart-{opco_key}-{gk.lower().replace('/', '-').replace(' ', '-')}"
        short    = gv["label"].split("–")[-1].strip() if "–" in gv["label"] else gv["label"]
        color    = gv["color"]

        sold_vals = []
        incl_vals = []
        for w in wnames:
            wd   = results[gk]["weeks"][w]
            cap  = wd.get("cap_h", 0)
            sold_vals.append(round(wd["sum_unbooked"]      / cap * 100) if cap > 0 else None)
            incl_vals.append(round(wd["sum_unbooked_incl"] / cap * 100) if cap > 0 else None)

        mini_data = json.dumps({
            "labels": wnames,
            "datasets": [
                {"type": "bar",  "label": "Avail (Sold) %",     "data": sold_vals,
                 "backgroundColor": color, "barPercentage": 0.85},
                {"type": "line", "label": "Avail incl Tent. %", "data": incl_vals,
                 "borderColor": "#888", "backgroundColor": "transparent",
                 "borderWidth": 1.5, "pointRadius": 0, "borderDash": [4, 3], "tension": 0.3},
            ]
        })

        mini_html += (
            f'<div style="background:#fff;border:1px solid #e0e0e0;border-radius:6px;padding:12px 10px 8px">\n'
            f'  <div style="font-size:12px;font-weight:700;margin-bottom:6px;color:#333">{short}</div>\n'
            f'  <div style="position:relative;height:200px">\n'
            f'    <canvas id="{mid}"></canvas>\n'
            f'  </div>\n'
            f'</div>\n'
        )
        mini_script += f"""(function(){{
  function build(){{
    var ctx=document.getElementById('{mid}'); if(!ctx)return;
    if(ctx._ci)ctx._ci.destroy();
    ctx._ci=new Chart(ctx,{{
      type:'bar',data:{mini_data},
      options:{{
        responsive:true,maintainAspectRatio:false,
        scales:{{
          x:{{ticks:{{font:{{size:9}},maxRotation:0,autoSkip:true,maxTicksLimit:10}}}},
          y:{{min:0,max:100,ticks:{{callback:function(v){{return v+'%'}},font:{{size:9}},stepSize:25}},
             grid:{{color:'#f0f0f0'}}}}
        }},
        plugins:{{legend:{{display:false}},tooltip:{{mode:'index',intersect:false}}}}
      }}
    }});
  }}
  if(typeof Chart!=='undefined')build();
  else{{var s=document.createElement('script');s.src='https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js';s.onload=build;document.head.appendChild(s);}}
}})();
"""

    script = f"""(function(){{
  function build(){{
    var ctx=document.getElementById('{canvas_id}'); if(!ctx)return;
    if(ctx._ci){{ctx._ci.destroy();}}
    ctx._ci=new Chart(ctx,{{
      type:'bar',
      data:{chart_json},
      options:{{
        responsive:true,maintainAspectRatio:false,
        scales:{{
          x:{{stacked:true,ticks:{{font:{{size:11}}}}}},
          y:{{stacked:true,position:'left',
            title:{{display:true,text:'Availability (FTE)',font:{{size:12}}}},
            ticks:{{font:{{size:11}}}}}},
          y2:{{position:'right',min:0,max:100,
            title:{{display:true,text:'Availability %',font:{{size:12}}}},
            grid:{{drawOnChartArea:false}},
            ticks:{{callback:function(v){{return v+'%';}},font:{{size:11}}}}}}
        }},
        plugins:{{
          legend:{{position:'bottom',labels:{{boxWidth:14,font:{{size:12}}}}}},
          tooltip:{{mode:'index',intersect:false}}
        }}
      }}
    }});
  }}
  if(typeof Chart!=='undefined'){{build();}}
  else{{
    var s=document.createElement('script');
    s.src='https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js';
    s.onload=build; document.head.appendChild(s);
  }}
}})();
{mini_script}"""

    # Pad to always show 8 slots (4 col × 2 row) — skeleton placeholders for empty slots
    GRID_SLOTS = 8
    # Skeleton: static gray fake-bar chart
    _bar_heights = [30, 55, 40, 70, 50, 85, 60, 45, 75, 35, 65, 80, 55, 40, 70, 50, 85, 60, 45, 75]
    _bars_svg = "".join(
        f'<rect x="{3 + i*14}" y="{100 - h}" width="10" height="{h}" rx="1" fill="#e4e4e4"/>'
        for i, h in enumerate(_bar_heights)
    )
    skeleton_card = (
        '<div style="background:#f9f9f9;border:1px solid #ebebeb;border-radius:6px;'
        'padding:12px 10px 8px;opacity:0.55">\n'
        '  <div style="width:50%;height:10px;background:#e4e4e4;border-radius:3px;margin-bottom:10px"></div>\n'
        f'  <svg viewBox="0 0 283 100" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:200px">\n'
        f'    {_bars_svg}\n'
        '    <line x1="0" y1="99" x2="283" y2="99" stroke="#e4e4e4" stroke-width="1"/>\n'
        '  </svg>\n'
        '</div>\n'
    )
    placeholders_needed = max(0, GRID_SLOTS - len(active_groups))
    mini_html += skeleton_card * placeholders_needed

    mini_grid = (
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);'
        'gap:12px;margin-top:20px">\n'
        f'{mini_html}'
        '</div>\n'
    )

    return (
        f'<section id="opco-{opco_key}-graph" class="slide" style="overflow-y:auto">\n'
        f'<div class="slide-label"><span>{cfg["display_name"]}</span></div>\n'
        f'<div class="slide-content" style="overflow-y:auto;height:calc(100vh - 80px);padding-bottom:32px">\n'
        f'<div class="slide-title">Availability Graph</div>\n'
        f'<div style="position:relative;height:380px;min-width:600px">\n'
        f'  <canvas id="{canvas_id}"></canvas>\n'
        f'</div>\n'
        f'{mini_grid}'
        f'<script>\n{script}\n</script>\n'
        f'</div>\n</section>\n'
    )


def generate_dept_slide(opco_key, group_key, results, consultants, pid_conf_text, pid_tent_text, pid_level):
    cfg   = OPCOS[opco_key]
    gv    = cfg["groups"][group_key]
    wdata = results[group_key]["weeks"]

    lvl_td_style = "text-align:center;font-size:11px;color:#555;background:#f5f5f5;min-width:52px"

    # Summary rows
    rows = []
    for label, key, colorize in [
        ("Total FTE",                "total_fte",      False),
        ("Availability FTE Sum",     "avail_fte",      False),
        ("Available heads (50%+)",   "avail_heads_50", False),
        ("Tentative FTE Sum",        "tent_fte",       False),
        ("Availability",      "avail_pct_sold", True),
        ("Availability incl Tentative","avail_pct_incl",False),
    ]:
        if key in ("avail_pct_sold", "avail_pct_incl"):
            cells = _kpi_cells_pct(lambda w, k=key: wdata[w][k], colorize)
        elif key in ("avail_fte", "tent_fte", "total_fte"):
            cells = _kpi_cells_val(lambda w, k=key: fmt_fte(wdata[w][k]))
        else:
            cells = _kpi_cells_val(lambda w, k=key: str(wdata[w][k]))
        rows.append(
            f'<tr class="sumrow"><td class="tname sum-label">{label}</td>'
            f'<td class="wk level-val" style="{lvl_td_style}"></td>'
            + cells + '</tr>'
        )
    # Chargeability rows (reversed color scale)
    rows.append(
        f'<tr class="sumrow"><td class="tname sum-label">Chargeability</td>'
        f'<td class="wk level-val" style="{lvl_td_style}"></td>'
        + _kpi_cells_pct_charge(lambda w: wdata[w]["charge_pct"], True) + '</tr>'
    )
    rows.append(
        f'<tr class="sumrow"><td class="tname sum-label">Chargeability incl Tentative</td>'
        f'<td class="wk level-val" style="{lvl_td_style}"></td>'
        + _kpi_cells_pct_charge(lambda w: wdata[w]["charge_incl_pct"], False) + '</tr>'
    )

    # Consultant rows — pid comes straight from consultants_by_group, no
    # name-based re-lookup (which would silently collide for two people
    # sharing an exact display name).
    for pid, name, level in consultants:
        p_start, p_end = pid_dates.get(pid, (None, None))
        cells = ""
        for i, (wname, ws, we) in enumerate(WEEKS):
            if i == N_VISIBLE:
                cells += _toggle_td()
            ext = " wk-ext" if i >= N_VISIBLE else ""
            if (p_start and we < p_start) or (p_end and ws > p_end):
                cells += make_inactive_cell(ext)
                continue
            wd       = wdata[wname]
            timeoff  = wd["person_timeoff"].get(pid, 0.0) if pid else 0.0
            conf     = wd["person_conf"].get(pid, 0.0)    if pid else 0.0
            tent     = wd["person_tent"].get(pid, 0.0)    if pid else 0.0
            unbooked = max(0.0, 40.0 - timeoff - conf)
            cells += make_wk_cell(unbooked, tent, timeoff, ext)

        conf_t = pid_conf_text.get(pid, "–") if pid else "–"
        tent_t = pid_tent_text.get(pid, "–") if pid else "–"
        rows.append(
            f'<tr class="prow">'
            f'<td class="tname">{name}</td>'
            f'<td class="wk level-val" style="{lvl_td_style}">{level}</td>'
            + cells
            + f'<td class="tclients">{conf_t}</td>'
            + f'<td class="tclients proj-tent">{tent_t}</td>'
            + '</tr>'
        )

    slide_id   = f"opco-{opco_key}-{group_key.lower().replace('/', '-').replace(' ', '-')}"
    color      = gv["color"]

    return (
        f'<section id="{slide_id}" class="slide">\n'
        f'<div class="slide-label" style="background:{color}"><span>{gv["label"]}</span></div>\n'
        f'<div class="slide-content">\n'
        f'<div class="slide-title">{gv["label"]}</div>\n'
        f'<div class="tbl-wrap">\n'
        f'<table>\n'
        f'<thead>\n'
        + _month_row() + '\n'
        + '<tr class="hdr">'
        + '<th class="tname">Consultant</th>'
        + '<th class="wk level-col" style="text-align:center;font-size:11px">Level</th>'
        + _week_ths() + '\n'
        + '<th class="tclients">Confirmed projects</th>'
        + '<th class="tclients">Tentative projects</th>'
        + '</tr>\n'
        + '</thead>\n<tbody>\n'
        + "\n".join(rows)
        + '\n</tbody>\n</table>\n</div>\n</div>\n</section>\n'
    )

def generate_contractor_slide(opco_key, contractor_results, dept_groups,
                              pid_conf_text, pid_tent_text):
    """
    Renders a heatmap slide for the opco's contractors, grouped by sub-department.
    Contractors are not included in any opco KPI — this slide is informational only.
    dept_groups: [(dept_label, [(name, level), ...]), ...]
    """
    cfg    = OPCOS[opco_key]
    wdata  = contractor_results["weeks"]
    color  = "#555555"   # neutral accent for contractors
    # Total columns: name + level + N_VISIBLE + toggle + ext + confirmed + tentative
    total_cols = 2 + N_VISIBLE + 1 + len(WEEKS_EXT) + 2

    lvl_td_style = "text-align:center;font-size:11px;color:#555;background:#f5f5f5;min-width:52px"

    # Summary rows (same metrics as a dept slide)
    rows = []
    for label, key, colorize in [
        ("Total contractors",          "total_fte",      False),
        ("Availability FTE Sum",       "avail_fte",      False),
        ("Available heads (50%+)",     "avail_heads_50", False),
        ("Tentative FTE Sum",          "tent_fte",       False),
        ("Availability",        "avail_pct_sold", True),
        ("Availability incl Tentative","avail_pct_incl", False),
    ]:
        if key in ("avail_pct_sold", "avail_pct_incl"):
            cells = _kpi_cells_pct(lambda w, k=key: wdata[w][k], colorize)
        elif key in ("avail_fte", "tent_fte", "total_fte"):
            cells = _kpi_cells_val(lambda w, k=key: fmt_fte(wdata[w][k]))
        else:
            cells = _kpi_cells_val(lambda w, k=key: str(wdata[w][k]))
        rows.append(
            f'<tr class="sumrow"><td class="tname sum-label">{label}</td>'
            f'<td class="wk level-val" style="{lvl_td_style}"></td>'
            + cells + '</tr>'
        )

    # Per-group: divider header + per-contractor rows. pid comes straight
    # from dept_groups (no name-based re-lookup — see consultants_by_group).
    for dept_label, members in dept_groups:
        # Divider spacer
        rows.append(
            f'<tr><td colspan="{total_cols}" '
            f'style="height:4px;background:#ddd;padding:0"></td></tr>'
        )
        # Sub-dept header row
        label_text = dept_label if dept_label else "Unassigned"
        rows.append(
            f'<tr style="background:#efefef">'
            f'<td class="tname" colspan="2" style="font-weight:700;font-size:11px;'
            f'color:#333;padding:5px 8px;border-left:3px solid #888;'
            f'font-style:italic;letter-spacing:.2px">{label_text}</td>'
            + "".join(f'<td class="wk" style="background:#efefef"></td>'          for _ in WEEKS_MAIN)
            + _toggle_td()
            + "".join(f'<td class="wk wk-ext" style="background:#efefef"></td>'  for _ in WEEKS_EXT)
            + f'<td class="tclients" style="background:#efefef"></td>'
            + f'<td class="tclients" style="background:#efefef"></td>'
            + '</tr>'
        )

        for pid, name, level in members:
            p_start, p_end = pid_dates.get(pid, (None, None))
            cells = ""
            for i, (wname, ws, we) in enumerate(WEEKS):
                if i == N_VISIBLE:
                    cells += _toggle_td()
                ext = " wk-ext" if i >= N_VISIBLE else ""
                if (p_start and we < p_start) or (p_end and ws > p_end):
                    cells += make_inactive_cell(ext)
                    continue
                wd       = wdata[wname]
                timeoff  = wd["person_timeoff"].get(pid, 0.0) if pid else 0.0
                conf     = wd["person_conf"].get(pid, 0.0)    if pid else 0.0
                tent     = wd["person_tent"].get(pid, 0.0)    if pid else 0.0
                unbooked = max(0.0, 40.0 - timeoff - conf)
                cells += make_wk_cell(unbooked, tent, timeoff, ext)

            conf_t = pid_conf_text.get(pid, "–") if pid else "–"
            tent_t = pid_tent_text.get(pid, "–") if pid else "–"
            rows.append(
                f'<tr class="prow">'
                f'<td class="tname">{name}</td>'
                f'<td class="wk level-val" style="{lvl_td_style}">{level}</td>'
                + cells
                + f'<td class="tclients">{conf_t}</td>'
                + f'<td class="tclients proj-tent">{tent_t}</td>'
                + '</tr>'
            )

    return (
        f'<section id="opco-{opco_key}-contractors" class="slide">\n'
        f'<div class="slide-label" style="background:{color}"><span>Contractors</span></div>\n'
        f'<div class="slide-content">\n'
        f'<div class="slide-title">Contractors — {cfg["display_name"]}</div>\n'
        f'<p style="font-size:11px;color:#888;margin-bottom:10px">'
        f'Contractors are shown here for reference only and are not included in any opco KPIs.</p>\n'
        f'<div class="tbl-wrap">\n'
        f'<table>\n'
        f'<thead>\n'
        + _month_row() + '\n'
        + '<tr class="hdr">'
        + '<th class="tname">Contractor</th>'
        + '<th class="wk level-col" style="text-align:center;font-size:11px">Level</th>'
        + _week_ths() + '\n'
        + '<th class="tclients">Confirmed projects</th>'
        + '<th class="tclients">Tentative projects</th>'
        + '</tr>\n'
        + '</thead>\n<tbody>\n'
        + "\n".join(rows)
        + '\n</tbody>\n</table>\n</div>\n</div>\n</section>\n'
    )


# ── Run per-opco computation ───────────────────────────────────────────────────
opco_data = {}
for opco_key in OPCO_ORDER:
    cfg = OPCOS[opco_key]
    print(f"\n── {cfg['display_name']} ──")
    results, consultants_by_group, pid_conf_text, pid_tent_text, pid_level = compute_opco(opco_key)
    total_people = sum(len(v) for v in consultants_by_group.values())
    print(f"   {total_people} active employees across {len(cfg['groups'])} group(s)")
    ctr_data = compute_contractors(opco_key)
    if ctr_data:
        ctr_results, ctr_dept_groups, ctr_conf_text, ctr_tent_text = ctr_data
        ctr_total = sum(len(m) for _, m in ctr_dept_groups)
        print(f"   {ctr_total} contractor(s) across {len(ctr_dept_groups)} sub-dept(s)")
    else:
        ctr_results = ctr_dept_groups = ctr_conf_text = ctr_tent_text = None
    opco_data[opco_key] = {
        "results":            results,
        "consultants":        consultants_by_group,
        "pid_conf_text":      pid_conf_text,
        "pid_tent_text":      pid_tent_text,
        "pid_level":          pid_level,
        "ctr_results":        ctr_results,
        "ctr_dept_groups":    ctr_dept_groups,
        "ctr_conf_text":      ctr_conf_text,
        "ctr_tent_text":      ctr_tent_text,
    }

# ── Build full HTML ────────────────────────────────────────────────────────────
print("\nGenerating HTML…")

_tz      = ZoneInfo("Europe/Stockholm")
_now     = datetime.now(_tz)
_now_str = _now.strftime("%Y-%m-%d %H:%M ") + _now.strftime("%Z")
first_w, last_w = WEEKS[0][0], WEEKS[-1][0]

# ── CSS ────────────────────────────────────────────────────────────────────────
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
     background:#f2f2f2;color:#1a1a1a;font-size:12px;overflow:hidden}

/* ── Top nav ── */
#topnav{
  position:fixed;top:0;left:0;right:0;z-index:100;
  background:#1a1a1a;color:#fff;
  display:flex;flex-direction:column;
  height:auto;
}
.nav-row{
  display:flex;align-items:center;
  padding:0 16px;height:40px;gap:0;
  overflow-x:auto;white-space:nowrap;
}
.nav-title{
  font-size:13px;font-weight:800;color:#fff;
  margin-right:16px;flex-shrink:0;letter-spacing:.3px;
}
.nav-row a, .nav-row button.slide-link{
  color:#ccc;text-decoration:none;font-size:11px;font-weight:500;
  padding:4px 10px;border-radius:4px;
  transition:background .15s,color .15s;
  flex-shrink:0;border:none;background:none;cursor:pointer;
}
.nav-row a:hover, .nav-row button.slide-link:hover{background:#333;color:#fff}
.nav-row a.active, .nav-row button.slide-link.active{background:#444;color:#fff}
.nav-sep{width:1px;height:20px;background:#444;margin:0 6px;flex-shrink:0}

/* OpCo dropdown */
#opco-select{
  background:#2a2a2a;color:#fff;border:1px solid #555;
  border-radius:6px;font-size:12px;font-weight:600;
  padding:4px 28px 4px 10px;cursor:pointer;flex-shrink:0;
  appearance:none;-webkit-appearance:none;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23aaa'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 9px center;
  transition:border-color .15s;
}
#opco-select:hover{border-color:#888}
#opco-select:focus{outline:none;border-color:#aaa}
#opco-select option{background:#1a1a1a;color:#fff}

/* Slide nav row */
#slide-nav-row{border-top:1px solid #333;background:#1a1a1a}
#slide-nav-row.hidden{display:none}

/* Legend bar */
#legendbar{
  position:fixed;top:80px;left:0;right:0;z-index:99;
  background:#fff;border-bottom:1px solid #ddd;
  display:flex;align-items:center;gap:14px;flex-wrap:wrap;
  padding:6px 16px;height:36px;overflow:hidden;
}
#legendbar b{font-size:11px;color:#555}
.legend-item{display:flex;align-items:center;gap:5px;font-size:11px;color:#444}
.swatch{width:14px;height:14px;border-radius:2px;border:1px solid #ccc;display:inline-block}
.legend-sep{width:1px;height:20px;background:#ddd;flex-shrink:0}

/* Scroll container */
#scroll-container{
  position:fixed;
  top:116px;left:0;right:0;bottom:0;
  overflow-y:scroll;
  scroll-snap-type:y mandatory;
  scroll-behavior:smooth;
}

/* OpCo sections */
.opco-section{display:none}
.opco-section.active{display:block}

/* Slides */
.slide{
  height:100vh;scroll-snap-align:start;
  display:flex;background:#f2f2f2;
}
.slide-label{
  width:60px;min-width:60px;background:#1a1a1a;color:#fff;
  display:flex;align-items:center;justify-content:center;
  overflow:hidden;flex-shrink:0;
}
.slide-label span{
  writing-mode:vertical-rl;transform:rotate(180deg);
  font-size:11px;font-weight:700;text-transform:uppercase;
  letter-spacing:.8px;white-space:nowrap;padding:12px 0;
}
.slide-content{
  flex:1;display:flex;flex-direction:column;
  padding:16px 20px;overflow:hidden;min-width:0;
}
.slide-title{
  font-size:18px;font-weight:800;margin-bottom:10px;
  color:#1a1a1a;letter-spacing:.2px;flex-shrink:0;
}

/* Tables */
.tbl-wrap{
  flex:1;overflow-y:auto;overflow-x:auto;
  border-radius:4px;box-shadow:0 1px 4px rgba(0,0,0,.08);
}
table{border-collapse:collapse;width:100%;background:#fff;
      border:1px solid #ddd;min-width:900px}
.hdr th{background:#2d2d2d;color:#fff;font-size:10px;font-weight:700;
        padding:7px 6px;text-align:center;border:1px solid #444;
        white-space:nowrap;position:sticky;top:0;z-index:2}
.hdr th.tname{text-align:left;min-width:160px}
.hdr th.tclients{text-align:left;min-width:160px;max-width:220px}
.sumrow td{background:#e8e8e8;font-weight:600;font-size:9px;padding:2px 4px;
           line-height:1.2;border:1px solid #ccc;text-align:center;color:#333}
.sumrow td.tname{text-align:left}
.prow td{padding:4px 6px;border:1px solid #eee;text-align:center;
         vertical-align:middle;font-size:11px}
.prow td.tname{text-align:left;white-space:nowrap;font-weight:500;min-width:160px}
.prow td.tclients{text-align:left;font-size:10px;color:#333;
                  min-width:160px;max-width:220px;
                  white-space:normal;overflow:hidden;line-height:1.5;vertical-align:middle}
.prow td.wk{font-weight:600;font-size:10px;min-width:38px;width:38px}
.prow:nth-child(odd){background:#f9f9f9}
.prow:hover td{background:#e8f4fd!important}
.proj-tent{color:#888;font-style:italic}
.sum-label{font-weight:600;font-size:9px;color:#444;
           background:#f0f0f0;padding:2px 4px;line-height:1.2}
.sum-val{font-size:9px;font-weight:600;color:#333;
         background:#f0f0f0;padding:2px 4px;line-height:1.2}
.month-hdr th{border:1px solid #666;font-weight:700;letter-spacing:.3px}

/* ── Extended-week collapse/expand ── */
.wk-ext{display:none}
body.wk-expanded .wk-ext{display:table-cell}

.wk-toggle-col{
  cursor:pointer;
  width:22px;min-width:22px;
  background:#d0d0d0;
  border-left:2px solid #aaa!important;
  padding:0;
  vertical-align:middle;
  text-align:center;
  user-select:none;
}
.hdr .wk-toggle-col{background:#3a3a3a;border-color:#555!important}
.month-hdr .wk-toggle-col{background:#3a3a3a;border-color:#555!important}
.wk-toggle-col:hover{opacity:.75}
.wk-toggle-label{
  display:block;
  writing-mode:vertical-rl;
  font-size:9px;font-weight:700;
  color:#bbb;letter-spacing:.4px;
  padding:6px 0;white-space:nowrap;
}
.wk-toggle-label::after{content:'▶ +8W'}
body.wk-expanded .wk-toggle-label::after{content:'◀'}
"""

# ── JS ─────────────────────────────────────────────────────────────────────────
# Build slide-nav data per opco
opco_slide_nav_data = {}
for opco_key in OPCO_ORDER:
    cfg    = OPCOS[opco_key]
    groups = cfg["groups"]
    links  = [
        {"id": f"opco-{opco_key}-summary",        "label": "Summary"},
        {"id": f"opco-{opco_key}-all-consultants", "label": "All Consultants"},
        {"id": f"opco-{opco_key}-graph",           "label": "Graph"},
    ]
    for gk, gv in groups.items():
        slide_id = f"opco-{opco_key}-{gk.lower().replace('/', '-').replace(' ', '-')}"
        links.append({"id": slide_id, "label": gk})
    # Add Contractors nav link if the opco has contractors
    if opco_data[opco_key]["ctr_results"] is not None:
        links.append({"id": f"opco-{opco_key}-contractors", "label": "Contractors"})
    opco_slide_nav_data[opco_key] = links

nav_data_json = json.dumps(opco_slide_nav_data)

JS = f"""
const NAV_DATA = {nav_data_json};
let activeOpco = null;

function showOpco(key) {{
  // Update opco sections
  document.querySelectorAll('.opco-section').forEach(el => el.classList.remove('active'));
  const sec = document.getElementById('opco-section-' + key);
  if (sec) sec.classList.add('active');

  // Update dropdown
  const sel = document.getElementById('opco-select');
  if (sel && sel.value !== key) sel.value = key;

  // Update slide nav
  const row = document.getElementById('slide-nav-inner');
  row.innerHTML = '';
  const links = NAV_DATA[key] || [];
  links.forEach((lk, i) => {{
    if (i === 3) {{
      const sep = document.createElement('div');
      sep.className = 'nav-sep'; row.appendChild(sep);
    }}
    const a = document.createElement('a');
    a.href = '#' + lk.id;
    a.textContent = lk.label;
    a.className = 'slide-link';
    row.appendChild(a);
  }});

  activeOpco = key;

  // Scroll to summary
  const sumSlide = document.getElementById('opco-' + key + '-summary');
  if (sumSlide) sumSlide.scrollIntoView();

  // Trigger chart render for the graph slide
  setTimeout(() => {{
    const canvas = document.getElementById('chart-' + key);
    if (canvas && typeof Chart !== 'undefined') {{
      canvas.dispatchEvent(new Event('resize'));
    }}
  }}, 200);
}}

// Highlight active slide link on scroll
const sc = document.getElementById('scroll-container');
if (sc) sc.addEventListener('scroll', () => {{
  if (!activeOpco) return;
  const links = NAV_DATA[activeOpco] || [];
  let current = links[0]?.id;
  links.forEach(lk => {{
    const el = document.getElementById(lk.id);
    if (el && el.getBoundingClientRect().top <= 120) current = lk.id;
  }});
  document.querySelectorAll('#slide-nav-inner a').forEach(a => {{
    a.classList.toggle('active', a.getAttribute('href') === '#' + current);
  }});
}});

// Auto-show first opco on load
const OPCO_CONFIGS = {json.dumps({k: {"color": OPCOS[k]["color"]} for k in OPCO_ORDER})};
document.addEventListener('DOMContentLoaded', () => {{
  showOpco('{OPCO_ORDER[0]}');
}});

// ── Extended-week toggle ──────────────────────────────────────────────────────
function toggleExtWeeks() {{
  document.body.classList.toggle('wk-expanded');
}}
"""

# ── Load and inline logos ────────────────────────────────────────────────────────
def _load_svg(filename, height_px, extra_style=""):
    p = BASE / filename
    if not p.exists():
        return ""
    svg = p.read_text(encoding="utf-8")
    # Strip XML declaration
    svg = re.sub(r'<\?xml[^>]*\?>', '', svg).strip()
    # Inject height + style into the <svg> tag
    svg = re.sub(r'<svg ', f'<svg height="{height_px}" style="flex-shrink:0;{extra_style}" ', svg, count=1)
    return svg

# Eidra: make all fills white (logo is black on transparent)
_eidra_svg_raw = _load_svg("eidra-logo-maj-2024.svg", 20)
_eidra_svg = _eidra_svg_raw.replace('fill: #000', 'fill: #fff').replace('fill="#000"', 'fill="#fff"').replace('fill="#000000"', 'fill="#fff"')

# Float: keep only the blue icon elements (strip white wordmark paths), crop viewBox
_float_raw = (BASE / "float logo.svg").read_text(encoding="utf-8") if (BASE / "float logo.svg").exists() else ""
if _float_raw:
    # Remove all paths/rects with fill="white" (the wordmark letters)
    _float_icon = re.sub(r'<path[^>]+fill="white"[^/]*/>', '', _float_raw)
    _float_icon = re.sub(r'<path[^>]+fill="white"[^>]*>.*?</path>', '', _float_icon, flags=re.DOTALL)
    # Strip XML declaration
    _float_icon = re.sub(r'<\?xml[^>]*\?>', '', _float_icon).strip()
    # Remove original width/height attrs, set viewBox to icon only, add sizing via CSS
    _float_icon = re.sub(r'\s*width="[^"]*"', '', _float_icon)
    _float_icon = re.sub(r'\s*height="[^"]*"', '', _float_icon)
    _float_icon = re.sub(r'viewBox="[^"]*"', 'viewBox="0 0 245 178"', _float_icon)
    _float_icon = re.sub(r'<svg ', '<svg style="height:20px;width:auto;flex-shrink:0;vertical-align:middle" ', _float_icon, count=1)
    _float_svg = _float_icon
else:
    _float_svg = ""

# ── Build opco dropdown ─────────────────────────────────────────────────────────
pills_html = '<select id="opco-select" onchange="showOpco(this.value)">'
for key in OPCO_ORDER:
    cfg = OPCOS[key]
    pills_html += f'<option value="{key}">{cfg["short_name"]}</option>'
pills_html += '</select>'

# ── Legend HTML ────────────────────────────────────────────────────────────────
LEGEND_HTML = """
  <b>Available hours/week:</b>
  <div class="legend-item"><span class="swatch" style="background:#ffffff"></span>0h</div>
  <div class="legend-item"><span class="swatch" style="background:#ffeeee"></span>1–8h</div>
  <div class="legend-item"><span class="swatch" style="background:#ffd3d3"></span>9–20h</div>
  <div class="legend-item"><span class="swatch" style="background:#ffa7a7"></span>21–30h</div>
  <div class="legend-item"><span class="swatch" style="background:#ff7b7b"></span>31–40h</div>
  <div class="legend-item"><span class="swatch" style="background:#ff5050"></span>40h+</div>
  <div class="legend-sep"></div>
  <b>Tentatively booked:</b>
  <div class="legend-item"><span class="swatch" style="background:#d5e5f1"></span>1–8h</div>
  <div class="legend-item"><span class="swatch" style="background:#94c0dc"></span>9–20h</div>
  <div class="legend-item"><span class="swatch" style="background:#60a0cb"></span>21–30h</div>
  <div class="legend-item"><span class="swatch" style="background:#2980b9"></span>31–40h</div>
  <div class="legend-sep"></div>
  <div class="legend-item"><span class="swatch" style="background:#e0e0e0"></span>Time Off</div>
  <div class="legend-item"><span class="swatch" style="background:repeating-linear-gradient(45deg,#d0d0d0,#d0d0d0 2px,#ebebeb 2px,#ebebeb 8px)"></span>Not in contract</div>
"""

# ── Assemble all opco slides ───────────────────────────────────────────────────
all_opco_html = ""
for opco_key in OPCO_ORDER:
    cfg  = OPCOS[opco_key]
    data = opco_data[opco_key]
    results           = data["results"]
    consultants       = data["consultants"]
    pid_conf_text     = data["pid_conf_text"]
    pid_tent_text     = data["pid_tent_text"]
    pid_level         = data["pid_level"]

    slides_html = ""
    slides_html += generate_summary_slide(opco_key, results)
    slides_html += generate_all_consultants_slide(
        opco_key, results, consultants, pid_conf_text, pid_tent_text
    )
    slides_html += generate_graph_slide(opco_key, results)
    for gk in cfg["groups"]:
        if gk not in results:
            continue
        slides_html += generate_dept_slide(
            opco_key, gk, results,
            consultants.get(gk, []),
            pid_conf_text, pid_tent_text, pid_level
        )
    if data["ctr_results"] is not None:
        slides_html += generate_contractor_slide(
            opco_key,
            data["ctr_results"],
            data["ctr_dept_groups"],
            data["ctr_conf_text"],
            data["ctr_tent_text"],
        )

    all_opco_html += (
        f'<div class="opco-section" id="opco-section-{opco_key}">\n'
        + slides_html
        + '</div>\n'
    )
    print(f"  ✓ {cfg['display_name']}")

# ── Final HTML document ────────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Eidra Allocation Report – {first_w}–{last_w} 2026</title>
<style>
{CSS}
</style>
</head>
<body>

<nav id="topnav">
  <!-- Row 1: logos + opco switcher -->
  <div class="nav-row">
    {_eidra_svg}
    <div class="nav-sep"></div>
    {pills_html}
    <span id="report-updated" style="
      margin-left:auto;display:flex;align-items:center;gap:8px;
      font-size:10px;color:#aaa;white-space:nowrap;flex-shrink:0;padding-left:16px">
      {_float_svg}
      Float sync {_now_str}
    </span>
  </div>
  <!-- Row 2: slide nav for active opco -->
  <div class="nav-row" id="slide-nav-row">
    <div id="slide-nav-inner" style="display:flex;align-items:center;gap:0;flex-wrap:nowrap"></div>
  </div>
</nav>

{banner_html}

<div id="legendbar">
  {LEGEND_HTML}
</div>

<div id="scroll-container">
  {all_opco_html}
</div>

<script>
{JS}
</script>
</body>
</html>"""

# ── Patch hover behaviour (idempotent — strip old injected block, re-insert) ───
html = re.sub(r'\.prow:hover\s+td\s*\{[^}]*\}', '.prow:hover td{}', html)
_HOVER_CSS = (
    '<style id="hover-patch">'
    '.prow:hover td{'
        'box-shadow:inset 0 1px 0 0 #555,inset 0 -1px 0 0 #555}'
    '.prow:hover td:first-child{'
        'box-shadow:inset 2px 0 0 0 #555,inset 0 1px 0 0 #555,inset 0 -1px 0 0 #555}'
    '.prow:hover td:last-child{'
        'box-shadow:inset -2px 0 0 0 #555,inset 0 1px 0 0 #555,inset 0 -1px 0 0 #555}'
    '.sumrow:hover td{background:#d4d4d4!important}'
    '</style>'
)
html = re.sub(r'<style id="hover-patch">.*?</style>', '', html, flags=re.DOTALL)
html = re.sub(r'<script id="hover-script">.*?</script>', '', html, flags=re.DOTALL)
html = html.replace('</style>', '</style>' + _HOVER_CSS, 1)

# COO self-serve mode: set EIDRA_COO_OPCO_KEY to an OPCOS key (e.g. "curamando-nl")
# to skip generating/writing the full multi-opco report and all 6 per-opco
# pages ENTIRELY — not just the GitHub Pages push. Those files contain every
# OTHER opco's data too, and this mode has no password set, so they must
# never be written to disk on a COO's machine. Only my_opco_report.html
# (their own opco, built further down) is written in this mode.
import os as _os
_coo_opco_key = (_os.environ.get("EIDRA_COO_OPCO_KEY") or "").strip()

# Password priority: EIDRA_REPORT_PASSWORD env var → .report_password file in project folder
_password = (_os.environ.get("EIDRA_REPORT_PASSWORD") or "").strip()
if not _password:
    _pw_file = BASE / ".report_password"
    if _pw_file.exists():
        _password = _pw_file.read_text().strip()

import subprocess, shutil

if not _coo_opco_key:
    HTML_OUT.write_text(html, encoding="utf-8")
    size_kb = HTML_OUT.stat().st_size // 1024
    print(f"\n✅ Done — {HTML_OUT.name} ({size_kb} KB)")
    print(f"   Path: {HTML_OUT}")

    # ── Auto-publish to GitHub Pages ──────────────────────────────────────────
    index_path = BASE / "index.html"
    shutil.copy(HTML_OUT, index_path)
else:
    print(f"  (COO mode: EIDRA_COO_OPCO_KEY={_coo_opco_key!r} — skipping full multi-opco "
          f"report + all per-opco pages entirely, generating only this opco's report)")

def _make_protected_html(html_content: str, password: str):
    """
    Encrypt html_content with PBKDF2-SHA256 + AES-256-GCM and return a
    self-contained login-page HTML that decrypts client-side via SubtleCrypto.
    Returns None if the `cryptography` package is not installed.
    """
    import hashlib, os as _os2
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        return None
    salt = _os2.urandom(32)
    iv   = _os2.urandom(12)
    key  = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000, dklen=32)
    ct   = AESGCM(key).encrypt(iv, html_content.encode("utf-8"), None)
    sh, ih, ch = salt.hex(), iv.hex(), ct.hex()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Eidra Allocation Report</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
     background:#1a1a1a;display:flex;align-items:center;justify-content:center;min-height:100vh}}
.box{{background:#fff;border-radius:10px;padding:40px;max-width:360px;width:90%;
      box-shadow:0 8px 32px rgba(0,0,0,.4);text-align:center}}
.logo{{font-size:22px;font-weight:800;letter-spacing:.3px;margin-bottom:6px}}
.sub{{font-size:12px;color:#888;margin-bottom:28px}}
input{{width:100%;padding:10px 14px;font-size:14px;border:1px solid #ddd;
       border-radius:6px;outline:none;margin-bottom:12px;transition:border-color .2s}}
input:focus{{border-color:#555}}
button{{width:100%;padding:10px;font-size:14px;font-weight:600;
        background:#1a1a1a;color:#fff;border:none;border-radius:6px;
        cursor:pointer;transition:background .2s}}
button:hover{{background:#333}}
.err{{font-size:12px;color:#c0392b;margin-top:10px;display:none}}
</style>
</head>
<body>
<div class="box">
  <div class="logo">Eidra</div>
  <div class="sub">Allocation Report — enter password to continue</div>
  <input type="password" id="pw" placeholder="Password" autofocus
         onkeydown="if(event.key==='Enter')unlock()">
  <button onclick="unlock()">Open report</button>
  <div class="err" id="err">Incorrect password</div>
</div>
<script>
const SH='{sh}',IH='{ih}',CH='{ch}';
function h2b(h){{const b=new Uint8Array(h.length/2);for(let i=0;i<b.length;i++)b[i]=parseInt(h.substr(i*2,2),16);return b;}}
async function unlock(){{
  const pw=document.getElementById('pw').value;if(!pw)return;
  try{{
    const km=await crypto.subtle.importKey('raw',new TextEncoder().encode(pw),'PBKDF2',false,['deriveKey']);
    const key=await crypto.subtle.deriveKey(
      {{name:'PBKDF2',salt:h2b(SH),iterations:100000,hash:'SHA-256'}},
      km,{{name:'AES-GCM',length:256}},false,['decrypt']);
    const pt=await crypto.subtle.decrypt({{name:'AES-GCM',iv:h2b(IH)}},key,h2b(CH));
    document.open();document.write(new TextDecoder().decode(pt));document.close();
  }}catch{{
    const e=document.getElementById('err');e.style.display='block';
    document.getElementById('pw').value='';document.getElementById('pw').focus();
  }}
}}
</script>
</body>
</html>"""

if not _coo_opco_key:
    if _password:
        print("🔒 Encrypting…")
        protected = _make_protected_html(index_path.read_text(encoding="utf-8"), _password)
        if protected is None:
            print("  ⚠ Missing dependency — run once:")
            print("    pip3 install cryptography")
        else:
            index_path.write_text(protected, encoding="utf-8")
            size_enc = index_path.stat().st_size // 1024
            print(f"  ✓ Encrypted — {size_enc} KB")
    else:
        print("⚠️  No password set — publishing unencrypted.")
        print("   Create .report_password in the project folder to enable encryption.")

def _git(args, **kw):
    result = subprocess.run(["git"] + args, cwd=BASE, capture_output=True, text=True, **kw)
    if result.returncode != 0:
        print(f"  git warning: {result.stderr.strip()}")
    return result

# Remove stale lock files left by background processes (e.g. Cowork sandbox)
for _lock in (BASE / ".git").glob("*.lock"):
    try:
        _lock.unlink(missing_ok=True)
    except OSError:
        pass

today_str = date.today().isoformat()
if _coo_opco_key:
    print(f"  (COO mode: EIDRA_COO_OPCO_KEY={_coo_opco_key!r} — skipping GitHub Pages push)")
else:
    _git(["add", "index.html"])
    _git(["commit", "-m", f"Auto-update: {today_str}"])
    push = _git(["push", "origin", "master"])
    if push.returncode == 0:
        print(f"🚀 Published to GitHub Pages (https://jonhawkandson.github.io/eidra-allocation-report/)")
    else:
        print(f"  Push failed — check git remote / token: {push.stderr.strip()}")

# ── Per-opco standalone HTML pages ────────────────────────────────────────────

def _build_single_opco_html(opco_key: str) -> str:
    """Generate a self-contained single-opco HTML page (no opco switcher)."""
    cfg  = OPCOS[opco_key]
    data = opco_data[opco_key]

    results       = data["results"]
    consultants   = data["consultants"]
    pid_conf_text = data["pid_conf_text"]
    pid_tent_text = data["pid_tent_text"]
    pid_level     = data["pid_level"]

    slides_html = ""
    slides_html += generate_summary_slide(opco_key, results)
    slides_html += generate_all_consultants_slide(
        opco_key, results, consultants, pid_conf_text, pid_tent_text
    )
    slides_html += generate_graph_slide(opco_key, results)
    for gk in cfg["groups"]:
        if gk not in results:
            continue
        slides_html += generate_dept_slide(
            opco_key, gk, results,
            consultants.get(gk, []),
            pid_conf_text, pid_tent_text, pid_level,
        )
    if data["ctr_results"] is not None:
        slides_html += generate_contractor_slide(
            opco_key,
            data["ctr_results"],
            data["ctr_dept_groups"],
            data["ctr_conf_text"],
            data["ctr_tent_text"],
        )

    # Slide nav links for this opco
    nav_links = [
        {"id": f"opco-{opco_key}-summary",        "label": "Summary"},
        {"id": f"opco-{opco_key}-all-consultants", "label": "All Consultants"},
        {"id": f"opco-{opco_key}-graph",           "label": "Graph"},
    ]
    for gk, gv in cfg["groups"].items():
        slide_id = f"opco-{opco_key}-{gk.lower().replace('/', '-').replace(' ', '-')}"
        nav_links.append({"id": slide_id, "label": gk})
    if data["ctr_results"] is not None:
        nav_links.append({"id": f"opco-{opco_key}-contractors", "label": "Contractors"})

    links_js = json.dumps(nav_links)

    # Simplified JS: no opco switching, just slide-link highlighting + week toggle
    js_single = f"""
const LINKS = {links_js};

function initNav() {{
  const row = document.getElementById('slide-nav-inner');
  LINKS.forEach((lk, i) => {{
    if (i === 3) {{
      const sep = document.createElement('div');
      sep.className = 'nav-sep'; row.appendChild(sep);
    }}
    const a = document.createElement('a');
    a.href = '#' + lk.id;
    a.textContent = lk.label;
    a.className = 'slide-link';
    row.appendChild(a);
  }});
}}

const sc = document.getElementById('scroll-container');
if (sc) sc.addEventListener('scroll', () => {{
  let current = LINKS[0]?.id;
  LINKS.forEach(lk => {{
    const el = document.getElementById(lk.id);
    if (el && el.getBoundingClientRect().top <= 120) current = lk.id;
  }});
  document.querySelectorAll('#slide-nav-inner a').forEach(a => {{
    a.classList.toggle('active', a.getAttribute('href') === '#' + current);
  }});
}});

document.addEventListener('DOMContentLoaded', () => {{
  initNav();
  const first = document.getElementById(LINKS[0]?.id);
  if (first) first.scrollIntoView();
}});

function toggleExtWeeks() {{
  document.body.classList.toggle('wk-expanded');
}}
"""

    opco_color = cfg["color"]
    opco_title = f'<span class="nav-title" style="color:{opco_color}">{cfg["display_name"]}</span>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{cfg["display_name"]} – Allocation Report {first_w}–{last_w}</title>
<style>
{CSS}
</style>
</head>
<body>

<nav id="topnav">
  <div class="nav-row">
    {_eidra_svg}
    <div class="nav-sep"></div>
    {opco_title}
    <span id="report-updated" style="
      margin-left:auto;display:flex;align-items:center;gap:8px;
      font-size:10px;color:#aaa;white-space:nowrap;flex-shrink:0;padding-left:16px">
      {_float_svg}
      Float sync {_now_str}
    </span>
  </div>
  <div class="nav-row" id="slide-nav-row">
    <div id="slide-nav-inner" style="display:flex;align-items:center;gap:0;flex-wrap:nowrap"></div>
  </div>
</nav>

{banner_html}

<div id="legendbar">
  {LEGEND_HTML}
</div>

<div id="scroll-container">
  {slides_html}
</div>

<script>
{js_single}
</script>
</body>
</html>"""


if not _coo_opco_key:
    print("\nGenerating per-opco pages…")
    for opco_key, subfolder in PER_OPCO_PAGES.items():
        cfg = OPCOS[opco_key]
        per_html = _build_single_opco_html(opco_key)

        # Apply the same hover patch as the main report
        per_html = re.sub(r'\.prow:hover\s+td\s*\{[^}]*\}', '.prow:hover td{}', per_html)
        per_html = re.sub(r'<style id="hover-patch">.*?</style>', '', per_html, flags=re.DOTALL)
        per_html = re.sub(r'<script id="hover-script">.*?</script>', '', per_html, flags=re.DOTALL)
        per_html = per_html.replace('</style>', '</style>' + _HOVER_CSS, 1)

        # Encrypt if password is set
        if _password:
            protected = _make_protected_html(per_html, _password)
            if protected is None:
                print(f"  ⚠ cryptography not installed — writing unencrypted for {opco_key}")
                protected = per_html
        else:
            protected = per_html

        subfolder_dir = BASE / subfolder
        subfolder_dir.mkdir(exist_ok=True)
        opco_index = subfolder_dir / "index.html"
        opco_index.write_text(protected, encoding="utf-8")
        size_kb = opco_index.stat().st_size // 1024
        print(f"  ✓ {cfg['display_name']} → {subfolder}/index.html ({size_kb} KB)")
else:
    print("  (COO mode: skipping per-opco page generation for all opcos — only "
          "building this opco's own report below)")

# ── COO self-serve single-opco output (no git push) ──────────────────────────
if _coo_opco_key:
    if _coo_opco_key not in OPCOS:
        print(f"  ⚠ EIDRA_COO_OPCO_KEY={_coo_opco_key!r} is not a valid opco key in "
              f"eidra_opco_config.py — no local report written. Valid keys: "
              f"{', '.join(OPCO_ORDER)}")
    else:
        coo_html = _build_single_opco_html(_coo_opco_key)
        coo_html = re.sub(r'\.prow:hover\s+td\s*\{[^}]*\}', '.prow:hover td{}', coo_html)
        coo_html = re.sub(r'<style id="hover-patch">.*?</style>', '', coo_html, flags=re.DOTALL)
        coo_html = re.sub(r'<script id="hover-script">.*?</script>', '', coo_html, flags=re.DOTALL)
        coo_html = coo_html.replace('</style>', '</style>' + _HOVER_CSS, 1)
        if _password:
            coo_protected = _make_protected_html(coo_html, _password) or coo_html
        else:
            coo_protected = coo_html
        coo_path = BASE / "my_opco_report.html"
        coo_path.write_text(coo_protected, encoding="utf-8")
        size_kb = coo_path.stat().st_size // 1024
        print(f"✓ COO report — {OPCOS[_coo_opco_key]['display_name']} → my_opco_report.html ({size_kb} KB, local only)")

# Commit and push per-opco pages (skipped entirely in COO mode — Jon's repo only)
if _coo_opco_key:
    pass
else:
    # Clean stale git locks left by the previous push before starting a new commit
    for _lock in (BASE / ".git").glob("*.lock"):
        try:
            _lock.unlink(missing_ok=True)
        except OSError:
            pass
    _git(["add"] + [f"{sf}/index.html" for sf in PER_OPCO_PAGES.values()])
    commit_r = _git(["commit", "-m", f"Auto-update per-opco pages: {today_str}"])
    if "nothing to commit" in (commit_r.stdout + commit_r.stderr):
        print("  (no changes to per-opco pages)")
    else:
        push_opco = _git(["push", "origin", "master"])
        if push_opco.returncode == 0:
            print("🚀 Per-opco pages published:")
            for ok, sf in PER_OPCO_PAGES.items():
                print(f"   https://jonhawkandson.github.io/eidra-allocation-report/{sf}/"
                      f"  ({OPCOS[ok]['display_name']})")
        else:
            print(f"  Per-opco push failed: {push_opco.stderr.strip()}")
