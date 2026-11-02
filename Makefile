# CA-SPIKE-001 offline prototype (Python 3.13 standard library only; no network).
PYTHON ?= python

.PHONY: demo test verify-fixtures clean-demo supply-chain contracts-test

# CA-P2-002a provisional contract tests (src/cloud_autopsy/contracts); not yet run in CI.
contracts-test:
	$(PYTHON) -I -m unittest discover -s tests/contracts -t tests/contracts

# CA-P2-001 offline supply-chain checks (inventory, licenses, pins, imports, secrets, SBOM drift).
supply-chain:
	$(PYTHON) -I -m unittest discover -s tools/supply_chain -t tools/supply_chain
	$(PYTHON) -I tools/supply_chain/supply_chain.py check

demo:
	$(PYTHON) -I prototype/cli.py demo

test:
	$(PYTHON) -I -m unittest discover -s prototype/tests -t prototype -v

verify-fixtures:
	$(PYTHON) -I prototype/cli.py verify-fixtures

clean-demo:
	$(PYTHON) -I -c "import shutil; shutil.rmtree('prototype/out', ignore_errors=True)"
