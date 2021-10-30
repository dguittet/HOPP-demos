import json
from pathlib import Path


fin_file = Path(__file__).parent / "parameter_files" / "financial_parameters.json"
with open(fin_file, "r") as f:
    rev_dict = json.load(f)["Revenue"]
pv_credit = rev_dict["pv"]["cp_capacity_credit_percent"]
wind_credit = rev_dict["wind"]["cp_capacity_credit_percent"]
batt_credit = rev_dict["battery"]["cp_capacity_credit_percent"]


def hybrid_capacity_credit(wind_mw, solar_mw, battery_mw):
    hybrid_mw = sum([wind_mw, solar_mw, battery_mw])
    min_len = min(len(pv_credit), min(len(wind_credit), len(batt_credit)))
    hybrid_credit = []
    if hybrid_mw == 0:
        return [0] * min_len
    for i in range(min_len):
        hybrid_credit.append((wind_credit[i] * wind_mw
                              + pv_credit[i] * solar_mw
                              + batt_credit[i] * battery_mw) / hybrid_mw)
    return hybrid_credit
