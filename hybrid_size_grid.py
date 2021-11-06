from pathlib import Path
import json
from itertools import product
import multiprocessing as mp
import sys
sys.path.append(str(Path(__file__).parent.parent.parent.absolute()))
from hybrid.sites import SiteInfo, make_irregular_site
from hybrid.hybrid_simulation import HybridSimulation, logger
from hybrid.dispatch.plot_tools import plot_battery_output, plot_battery_dispatch_error, plot_generation_profile

from financial_calcs import hybrid_capacity_credit

# from hybrid.keys import set_nrel_key_dot_env
# Set API key
# set_nrel_key_dot_env()

params_dir = (Path(__file__).parent / "parameter_files").absolute()

with open(params_dir / "pv_parameters.json", 'r') as f:
    pv_info = json.load(f)["SystemDesign"]
with open(params_dir / "wind_parameters.json", 'r') as f:
    wind_info = json.load(f)
turb_rating_kw = max(wind_info['Turbine']['wind_turbine_powercurve_powerout'])
with open(params_dir / "financial_parameters.json", 'r') as f:
    fin_info = json.load(f)
cost_info = fin_info['capex']

# Get resource
resource_dir = (Path(__file__).parent / "resource_files").absolute()

# texas
# solar_file = resource_dir / "32.43861838431444__-99.73363995829895_32.438818_-99.734703_psm3_60_2013.csv"
# wind_file = resource_dir / "lat32.43_lon-99.73__2013_120m.srw"

# paper location
location = (36.334, -119.769, 70.0)
solar_file = resource_dir / "36.334__-119.769_43.724007_-65.978570_psm3_60_2012.csv"
wind_file = resource_dir / "lat36.33_lon-119.77__2012_120m.srw"

prices_file = resource_dir / "pricing-data-2015-IronMtn-002_factors.csv"
site = SiteInfo(make_irregular_site(lat=location[0], lon=location[1], elev=location[2]),
                solar_resource_file=solar_file,
                wind_resource_file=wind_file,
                grid_resource_file=prices_file)
year1_prices = site.elec_prices._data[0:8760]

dispatch_options = {
        'battery_dispatch': 'simple',
        # 'battery_dispatch': 'one_cycle_heuristic',
        'grid_charging': True,
        'log_name': ""        # need to disable for multiprocessing
    }


def simulate_hybrid(sizes, plotting=False):
    solar_mw, wind_mw, battery_mw = sizes
    solar_plus_wind_mw = solar_mw + wind_mw
    hybrid_mw = solar_plus_wind_mw + battery_mw

    technologies = {'pv': {
                        'system_capacity_kw': solar_mw * 1000,
                    },
                    'wind': {
                        'num_turbines': wind_mw * 1000 // turb_rating_kw,
                        'turbine_rating_kw': turb_rating_kw
                    },
                    'battery': {
                        'system_capacity_kwh': battery_mw * 4 * 1000,
                        'system_capacity_kw': battery_mw * 1000
                    }}
    if battery_mw == 0:
        technologies.pop('battery')

    # use just 1 year of energy and capacity prices for now
    site.elec_prices._data = [i * 1.0 for i in year1_prices]

    hybrid_plant = HybridSimulation(technologies, site, interconnect_kw=hybrid_mw * 1000,
                                    cost_info=cost_info, dispatch_options=dispatch_options)

    hybrid_plant.assign({"pv": pv_info})

    # setup wind turbine parameters
    hybrid_plant.assign({"wind": wind_info['Turbine']})
    hybrid_plant.assign({"wind": wind_info['Losses']})
    hybrid_plant.wind.wake_model = 3                            # no wake modeling because no layout
    hybrid_plant.wind._system_model.Losses.wake_int_loss = 5    # fixed wake loss of 5%

    # financial & depreciation parameters also invariant across sizes
    hybrid_plant.assign(fin_info["FinancialParameters"])
    hybrid_plant.assign(fin_info["TaxCreditIncentives"])
    hybrid_plant.assign(fin_info["Depreciation"])

    # setup capacity credit for wind and solar, hybrid will be set up within opt loop
    hybrid_plant.assign(fin_info["Revenue"])

    # O&M costs
    hybrid_plant.assign(fin_info["SystemCosts"])

    hybrid_plant.grid.capacity_credit_percent = hybrid_capacity_credit(wind_mw, solar_mw, battery_mw)

    # use single year for now, multiple years with battery not implemented yet
    hybrid_plant.simulate(project_life=35)

    # Save the outputs for JSON
    annual_energies = str(hybrid_plant.annual_energies)
    cap_factor = str(hybrid_plant.capacity_factors)
    cap_payment = str(hybrid_plant.capacity_payments)
    benefit_cost_ratios = str(hybrid_plant.benefit_cost_ratios)
    npvs = str(hybrid_plant.net_present_values)

    res = {
        "sizes": sizes,
    }
    outputs = ("annual_energies", "capacity_factors", "capacity_payments", "total_revenues", "net_present_values",
               "benefit_cost_ratios", "energy_values", "energy_purchases_values", "energy_sales_values",
               "federal_depreciation_totals", "federal_taxes", "om_expenses", "cost_installed")
    for val in outputs:
        try:
            res[val] = json.loads(str(getattr(hybrid_plant, val)))
        except:
            print("error printing", val)
    import pprint
    pprint.pprint(res)
    print(sizes, {"npvs": npvs, "bcr": benefit_cost_ratios})
    print(hybrid_plant.battery.replacement_costs)

    # import numpy as np
    # np.savetxt(str(params_dir / "grid_output.txt"), hybrid_plant.grid.generation_profile[0:8760])
    if plotting and battery_mw > 0:
        plot_battery_dispatch_error(hybrid_plant)
        plot_battery_output(hybrid_plant)
        plot_generation_profile(hybrid_plant)
    return sizes, annual_energies, cap_factor, npvs, benefit_cost_ratios


if __name__ == "__main__":
    config_dict = {}
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r") as f:
            config_dict = json.load(f)

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
        elif k != 'objective':
            raise IOError(f"Configuration key '{k}' not recognized")
    logger.info(f"config: {config_dict}")

    # Run a single system
    # simulate_hybrid((123, 60, 2), True)
    # exit()

    # Run a grid of sizes
    solar_sizes = range(1, 401, 75)
    wind_sizes = range(6, 406, 72)
    battery_sizes = range(0, 407, 75)

    out_dir = params_dir.parent / "results"
    if config_dict:
        out_dir = Path(sys.argv[1]).parent
    with mp.Pool(36) as p:
        results = p.map(simulate_hybrid, product(solar_sizes, wind_sizes, battery_sizes))
        with open(out_dir / "hybrid_size_grid.json", "w") as f:
            json.dump(results, f)
