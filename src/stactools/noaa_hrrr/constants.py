"""Constants for NOAA HRRR"""

ITEM_ID_FORMAT = "hrrr-{region}-{product}-{reference_datetime}-FH{forecast_hour}"
COLLECTION_ID_FORMAT = "noaa-hrrr-{product}-{region}"

EXTENDED_FORECAST_MAX_HOUR = 48
STANDARD_FORECAST_MAX_HOUR = 18

RESOLUTION_METERS = 3000

VSI_PATH_FORMAT = "/vsisubfile/{start_byte}_{byte_size},/vsicurl/{grib_url}"

START_BYTE = "start_byte"
BYTE_SIZE = "byte_size"
REFERENCE_TIME = "reference_time"
VALID_TIME = "valid_time"
FORECAST_HOUR = "forecast_hour"
FORECAST_VALID = "forecast_valid"
FORECAST_TYPE = "forecast_type"
LEVEL = "level"
GRIB_MESSAGE = "grib_message"
VARIABLE = "variable"
DESCRIPTION = "description"
UNIT = "unit"
GRIB_MESSAGES = "grib:messages"
GRIB_LAYER_DEFINITIONS = "grib:layer_definitions"
