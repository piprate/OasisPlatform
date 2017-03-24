import inspect
import logging
import fasteners
import json
import os
import shutil
import tarfile
import sys
import supplier_model_runner
from celery import Celery
from celery.task import task
from ConfigParser import ConfigParser

'''
Celery task wrapper for Oasis ktools calculation.
'''

CONFIG_PARSER = ConfigParser()
CURRENT_DIRECTORY = \
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
sys.path.append(os.path.join(CURRENT_DIRECTORY, ".."))
INI_PATH = os.path.abspath(os.path.join(CURRENT_DIRECTORY, 'Tasks.ini'))
CONFIG_PARSER.read(INI_PATH)

from oasis_utils import oasis_utils, oasis_log_utils

INPUTS_DATA_DIRECTORY = CONFIG_PARSER.get('Default', 'INPUTS_DATA_DIRECTORY')
OUTPUTS_DATA_DIRECTORY = CONFIG_PARSER.get('Default', 'OUTPUTS_DATA_DIRECTORY')
MODEL_DATA_DIRECTORY = CONFIG_PARSER.get('Default', 'MODEL_DATA_DIRECTORY')
WORKING_DIRECTORY = CONFIG_PARSER.get('Default', 'WORKING_DIRECTORY')

KTOOLS_BATCH_COUNT = int(os.environ.get("KTOOLS_BATCH_COUNT") or -1)
IS_WINDOWS_HOST = bool(os.environ.get("IS_WINDOWS_HOST") or False)
MODEL_SUPPLIER_ID = os.environ.get("MODEL_SUPPLIER_ID")
MODEL_VERSION_ID = os.environ.get("MODEL_VERSION_ID")
LOCK_FILE = os.environ.get("LOCK_FILE") or '/tmp/tmp_lock_file'
LOCK_TIMEOUT_IN_SECS = os.environ.get("LOCK_TIMEOUT_IN_SECS") or 30 * 60

ARCHIVE_FILE_SUFFIX = '.tar'

CELERY = Celery()
CELERY.config_from_object('common.CeleryConfig')

logging.info("Started worker")
logging.info("INPUTS_DATA_DIRECTORY: {}".format(INPUTS_DATA_DIRECTORY))
logging.info("OUTPUTS_DATA_DIRECTORY: {}".format(OUTPUTS_DATA_DIRECTORY))
logging.info("MODEL_DATA_DIRECTORY: {}".format(MODEL_DATA_DIRECTORY))
logging.info("WORKING_DIRECTORY: {}".format(WORKING_DIRECTORY))
logging.info("KTOOLS_BATCH_COUNT: {}".format(KTOOLS_BATCH_COUNT))

@task(name='run_analysis', bind=True)
def start_analysis_task(self, input_location, analysis_settings_json):
    '''
    Task wrapper for running an analysis.
    Args:
        analysis_profile_json (string): The analysis settings.
    Returns:
        (string) The location of the outputs.
    '''

    a_lock = fasteners.InterProcessLock(LOCK_FILE)
    gotten = a_lock.acquire(blocking=False, timeout=LOCK_TIMEOUT_IN_SECS)
    if not gotten:
        logging.info("Failed to get resource lock - retry task")
        retry_countdown_in_secs=10
        raise self.retry(countdown=retry_countdown_in_secs)
    logging.info("Acquired resource lock")

    try:
        logging.info("INPUTS_DATA_DIRECTORY: {}".format(INPUTS_DATA_DIRECTORY))
        logging.info("OUTPUTS_DATA_DIRECTORY: {}".format(OUTPUTS_DATA_DIRECTORY))
        logging.info("MODEL_DATA_DIRECTORY: {}".format(MODEL_DATA_DIRECTORY))
        logging.info("WORKING_DIRECTORY: {}".format(WORKING_DIRECTORY))
        logging.info("KTOOLS_BATCH_COUNT: {}".format(KTOOLS_BATCH_COUNT))

        self.update_state(state=oasis_utils.STATUS_RUNNING)
        output_location = start_analysis(
            analysis_settings_json[0],
            input_location)
    except Exception as exc:
        logging.exception("Model execution task failed.")
        raise exc

    return output_location

def get_current_module_directory():
    ''' Get the directory of the current module.'''
    return os.path.dirname(
        os.path.abspath(inspect.getfile(inspect.currentframe())))

def format_setting_for_file(setting):
    ''' Format a setting for selecting a data file '''
    return setting.replace(' ', '_').lower()

@oasis_log_utils.oasis_log()
def start_analysis(analysis_settings, input_location):
    '''
    Run an analysis.
    Args:
        analysis_profile_json (string): The analysis settings.
    Returns:
        (string) The location of the outputs.
    '''
    os.chdir(WORKING_DIRECTORY)

    #
    # Set up the following directory structure:
    # - WORKING_DIRECTORY
    # |-Analysis working directory
    #   |-static  (soft-link to model files)
    #   |-input   (upload repository)
    #   |-output  (model results will be written into
    #   |          this folder then archived to the
    #   |          download directory)
    #   |-fifo (scratch directory for named pipes)
    #   |-work (scratch directory for intermediate files)
    #

    # Check that the input archive exists and is valid
    input_archive = os.path.join(
        INPUTS_DATA_DIRECTORY,
        input_location + ARCHIVE_FILE_SUFFIX)
    if not os.path.exists(input_archive):
        raise Exception("Inputs location not found: {}".format(input_archive))
    if not tarfile.is_tarfile(input_archive):
        raise Exception(
            "Inputs location not a tarfile: {}".format(input_archive))

    source_tag = \
        analysis_settings['analysis_settings']['source_tag']
    analysis_tag = \
        analysis_settings['analysis_settings']['analysis_tag']
    logging.info(
        "Source tag = {}; Analysis tag: {}".format(
            analysis_tag, source_tag))

    MODULE_SUPPLIER_ID = \
        analysis_settings['analysis_settings']['module_supplier_id']
    MODEL_VERSION_ID = \
        analysis_settings['analysis_settings']['model_version_id']
    logging.info(
        "Model supplier - version = {} {}".format(
            MODULE_SUPPLIER_ID, MODEL_VERSION_ID))

    # Get the supplier module and call it
    use_default_model_runner = True
    if os.path.exists(os.path.join(
            get_current_module_directory(),
            MODULE_SUPPLIER_ID)):
        use_default_model_runner = False
    model_data_path = \
        os.path.join(MODEL_DATA_DIRECTORY,
                     MODULE_SUPPLIER_ID,
                     MODEL_VERSION_ID)
    if not os.path.exists(model_data_path):
        raise Exception("Model data not found: {}".format(model_data_path))

    logging.info("Setting up analysis working directory")

    directory_name = "{}_{}_{}".format(
        source_tag, analysis_tag, oasis_utils.generate_unique_filename())
    working_directory = \
        os.path.join(WORKING_DIRECTORY, directory_name)
    os.mkdir(working_directory)
    os.mkdir(os.path.join(working_directory, "work"))
    os.mkdir(os.path.join(working_directory, "fifo"))
    output_directory = os.path.join(working_directory, "output")
    os.mkdir(output_directory)

    with tarfile.open(input_archive) as input_tarfile:
        input_tarfile.extractall(
            path=(os.path.join(working_directory, 'input')))
    if not os.path.exists(os.path.join(working_directory, 'input')):
        raise Exception("Input archive did not extract correctly")

    analysis_model_data_path = os.path.join(working_directory, "static")
    if IS_WINDOWS_HOST:
        shutil.copytree(model_data_path, analysis_model_data_path)
    else:
        os.symlink(model_data_path, analysis_model_data_path)

    # If an events file has not been included in the analysis input,
    # then use the default file with all events from the model data.
    analysis_events_filepath = os.path.join(working_directory, 'input', 'events.bin')
    if not os.path.exists(analysis_events_filepath):
        logging.info("Using default events.bin")
        event_set = analysis_settings['analysis_settings']["model_settings"].get("event_set")
        if event_set is None:
            model_data_events_filepath = os.path.join(
                working_directory, 'static', 'events.bin')
        else:
            # Format for data file names
            event_set = format_setting_for_file(event_set)
            model_data_events_filepath = os.path.join(
                working_directory, 'static', 'events_{}.bin'.format(event_set))
        logging.info("Using event file: {}".format(model_data_events_filepath))
        if not os.path.exists(model_data_events_filepath):
            raise Exception(
                "Could not find events data file: {}".format(model_data_events_filepath))
        shutil.copyfile(model_data_events_filepath, analysis_events_filepath)

    # If a return periods file has not been included in the analysis input,
    # then use the default from the model data.
    analysis_returnperiods_filepath = os.path.join(
        working_directory, 'input', 'returnperiods.bin')
    model_data_returnperiods_filepath = os.path.join(
        working_directory, 'static', 'returnperiods.bin')
    if not os.path.exists(analysis_returnperiods_filepath):
        logging.info("Using default returnperiods.bin")
        shutil.copyfile(model_data_returnperiods_filepath, analysis_returnperiods_filepath)

    # Get the occurrence file from the static.
    occurrence_id = analysis_settings['analysis_settings']["model_settings"].get("event_occurrence_id")
    analysis_occurrence_filepath = os.path.join(
        working_directory, 'input', 'occurrence.bin')
    if occurrence_id is None:
        model_data_occurrence_filepath = os.path.join(
            working_directory, 'static', 'occurrence.bin')
    else:
        occurrence_id = format_setting_for_file(occurrence_id)
        model_data_occurrence_filepath = os.path.join(
            working_directory, 'static', 'occurrence{}.bin'.format(occurrence_id))
    if not os.path.exists(analysis_events_filepath):
        raise Exception(
            "Could not find occurrence data file: {}".format(model_data_occurrence_filepath))
    shutil.copyfile(model_data_occurrence_filepath, analysis_occurrence_filepath)

    os.chdir(working_directory)
    logging.info("Working directory = {}".format(working_directory))

    # Persist the analysis_settings
    with open("analysis_settings.json", "w") as json_file:
        json.dump(analysis_settings, json_file)

    if use_default_model_runner:
        model_runner_module = supplier_model_runner
    else:
        model_runner_module = __import__(
            "{}.{}".format(MODULE_SUPPLIER_ID, "supplier_model_runner"),
            globals(),
            locals(),
            ['run'],
            -1)
    model_runner_module.run(
        analysis_settings['analysis_settings'], KTOOLS_BATCH_COUNT)

    output_location = oasis_utils.generate_unique_filename()
    output_filepath = os.path.join(
        OUTPUTS_DATA_DIRECTORY, output_location + ARCHIVE_FILE_SUFFIX)
    with tarfile.open(output_filepath, "w:gz") as tar:
        tar.add(output_directory, arcname="output")

    os.chdir(WORKING_DIRECTORY)

    logging.info("Output location = {}".format(output_location))

    return output_location
