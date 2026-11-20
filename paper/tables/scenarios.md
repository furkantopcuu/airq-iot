| Scenario | Item | Metric | Expected | Reference | Measured | Verdict |
|---|---|---|---|---|---|---|
| ag_bozulmasi | net-degraded | delivery_ratio | less than | 0.95 | 0.88 | confirmed |
| ag_bozulmasi | net-degraded | latency_p95_ms | greater than | 250.00 | 318.00 | confirmed |
| bolgesel_artis | regional-ramp | warned | true |  | True | confirmed |
| cihaz_kopmasi | three-offline | min_n_neighbors | less than | 11.00 | 8.00 | confirmed |
| gercek_haze_replay | haze-replay | warned | true |  | True | confirmed |
| gercek_haze_replay | haze-replay | lead_time_h | greater than | 0.00 | 22.00 | confirmed |
| sensor_sicramasi | spike-edge-off | peak_forecast_h6 | greater than | 54.00 | 87.69 | confirmed |
| sensor_sicramasi | spike-edge-off | warned | true |  | True | confirmed |
| sensor_takilmasi | stuck-edge-off | mae_next_6h_h6 | greater than | 12.57 | 10.54 | refuted |
| yerel_artis | local-ramp | warned | true |  | True | confirmed |
| yerel_artis | neighbor-huairou | peak_forecast_h6 | less than | 101.91 | 39.03 | confirmed |
