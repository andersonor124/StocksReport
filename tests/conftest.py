import pickle
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


def pytest_configure(config):
    config.addinivalue_line("markers", "live: hits real network data sources")


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", help="run live network tests")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="needs --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


def _bundle(name):
    with open(FIX / f"{name}.pkl", "rb") as f:
        return pickle.load(f)


@pytest.fixture(scope="session")
def aapl():
    return _bundle("AAPL")


@pytest.fixture(scope="session")
def jpm():
    return _bundle("JPM")
