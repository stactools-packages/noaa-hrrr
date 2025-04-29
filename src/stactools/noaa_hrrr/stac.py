import logging
import multiprocessing as mp
from datetime import datetime, timedelta
from typing import Optional, Union

import pandas as pd
import pystac
from pystac import (
    Collection,
    Extent,
    Item,
    ItemAssetDefinition,
    SpatialExtent,
    TemporalExtent,
)
from pystac.catalog import CatalogType
from pystac.extensions.datacube import (
    DatacubeExtension,
    Dimension,
    DimensionType,
    Variable,
    VariableType,
)
from pystac.extensions.item_assets import AssetDefinition, ItemAssetsExtension
from pystac.item_collection import ItemCollection
from pystac.provider import Provider, ProviderRole

from stactools.noaa_hrrr.constants import (
    BYTE_SIZE,
    COLLECTION_ID_FORMAT,
    DESCRIPTION,
    FORECAST_TYPE,
    FORECAST_VALID,
    GRIB_LAYERS,
    GRIB_MESSAGE,
    ITEM_ID_FORMAT,
    LEVEL,
    REFERENCE_TIME,
    RESOLUTION_METERS,
    START_BYTE,
    UNIT,
    VALID_TIME,
    VARIABLE,
)
from stactools.noaa_hrrr.inventory import (
    NotFoundError,
    load_idx,
    read_idx,
    read_inventory_df,
)
from stactools.noaa_hrrr.metadata import (
    CLOUD_PROVIDER_CONFIGS,
    PRODUCT_CONFIGS,
    REGION_CONFIGS,
    CloudProvider,
    ForecastCycleType,
    ForecastLayerType,
    ItemType,
    Product,
    Region,
)

GRIB2_MEDIA_TYPE = "application/wmo-GRIB2"
NDJSON_MEDIA_TYPE = "application/x-ndjson"
INDEX_ASSET_DEFINITION = AssetDefinition(
    {
        "type": NDJSON_MEDIA_TYPE,
        "roles": ["index"],
        "title": "Index file",
        DESCRIPTION: (
            "The index file contains information on each message within the GRIB2 file."
        ),
    }
)

ITEM_BASE_ASSETS = {
    Product.sfc: {
        ItemType.GRIB: ItemAssetDefinition(
            {
                "type": GRIB2_MEDIA_TYPE,
                "roles": ["data"],
                "title": "2D Surface Levels",
                DESCRIPTION: (
                    "2D Surface Level forecast data as a grib2 file. Subsets of the "
                    "data can be loaded using the provided byte range."
                ),
            }
        ),
        ItemType.INDEX: INDEX_ASSET_DEFINITION,
    },
    Product.subh: {
        ItemType.GRIB: ItemAssetDefinition(
            {
                "type": GRIB2_MEDIA_TYPE,
                "roles": ["data"],
                "title": "2D Surface Levels - Sub Hourly",
                DESCRIPTION: (
                    "2D Surface Level forecast data (sub-hourly, 15 minute intervals) "
                    "as a grib2 file. Subsets of the data can be loaded using the "
                    "provided byte range."
                ),
            }
        ),
        ItemType.INDEX: INDEX_ASSET_DEFINITION,
    },
    Product.prs: {
        ItemType.GRIB: ItemAssetDefinition(
            {
                "type": GRIB2_MEDIA_TYPE,
                "roles": ["data"],
                "title": "3D Pressure Levels",
                DESCRIPTION: (
                    "3D Pressure Level forecast data as a grib2 file. Subsets of the "
                    "data can be loaded using the provided byte range."
                ),
            }
        ),
        ItemType.INDEX: INDEX_ASSET_DEFINITION,
    },
    Product.nat: {
        ItemType.GRIB: ItemAssetDefinition(
            {
                "type": GRIB2_MEDIA_TYPE,
                "roles": ["data"],
                "title": "Native Levels",
                DESCRIPTION: (
                    "Native Level forecast data as a grib2 file. Subsets of the data "
                    "can be loaded using the provided byte range."
                ),
            }
        ),
        ItemType.INDEX: INDEX_ASSET_DEFINITION,
    },
}

RENDER_PARAMS = {
    Product.sfc: {
        "WIND__10_m_above_ground__periodic_max": {
            "title": "Wind speed (m/s) 10 m above ground",
            "colormap_name": "viridis",
            "rescale": [[0, 20]],
            "resampling": "nearest",
        },
        "WIND__10_m_above_ground__instantaneous": {
            "title": "Wind speed (m/s) 10 m above ground",
            "colormap_name": "viridis",
            "rescale": [[0, 20]],
            "resampling": "nearest",
        },
        "DSWRF__surface__point_in_time": {
            "title": "Downward Short-Wave Radiation Flux (W/m2)",
            "colormap_name": "rainbow",
            "rescale": [[0, 800]],
            "resampling": "nearest",
        },
        "REFC__entire_atmosphere__point_in_time": {
            "title": "Composite reflectivity (dB)",
            "colormap": [
                ((5, 10), (0, 236, 236, 255)),
                ((10, 15), (1, 160, 246, 255)),
                ((15, 20), (0, 0, 246, 255)),
                ((20, 25), (0, 255, 0, 255)),
                ((25, 30), (0, 200, 0, 255)),
                ((30, 35), (0, 144, 0, 255)),
                ((35, 40), (255, 255, 0, 255)),
                ((40, 45), (231, 192, 0, 255)),
                ((45, 50), (255, 144, 0, 255)),
                ((50, 55), (255, 0, 0, 255)),
                ((55, 60), (214, 0, 0, 255)),
                ((60, 65), (192, 0, 0, 255)),
                ((65, 70), (255, 0, 255, 255)),
                ((70, 75), (153, 85, 201, 255)),
            ],
            "resampling": "nearest",
        },
    }
}


def create_collection(
    region: Region,
    product: Product,
    cloud_provider: CloudProvider,
) -> Collection:
    """Creates a STAC Collection.

    Args:
        product (Product): The product for this collection, must be one of the members
            of the Product Enum.
        cloud_provider (CloudProvider): cloud provider for the assets. Must be a member
            of the CloudProvider Enum. Each cloud_provider has data available from a
            different start date.
    Returns:
        Collection: STAC Collection object
    """
    region_config = REGION_CONFIGS[region]
    product_config = PRODUCT_CONFIGS[product]
    cloud_provider_config = CLOUD_PROVIDER_CONFIGS[cloud_provider]

    inventory_df = read_inventory_df(
        region=region,
        product=product,
    )

    extent = Extent(
        SpatialExtent([region_config.bbox_4326]),
        TemporalExtent([[cloud_provider_config.start_date, None]]),
    )

    providers = [
        Provider(
            name="NOAA",
            roles=[ProviderRole.PRODUCER],
            url="https://www.noaa.gov/",
        )
    ]

    links = [
        pystac.Link(
            rel=pystac.RelType.LICENSE,
            target="https://creativecommons.org/licenses/by/4.0/",
            media_type="text/html",
            title="CC-BY-4.0 license",
        ),
        pystac.Link(
            rel="documentation",
            target="https://rapidrefresh.noaa.gov/hrrr/",
            media_type="text/html",
            title="NOAA HRRR documentation",
        ),
    ]

    keywords = [
        "NOAA",
        "HRRR",
        "forecast",
        "atmospheric",
        "weather",
    ]

    collection = Collection(
        id=COLLECTION_ID_FORMAT.format(
            product=product.value,
            region=region.value,
        ),
        title=(
            "NOAA High Resolution Rapid Refresh (HRRR) - "
            f"{product_config.description} - "
            f"{region.value}"
        ),
        description=(
            "The NOAA HRRR is a real-time 3km resolution, hourly updated, "
            "cloud-resolving, convection-allowing atmospheric model, "
            "initialized by 3km grids with 3km radar assimilation. Radar data is "
            "assimilated in the HRRR every 15 min over a 1-hour period adding further "
            "detail to that provided by the hourly data assimilation from the 13km "
            "radar-enhanced Rapid Refresh (RAP) system. "
            f"This specific collection represents {product_config.description} "
            f"for the {region.value} region."
        ),
        extent=extent,
        license="CC-BY-4.0",
        providers=providers,
        catalog_type=CatalogType.RELATIVE_PUBLISHED,
        keywords=keywords,
    )

    collection.add_links(links)

    # item assets extension
    item_assets_ext = ItemAssetsExtension.ext(collection, add_if_missing=True)

    assets = {
        item_type.value: item_asset
        for item_type, item_asset in ITEM_BASE_ASSETS[product].items()
    }

    # fill out the grib:layers for the grib asset
    grib_asset = assets[ItemType.GRIB.value]
    grib_asset.properties[GRIB_LAYERS] = {}

    for _, row in inventory_df[
        [
            DESCRIPTION,
            UNIT,
            VARIABLE,
            LEVEL,
            FORECAST_VALID,
        ]
    ].iterrows():
        forecast_valid = row.pop(FORECAST_VALID)
        forecast_layer_type = ForecastLayerType.from_str(forecast_valid)

        layer_key = "__".join(
            [
                row.variable.replace(" ", "_"),
                row.level.replace(" ", "_"),
                str(forecast_layer_type),
            ]
        )
        grib_asset.properties[GRIB_LAYERS][layer_key] = {
            **row,
            "forecast_layer_type": forecast_layer_type.forecast_layer_type,
        }

    item_assets_ext.item_assets = assets

    # define the datacube metadata using the inventory files for this
    # region x product
    datacube_ext = DatacubeExtension.ext(collection, add_if_missing=True)

    variable_df = inventory_df.set_index(keys=[VARIABLE, DESCRIPTION, UNIT]).sort_index(
        level=VARIABLE
    )

    datacube_ext.apply(
        dimensions={
            "x": Dimension(
                properties={
                    "type": DimensionType.SPATIAL,
                    "reference_system": region_config.item_crs.to_wkt(),
                    "extent": [
                        region_config.item_bbox_proj[0] + RESOLUTION_METERS / 2,
                        region_config.item_bbox_proj[2] - RESOLUTION_METERS / 2,
                    ],
                    "axis": "x",
                }
            ),
            "y": Dimension(
                properties={
                    "type": DimensionType.SPATIAL,
                    "reference_system": region_config.item_crs.to_wkt(),
                    "extent": [
                        region_config.item_bbox_proj[1] + RESOLUTION_METERS / 2,
                        region_config.item_bbox_proj[3] - RESOLUTION_METERS / 2,
                    ],
                    "axis": "y",
                }
            ),
            REFERENCE_TIME: Dimension(
                properties={
                    "type": DimensionType.TEMPORAL,
                    "extent": [
                        cloud_provider_config.start_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        None,
                    ],
                    "step": "PT1H" if region == Region.conus else "PT3H",
                }
            ),
            VALID_TIME: Dimension(
                properties={
                    "type": DimensionType.TEMPORAL,
                    "extent": [
                        cloud_provider_config.start_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        None,
                    ],
                    "step": "PT15M" if product == Product.subh else "PT1H",
                }
            ),
            # could be a z spatial dimension but the units are not consistent
            LEVEL: Dimension(
                properties={
                    "type": "atmospheric level",
                    "description": (
                        "The atmospheric level for which the forecast is applicable, "
                        "e.g. surface, top of atmosphere, 100 m above ground, etc."
                    ),
                    "values": list(sorted(set(inventory_df[LEVEL].unique()))),
                }
            ),
            FORECAST_TYPE: Dimension(
                properties={
                    "type": DimensionType.TEMPORAL,
                    "description": (
                        "Either point-in-time, periodic summary, or cumulative summary."
                    ),
                    "values": list(
                        set(
                            [
                                ForecastLayerType.from_str(
                                    forecast_valid
                                ).forecast_layer_type
                                for forecast_valid in inventory_df[
                                    FORECAST_VALID
                                ].unique()
                            ]
                        )
                    ),
                }
            ),
        },
        variables={
            variable: Variable(
                properties=dict(
                    dimensions=[
                        "x",
                        "y",
                        REFERENCE_TIME,
                        VALID_TIME,
                        LEVEL,
                        FORECAST_TYPE,
                    ],
                    type=VariableType.DATA,
                    description=description,
                    unit=unit,
                    # experimental new field for defining the specific values of each
                    # domain where this variable has data
                    dimension_domains={
                        LEVEL: list(group[LEVEL].unique()),
                        FORECAST_TYPE: list(
                            set(
                                [
                                    ForecastLayerType.from_str(
                                        forecast_valid
                                    ).forecast_layer_type
                                    for forecast_valid in group[FORECAST_VALID].unique()
                                ]
                            )
                        ),
                    },
                )
            )
            for (variable, description, unit), group in variable_df.groupby(
                level=[VARIABLE, DESCRIPTION, UNIT]
            )
        },
    )

    # add render params if available
    if render_params := RENDER_PARAMS.get(product):
        collection.extra_fields["renders"] = render_params

    return collection


def create_item(
    region: Region,
    product: Product,
    cloud_provider: CloudProvider,
    reference_datetime: datetime,
    forecast_hour: int,
    collection: Optional[Collection] = None,
) -> Item:
    """Creates a STAC item for a region x product x cloud provider x reference_datetime
    (cycle run hour) combination.

    Args:
        region (Region): Either Region.conus or Region.Alaska
        product (Product): The product for this collection, must be one of the members
            of the Product Enum.
        cloud_provider (CloudProvider): cloud provider for the assets. Must be a member
            of the CloudProvider Enum. Each cloud_provider has data available from a
            different start date.
        reference_datetime (datetime): The reference datetime for the forecast data,
            corresponds to 'date' + 'cycle run hour'
        forecast_hour (int): The forecast hour (FH) for the item.
            This will set the item's datetime property ('date' + 'cycle run hour' +
            'forecast hour')

    Returns:
        Item: STAC Item object
    """
    region_config = REGION_CONFIGS[region]

    # make sure there is data for the reference_datetime
    # (Alaska only runs the model every three hours)
    if cycle_run_hour := reference_datetime.hour not in region_config.cycle_run_hours:
        cycle_run_hours = [str(hour) for hour in region_config.cycle_run_hours]
        raise ValueError(
            f"{cycle_run_hour} is not a valid cycle run hour for {region.value}\n"
            f"Please select one of {' ,'.join(cycle_run_hours)}"
        )

    # read the .idx sidecar file into a dataframe
    idx_df = read_idx(
        idx=load_idx(
            region=region,
            product=product,
            cloud_provider=cloud_provider,
            reference_datetime=reference_datetime,
            forecast_hour=forecast_hour,
        ),
    )

    return create_item_from_idx_df(
        idx_df=idx_df,
        region=region,
        product=product,
        cloud_provider=cloud_provider,
        reference_datetime=reference_datetime,
        forecast_hour=forecast_hour,
        collection=collection,
    )


def create_item_from_idx_df(
    idx_df: pd.DataFrame,
    region: Region,
    product: Product,
    cloud_provider: CloudProvider,
    reference_datetime: datetime,
    forecast_hour: int,
    collection: Optional[Collection] = None,
) -> Item:
    """Creates a STAC item for a region x product x cloud provider x reference_datetime
    (cycle run hour) combination and a provided idx dataframe.

    Args:
        idx_df (pandas.DataFrame): Dataframe with the contents of the .idx file as read
            by stactools.noaa_hrrr.inventory.read_idx
        region (Region): Either Region.conus or Region.Alaska
        product (Product): The product for this collection, must be one of the members
            of the Product Enum.
        cloud_provider (CloudProvider): cloud provider for the assets. Must be a member
            of the CloudProvider Enum. Each cloud_provider has data available from a
            different start date.
        reference_datetime (datetime): The reference datetime for the forecast data,
            corresponds to 'date' + 'cycle run hour'
        forecast_hour (int): The forecast hour (FH) for the item.
            This will set the item's datetime property ('date' + 'cycle run hour' +
            'forecast hour')

    Returns:
        Item: STAC Item object
    """
    region_config = REGION_CONFIGS[region]
    cloud_provider_config = CLOUD_PROVIDER_CONFIGS[cloud_provider]

    grib_url = cloud_provider_config.url_base + region_config.format_grib_url(
        product=product,
        reference_datetime=reference_datetime,
        forecast_hour=forecast_hour,
        idx=False,
    )
    idx_url = grib_url + ".idx"

    # set up item
    forecast_datetime = reference_datetime + timedelta(hours=forecast_hour)

    # the forecast_cycle_type defines the available forecast hours and products
    forecast_cycle_type = ForecastCycleType.from_timestamp(
        reference_datetime=reference_datetime
    )

    forecast_cycle_type.validate_forecast_hour(forecast_hour)

    item = Item(
        ITEM_ID_FORMAT.format(
            product=product.value,
            reference_datetime=reference_datetime.strftime("%Y-%m-%dT%H"),
            forecast_hour=forecast_hour,
            region=region.value,
        ),
        geometry=region_config.geometry_4326,
        bbox=region_config.bbox_4326,
        datetime=forecast_datetime,
        collection=collection,
        properties={
            "forecast:reference_time": reference_datetime.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "forecast:horizon": f"PT{forecast_hour}H",
            "noaa-hrrr:forecast_cycle_type": str(forecast_cycle_type),
            "noaa-hrrr:region": region.value,
        },
    )

    item.assets[ItemType.GRIB.value] = ITEM_BASE_ASSETS[product][
        ItemType.GRIB
    ].create_asset(grib_url)

    item.assets[ItemType.INDEX.value] = ITEM_BASE_ASSETS[product][
        ItemType.INDEX
    ].create_asset(idx_url)

    # create an asset for each row in the inventory dataframe
    grib_asset = item.assets[ItemType.GRIB.value]
    grib_asset.extra_fields[GRIB_LAYERS] = {}
    for _, row in idx_df[
        [
            DESCRIPTION,
            UNIT,
            GRIB_MESSAGE,
            START_BYTE,
            BYTE_SIZE,
            VARIABLE,
            LEVEL,
            FORECAST_VALID,
        ]
    ].iterrows():
        forecast_layer_type = ForecastLayerType.from_str(row.forecast_valid)

        layer_key = "__".join(
            [
                row.variable.replace(" ", "_"),
                row.level.replace(" ", "_"),
                str(forecast_layer_type),
            ]
        )

        if product == Product.subh:
            layer_key += "_" + row.forecast_valid.replace(" ", "_")

        if pd.isna(row.byte_size):
            row.byte_size = None

        grib_asset.extra_fields[GRIB_LAYERS][layer_key] = {
            **row,
            **forecast_layer_type.asset_properties(),
        }

    return item


def create_item_safe(
    region: Region,
    product: Product,
    cloud_provider: CloudProvider,
    reference_datetime: datetime,
    forecast_hour: int,
    collection: Optional[Collection],
) -> Union[Item, None]:
    """Try to create an item and raise a warning if it fails"""
    try:
        return create_item(
            region,
            product,
            cloud_provider,
            reference_datetime,
            forecast_hour,
            collection,
        )
    except NotFoundError as e:
        logging.warning(e)
        return None


def create_item_collection(
    region: Region,
    product: Product,
    cloud_provider: CloudProvider,
    start_date: datetime,
    end_date: datetime,
    collection: Optional[Collection] = None,
) -> pystac.ItemCollection:
    """Create an item collection containing all items for a date range"""

    region_config = REGION_CONFIGS[region]

    one_day = timedelta(days=1)
    tasks = []
    reference_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    while reference_date <= end_date:
        for cycle_run_hour in region_config.cycle_run_hours:
            reference_datetime = reference_date + timedelta(hours=cycle_run_hour)
            forecast_cycle_type = ForecastCycleType.from_timestamp(reference_datetime)
            for forecast_hour in forecast_cycle_type.generate_forecast_hours():
                tasks.append(
                    (
                        region,
                        product,
                        cloud_provider,
                        reference_datetime,
                        forecast_hour,
                        collection,
                    )
                )

        reference_date += one_day

    print(f"creating {len(tasks)} items")
    with mp.Pool(4) as pool:
        items = pool.starmap(create_item_safe, tasks)

    return ItemCollection(item for item in items if item is not None)
