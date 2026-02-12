# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project attempts to match the major and minor versions of
[stactools](https://github.com/stac-utils/stactools) and increments the patch
number as needed.

## [Unreleased]

- Dependencies: upgrade to pystac>=1.12.0, ruff==0.11.7
- BREAKING CHANGE: Split `grib:layers` into `grib:messages` and `grib:layer_definitions`
- fix: `forecast:reference_time` -> `forecast:reference_datetime`

## [0.1.2] - 2024-08-16

- Add `collection` to items

## [0.1.1] - 2024-07-15

- Fixed the broken project links in pyproject.toml

## [0.1.0] - 2024-06-25

- Initial package setup
- Collection creation
- Item creation
- `grib:layers` asset property for describing individual layers within a GRIB2 file

[0.1.2]: <https://github.com/developmentseed/noaa-hrrr/releases/tag/0.1.2>
[0.1.1]: <https://github.com/developmentseed/noaa-hrrr/releases/tag/0.1.1>
[0.1.0]: <https://github.com/developmentseed/noaa-hrrr/releases/tag/0.1.0>
[Unreleased]: <https://github.com/stactools-packages/noaa-hrrr/tree/main/>
