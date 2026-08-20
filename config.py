"""
Configuration for the RCA categorization tool.

Source: Network Rail Investigators' Handbook, Part 4 - Causation,
Issue 3 (March 2021), pages 47-50 (10 Incident Factors) and page 25
(Behavioural Cause / Fair Culture flowchart, i.e. the GEMR model).

IMPORTANT - version dependency:
This file encodes the definitions from Issue 3 (March 2021). If Network
Rail issues a revised Handbook, this file must be checked and updated -
the LLM classifies purely against what is written here, not against the
live document.
"""

HANDBOOK_VERSION = "Investigators' Handbook Part 4 - Causation, Issue 3 (March 2021)"

# ---------------------------------------------------------------------------
# The 10 Incident Factors
# Used by extraction.py as the fixed, closed list of categories the LLM must
# choose from. Each entry's "definition" and "example" are fed into the
# system prompt verbatim so the model classifies against Network Rail's
# actual working definition, not a guess from the label alone.
# ---------------------------------------------------------------------------

INCIDENT_FACTORS = {
    "Verbal communication": {
        "definition": (
            "The exchange of spoken information only, concerned with how safety "
            "critical information is communicated between staff. Information "
            "conveyed in written format is covered separately by 'Written "
            "information on the day'. Look for the underlying causes of the "
            "communication issue itself, not just that a communication protocol "
            "was not followed - identify what led to that."
        ),
        "example": (
            "Communications within and between job roles such as Driver, "
            "Signaller, Engineering Supervisor, Shunter, Person in Charge of "
            "Possession, Route Conductor. E.g. 'The driver did not repeat back "
            "the signaller's message to check that he had understood it correctly.'"
        ),
    },
    "Fatigue, health and wellbeing": {
        "definition": (
            "The individual's fatigue, health and wellbeing, which is the joint "
            "responsibility of the company and the member of staff, and can "
            "affect the individual's ability to maintain focus and attention "
            "whilst at work. Consider the broader fatigue risk management and "
            "health management processes, not just adherence to a fatigue index."
        ),
        "example": (
            "Fatigue risk management (rostering, rest breaks), managing for "
            "attendance processes, health monitoring. E.g. 'The working hours of "
            "the track worker were in excess of industry guidelines and he was "
            "tired. In the 2 weeks prior to the incident the driver had worked "
            "over 12 hours in a shift on 3 occasions and had less than 12 hours "
            "rest on 3 occasions.'"
        ),
    },
    "Processes and procedure documents": {
        "definition": (
            "Laws, rules, policies, procedures, standards, guidelines etc. which "
            "are long-term documents guiding the actions of staff, passengers "
            "and the public on or around the railway, including operational "
            "rules for train driving, signalling, maintenance, fault "
            "identification/reporting, and setting up safe systems of work, as "
            "well as management/office processes."
        ),
        "example": (
            "Rule Book, risk-triggered commentary procedure, maintenance "
            "procedures. E.g. 'The method of working for the freight yard left "
            "trains blocking the level crossing for up to an hour at a time, "
            "increasing road user frustration and risk.'"
        ),
    },
    "Written information on the day": {
        "definition": (
            "Data and documentation which can be renewed from day to day or "
            "week to week, supporting people in carrying out a task/applying a "
            "process in specific situations. Must be relevant, timely and "
            "well-designed - investigate whether it was presented in a usable "
            "format and made available on time."
        ),
        "example": (
            "Train running information, timetable simplifiers, late notices, "
            "special train notices, weekly/periodic operating notices, "
            "pre-job information, electrification/isolation diagrams. E.g. 'The "
            "company produced incorrect diagrams, failing to show the correct "
            "shunt moves and where and when drivers were to be collected.'"
        ),
    },
    "Competence management": {
        "definition": (
            "The company's competence management systems and has to do with "
            "the selection, training and assessment process a person has (or "
            "has not) gone through. Consider technical skills and also "
            "non-technical skills, incident reporting, etc."
        ),
        "example": (
            "Route knowledge or local knowledge, traction knowledge, "
            "non-technical skills competence. E.g. 'The person had not been "
            "given practical training to deal with the particular type of "
            "emergency.'"
        ),
    },
    "Infrastructure, vehicles, equipment and clothing": {
        "definition": (
            "Any infrastructure, vehicles, equipment and clothing that are used "
            "to undertake or support an activity. Always aim to identify the "
            "underlying causes of equipment issues - ask 'why', rather than "
            "concluding that the infrastructure, equipment or materials failed "
            "or was badly maintained."
        ),
        "example": (
            "Railway signals, train brakes, DRA, AWS, ERTMS, controls and "
            "displays in cabs, signal boxes or control centres, PPE. E.g. 'The "
            "signal was poorly located, with inadequate siting, and the "
            "signalling design contributed to the incident.'"
        ),
    },
    "The person's environment": {
        "definition": (
            "The environmental stressors which can affect the decisions and/or "
            "performance of the person. Identify the environment as an "
            "influencing factor even when it is not directly causal, because it "
            "may become important if it is identified as an influence across a "
            "number of incidents."
        ),
        "example": (
            "Hot/cold environments, wet, draughty or noisy environments, "
            "sunlight, fog and snow. E.g. 'The sun was shining directly in the "
            "lookout's eyes and they had difficulty seeing.'"
        ),
    },
    "Workload (real or perceived) and resourcing": {
        "definition": (
            "The demand on a person, and resourcing, which is about the number "
            "of people or amount of equipment available to do the task. If "
            "workload is higher than acceptable limits it will be stressful, "
            "fatiguing and demotivating; if workload is low, staff may have "
            "reduced attention and be slower to react to non-routine situations."
        ),
        "example": (
            "High workload created by complex tasks or locations, or when "
            "non-routine tasks need attention at the same time as routine "
            "tasks. E.g. 'The driver of the stranded train was faced with the "
            "conflicting demands of communicating with the signaller, "
            "fault-finding, spurious passcom activations and passenger "
            "complaints and queries.'"
        ),
    },
    "Teamworking and leadership": {
        "definition": (
            "How people are organised to work together, how they relate to "
            "each other and influence each other in order to carry out their "
            "work safely. Team members may not necessarily work in the same "
            "location or even for the same organisation as each other."
        ),
        "example": (
            "Team working within maintenance, team working between company "
            "departments, leadership behaviours. E.g. 'A crowd of seven members "
            "of platform staff were used to dispatch a train, but there was no "
            "lead dispatcher and responsibilities were not clear.'"
        ),
    },
    "Risk management": {
        "definition": (
            "The processes used to identify, assess, reduce and monitor safety "
            "problems. Risk management processes can be an underlying reason "
            "for an accident or incident if the organisation is not mitigating "
            "risk effectively - because of an ineffective risk assessment, or "
            "because monitoring/feedback systems have not detected safety "
            "problems, or because management chose not to act on problems "
            "picked up through reporting/monitoring."
        ),
        "example": (
            "Risk assessment of routes or maintenance activities, escalation of "
            "safety issues, prioritisation and action on safety problems. E.g. "
            "'Management failed to identify that vehicle maintenance standards "
            "were not being applied.'"
        ),
    },
}

INCIDENT_FACTOR_NAMES = list(INCIDENT_FACTORS.keys())


# ---------------------------------------------------------------------------
# Behavioural Cause / Fair Culture flowchart (GEMR - Generic Error Model
# for Rail), from Handbook Section H, page 25.
#
# This is a deterministic decision tree, not a free-classification task.
# Implement as an ordered sequence of yes/no questions; the LLM's job is
# only to answer each question from the incident narrative (with a short
# justification), never to pick the final outcome directly. A plain Python
# function then walks the tree from the answers to the outcome, so the
# result is auditable and cannot be hallucinated.
# ---------------------------------------------------------------------------

FAIR_CULTURE_QUESTIONS = [
    {
        "id": "deliberate",
        "question": "Was the action deliberate?",
        "branch": "deliberate_harm",
    },
    {
        "id": "well_intentioned",
        "question": "Was the action well intentioned?",
        "branch": "deliberate_harm",
        "depends_on": {"deliberate": True},
    },
    {
        "id": "sabotage_or_reckless",
        "question": (
            'Was it "Sabotage, malicious intention" (well_intentioned=No) or '
            '"Reckless contravention" (well_intentioned=Yes but deliberate)?'
        ),
        "branch": "deliberate_harm",
        "depends_on": {"deliberate": True},
        "terminal": True,
    },
    {
        "id": "informed_about_procedures",
        "question": "Informed about procedures?",
        "branch": "foresight",
        "depends_on": {"deliberate": False},
    },
    {
        "id": "procedures_clear_and_workable",
        "question": "Procedures clear and workable?",
        "branch": "foresight",
        "depends_on": {"deliberate": False, "informed_about_procedures": True},
    },
    {
        "id": "contravention_or_mistake",
        "question": (
            "If informed and procedures were clear/workable but not followed: "
            "Contravention or Slip/lapse? If procedures were NOT clear/workable: "
            "Mistake caused by system."
        ),
        "branch": "foresight",
        "depends_on": {"deliberate": False, "informed_about_procedures": True},
        "terminal": True,
    },
    {
        "id": "would_others_have_done_the_same",
        "question": "Would others have done the same?",
        "branch": "substitution",
        "depends_on": {"deliberate": False, "informed_about_procedures": False},
    },
    {
        "id": "adequate_selection_training_experience",
        "question": "Adequate selection, training and experience?",
        "branch": "substitution",
        "depends_on": {
            "deliberate": False,
            "informed_about_procedures": False,
            "would_others_have_done_the_same": False,
        },
        "terminal_if_no": "Poor judgement",
    },
    {
        "id": "history_of_contravening_procedures",
        "question": "History of contravening procedures?",
        "branch": "personal_history",
        "depends_on": {
            "deliberate": False,
            "informed_about_procedures": False,
            "would_others_have_done_the_same": True,
        },
        "terminal": True,  # Yes -> Routine error, personal history
        # No -> Routine error, different people
    },
]

# Final outcome labels this tree can produce - matches Handbook Fig. 9 (GEMR)
# leaf nodes and the CSV's "Behavioural Cause" columns.
FAIR_CULTURE_OUTCOMES = [
    "Sabotage, malicious intention",
    "Reckless contravention",
    "Contravention",
    "Slip/lapse",
    "Mistake caused by system",
    "Poor judgement",
    "Routine error - personal history",
    "Routine error - different people",
]


# ---------------------------------------------------------------------------
# Mapping from raw CSV columns to the normalized table's circumstance fields.
# Update this dict, not the extraction logic, when the client's form changes.
# Column names below match Investigation_Full_V41_230826_YTD.csv as of the
# version reviewed with the client.
# ---------------------------------------------------------------------------

RAW_COLUMN_TO_NORMALIZED_FIELD = {
    "IRIS Reference Number": "incident_id",
    "Date of Incident / Accident": "date",
    "Time of Incident / Accident": "time",
    "Shift": "shift",
    "Route": "route",
    "DU / Depot / Area": "du_depot_area",
    "Site/Route": "site_route",
    "Type of Location": "type_of_location",
    "Specific location of incident / accident": "specific_location",
    "Latitude": "latitude",
    "Longitude": "longitude",
    "Incident / Accident Severity": "severity",
    "Incident / Accident Event": "incident_accident_event",
    "Type of Incident / Accident": "type_of_incident",
    "Incident Sub Type": "incident_sub_type",
    "What were the weather conditions? (multi select): Answer": "weather_conditions",
    "Lighting (multi select max 3): Answer": "lighting",
    "Visibility: Answer": "visibility",
    "Wet or Dry: Answer": "surface_wet_or_dry",
    "RIDDOR Reportable?": "riddor_reportable",
    "Lost Time Accident?": "lost_time_accident",
    "Specified Injury?": "specified_injury",
    "Near Miss?": "near_miss",
    "Was this Incident an Operational Close Call?": "operational_close_call",
    "Life Saving Rule Breach: Answer": "life_saving_rule_breach",
    "Breach Type:: Answer": "breach_type",
    "Type of Person Involved": "type_of_person_involved",
    "Age Range": "age_range",
    "Years in current role?": "years_in_current_role",
    "Years of Service in NR": "years_of_service_nr",
    "Hours into shift": "hours_into_shift",
    "Fatigue Risk Index Result ": "fatigue_risk_index_result",
    "Was Any Equipment Involved?": "was_equipment_involved",
    "Equipment Description": "equipment_description",
    "Drug & Alcohol Screening undertaken?": "drug_alcohol_screening",
    "Investigation Level: Answer": "investigation_level",
    "Cost of incident (£): Answer": "cost_of_incident",
    "Delay to Operational Railway (minutes): Answer": "delay_to_operational_railway_minutes",
}

# Columns holding cause text that gets fed to the LLM for categorization.
# There are 25 repeating slots (01-25) in the raw sheet; most incidents
# only populate 1-4 of them.
UNDERLYING_CAUSE_COLUMN_PATTERN = " Underlying cause - {:02d}:: Answer"
IMMEDIATE_CAUSE_COLUMN = "Immediate cause:: Answer"


# ---------------------------------------------------------------------------
# System prompt builders.
# NOTE: appended by Claude Code on 2026-07-15 - the project brief referenced
# these three functions as already existing in this file, but they were not
# present, so they are added here. Everything above this comment is unchanged.
# ---------------------------------------------------------------------------


def build_incident_factor_system_prompt():
    """System prompt for classifying an incident's cause text into exactly
    one of the 10 Incident Factors. The model must answer in JSON."""
    factor_blocks = []
    for name, info in INCIDENT_FACTORS.items():
        factor_blocks.append(
            f"### {name}\n"
            f"Definition: {info['definition']}\n"
            f"Example: {info['example']}"
        )
    factors_text = "\n\n".join(factor_blocks)
    allowed = "\n".join(f"- {name}" for name in INCIDENT_FACTOR_NAMES)
    return (
        "You are a Network Rail safety investigation analyst. You classify the "
        "root cause of an incident into exactly ONE of Network Rail's 10 Incident "
        f"Factors, as defined in the {HANDBOOK_VERSION}.\n\n"
        "The 10 Incident Factors and their official definitions:\n\n"
        f"{factors_text}\n\n"
        "The user will give you the immediate cause and underlying cause text "
        "from one investigation. Choose the single Incident Factor that best "
        "matches the UNDERLYING cause of the incident (prefer the underlying "
        "cause over the immediate cause when they point to different factors).\n\n"
        "Respond with a JSON object only, in exactly this shape:\n"
        '{"incident_factor": "<one of the 10 factor names, copied verbatim>", '
        '"confidence": <number between 0 and 1>, '
        '"justification": "<one or two sentences quoting the cause text>"}\n\n'
        "The value of \"incident_factor\" MUST be copied character-for-character "
        "from this list and nothing else:\n"
        f"{allowed}"
    )


def build_fair_culture_question_system_prompt(question_text):
    """System prompt for answering ONE yes/no question from the Fair Culture
    (GEMR) decision tree about an unsafe act. The model must answer in JSON."""
    return (
        "You are assisting a Network Rail fair-culture review (the GEMR "
        "behavioural-cause flowchart from the Investigators' Handbook). The user "
        "will give you the description of an unsafe act taken from an incident "
        "investigation. Answer ONLY this one question about that unsafe act:\n\n"
        f"QUESTION: {question_text}\n\n"
        "Rules:\n"
        "- Answer strictly from what the description says or clearly implies. "
        "If the description gives no evidence either way, choose the more "
        "charitable answer for the person involved (the fair-culture default) "
        "and say so in the justification.\n"
        "- If the question offers two named alternatives instead of a plain "
        "yes/no, answer true if the FIRST alternative applies and false if the "
        "SECOND applies.\n\n"
        "Respond with a JSON object only, in exactly this shape:\n"
        '{"answer": true or false, '
        '"justification": "<one or two sentences citing the description>"}'
    )


def build_qa_sql_system_prompt(create_table_sql):
    """System prompt for translating a plain-English question into a single
    SQLite SELECT statement over incidents_normalized."""
    factor_list = "\n".join(f"- {name}" for name in INCIDENT_FACTOR_NAMES)
    outcome_list = "\n".join(f"- {name}" for name in FAIR_CULTURE_OUTCOMES)
    return (
        "You translate a manager's plain-English question about railway safety "
        "incidents into ONE SQLite SELECT statement.\n\n"
        "The only table available is created by:\n\n"
        f"{create_table_sql}\n\n"
        "Facts about the data:\n"
        "- 'date' is stored as an ISO text date (YYYY-MM-DD); group by month "
        "with strftime('%Y-%m', date).\n"
        "- BOOLEAN columns hold 1, 0 or NULL.\n"
        "- Text columns (route, incident_factor, severity, etc.) are case-sensitive. "
        "For case-insensitive matching, use LOWER(column) = LOWER('value'). "
        "Routes are: North West, South East, Central, Northern, South Western. "
        "Severity is: Minor, Major, Shock/trauma, Fatality.\n"
        "- 'incident_factor' is always one of:\n"
        f"{factor_list}\n"
        "- 'behavioural_outcome' is always one of:\n"
        f"{outcome_list}\n\n"
        "Rules:\n"
        "- Produce exactly ONE statement, and it must be a SELECT. Never produce "
        "INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, PRAGMA or ATTACH, and "
        "never more than one statement.\n"
        "- Only use columns that exist in the table above.\n"
        "- Give aggregate columns clear lower_snake_case aliases (e.g. "
        "incident_count).\n"
        "- Add ORDER BY where it makes the answer easier to read, and LIMIT 100 "
        "unless the question asks for everything.\n\n"
        "Respond with a JSON object only, in exactly this shape:\n"
        '{"sql": "<the single SELECT statement>"}'
    )
