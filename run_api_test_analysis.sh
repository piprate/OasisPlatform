#!/bin/bash
oasislmf test model-api http://oasis_api_server -a tests/integration/analysis_settings.json -i tests/integration/input/csv -o tests/integration/output
