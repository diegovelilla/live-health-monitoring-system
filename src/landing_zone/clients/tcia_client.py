import logging

import pandas as pd
from tcia_utils import nbia

from src.utils import require_env

logger = logging.getLogger(__name__)

TCIA_COLLECTION = require_env("TCIA_COLLECTION")

"""
This module implements a client for interacting with the TCIA API to fetch metadata and download DICOM series.
Since TCIA does not provide an annotation API, we are implementing a simple logic to create a balanced sample 
of "Positive" and "Negative". Here we are simply labeling every other series as "Positive" or "Negative" based 
on the index. In a real scenario, you would have actual annotation data to determine these labels, but this allows 
us to focus on data modeling and ingestion logic.
"""

def balanced_sample(
        df: pd.DataFrame, 
        total_series_limit: int
    ) -> pd.DataFrame:
    """
    Given the tcia metadata Dataframe, 
    return a balanced sample of tumor and negative series.
    
    Args:
        df (pd.DataFrame): DataFrame containing TCIA series metadata with 'AnnotationType' column.
        total_series_limit (int): Total number of series to include in the balanced sample.
    
    Returns:
        pd.DataFrame: A balanced DataFrame with approximately equal numbers of 'Positive' 
                      and 'Negative' samples, limited to total_series_limit.
    """
    tumor_series = df[df["AnnotationType"] == "Positive"]
    negative_series = df[df["AnnotationType"] == "Negative"]

    n_per_class = max(1, total_series_limit // 2)
    sampled_tumor = tumor_series.sample(n=min(n_per_class, len(tumor_series)), random_state=42)
    sampled_negative = negative_series.sample(n=min(n_per_class, len(negative_series)), random_state=42)
    return pd.DataFrame(pd.concat([sampled_tumor, sampled_negative], ignore_index=True))


def get_balanced_metadata(total_series_limit: int = 20) -> pd.DataFrame:
    """
    Build metadata directly from TCIA API.
    
    Args:
        total_series_limit (int): Total number of series to include in the balanced sample.
    
    Returns:
        pd.DataFrame: A DataFrame containing the balanced metadata.
    """
    logger.info(
        f"Fetching TCIA series metadata for collection={TCIA_COLLECTION} with total_limit={total_series_limit}"
    )
    series_rows = nbia.getSeries(collection=TCIA_COLLECTION)
    if not series_rows:
        raise ValueError(f"No series returned for TCIA collection '{TCIA_COLLECTION}'")
    logger.info(f"Retrieved {len(series_rows)} raw series row(s) from TCIA")

    records = []
    for idx, row in enumerate(series_rows):
        series_description = row.get("SeriesDescription") or ""
        # DCIM does not offer support for the annotation API
        # so we added this placeholder logic to create a balanced sample.
        label = "Positive" if idx % 2 == 0 else "Negative"
        records.append(
            {
                "SeriesInstanceUID": row.get("SeriesInstanceUID"),
                "AnnotationType": label,
                "Subject ID": row.get("PatientID") or row.get("PatientName") or "unknown",
                "SeriesDescription": series_description,
            }
        )

    df = pd.DataFrame(records)
    if df.empty:
        raise ValueError("TCIA fallback metadata is empty")
    balanced_df = balanced_sample(df=df, total_series_limit=total_series_limit)
    positive_count = int((balanced_df["AnnotationType"] == "Positive").sum())
    negative_count = int((balanced_df["AnnotationType"] == "Negative").sum())
    logger.info(
        f"Prepared balanced TCIA sample with {len(balanced_df)} series (Positive={positive_count}, Negative={negative_count})"
    )
    return balanced_df


def download_dicom_series(series_id: str, download_path: str):
    """
    Downloads a specific series from TCIA to a local temporary directory.

    Args:
        series_id (str): The SeriesInstanceUID of the series to download.
        download_path (str): The local directory path where the downloaded series will be stored.
    """
    logger.info(f"Downloading TCIA series {series_id} into {download_path}...")
    # nbia.downloadSeries makes the API call and zip extraction locally
    nbia.downloadSeries(
        [{"SeriesInstanceUID": series_id}],
        path=download_path,
        format="zip",
    )
    logger.info(f"Finished TCIA series download for {series_id}")