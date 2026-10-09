"""Result of a variance run."""
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Result:
    lines: pd.DataFrame            # one row per budget line (+ one per unbudgeted actual category)
    totals: dict                   # overall / rollups, all money in cents
    txns: pd.DataFrame             # in-period actuals with the line_id each was assigned to
    as_of_date: object = None      # datetime.date
    period: dict = field(default_factory=dict)
    quality: list = field(default_factory=list)   # data-quality findings (variance.quality)
