.PHONY: setup test eval run docker-build docker-run all
PY ?= .venv/bin/python

setup:
	python3 -m venv .venv && $(PY) -m pip install -q -r requirements-dev.txt

test:
	$(PY) -m pytest -q

eval:
	$(PY) -m evals.run_eval

run:
	$(PY) -m uvicorn src.app:app --reload

docker-build:
	docker build -t extraction-api-structured .

docker-run:
	docker run --rm -p 8000:8000 extraction-api-structured

all: test eval
