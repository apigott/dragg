import os
import sys
import json
import toml
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import itertools as it
import random

import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
# from kaleido.scopes.plotly import PlotlyScope
import plotly.io as pio

from dragg.logger import Logger
import dragg.aggregator as agg

class Reformat:
    def __init__(self, add_outputs={}, agg_params={}, mpc_params={}, date_ranges={}, include_runs={}, log=Logger("reformat")):
        self.ref_log = log
        self.data_dir = 'data'
        self.outputs_dir = set()
        if os.path.isdir('outputs'):
            self.outputs_dir = {'outputs'}
            for i in add_outputs:
                path = os.path.join('outputs', i)
                if os.path.isdir(path):
                    self.outputs_dir.add(path)
        if len(self.outputs_dir) == 0:
            self.ref_log.logger.error("No outputs directory found.")
            quit()
        self.config_file = os.path.join(self.data_dir, os.environ.get('CONFIG_FILE', 'config.toml'))
        self.config = self._import_config()

        self.include_runs = include_runs

        self.date_folders = self.set_date_folders(date_ranges)
        self.mpc_folders = self.set_mpc_folders(mpc_params)
        self.baselines = self.set_base_file()
        self.parametrics = []
        self.parametrics = self.set_parametric_files(agg_params)

        np.random.seed(self.config['simulation']['random_seed'])
        self.fig_list = None

    def main(self, add_outputs={}, agg_params={}, mpc_params={}, include_runs={}, date_ranges={}):
        # if len(self.parametrics) < 1:
        #     self.ref_log.logger.error("No parametric files found for comparison.")
        #     sys.exit(1)

        if self.config['simulation']['run_rl_agg']:
            figs = [self.rl2baseline(),
                    self.rl2baseline_error()]
            # self.rl_thetas()
            # self.rl_qvals()
            # self.plot_mu()

        else:
            figs = [self.rl_simplified(),
            # self.rl_thetas()
            # self.rl_qvals()
            self.plot_mu()]

        dir_name = os.path.join('outputs', 'images', datetime.now().strftime("%m%dT%H%M%S"))
        if not os.path.isdir(dir_name):
            os.makedirs(dir_name)
        for fig in figs:
            self.ref_log.logger.info(f"Saving images of outputs to timestamped folder at {dir_name}.")
            try:
                path = os.path.join(dir_name, f"{fig.layout.title.text}.png")
                pio.write_image(fig, path, width=1024, height=768)
            except:
                self.ref_log.logger.error("Could not save plotly image(s) to outputs directory.")

    def write_most_recent(self):
        return

    def add_date_ranges(self, additional_params):
        start_dates = [datetime.strptime(self.config['simulation']['start_datetime'], '%Y-%m-%d %H')]
        end_dates = set([datetime.strptime(self.config['simulation']['end_datetime'], '%Y-%m-%d %H')])
        temp = {"start_datetime": start_dates, "end_datetime": end_dates}
        for key in temp:
            if key in additional_params:
                temp[key].add(datetime.strptime(additional_params[key], '%Y-%m-%d %H'))
        self.date_ranges = temp

    def add_agg_params(self, additional_params):
        alphas = set(self.config['rl']['parameters']['learning_rate'])
        epsilons = set(self.config['rl']['parameters']['exploration_rate'])
        betas = set(self.config['rl']['parameters']['discount_factor'])
        batch_sizes = set(self.config['rl']['parameters']['batch_size'])
        rl_horizons = set(self.config['rl']['utility']['rl_agg_action_horizon'])
        mpc_disutil = set(self.config['home']['hems']['disutility'])
        mpc_discomf = set(self.config['home']['hems']['discomfort'])
        temp = {"alpha": alphas, "epsilon": epsilons, "beta": betas, "batch_size": batch_sizes, "rl_horizon": rl_horizons, "mpc_disutility": mpc_disutil, "mpc_discomfort": mpc_discomf}
        for key in temp:
            if key in additional_params:
                temp[key] |= set(additional_params[key])
        self.agg_params = temp

    def add_mpc_params(self, additional_params):
        n_houses = self.config['community']['total_number_homes']
        mpc_horizon = self.config['home']['hems']['prediction_horizon']
        dt = self.config['rl']['utility']['hourly_steps']
        check_type = self.config['simulation']['check_type']
        mpc_discomf = set(self.config['home']['hems']['discomfort'])
        temp = {"n_houses": set([n_houses]), "mpc_prediction_horizons": set(mpc_horizon), "mpc_hourly_steps": set([dt]), "check_type": set([check_type]), "mpc_discomfort": mpc_discomf}
        for key in temp:
            if key in additional_params:
                temp[key] |= set(additional_params[key])
        self.mpc_params = temp

    def set_date_folders(self, additional_params):
        self.add_date_ranges(additional_params)
        temp = []
        keys, values = zip(*self.date_ranges.items())
        permutations = [dict(zip(keys, v)) for v in it.product(*values)]
        permutations = sorted(permutations, key=lambda i: i['end_datetime'], reverse=True)
        for j in self.outputs_dir:
            for i in permutations:
                date_folder = os.path.join(j, f"{i['start_datetime'].strftime('%Y-%m-%dT%H')}_{i['end_datetime'].strftime('%Y-%m-%dT%H')}")
                if os.path.isdir(date_folder):
                    hours = i['end_datetime'] - i['start_datetime']
                    hours = int(hours.total_seconds() / 3600)
                    new_folder = {"folder": date_folder, "hours": hours, "start_dt": i['start_datetime'], "name": j+" "}
                    temp.append(new_folder)
        if len(temp) == 0:
            self.ref_log.logger.error("No files found for the date ranges specified.")
            exit()
        return temp

    def set_mpc_folders(self, additional_params):
        self.add_mpc_params(additional_params)
        temp = []
        keys, values = zip(*self.mpc_params.items())
        permutations = [dict(zip(keys, v)) for v in it.product(*values)]
        for j in self.date_folders:
            for i in permutations:
                interval_minutes = 60 // i['mpc_hourly_steps']
                mpc_folder = os.path.join(j["folder"], f"{i['check_type']}-homes_{i['n_houses']}-horizon_{i['mpc_prediction_horizons']}-interval_{interval_minutes}")
                if os.path.isdir(mpc_folder):
                    timesteps = j['hours']*i['mpc_hourly_steps']
                    x_lims = [j['start_dt'] + timedelta(minutes=x*interval_minutes) for x in range(timesteps + max(self.config['rl']['utility']['rl_agg_action_horizon'])*i['mpc_hourly_steps'])]
                    name = j['name']
                    set = {'path': mpc_folder, 'dt': i['mpc_hourly_steps'], 'ts': timesteps, 'x_lims': x_lims, 'name': name}
                    if not mpc_folder in temp:
                        temp.append(set)
        return temp

    def set_base_file(self):
        temp = []
        keys, values = zip(*self.mpc_params.items())
        permutations = [dict(zip(keys, v)) for v in it.product(*values)]
        for j in self.mpc_folders:
            path = j['path']
            print(path)
            for i in permutations:
                file = os.path.join(path, "baseline", f"baseline_discomf-{float(i['mpc_discomfort'])}-results.json")
                self.ref_log.logger.debug(f"Looking for baseline file at {file}")
                if os.path.isfile(file):
                    name = f"Baseline - {j['name']}"
                    set = {"results": file, "name": name, "parent": j}
                    temp.append(set)
                    self.ref_log.logger.info(f"Adding baseline file at {file}")
        return temp

    def set_rl_files(self, additional_params):
        temp = []
        self.add_agg_params(additional_params)
        counter = 1
        for i in self.mpc_folders:
            path = i['path']
            rl_agg_folder = os.path.join(path, "rl_agg")
            all_params = {**self.agg_params, **self.mpc_params}
            keys, values = zip(*all_params.items())
            permutations = [dict(zip(keys, v)) for v in it.product(*values)]
            for j in permutations:
                if os.path.isdir(rl_agg_folder):
                    rl_agg_path = f"agg_horizon_{j['rl_horizon']}-alpha_{j['alpha']}-epsilon_{j['epsilon']}-beta_{j['beta']}_batch-{j['batch_size']}_disutil-{float(j['mpc_disutility'])}_discomf-{float(j['mpc_discomfort'])}"
                    rl_agg_file = os.path.join(rl_agg_folder, rl_agg_path, "results.json")
                    self.ref_log.logger.debug(f"Looking for a RL aggregator file at {rl_agg_file}")
                    if os.path.isfile(rl_agg_file):
                        q_results = os.path.join(rl_agg_path, "q-results.json")
                        q_file = os.path.join(rl_agg_folder, q_results)
                        # name = i['name']
                        name = ""
                        for k,v in j.items():
                            if len(all_params[k]) > 1:
                                name += f"{k} = {v}, "
                        # name =  f"horizon={j['rl_horizon']}, alpha={j['alpha']}, beta={j['beta']}, epsilon={j['epsilon']}, batch={j['batch_size']}, disutil={j['mpc_disutility']}, discomf={j['mpc_discomfort']}"
                        set = {"results": rl_agg_file, "q_results": q_file, "name": name, "parent": i, "rl_agg_action_horizon": j["rl_horizon"]}
                        temp.append(set)
                        self.ref_log.logger.info(f"Adding an RL aggregator agent file at {rl_agg_file}")

        if len(temp) == 0:
            self.ref_log.logger.warning("Parameterized RL aggregator runs are empty for this config file.")
        return temp

    def set_simplified_files(self, additional_params):
        temp = []
        self.add_agg_params(additional_params)
        for i in self.mpc_folders:
            path = i['path']
            simplified_folder = os.path.join(path, "simplified")
            all_params = {**self.agg_params, **self.mpc_params}
            keys, values = zip(*all_params.items())
            permutations = [dict(zip(keys, v)) for v in it.product(*values)]
            for j in permutations:
                if os.path.isdir(simplified_folder):
                    simplified_path = f"agg_horizon_{j['rl_horizon']}-alpha_{j['alpha']}-epsilon_{j['epsilon']}-beta_{j['beta']}_batch-{j['batch_size']}_disutil-{float(j['mpc_disutility'])}_discomf-{float(j['mpc_discomfort'])}"
                    simplified_file = os.path.join(simplified_folder, simplified_path, "results.json")
                    if os.path.isfile(simplified_file):
                        q_file = os.path.join(simplified_folder, simplified_path, "horizon_agent-results.json")
                        if os.path.isfile(q_file):
                            # name = i['name']
                            name = ""
                            for k,v in j.items():
                                if len(all_params[k]) > 1:
                                    name += f"{k} = {v}, "
                            set = {"results": simplified_file, "q_results": q_file, "name": name, "parent": i}
                            temp.append(set)
        return temp

    def set_parametric_files(self, additional_params):
        if self.config['simulation']['run_rl_agg'] or "rl_agg" in self.include_runs:
            self.parametrics += self.set_rl_files(additional_params)
        if self.config['simulation']['run_rl_simplified'] or "simplified" in self.include_runs:
            self.parametrics += self.set_simplified_files(additional_params)
        return self.parametrics

    def set_other_files(self, otherfile):
        self.parametrics.append(otherfile)

    def _type_list(self, type):
        type_list = set([])
        i = 0
        for file in (self.baselines + self.parametrics):
            with open(file["results"]) as f:
                data = json.load(f)

            temp = set([])
            for name, house in data.items():
                try:
                    if house["type"] == type:
                        temp.add(name)
                except:
                    pass

            if i < 1:
                type_list = temp
            else:
                type_list = type_list.intersection(temp)

        return type_list

    def _import_config(self):
        if not os.path.exists(self.config_file):
            self.ref_log.logger.error(f"Configuration file does not exist: {self.config_file}")
            sys.exit(1)
        with open(self.config_file, 'r') as f:
            data = toml.load(f)
        return data

    def plot_environmental_values(self, fig, summary, file):
        fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=summary["OAT"][0:file["parent"]["ts"]], name=f"OAT (C)"))
        fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=summary["GHI"][0:file["parent"]["ts"]], name=f"GHI (W/m2)"))
        fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=summary["TOU"][0:file["parent"]["ts"]], name=f"TOU Price ($/kWh)", line_shape='hv'), secondary_y=True)
        return fig

    def plot_base_home(self, name, fig, data, summary, fname, file):
        fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["temp_in_opt"], name=f"Tin (C) - {fname}"))
        fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["temp_wh_opt"], name=f"Twh (C) - {fname}"))
        fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["temp_in_sp"] * np.ones(file["parent"]["ts"]), name=f"Tin_sp (C) - {fname}"))
        fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["temp_wh_sp"] * np.ones(file["parent"]["ts"]), name=f"Twh_sp (C) - {fname}"))
        fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["p_grid_opt"], name=f"Pgrid (kW) - {fname}", line_shape='hv'))
        fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["p_load_opt"], name=f"Pload (kW) - {fname}", line_shape='hv'))
        fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["hvac_cool_on_opt"], name=f"HVAC Cool Cmd - {fname}", line_shape='hv'), secondary_y=True)
        fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["hvac_heat_on_opt"], name=f"HVAC Heat Cmd - {fname}", line_shape='hv'), secondary_y=True)
        fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["wh_heat_on_opt"], name=f"WH Heat Cmd - {fname}", line_shape='hv'), secondary_y=True)
        try: # only for aggregator files
            fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=np.add(summary["TOU"], summary["RP"]), name=f"Actual Price ($/kWh) - {fname}", line_shape='hv'), secondary_y=True)
        except:
            pass
        return fig

    def plot_pv(self, name, fig, data, fname, file):
        fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["p_pv_opt"], name=f"Ppv (kW) - {fname}", line_shape='hv'))
        return fig

    def plot_battery(self, name, fig, data, fname, file):
        fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["e_batt_opt"], name=f"SOC (kW) - {fname}", line_shape='hv'))
        fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["p_batt_ch"], name=f"Pch (kW) - {fname}", line_shape='hv'))
        fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["p_batt_disch"], name=f"Pdis (kW) - {fname}", line_shape='hv'))
        return fig

    def plot_single_home(self, name=None, type=None):
        if name is None:
            if type is None:
                type = "base"
                self.ref_log.logger.warning("Specify a home type or name. Proceeding with home of type: \"base\".")

            type_list = self._type_list(type)
            name = random.sample(type_list,1)[0]
            self.ref_log.logger.info(f"Proceeding with home: {name}")

        fig = make_subplots(specs=[[{"secondary_y": True}]])
        flag = False
        for file in (self.baselines + self.parametrics):
            with open(file["results"]) as f:
                comm_data = json.load(f)

            try:
                data = comm_data[name]
            except:
                self.ref_log.logger.error(f"No home with name: {name}")
                return

            type = data["type"]
            summary = comm_data["Summary"]
            horizon = summary["horizon"]

            if not flag:
                fig = self.plot_environmental_values(fig, summary, file)
                flag = True

            fig = self.plot_base_home(name, fig, data, summary, file["name"], file)

            case = summary["case"]
            fig.update_xaxes(title_text="Time of Day (hour)")
            fig.update_layout(title_text=f"{name} - {type} type")

            if 'pv' in type:
                fig = self.plot_pv(name, fig, data, file["name"], file)

            if 'battery' in type:
                fig = self.plot_battery(name, fig, data, file["name"], file)

        fig.show()
        return fig

    def plot_all_homes(self):
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        for file in (self.baselines + self.parametrics):
            with open(file["results"]) as f:
                data = json.load(f)

            fname = file["name"]
            for name, house in data.items():
                if name != "Summary":
                    fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=house["temp_in_opt"], name=f"Tin (C) - {name} - {fname}"))
                    fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=house["temp_wh_opt"], name=f"Twh (C) - {name} - {fname}"))
                    fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=house["p_grid_opt"], name=f"Pgrid (kW) - {name} - {fname}", line_shape='hv', visible='legendonly'))
                    fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=house["p_load_opt"], name=f"Pload (kW) - {name} - {fname}", line_shape='hv', visible='legendonly'))
                    fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=house["hvac_cool_on_opt"], name=f"HVAC Cool Cmd - {name} - {fname}", line_shape='hv', visible='legendonly'), secondary_y=True)
                    fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=house["hvac_heat_on_opt"], name=f"HVAC Heat Cmd - {name} - {fname}", line_shape='hv', visible='legendonly'), secondary_y=True)
                    fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=house["wh_heat_on_opt"], name=f"WH Heat Cmd - {name} - {fname}", line_shape='hv', visible='legendonly'), secondary_y=True)

        fig.show()
        return fig

    def rl_simplified(self):
        flag = False
        fig1 = make_subplots()
        fig2 = make_subplots()
        for file in self.parametrics:
            with open(file['results']) as f:
                data = json.load(f)
            if flag == False:
                fig1.add_trace(go.Scatter(x=file['parent']['x_lims'], y=data["Summary"]["p_grid_setpoint"][1:], name=f"Aggregate Load Setpoint"))
                setpoint = np.array(data["Summary"]["p_grid_setpoint"])
                flag = True
            fig1.add_trace(go.Scatter(x=file['parent']['x_lims'], y=data["Summary"]["p_grid_aggregate"][1:], name=f"Aggregate Load - {file['name']}"))
            agg = np.array(data["Summary"]["p_grid_aggregate"][1:])
            error = np.subtract(agg, 50*np.ones(len(agg)))
            # fig1.add_trace(go.Scatter(x=file['parent']['x_lims'], y=np.cumsum(np.square(error)), name=f"L2 Norm Error {file['name']}"))
            fig1.add_trace(go.Scatter(x=file['parent']['x_lims'], y=np.cumsum(abs(error)), name=f"Cummulative Error - {file['name']}"))
            fig1.add_trace(go.Scatter(x=file['parent']['x_lims'], y=abs(error), name=f"Abs Error - {file['name']}"))

            fig1.update_layout(title_text="Aggregate Load")
            fig2.add_trace(go.Scatter(x=file['parent']['x_lims'], y=data["Summary"]["RP"], name=f"Reward Price Signal - {file['name']}"))
            fig2.add_trace(go.Scatter(x=file['parent']['x_lims'], y=np.divide(np.cumsum(data["Summary"]["RP"]), np.arange(file['parent']['ts']) + 1), name=f"Rolling Average Reward Price - {file['name']}"))
            fig2.update_layout(title_text="Reward Price Signal")
        fig1.show()
        fig2.show()

        return fig1, fig2

    def plot_mu(self):
        fig = make_subplots()
        for file in self.parametrics:

            with open(file['results']) as f:
                data = json.load(f)

            fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["Summary"]["RP"][16:], name=f"RP (Selected Action)", line_shape='hv'))
            fig.add_trace(go.Scatter(x=file['parent']['x_lims'], y=np.divide(np.cumsum(data["Summary"]["RP"]), np.arange(file['parent']['ts']) + 1), name=f"Rolling Average Reward Price - {file['name']}"))

            with open(file['q_results']) as f:
                data = json.load(f)
            data = data["horizon"]
            fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=np.multiply(self.config['rl']['utility']['action_scale'],data["mu"]), name=f"Mu (Assumed Best Action)"))
        fig.update_layout(yaxis = {'exponentformat':'e'})
        fig.update_layout(title_text = "Reward Price Signal")
        fig.show()
        return fig

    def plot_baseline(self, fig):
        for file in self.baselines:
            with open(file["results"]) as f:
                data = json.load(f)

            fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["Summary"]["p_grid_aggregate"], name=f"Agg Load - {file['name']}", visible='legendonly'))
            fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=np.cumsum(data["Summary"]["p_grid_aggregate"]), name=f"Cumulative Agg Load - {file['name']}", visible='legendonly'))
            fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=np.divide(np.cumsum(data["Summary"]["p_grid_aggregate"]), np.arange(file['parent']['ts']) + 1), name=f"Cumulative Agg Load - {file['name']}", visible='legendonly'))
        return fig

    def plot_parametric(self, fig):
        if self.parametrics[0]:
            file = self.parametrics[0]
            with open(file["results"]) as f:
                rldata = json.load(f)

            fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=rldata["Summary"]["p_grid_setpoint"], name="RL Setpoint Load"))

        for file in self.parametrics:
            with open(file["results"]) as f:
                data = json.load(f)

            name = file["name"]
            fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["Summary"]["p_grid_aggregate"][1:], name=f"Agg Load - RL - {name}"))
            fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=np.cumsum(data["Summary"]["p_grid_aggregate"][1:]), name=f"Cumulative Agg Load - RL - {name}", visible='legendonly'))
            fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=np.divide(np.cumsum(data["Summary"]["p_grid_aggregate"][1:file["parent"]["ts"]+1]),np.arange(file["parent"]["ts"])+1), name=f"Avg Load - RL - {name}", visible='legendonly'))
            fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["Summary"]["RP"], name=f"RP - RL - {name}", line_shape='hv'), secondary_y=True)
            fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=np.divide(np.cumsum(data["Summary"]["RP"])[:file["parent"]["ts"]], np.arange(file["parent"]["ts"]) + 1), name=f"Average RP", visible='legendonly'), secondary_y=True)
            self.plot_mu()

        return fig

    def plot_baseline_error(self, fig):
        if self.parametrics[0]:
            max_file = self.parametrics[np.argmax([file['parent']['ts'] for file in self.parametrics])]
            max_ts = max_file['parent']['ts']
            max_x_lims = max_file['parent']['x_lims']

            with open(max_file["results"]) as f:
                rldata = json.load(f)

            fig.add_trace(go.Scatter(x=max_x_lims, y=rldata["Summary"]["p_grid_setpoint"], name="RL Setpoint Load"))

        for file in self.baselines:
            with open(file["results"]) as f:
                data = json.load(f)

            scale = max(max_ts // file['parent']['ts'], 1)
            baseline_load = np.repeat(data["Summary"]["p_grid_aggregate"], scale)
            scale = max(file['parent']['ts'] // max_ts, 1)
            baseline_setpoint = np.repeat(rldata["Summary"]["p_grid_setpoint"], scale)
            baseline_error = np.subtract(baseline_load, baseline_setpoint[:len(baseline_load)])
            fig.add_trace(go.Scatter(x=max_x_lims, y=(baseline_error), name=f"Error - {file['name']}", line_shape='hv', visible='legendonly'))
            fig.add_trace(go.Scatter(x=max_x_lims, y=abs(baseline_error), name=f"Abs Error - {file['name']}", line_shape='hv', visible='legendonly'))
            fig.add_trace(go.Scatter(x=max_x_lims, y=np.cumsum(np.abs(baseline_error)), name=f"Abs Cummulative Error - {file['name']}", line_shape='hv'))
            fig.add_trace(go.Scatter(x=max_x_lims, y=np.cumsum(baseline_error), name=f"Cummulative Error - {file['name']}", line_shape='hv', visible='legendonly'))
            fig.add_trace(go.Scatter(x=max_x_lims, y=np.divide(np.cumsum(baseline_error)[:file["parent"]["ts"]],np.arange(file["parent"]["ts"]) + 1), name=f"Average Error - {file['name']}", line_shape='hv', visible='legendonly'))
            fig.add_trace(go.Scatter(x=max_x_lims, y=np.cumsum(np.square(baseline_error)), name=f"L2 Norm Cummulative Error - {file['name']}", line_shape='hv'))

        return fig

    def plot_parametric_error(self, fig):
        max_file = self.parametrics[np.argmax([file['parent']['ts'] for file in self.parametrics])]
        max_ts = max_file['parent']['ts']
        max_x_lims = max_file['parent']['x_lims']
        for file in self.parametrics:
            with open(file["results"]) as f:
                data = json.load(f)

            name = file["name"]
            rl_load = data["Summary"]["p_grid_aggregate"][1:]
            rl_setpoint = data["Summary"]["p_grid_setpoint"]
            scale = max_ts // file['parent']['ts']
            # scale = 1
            rl_load = np.repeat(rl_load, scale)
            rl_setpoint = np.repeat(rl_setpoint, scale)
            rl_error = np.subtract(rl_load, rl_setpoint)
            fig.add_trace(go.Scatter(x=max_x_lims, y=(rl_error), name=f"Error - {name}", line_shape='hv', visible='legendonly'))
            fig.add_trace(go.Scatter(x=max_x_lims, y=abs(rl_error), name=f"Abs Error - {name}", line_shape='hv', visible='legendonly'))
            fig.add_trace(go.Scatter(x=max_x_lims, y=np.cumsum(np.abs(rl_error)), name=f"Cummulative Abs Error - {name}", line_shape='hv'))
            fig.add_trace(go.Scatter(x=max_x_lims, y=np.cumsum(rl_error), name=f"Cummulative Error - {name}", line_shape='hv', visible='legendonly'))
            fig.add_trace(go.Scatter(x=max_x_lims, y=np.divide(np.cumsum(rl_error),np.arange(len(rl_error))+1), name=f"Average Error - {name}", line_shape='hv', visible='legendonly'))
            fig.add_trace(go.Scatter(x=max_x_lims, y=np.cumsum(np.square(rl_error)), name=f"L2 Norm Cummulative Error - {name}", line_shape='hv'))

        return fig

    def plot_rewards(self, fig):
        for file in self.parametrics:
            with open(file["q_results"]) as f:
                data = json.load(f)

            data = data["horizon"]
            name = file["name"]
            fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["average_reward"], name=f"Average Reward - {name}", line_shape='hv', visible='legendonly'))
            fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["cumulative_reward"], name=f"Cumulative Reward - {name}", line_shape='hv', visible='legendonly'))
            fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["reward"], name=f"Reward - {name}", line_shape='hv'), secondary_y=True)

        return fig

    def just_the_baseline(self):
        if len(self.baselines) == 0:
            self.ref_log.logger.error("No baseline run files found for analysis.")
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig = self.plot_baseline(fig)
        fig.update_layout(title_text="Baseline Summary")
        fig.show()
        return fig

    def rl2baseline(self):
        if len(self.parametrics) == 0:
            self.ref_log.logger.warning("No parameterized RL aggregator runs found for comparison to baseline.")
            fig = self.just_the_baseline()
            return fig

        fig = make_subplots(specs=[[{"secondary_y": True}]])

        # fig = self.plot_greedy(fig)
        fig = self.plot_baseline(fig)
        fig = self.plot_parametric(fig)
        fig.update_layout(title_text="RL Baseline Comparison")

        fig.show()
        return fig

    def rl2baseline_error(self):
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        fig = self.plot_baseline_error(fig)
        fig = self.plot_parametric_error(fig)
        fig = self.plot_rewards(fig)
        fig.update_layout(title_text="RL Baseline Error Metrics")

        fig.show()
        return fig

    def q_values(self, rl_q_file):
        with open(rl_q_file) as f:
            data = json.load(f)

        x1 = []
        x2 = []
        for i in data["state"]:
            if i[0] < 0:
                x1.append(i[0])
            else:
                x2.append(i[0])
        fig = make_subplots()
        fig.add_trace(go.Scatter3d(x=x1, y=data["action"], z=data["q_obs"], mode="markers"))
        fig.add_trace(go.Scatter3d(x=x2, y=data["action"], z=data["q_obs"], mode="markers"))
        fig.show()
        return fig

    def rl_qvals(self):
        fig = make_subplots()
        for file in self.parametrics:
            with open(file["q_results"]) as f:
                data = json.load(f)


            fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["q_pred"], name=f"Q predicted - {file['name']}", marker={'opacity':0.2}))
            fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=data["q_obs"], name=f"Q observed - {file['name']}"))

        fig.update_layout(title_text="Critic Network")
        fig.show()
        return fig

    def rl_thetas(self):
        fig = make_subplots()
        counter = 1
        for file in self.parametrics:
            with open(file["q_results"]) as f:
                data = json.load(f)

            data = data["horizon"]
            theta = data["theta"]
            # phi = data["phi"]

            # x = np.arange(self.hours)
            for i in range(len(data["theta"][0])):
                y = []
                # z = []
                for j in range(file['parent']['ts']):
                    y.append(theta[j][i])
                    # z.append(phi[j][i])
                fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=y, name=f"Theta_{i}", line_shape='hv', legendgroup=file['name']))
                # fig.add_trace(go.Scatter(x=file["parent"]["x_lims"], y=z, name=f"Phi_{i} - {file['name']}", line_shape='hv'),2,counter)
            counter += 1
        fig.update_layout(title_text="Critic Network Coefficients")
        fig.show()

        return fig

    def all_rps(self):
        fig = make_subplots()
        for file in self.parametrics:
            with open(file['results']) as f:
                data = json.load(f)

            fig.add_trace(go.Histogram(x=data['Summary']['RP'], name=f"{file['name']}"))

        fig.show()
        return fig

if __name__ == "__main__":
    r = Reformat()
    r.main()
