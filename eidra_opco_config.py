#!/usr/bin/env python3
"""
Eidra Float Allocation Report — OpCo Configuration
====================================================
Source of truth for all opco → department/sub-department → group mappings.

Structure per opco:
  display_name     Full name shown in the report header
  short_name       Short label for nav buttons
  color            Accent colour (nav pill, slide label bar)
  dept_id          Float top-level department_id for this opco
  groups           dict of group_key → {ids, label, color}
                   ids = list of Float sub-department_ids that belong to this group
                   For opcos without sub-depts, use a single group with [dept_id]
  exclude_dept_ids Float dept IDs to ignore (management, support, etc.)
  role_level_map   Float role_id → level label ("L1" … "L6", "Lx", "Intern")

All dept/role IDs verified against Eidra Float as of 2026-06-30.
"""

# ── Shared sub-dept group colour palette ──────────────────────────────────────
_P = [
    "#5B9BD5", "#ED7D31", "#A9D18E", "#FF8080",
    "#4472C4", "#70AD47", "#FFC000", "#9E480E",
    "#B070D0", "#FF6060", "#20B2AA", "#DC143C",
]

OPCOS = {

    # ──────────────────────────────────────────────────────────────────────────
    "eidra-consulting-se": {
        "display_name": "Eidra Consulting SE",
        "short_name":   "EC SE",
        "color":        "#1B2A4A",
        "dept_id":      16963437,
        "groups": {
            "Consulting": {"ids": [16963438], "label": "Consulting Team",          "color": _P[0]},
            "BizDir":     {"ids": [16963439], "label": "Business Direction",        "color": _P[1]},
            "InnExp":     {"ids": [16963440], "label": "Innovation & Experience",   "color": _P[2]},
            "BrandComm":  {"ids": [16963441], "label": "Brand & Communication",     "color": _P[3]},
            "Commerce":   {"ids": [16963442], "label": "Commerce & AI",             "color": _P[4]},
            "Sustain":    {"ids": [16963444], "label": "Sustainability",            "color": _P[5]},
            "TechProd":   {"ids": [16969559], "label": "Tech & Product",            "color": _P[7]},
            "General":    {"ids": [16963437], "label": "Eidra Consulting SE",       "color": _P[6]},
        },
        "exclude_dept_ids": [16963443],   # Management (EC SE)
        "role_level_map": {
            342866: "L0",
            342859: "L1",
            342860: "L2",
            342862: "L3",
            342865: "L4",
            342863: "L5",
            342864: "L6",
            342861: "Lx",
        },
    },

    # ──────────────────────────────────────────────────────────────────────────
    # NOTE: Above SE exists in Eidra Float but is not yet populated.
    # People will be migrated from the Above Float instance at a later date.
    "above-se": {
        "display_name": "Above SE",
        "short_name":   "Above SE",
        "color":        "#1a1a1a",
        "dept_id":      16961798,
        "groups": {
            "UX":         {"ids": [16961801], "label": "Design – UX",                    "color": _P[0]},
            "UI":         {"ids": [16961802], "label": "Design – UI",                    "color": _P[1]},
            "PM":         {"ids": [16961803], "label": "Strategy & Change – PM",         "color": _P[2]},
            "XM":         {"ids": [16961804], "label": "Strategy & Change – XM",         "color": _P[3]},
            "HW/SW":      {"ids": [16961807], "label": "Engineering – HW/SW",            "color": _P[4]},
            "Mech":       {"ids": [16961808], "label": "Engineering – Mech",             "color": _P[5]},
            "ID":         {"ids": [16961805], "label": "Physical Design – ID",           "color": _P[6]},
            "DesignTech": {"ids": [16961806], "label": "Physical Design – Design Tech",  "color": _P[7]},
            "General":    {"ids": [16961798], "label": "Above SE",                       "color": _P[8]},
        },
        "exclude_dept_ids": [16961800],   # Commercial (Above SE)
        "role_level_map": {
            344287: "L0",
            344289: "L1",
            344293: "L2",
            344296: "L3",
            344297: "L4",
            344298: "L5",
            344300: "L6",
        },
    },

    # ──────────────────────────────────────────────────────────────────────────
    "frojd-se": {
        "display_name": "Fröjd SE",
        "short_name":   "Fröjd SE",
        "color":        "#7B3FA0",
        "dept_id":      16961762,
        "groups": {
            "Design":    {"ids": [16961743], "label": "Design",              "color": _P[0]},
            "Dev":       {"ids": [16961744], "label": "Development",         "color": _P[1]},
            "Strategy":  {"ids": [16961745], "label": "Strategy & Insights", "color": _P[2]},
            "General":   {"ids": [16961762], "label": "Fröjd SE",            "color": _P[3]},
        },
        "exclude_dept_ids": [16961742],   # Commercial (Fröjd SE)
        "role_level_map": {
            344285: "L0",
            344284: "L1",
            344283: "L2",
            344282: "L3",
            344281: "L4",
            344280: "L5",
            344279: "L6",
            338732: "Lx",
        },
    },

    # ──────────────────────────────────────────────────────────────────────────
    "curamando-se": {
        "display_name": "Curamando SE",
        "short_name":   "Curamando SE",
        "color":        "#1B7A6B",
        "dept_id":      16944146,
        "groups": {
            "I&A":      {"ids": [16963220], "label": "Insights & Analytics",  "color": _P[0]},
            "TAM":      {"ids": [16963221], "label": "TA&M",                  "color": _P[1]},
            "BizCons":  {"ids": [16963223], "label": "Business Consulting",   "color": _P[2]},
            "Advisory": {"ids": [16963271], "label": "Advisory Consulting",   "color": _P[3]},
            "CommTeam": {"ids": [16963224], "label": "Core Commercial Team",  "color": _P[4]},
            # Dept 16963222 was "Project Management" — renamed in Float (~2026-08)
            # to "AI Core" and repopulated with a new practice team (10 of 11
            # people moved in during the week of 2026-08-31). Promoted from
            # exclude_dept_ids to its own group as of 2026-08-31.
            "AICore":   {"ids": [16963222], "label": "AI Core",               "color": _P[9]},
            "General":  {"ids": [16944146], "label": "Curamando SE",          "color": _P[5]},
        },
        "exclude_dept_ids": [16963273],  # Management
        "role_level_map": {
            342850: "L1",
            342848: "L2",
            342845: "L3",
            342846: "L4",
            342847: "L5",
            342849: "L6",
        },
    },

    # ──────────────────────────────────────────────────────────────────────────
    # New opco discovered in Float as of 2026-08-31 — not yet migrated fully
    # (2 people still sit directly on the top-level dept with no sub-dept).
    "curamando-nl": {
        "display_name": "Curamando NL",
        "short_name":   "Curamando NL",
        "color":        "#2E9E86",
        "dept_id":      16961813,
        "groups": {
            "AI":       {"ids": [16963733], "label": "AI",                 "color": _P[0]},
            "CommGrowth": {"ids": [16963734], "label": "Commerce & Growth", "color": _P[1]},
            "General":  {"ids": [16961813], "label": "Curamando NL",        "color": _P[2]},
        },
        "exclude_dept_ids": [],
        "role_level_map": {
            290405: "L1",
            290404: "L2",
            290401: "L3",
            290400: "L4",
            290399: "L5",
        },
    },

    # ──────────────────────────────────────────────────────────────────────────
    "conversionista-se": {
        "display_name": "Conversionista SE",
        "short_name":   "Conversionista SE",
        "color":        "#D4600A",
        "dept_id":      16963217,
        "groups": {
            "ExpertCons": {"ids": [16963216], "label": "Expert Consulting",   "color": _P[0]},
            "Insights":   {"ids": [16963574], "label": "Insights Team",       "color": _P[1]},
            "Advisory":   {"ids": [16963218], "label": "Advisory Consulting", "color": _P[2]},
            "DataQual":   {"ids": [16969904], "label": "Data Quality",        "color": _P[4]},
            "General":    {"ids": [16963217], "label": "Conversionista SE",   "color": _P[3]},
        },
        "exclude_dept_ids": [16963219],   # Management (Conversionista SE)
        "role_level_map": {
            342842: "L0",
            342844: "L1",
            342838: "L2",
            342839: "L3",
            342840: "L4",
            342841: "L5",
            342843: "L6",
        },
    },

    # ──────────────────────────────────────────────────────────────────────────
    "curious-mind-se": {
        "display_name": "Curious Mind SE",
        "short_name":   "Curious Mind SE",
        "color":        "#B5006E",
        "dept_id":      16963227,
        "groups": {
            "Expert1":   {"ids": [16963225], "label": "Expert 1",          "color": _P[0]},
            "Expert2":   {"ids": [16963226], "label": "Expert 2",          "color": _P[1]},
            "AccAdv":    {"ids": [16963228], "label": "Account & Advisory", "color": _P[2]},
            "General":   {"ids": [16963227], "label": "Curious Mind SE",   "color": _P[3]},
            "Interns":   {"ids": [16964449], "label": "Interns",           "color": _P[4]},
        },
        "exclude_dept_ids": [16964450],  # Management
        "role_level_map": {
            342853: "L0",
            342856: "L1",
            342851: "L2",
            342852: "L3",
            342854: "L4",
            342855: "L5",
            342857: "L6",
            342858: "Lx",
        },
    },

    # ──────────────────────────────────────────────────────────────────────────
    # Float name is "Fabrique" — display as "Fabrique NL" per spec
    "fabrique-nl": {
        "display_name": "Fabrique NL",
        "short_name":   "Fabrique NL",
        "color":        "#1A3F7A",
        "dept_id":      16961811,
        "groups": {
            "UX":       {"ids": [16963476], "label": "Design – UX",       "color": _P[0]},
            "Visual":   {"ids": [16963475], "label": "Design – Visual",   "color": _P[1]},
            "Strategy": {"ids": [16963477], "label": "Strategy & PM",     "color": _P[2]},
            # Top-level dept catches people not yet assigned to a sub-dept
            "General":  {"ids": [16961811], "label": "Fabrique NL",       "color": _P[3]},
        },
        "exclude_dept_ids": [],
        "role_level_map": {
            291390: "L1",
            291391: "L2",
            290402: "L3",
            290407: "L4",  # Fabrique L4
            290404: "L4",  # Fabrique L4 (alt)
            291389: "L5",
            290406: "L6",
            309452: "Intern",
        },
    },

    # ──────────────────────────────────────────────────────────────────────────
    # Float name is "Q42" — display as "Q42 NL" per spec
    # No sub-departments in Float yet; use top-level dept as single group
    "q42-nl": {
        "display_name": "Q42 NL",
        "short_name":   "Q42 NL",
        "color":        "#2A6B1A",
        "dept_id":      16961812,
        "groups": {
            "Q42 NL": {"ids": [16961812], "label": "Q42 NL", "color": _P[0]},
        },
        "exclude_dept_ids": [],
        "role_level_map": {
            307987: "L0",   # Q42 L0 – Trainee
            307981: "L1",
            307982: "L2",
            307983: "L3",
            288438: "L4",
            307984: "L5",
            288439: "L6",
        },
    },

    # ──────────────────────────────────────────────────────────────────────────
    # Eidra Consulting NL — no sub-departments in Float yet
    "eidra-consulting-nl": {
        "display_name": "Eidra Consulting NL",
        "short_name":   "EC NL",
        "color":        "#3F1B8A",
        "dept_id":      16961814,
        "groups": {
            "EC NL": {"ids": [16961814], "label": "Eidra Consulting NL", "color": _P[0]},
        },
        "exclude_dept_ids": [],
        "role_level_map": {
            290768: "L1",   # Consultant NL L1
            288142: "L2",
            288141: "L3",
            288137: "L4",
            288136: "L5",
            288135: "L6",
        },
    },

    # ──────────────────────────────────────────────────────────────────────────
    "eidra-dach": {
        "display_name": "Eidra DACH",
        "short_name":   "Eidra DACH",
        "color":        "#8A1B1B",
        "dept_id":      16946466,
        "groups": {
            "Elaboratum": {"ids": [16946467], "label": "Elaboratum",           "color": _P[0]},
            "EC DE":      {"ids": [16958047], "label": "Eidra Consulting DE",  "color": _P[1]},
            "General":    {"ids": [16946466], "label": "Eidra DACH",           "color": _P[2]},
        },
        "exclude_dept_ids": [],
        "role_level_map": {
            328362: "L0",   # Consultant DE L0
            328361: "L1",
            328360: "L2",
            328359: "L3",
            328358: "L4",
            328357: "L5",
            328356: "L6",
        },
    },

    # ──────────────────────────────────────────────────────────────────────────
    # Umain — three country entities; no sub-departments in Float yet
    "umain-se": {
        "display_name": "Umain SE",
        "short_name":   "Umain SE",
        "color":        "#0A7A8A",
        "dept_id":      16963445,
        "groups": {
            "Umain SE": {"ids": [16963445], "label": "Umain SE", "color": _P[0]},
        },
        "exclude_dept_ids": [],
        "role_level_map": {},   # Roles not yet defined for Umain
    },

    "umain-no": {
        "display_name": "Umain NO",
        "short_name":   "Umain NO",
        "color":        "#1A5A6B",
        "dept_id":      16963446,
        "groups": {
            "Umain NO": {"ids": [16963446], "label": "Umain NO", "color": _P[0]},
        },
        "exclude_dept_ids": [],
        "role_level_map": {},
    },

    "umain-us": {
        "display_name": "Umain US",
        "short_name":   "Umain US",
        "color":        "#1A3A5A",
        "dept_id":      16963447,
        "groups": {
            "Umain US": {"ids": [16963447], "label": "Umain US", "color": _P[0]},
        },
        "exclude_dept_ids": [],
        "role_level_map": {},
    },

    # ──────────────────────────────────────────────────────────────────────────
    "eidra-no": {
        "display_name": "Eidra NO",
        "short_name":   "Eidra NO",
        "color":        "#4A5A6B",
        "dept_id":      16935986,
        "groups": {
            "Eidra NO": {"ids": [16935986], "label": "Eidra NO", "color": _P[0]},
        },
        "exclude_dept_ids": [],
        "role_level_map": {},
    },

    # ──────────────────────────────────────────────────────────────────────────
    # Float name is "Essense" — display as "Essense NL" per user request
    # Restructured into 7 sub-departments in Float as of 2026-08-31 (was a
    # single flat team before). role_level_map only covers L2/L3/L4/L6 —
    # those are the only Essense role_ids observed in the data so far; L1/L5
    # will need adding once someone with those roles shows up.
    "essense-nl": {
        "display_name": "Essense NL",
        "short_name":   "Essense NL",
        "color":        "#8A1B4A",
        "dept_id":      16961815,
        "groups": {
            "ServiceDesign": {"ids": [16966211], "label": "Service Design",     "color": _P[0]},
            "ExpDesign":     {"ids": [16966212], "label": "Experience Design",  "color": _P[1]},
            "CXConsulting":  {"ids": [16966213], "label": "CX Consulting",      "color": _P[2]},
            "ClientMgmt":    {"ids": [16968070], "label": "Client Management",  "color": _P[3]},
            "NewBiz":        {"ids": [16968071], "label": "New Business",       "color": _P[4]},
            "Marketing":     {"ids": [16968072], "label": "Marketing",          "color": _P[5]},
            "Operations":    {"ids": [16968075], "label": "Operations",         "color": _P[6]},
            "General":       {"ids": [16961815], "label": "Essense NL",         "color": _P[7]},
        },
        "exclude_dept_ids": [],
        "role_level_map": {
            288133: "Consultant",  # Generic "Consultant" role
            351677: "L2",
            351678: "L3",
            351679: "L4",
            351681: "L6",
        },
    },

}

# ── Ordered list of opco keys for nav display ─────────────────────────────────
OPCO_ORDER = [
    "eidra-consulting-se",
    "above-se",
    "frojd-se",
    "curamando-se",
    "curamando-nl",
    "conversionista-se",
    "curious-mind-se",
    "fabrique-nl",
    "q42-nl",
    "eidra-consulting-nl",
    "eidra-dach",
    "umain-se",
    "umain-no",
    "umain-us",
    "eidra-no",
    "essense-nl",
]

# ── Generic role fallback (used when role_id not in opco's role_level_map) ────
GENERIC_ROLE_LEVEL = {
    288133: "Consultant",
    338733: "Intern",
}
