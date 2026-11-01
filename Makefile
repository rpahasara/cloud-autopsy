# CA-SPIKE-001 offline prototype (Python 3.13 standard library only; no network).
PYTHON ?= python

.PHONY: demo test verify-fixtures clean-demo

demo:
	$(PYTHON) -I prototype/cli.py demo

test:
	$(PYTHON) -I -m unittest discover -s prototype/tests -t prototype -v

verify-fixtures:
	$(PYTHON) -I prototype/cli.py verify-fixtures

clean-demo:
	$(PYTHON) -I -c "import shutil; shutil.rmtree('prototype/out', ignore_errors=True)"
