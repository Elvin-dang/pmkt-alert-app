import pytest

from factory import make_all


@pytest.fixture(scope="session")
def synthetic_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("synthetic")
    make_all(d)
    return d


@pytest.fixture(scope="session")
def synthetic_paths(synthetic_dir):
    return sorted(synthetic_dir.glob("*.xlsx"))


@pytest.fixture(scope="session")
def loaded(synthetic_dir):
    from pmkt_alert.loaders import detect_inputs, load_inputs
    return load_inputs(detect_inputs([synthetic_dir]))


@pytest.fixture(scope="session")
def logic(synthetic_dir):
    from pmkt_alert.logic import load_logic
    return load_logic(synthetic_dir / "Alert_Logic_Ver 1.xlsx")
