import json
from hybrid.sites import SiteInfo, make_irregular_site


def import_config(params_dir):
    with open(params_dir / "pv_parameters.json", 'r') as f:
        pv_info = json.load(f)["SystemDesign"]
    with open(params_dir / "wind_parameters.json", 'r') as f:
        wind_info = json.load(f)
    turb_rating_kw = max(wind_info['Turbine']['wind_turbine_powercurve_powerout'])
    with open(params_dir / "financial_parameters.json", 'r') as f:
        fin_info = json.load(f)
    cost_info = fin_info['capex']
    return pv_info, wind_info, fin_info, cost_info, turb_rating_kw


def setup_config(config_dict, fin_info, wind_info, resource_dir):
    location = solar_file = wind_file = None

    dispatch_options = {
        'battery_dispatch': 'simple',
        # 'battery_dispatch': 'one_cycle_heuristic',
        'grid_charging': True,
        'pv_charging_only': False,
        'log_name': ""  # need to disable for multiprocessing
    }

    for k, v in config_dict.items():
        if k == "discount_rate":
            fin_info["FinancialParameters"]["real_discount_rate"] = v
        elif k == "energy_price_base":
            fin_info["Revenue"]["ppa_price_input"] = (v * 0.01,)   # convert from cents
        elif k == "wind_losses":
            wind_info["Losses"]["avail_bop_loss"] = v
        elif k == "grid_charging":
            if dispatch_options:
                dispatch_options["grid_charging"] = bool(v)
                if v:
                    fin_info["TaxCreditIncentives"]["battery"]["itc_fed_percent"] = 0
        elif k == "pv_charging_only":
            if dispatch_options:
                dispatch_options["pv_charging_only"] = bool(v)
        elif k == "pv_itc_fed_percent":
            fin_info["TaxCreditIncentives"]["pv"]["itc_fed_percent"] = v
        elif k == "wind_ptc_fed_amount":
            fin_info["TaxCreditIncentives"]["wind"]["ptc_fed_amount"] = v
        elif k == "location":
            if v == "TX":
                location = (32.4386, -99.7336, 0)
                solar_file = resource_dir / "32.43861838431444__-99.73363995829895_32.438818_-99.734703_psm3_60_2013.csv"
                wind_file = resource_dir / "lat32.43_lon-99.73__2013_120m.srw"
            if v == "CA":
                # paper location
                location = (36.334, -119.769, 70.0)
                solar_file = resource_dir / "36.334__-119.769_43.724007_-65.978570_psm3_60_2012.csv"
                wind_file = resource_dir / "lat36.33_lon-119.77__2012_120m.srw"
        # elif k != 'objective':
        #     raise IOError(f"Configuration key '{k}' not recognized")

    prices_file = resource_dir / "pricing-data-2015-IronMtn-002_factors.csv"
    if not location or not solar_file or not wind_file:
        raise IOError

    site = SiteInfo(make_irregular_site(lat=location[0], lon=location[1], elev=location[2]),
                    solar_resource_file=solar_file,
                    wind_resource_file=wind_file,
                    grid_resource_file=prices_file)
    return fin_info, wind_info, dispatch_options, site
