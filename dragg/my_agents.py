from dragg.agent import RLAgent

class HorizonAgent(RLAgent):
    def __init__(self, parameters, rl_log):
        RLAgent.__init__(self, parameters, rl_log)
        self.name = "horizon"

    def reward(self):
        return -1*(self.state['curr_error']**4)

    def calc_state(self, obs):
        """
        Provides metrics to evaluate and classify the state of the system.
        :return: dictionary
        """
        current_error = (obs.agg_load - obs.agg_setpoint) #/ self.agg_setpoint
        # derivative_action = obs.action - obs.prev_action
        change_rp = obs.reward_price[0] - obs.reward_price[-1]
        time_of_day = obs.timestep % (24 * obs.dt)
        forecast_error = obs.forecast_load[0] - obs.forecast_setpoint
        forecast_trend = obs.forecast_load[0] - obs.forecast_load[-1]

        state = {"curr_error":current_error,
        "time_of_day":time_of_day,
        "fcst_error":forecast_error,
        "forecast_trend": forecast_trend,
        "delta_action": change_rp}
        self.state = state
        return state

class NextTSAgent(RLAgent):
    def __init__(self, parameters, rl_log):
        RLAgent.__init__(parameters, rl_log)
        self.name = "next"

    def reward(self):
        -self.state['curr_error']**2

    def calc_state(self, obs):
        """
        Provides metrics to evaluate and classify the state of the system.
        :return: dictionary
        """
        current_error = (obs.agg_load - obs.agg_setpoint) #/ self.agg_setpoint
        derivative_action = obs.action - obs.prev_action
        change_rp = obs.reward_price[0] - obs.reward_price[-1]
        time_of_day = obs.timestep % (24 * obs.dt)
        forecast_error = obs.forecast_load[0] - obs.forecast_setpoint
        forecast_trend = obs.forecast_load[0] - obs.forecast_load[-1]

        state = {"curr_error":current_error,
        "time_of_day":time_of_day,
        "int_error":integral_error,
        "fcst_error":forecast_error,
        "forecast_trend": forecast_trend,
        "delta_action": change_rp}
        self.state = state
        return state
