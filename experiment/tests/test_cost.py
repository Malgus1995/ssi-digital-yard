from unittest import TestCase

from experiment.cost import calculate_standard_cost_from_rows


class StandardCostTests(TestCase):
    def test_cost_breakdown_uses_shared_formula(self) -> None:
        assignments = [
            {
                "transport_score": "10",
                "handling_risk_score": "4",
                "first_fit_rank": "2",
            }
        ]
        utilization = [
            {
                "yard_code": "Y1",
                "used_area_m2": "800",
                "usable_area_m2": "1000",
            }
        ]

        result = calculate_standard_cost_from_rows(assignments, utilization)

        # Assignment: 10 + 4*0.35 + 2*0.20 = 11.8
        # Congestion: (300*2 + 100*6) / 1000 = 1.2
        # Peak: 0.8 * 6 = 4.8
        self.assertAlmostEqual(result["total_cost"], 17.8)
        self.assertAlmostEqual(result["breakdown"]["daily_utilization"], 1.2)
