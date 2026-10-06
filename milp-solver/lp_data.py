from data import (
    AssignmentOption,
    Block,
    CostWeights,
    ModelArtifacts,
    ModelConfig,
    Yard,
    occupied_dates,
)



@dataclass
class ModelArtifacts:
    """MIP-specific variables; intentionally excluded from common data.py."""
    assignment_vars: Dict[Tuple[str, str], pywraplp.Variable]
    option_by_key: Dict[Tuple[str, str], AssignmentOption]
    excess_area_vars: Dict[
        Tuple[str, date, float], Tuple[pywraplp.Variable, float]
    ]
    peak_utilization_vars: Dict[str, pywraplp.Variable]
    active_terms: Dict[
        Tuple[str, date], List[Tuple[pywraplp.Variable, float, str]]
    ]
