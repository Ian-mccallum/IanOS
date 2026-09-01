"""Fidelity CSV import tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.import_fidelity import parse_positions


def test_parse_fidelity_csv(tmp_path):
    csv = tmp_path / "positions.csv"
    csv.write_text(
        "Symbol,Description,Quantity,Current Value,Cost Basis Total\n"
        "AAPL,Apple Inc,10,$2000.00,$1800.00\n"
    )
    positions = parse_positions(csv)
    assert len(positions) == 1
    assert positions[0]["symbol"] == "AAPL"
    assert positions[0]["market_value"] == 2000.0
