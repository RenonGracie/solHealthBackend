# src/utils/state_utils.py
"""
State name/abbreviation and timezone utilities.
"""

STATE_NAME_TO_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
    "District of Columbia": "DC",
    "American Samoa": "AS", "Guam": "GU", "Northern Mariana Islands": "MP",
    "Puerto Rico": "PR", "U.S. Virgin Islands": "VI", "Virgin Islands": "VI",
    "Armed Forces Americas": "AA", "Armed Forces Europe": "AE", "Armed Forces Pacific": "AP",
}
ABBR_TO_STATE_NAME = {v: k for k, v in STATE_NAME_TO_ABBR.items()}

STATE_VARIATIONS = {
    "D.C.": "DC", "Washington D.C.": "DC", "Washington DC": "DC",
    "N.Y.": "NY", "N.J.": "NJ", "N.H.": "NH", "N.M.": "NM",
    "N.C.": "NC", "N.D.": "ND", "S.C.": "SC", "S.D.": "SD", "W.V.": "WV",
    "Calif.": "CA", "Fla.": "FL", "Ill.": "IL", "Mass.": "MA", "Mich.": "MI",
    "Minn.": "MN", "Miss.": "MS", "Penn.": "PA", "Tenn.": "TN", "Tex.": "TX",
    "Wash.": "WA", "Wisc.": "WI",
}

def get_state_abbreviation(state_input: str) -> str:
    if not state_input:
        return ""
    s = state_input.strip()
    if s.upper() in ABBR_TO_STATE_NAME:
        return s.upper()
    if s in STATE_VARIATIONS:
        return STATE_VARIATIONS[s]
    for name, abbr in STATE_NAME_TO_ABBR.items():
        if name.lower() == s.lower():
            return abbr
    s_low = s.lower()
    for name, abbr in STATE_NAME_TO_ABBR.items():
        if s_low in name.lower() or name.lower() in s_low:
            return abbr
    return s

def get_state_name(abbr_input: str) -> str:
    if not abbr_input:
        return ""
    a = abbr_input.strip().upper()
    if a in ABBR_TO_STATE_NAME:
        return ABBR_TO_STATE_NAME[a]
    if a.title() in STATE_NAME_TO_ABBR:
        return a.title()
    return a

def is_valid_state(state_input: str) -> bool:
    if not state_input:
        return False
    s = state_input.strip()
    return (
        s.upper() in ABBR_TO_STATE_NAME
        or any(name.lower() == s.lower() for name in STATE_NAME_TO_ABBR)
        or s in STATE_VARIATIONS
    )

def get_states_list(format_type: str = "abbr") -> list:
    if format_type == "abbr":
        return sorted(ABBR_TO_STATE_NAME.keys())
    if format_type == "name":
        return sorted(STATE_NAME_TO_ABBR.keys())
    raise ValueError("format_type must be 'abbr' or 'name'")

def get_contiguous_states() -> list:
    excluded = {"AK", "HI", "AS", "GU", "MP", "PR", "VI", "AA", "AE", "AP"}
    return [abbr for abbr in ABBR_TO_STATE_NAME if abbr not in excluded]

def get_state_timezone(state_abbr: str) -> str:
    # Primary timezones by state/territory using proper IANA timezone identifiers
    # FIXED: Use modern IANA timezone names instead of deprecated US/* format
    tz = {
        # Eastern Time Zone
        "CT":"America/New_York","DE":"America/New_York","DC":"America/New_York","FL":"America/New_York",
        "GA":"America/New_York","ME":"America/New_York","MD":"America/New_York","MA":"America/New_York",
        "NH":"America/New_York","NJ":"America/New_York","NY":"America/New_York","NC":"America/New_York",
        "OH":"America/New_York","PA":"America/New_York","RI":"America/New_York","SC":"America/New_York",
        "VT":"America/New_York","VA":"America/New_York","WV":"America/New_York","MI":"America/New_York",
        "IN":"America/New_York","KY":"America/New_York",
        # Central Time Zone
        "AL":"America/Chicago","AR":"America/Chicago","IL":"America/Chicago","IA":"America/Chicago",
        "LA":"America/Chicago","MN":"America/Chicago","MS":"America/Chicago","MO":"America/Chicago",
        "OK":"America/Chicago","WI":"America/Chicago","TX":"America/Chicago","TN":"America/Chicago",
        "KS":"America/Chicago","NE":"America/Chicago","SD":"America/Chicago","ND":"America/Chicago",
        # Mountain Time Zone
        "AZ":"America/Phoenix","CO":"America/Denver","ID":"America/Denver","MT":"America/Denver",
        "NM":"America/Denver","UT":"America/Denver","WY":"America/Denver",
        # Pacific Time Zone
        "CA":"America/Los_Angeles","NV":"America/Los_Angeles","OR":"America/Los_Angeles","WA":"America/Los_Angeles",
        # Alaska/Hawaii
        "AK":"America/Anchorage","HI":"Pacific/Honolulu",
        # Territories
        "PR":"America/Puerto_Rico","VI":"America/Virgin",
        "GU":"Pacific/Guam","AS":"Pacific/Samoa","MP":"Pacific/Saipan",
    }
    return tz.get((state_abbr or "").strip().upper(), "America/New_York")

def validate_state_for_licensing(state_abbr: str, licensed_states: list) -> bool:
    if not state_abbr or not licensed_states:
        return False
    target = get_state_abbreviation(state_abbr)
    for s in licensed_states:
        if get_state_abbreviation(s) == target:
            return True
    return False

__all__ = [
    "STATE_NAME_TO_ABBR","ABBR_TO_STATE_NAME","get_state_abbreviation","get_state_name",
    "is_valid_state","get_states_list","get_contiguous_states",
    "get_state_timezone","validate_state_for_licensing",
]
