import os
from pathlib import Path
import numpy as np
import json
from collections import OrderedDict
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from hybrid.sites import SiteInfo
from hybrid.hybrid_simulation import HybridSimulation, logger
from hybrid.layout.wind_layout import WindBoundaryGridParameters
from hybrid.layout.pv_layout import PVGridParameters, module_power
from tools.optimization import DataRecorder
from tools.optimization.optimization_problem import OptimizationProblem
from tools.optimization.optimization_driver import OptimizationDriver

from hybrid.sites import make_irregular_site
from financial_calcs import hybrid_capacity_credit
from setup_config import import_config, setup_config


resource_dir = (Path(__file__).parent / "resource_files").absolute()
params_dir = (Path(__file__).parent / "parameter_files").absolute()

simulation_options = {
        'pv': {'skip_financial': True},
        'wind': {'skip_financial': True},
        'battery': {'skip_financial': True}
        }


# Setup Optimization Candidate
class HybridLayoutProblem(OptimizationProblem):
    """
    Optimize the layout of the wind and solar plant

    border_spacing: spacing along border = (1 + border_spacing) * min spacing (0, 100)
    border_offset: turbine border spacing offset as ratio of border spacing  (0, 1)
    grid_angle: turbine inner grid rotation (0, pi) [radians]
    grid_aspect_power: grid aspect ratio [cols / rows] = 2^grid_aspect_power
    row_phase_offset: inner grid phase offset (0,1)  (20% suggested)
    num_turbines_ratio_max: ratio of num turbines to max num turbines (0, 1)
    solar_x_position: ratio of solar's x coords to site width (0, 1)
    solar_y_position: ratio of solar's y coords to site height (0, 1)
    solar_aspect_power: aspect ratio of solar to site width = 2^solar_aspect_power
    solar_gcr: gcr ratio of solar patch
    solar_s_buffer: south side buffer ratio (0, 1)
    solar_x_buffer: east and west side buffer ratio (0, 1)
    solar_ratio_of_max_mw: ratio of solar to max solar MW (0, 1)
    battery_ratio_of_max_mw: ratio of battery to max battery MW (0, 1)
    """

    def __init__(self, site_info,
                 turb_size_kw, wind_config, pv_config,
                 cost_config, fin_config,
                 sim_config, dispatch_config,
                 dispatch_db_dir: Path=None) -> None:
        """

        site: site info
        turb_size_kw:
        wind_config:
        pv_config:
        cost_config:
        fin_config:
        sim_config:
        dispatch_config:

        """
        super().__init__()

        self.site = site_info
        self.cost_info = cost_config
        self.simulation_options = sim_config
        self.dispatch_options = dispatch_config
        self.turb_rating_kw = turb_size_kw
        self.pv_info = pv_config
        self.wind_info = wind_config
        self.fin_info = fin_config

        self.battery_max_mw = 300
        self.solar_max_mw = 300
        self.turbines_max = 62

        self.candidate_dict = OrderedDict({
            "border_spacing": {
                "type": float,
                "prior": {
                    "mu": 5, "sigma": 5
                },
                "min": 0, "max": 100
            },
            "border_offset": {
                "type": float,
                "prior": {
                    "mu": 0.5, "sigma": 2
                },
                "min": 0.0, "max": 1.0
            },
            "grid_angle": {
                "type": float,
                "prior": {
                    "mu": np.pi / 2, "sigma": np.pi
                },
                "min": 0.0, "max": np.pi
            },
            "grid_aspect_power": {
                "type": float,
                "prior": {
                    "mu": 0, "sigma": 3
                },
                "min": -4, "max": 4
            },
            "row_phase_offset": {
                "type": float,
                "prior": {
                    "mu": 0.5, "sigma": .5
                },
                "min": 0.0, "max": 1.0
            },
            "num_turbines_ratio_max": {
                "type": float,
                "prior": {
                    "mu": 0.5, "sigma": .5
                },
                "min": 0.0, "max": 1.0
            },
            # solar parameters
            "solar_x_position": {
                "type": float,
                "prior": {
                    "mu": .5, "sigma": .5
                },
                "min": 0.0, "max": 1.0
            },
            "solar_y_position": {
                "type": float,
                "prior": {
                    "mu": .5, "sigma": .5
                },
                "min": 0.0, "max": 1.0
            },
            "solar_aspect_power": {
                "type": float,
                "prior": {
                    "mu": 0, "sigma": 3
                },
                "min": -4, "max": 4
            },
            "solar_gcr": {
                "type": float,
                "prior": {
                    "mu": .5, "sigma": .5
                },
                "min": 0.1, "max": 0.9
            },
            "solar_s_buffer": {
                "type": float,
                "prior": {
                    "mu": 4, "sigma": 4
                },
                "min": 0.0, "max": 9.0
            },
            "solar_x_buffer": {
                "type": float,
                "prior": {
                    "mu": 4, "sigma": 4
                },
                "min": 0.0, "max": 9.0
            },
            "solar_ratio_of_max_mw": {
                "type": float,
                "prior": {
                    "mu": 0.5, "sigma": 0.2
                },
                "min": 0, "max": 1
            },
            "battery_ratio_of_max_mw": {
                "type": float,
                "prior": {
                    "mu": 0.5, "sigma": 0.2
                },
                "min": 0, "max": 1
            }
        })

        self.dispatch_db_dir = dispatch_db_dir
        if self.dispatch_db_dir is not None and not os.path.isdir(self.dispatch_db_dir):
            os.mkdir(self.dispatch_db_dir)

    def _set_simulation_to_candidate(self,
                                     candidate: np.ndarray,
                                     ) -> HybridSimulation:
        self.check_candidate(candidate) # scaling

        # assign layout
        wind_layout_ind = 0
        num_turbines = int(np.floor(candidate[wind_layout_ind + 5] * self.turbines_max))
        wind_layout = WindBoundaryGridParameters(border_spacing=candidate[wind_layout_ind],
                                                 border_offset=candidate[wind_layout_ind + 1],
                                                 grid_angle=candidate[wind_layout_ind + 2],
                                                 grid_aspect_power=candidate[wind_layout_ind + 3],
                                                 row_phase_offset=candidate[wind_layout_ind + 4])
        solar_layout_ind = 6
        num_modules = int(np.floor(candidate[solar_layout_ind + 6] * self.solar_max_mw * 1e3 / module_power))
        solar_size_mw = num_modules * module_power * 1e-3
        solar_layout = PVGridParameters(x_position=candidate[solar_layout_ind],
                                        y_position=candidate[solar_layout_ind + 1],
                                        aspect_power=candidate[solar_layout_ind + 2],
                                        gcr=candidate[solar_layout_ind + 3],
                                        s_buffer=candidate[solar_layout_ind + 4],
                                        x_buffer=candidate[solar_layout_ind + 5]
                                        )
        battery_mw = self.battery_max_mw * candidate[-1]
        if battery_mw < 1e-3:
            battery_mw = 0

        technologies = {'pv': {
            'system_capacity_kw': solar_size_mw * 1000,
            'layout_params': solar_layout},
            'wind': {
                'num_turbines': num_turbines,
                'turbine_rating_kw': self.turb_rating_kw,
                'layout_mode': 'boundarygrid',
                'layout_params': wind_layout},
            'battery': {
                'system_capacity_kwh': battery_mw * 4e3,
                'system_capacity_kw': battery_mw * 1e3}
        }
        wind_mw = num_turbines * self.turb_rating_kw * 1e-3
        hybrid_mw = solar_size_mw + battery_mw + wind_mw

        # Create model
        hybrid_plant = HybridSimulation(technologies, self.site, interconnect_kw=hybrid_mw * 1000,
                                        cost_info=self.cost_info, dispatch_options=self.dispatch_options,
                                        simulation_options=self.simulation_options)

        # setup up pv_watts module, array type and tilt
        hybrid_plant.assign({"pv": self.pv_info})

        # setup wind turbine parameters
        hybrid_plant.assign({"wind": self.wind_info['Turbine']})
        hybrid_plant.assign({"wind": self.wind_info['Losses']})

        hybrid_plant.wind.wake_model = 1  # [Simple, Park, EV, Constant] [0/1/2/3]

        # financial & depreciation parameters also invariant across sizes
        hybrid_plant.assign(self.fin_info["FinancialParameters"])
        hybrid_plant.assign(self.fin_info["TaxCreditIncentives"])
        hybrid_plant.assign(self.fin_info["Depreciation"])

        # setup capacity credit for wind and solar, hybrid will be set up within opt loop
        hybrid_plant.assign(self.fin_info["Revenue"])

        # O&M costs
        hybrid_plant.assign(self.fin_info["SystemCosts"])

        # assign capacity credit
        hybrid_plant.grid.capacity_credit_percent = hybrid_capacity_credit(wind_mw, solar_size_mw, battery_mw)
        # hybrid_plant.layout.plot()
        # import matplotlib.pyplot as plt
        # plt.show()

        # return penalty
        return hybrid_plant

    def objective(self,
                  candidate: np.ndarray
                  ) -> (float, float):
        candidate_conforming, penalty_conforming = self.conform_candidate_and_get_penalty(candidate)
        try:
            hybrid_plant = self._set_simulation_to_candidate(candidate_conforming)
            penalty_layout = hybrid_plant.layout.pv.excess_buffer
            hybrid_plant.simulate(35)
            evaluation = hybrid_plant.net_present_values.hybrid
            print(candidate, evaluation)
            score = evaluation - penalty_conforming - penalty_layout

            # hybrid_plant.layout.plot()
            # import matplotlib.pyplot as plt
            # plt.show()
        except Exception as e:
            print(f"candidate {candidate} error: {e}")
            score = evaluation = 0

        return score, evaluation, candidate_conforming


optimizer_config = {
    'method':               'CMA-ES',
    'nprocs':               12,
    'generation_size':      100,
    'selection_proportion': .33,
    'prior_scale':          1.0,
    # 'prior_params':         {
    #     "grid_angle": {
    #         "mu": 0.1
    #         }
    #     }
    }

if __name__ == "__main__":
    config_dict = {}
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r") as f:
            config_dict = json.load(f)
    if config_dict:
        out_dir = Path(sys.argv[1]).parent
    else:
        out_dir = Path(os.getcwd())

    # read inputs from JSON files
    pv_info, wind_info, fin_info, cost_info, turb_rating_kw = import_config(params_dir)

    # modify original inputs from a config JSON file
    fin_info, wind_info, dispatch_options, site = setup_config(config_dict, fin_info, wind_info, resource_dir)

    logger.info(f"{config_dict}")
    logger.info(f"energy_price_base: {fin_info['Revenue']['ppa_price_input']}")
    logger.info(f"pv_components: {pv_info}")
    logger.info(f"wind_components: {wind_info}")
    logger.info(f"revenue_components: {fin_info['Revenue']}")
    logger.info(f"financial: {fin_info['FinancialParameters']}")

    problem = HybridLayoutProblem(site, turb_size_kw=turb_rating_kw, pv_config=pv_info, wind_config=wind_info,
                                  cost_config=cost_info, fin_config=fin_info, dispatch_config=dispatch_options,
                                  sim_config=simulation_options
                                  )
    optimizer = OptimizationDriver(problem, recorder=DataRecorder.make_data_recorder(str(out_dir),
                                                                                     "results"),
                                   **optimizer_config)
    # test
    # candidate = np.array([13.442437254309148, 1.0, 1.7815201461041121, 2.4659729450958254, 0.5280016407689111,
    #                       0.5906494019207649, 0.3604529998936307, 0.47203467667476945, -1.7071199331389482, 0.9,
    #                       6.691525809267106, 3.1519852116340292, 0.6416508078943377, 0.0])
    # print(problem.objective(candidate))
    # exit()

    best_score, best_evaluation, best_solution = optimizer.central_solution()
    print(-1, ' ', best_score, best_evaluation)

    while optimizer.num_iterations() < 16:
        optimizer.step()
        best_score, best_evaluation, best_solution = optimizer.best_solution()
        central_score, central_evaluation, central_solution = optimizer.central_solution()
        print(optimizer.num_iterations(), ' ', optimizer.num_evaluations(), best_score, best_evaluation)

