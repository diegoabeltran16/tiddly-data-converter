#!/usr/bin/env bash
set -euo pipefail

cd /repositorios/tiddly-data-converter
python3 -m unittest tests.fixtures.s55.test_corpus_governance

