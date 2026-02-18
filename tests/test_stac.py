import json
from datetime import datetime, timedelta

import pytest

from stactools.noaa_hrrr import stac
from stactools.noaa_hrrr.constants import (
    COLLECTION_ID_FORMAT,
    ITEM_ID_FORMAT,
)
from stactools.noaa_hrrr.inventory import NotFoundError
from stactools.noaa_hrrr.metadata import (
    REGION_CONFIGS,
    CloudProvider,
    ForecastCycleType,
    Product,
    Region,
)


@pytest.mark.parametrize("region", list(Region))  # type: ignore
@pytest.mark.parametrize("product", list(Product))  # type: ignore
@pytest.mark.parametrize("cloud_provider", list(CloudProvider))  # type: ignore
def test_create_collection(
    region: Region,
    product: Product,
    cloud_provider: CloudProvider,
) -> None:
    # This function should be updated to exercise the attributes of interest on
    # the collection

    collection = stac.create_collection(
        region=region,
        product=product,
        cloud_provider=cloud_provider,
    )
    collection.set_self_href(None)  # required for validation to pass
    assert collection.id == COLLECTION_ID_FORMAT.format(
        product=product.value,
        region=region.value,
    )
    collection.validate()

    # make sure we can write to json
    _ = json.dumps(collection.to_dict())


@pytest.mark.parametrize("product", list(Product))  # type: ignore
@pytest.mark.parametrize("cloud_provider", list(CloudProvider))  # type: ignore
@pytest.mark.parametrize("region", list(Region))  # type: ignore
def test_create_item(
    product: Product,
    cloud_provider: CloudProvider,
    region: Region,
) -> None:
    reference_datetime = datetime(
        year=2024, month=1, day=1, hour=6
    )  # pick hour=6 because alaska
    forecast_hour = 12
    item = stac.create_item(
        product=product,
        reference_datetime=reference_datetime,
        forecast_hour=forecast_hour,
        region=region,
        cloud_provider=cloud_provider,
    )
    assert item.id == ITEM_ID_FORMAT.format(
        region=region.value,
        reference_datetime=reference_datetime.strftime("%Y-%m-%dT%H"),
        forecast_hour=forecast_hour,
        product=product.value,
    )
    assert item.properties[
        "forecast:reference_datetime"
    ] == reference_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")
    item.validate()

    assert (
        item.properties["noaa-hrrr:forecast_cycle_type"] == "extended"
    )  # because hour=6

    _ = json.dumps(item.to_dict())


def test_create_collection_without_datacube_ext() -> None:
    collection = stac.create_collection(
        region=Region.conus,
        product=Product.sfc,
        cloud_provider=CloudProvider.aws,
        include_datacube_ext=False,
    )
    collection.set_self_href(None)
    collection.validate()
    assert not any("datacube" in ext for ext in collection.stac_extensions)


def test_create_item_with_collection() -> None:
    region = Region.conus
    product = Product.sfc
    cloud_provider = CloudProvider.aws
    item = stac.create_item(
        region=region,
        product=product,
        cloud_provider=cloud_provider,
        reference_datetime=datetime(year=2024, month=1, day=1, hour=6),
        forecast_hour=12,
        collection=stac.create_collection(
            region=region,
            product=product,
            cloud_provider=cloud_provider,
        ),
    )
    assert item.collection_id == COLLECTION_ID_FORMAT.format(
        region=region.value,
        product=product.value,
        cloud_provider=cloud_provider.value,
    )


def test_create_item_collection() -> None:
    start_date = datetime(year=2024, month=5, day=1)
    item_collection = stac.create_item_collection(
        product=Product.sfc,
        cloud_provider=CloudProvider.azure,
        region=Region.alaska,
        start_date=start_date,
        end_date=start_date,
    )

    n_expected_items = 0
    region_config = REGION_CONFIGS[Region.alaska]
    for cycle_run_hour in region_config.cycle_run_hours:
        forecast_cycle_type = ForecastCycleType.from_timestamp(
            start_date + timedelta(hours=cycle_run_hour)
        )
        for _ in forecast_cycle_type.generate_forecast_hours():
            n_expected_items += 1

    assert len(item_collection) == n_expected_items


def test_create_item_forecast_cycle_type() -> None:
    # try making an invalid forecast for a stand forecast cycle
    with pytest.raises(NotFoundError):
        _ = stac.create_item(
            product=Product.sfc,
            reference_datetime=datetime(year=2024, month=5, day=1, hour=3),
            forecast_hour=30,
            region=Region.conus,
            cloud_provider=CloudProvider.azure,
        )

    valid_extended_forecast_item = stac.create_item(
        product=Product.sfc,
        reference_datetime=datetime(year=2024, month=5, day=1, hour=6),
        forecast_hour=30,
        region=Region.conus,
        cloud_provider=CloudProvider.azure,
    )
    assert (
        valid_extended_forecast_item.properties["noaa-hrrr:forecast_cycle_type"]
        == "extended"
    )


def test_create_item_alaska() -> None:
    # Alaska only runs forecasts every three hours (no forecast for hour=2)
    with pytest.raises(ValueError):
        _ = stac.create_item(
            product=Product.sfc,
            reference_datetime=datetime(year=2024, month=5, day=1, hour=2),
            forecast_hour=0,
            region=Region.alaska,
            cloud_provider=CloudProvider.azure,
        )

    # extended forecasts are generated on hours 0, 6, 12, 18
    item = stac.create_item(
        product=Product.sfc,
        reference_datetime=datetime(year=2024, month=5, day=1, hour=0),
        forecast_hour=19,
        region=Region.alaska,
        cloud_provider=CloudProvider.azure,
    )

    assert (
        item.properties["noaa-hrrr:forecast_cycle_type"] == "extended"
    )  # because hour=6

    # standard forecasts are generated on hours 0, 3, 6, 9, 12, 15, 18, 21
    item = stac.create_item(
        product=Product.sfc,
        reference_datetime=datetime(year=2024, month=5, day=1, hour=3),
        forecast_hour=12,
        region=Region.alaska,
        cloud_provider=CloudProvider.azure,
    )

    assert (
        item.properties["noaa-hrrr:forecast_cycle_type"] == "standard"
    )  # because hour=3 (not divisible by 6)
