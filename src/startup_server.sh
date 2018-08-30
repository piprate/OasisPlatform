#!/bin/bash
set -e

chmod a+w /var/www/oasis/upload
chmod a+w /var/www/oasis/download
#chown -R www-data:www-data /var/www/oasis/upload
#chown -R www-data:www-data /var/www/oasis/download

# Set python path to search startup script dir
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
export PYTHONPATH=$SCRIPT_DIR

# Set the ini file path 
export OASIS_API_INI_PATH="${SCRIPT_DIR}/conf.ini"

# apachectl -k start -DFOREGROUND
apachectl start
