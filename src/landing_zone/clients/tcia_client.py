import os
import pandas as pd
import requests
import io
from tcia_utils import nbia


ANNOTATION_URL = os.getenv("TCIA_API_URL")


def get_balanced_metadata(total_series_limit: int = 20) -> pd.DataFrame:
    """
    Fetches annotations and returns a balanced df of tumor and negative samples.
    """
    response = requests.get(ANNOTATION_URL)
    response.raise_for_status()
    df = pd.read_csv(io.StringIO(response.text))
    
    # Define classes
    tumor_series = df[df['AnnotationType'] == 'Tumor Segmentation']
    negative_series = df[df['AnnotationType'] == 'Negative Assessment']
    
    # Balanced sampling
    n_per_class = total_series_limit // 2
    sampled_tumor = tumor_series.sample(n=min(n_per_class, len(tumor_series)))
    sampled_negative = negative_series.sample(n=min(n_per_class, len(negative_series)))
    
    return pd.concat([sampled_tumor, sampled_negative])


def download_dicom_series(series_id: str, download_path: str):
    """
    Downloads a specific series from TCIA to a local temporary directory.
    """
    # nbia.downloadSeries makes the API call and zip extraction locally
    nbia.downloadSeries(series_id, path=download_path, format="zip")